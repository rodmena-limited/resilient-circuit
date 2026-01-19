import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False

try:
    import psycopg

    HAS_PSYCOPG = True
except ImportError:
    HAS_PSYCOPG = False

logger = logging.getLogger(__name__)


class CircuitBreakerStorage(ABC):
    """Abstract base class for circuit breaker storage backends."""

    @abstractmethod
    def get_state(self, resource_key: str) -> Optional[Dict[str, Any]]:
        """Get the state for a given resource key.

        Returns:
            Dictionary with keys: state, failure_count, open_until, execution_log (optional)
            or None if no state found
        """
        pass

    @abstractmethod
    def set_state(
        self,
        resource_key: str,
        state: str,
        failure_count: int,
        open_until: float,
        execution_log: Optional[list] = None,
    ) -> None:
        """Set the state for a given resource key.

        Args:
            execution_log: Optional list of boolean success/failure results
        """
        pass


class InMemoryStorage(CircuitBreakerStorage):
    """In-memory storage implementation for circuit breaker state."""

    def __init__(self) -> None:
        self._states: Dict[str, Dict[str, Any]] = {}

    def get_state(self, resource_key: str) -> Optional[Dict[str, Any]]:
        return self._states.get(resource_key)

    def set_state(
        self,
        resource_key: str,
        state: str,
        failure_count: int,
        open_until: float,
        execution_log: Optional[list] = None,
    ) -> None:
        state_dict = {
            "state": state,
            "failure_count": failure_count,
            "open_until": open_until,
        }
        if execution_log is not None:
            state_dict["execution_log"] = execution_log
        self._states[resource_key] = state_dict


class PostgresStorage(CircuitBreakerStorage):
    """PostgreSQL storage implementation for circuit breaker state."""

    def __init__(self, connection_string: str, namespace: str = "default"):
        if not HAS_PSYCOPG:
            raise ImportError(
                "psycopg3 is required for PostgreSQL storage. Install with: pip install psycopg[binary]"
            )

        self.connection_string = connection_string
        self.namespace = namespace
        self._ensure_table_exists()

    def _get_connection(self) -> "psycopg.Connection":
        """Get a database connection."""
        return psycopg.connect(self.connection_string)

    def _ensure_table_exists(self) -> None:
        """Ensure the circuit breaker table exists with namespace support."""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # Check if namespace column exists
                    cur.execute("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'rc_circuit_breakers'
                        AND column_name = 'namespace'
                    """)
                    has_namespace = cur.fetchone() is not None

                    if not has_namespace:
                        # Old schema without namespace - need to migrate
                        cur.execute("""
                            CREATE TABLE IF NOT EXISTS rc_circuit_breakers (
                                resource_key VARCHAR(255) NOT NULL,
                                state VARCHAR(50) NOT NULL,
                                failure_count INTEGER NOT NULL DEFAULT 0,
                                open_until TIMESTAMP,
                                execution_log JSONB,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                namespace VARCHAR(255) NOT NULL DEFAULT 'default',
                                PRIMARY KEY (resource_key, namespace)
                            )
                        """)

                        # Add namespace and execution_log columns to existing table if it exists
                        cur.execute("""
                            DO $$
                            BEGIN
                                IF EXISTS (SELECT 1 FROM information_schema.tables
                                          WHERE table_name = 'rc_circuit_breakers') THEN
                                    ALTER TABLE rc_circuit_breakers
                                    DROP CONSTRAINT IF EXISTS rc_circuit_breakers_pkey;

                                    ALTER TABLE rc_circuit_breakers
                                    ADD COLUMN IF NOT EXISTS namespace VARCHAR(255) NOT NULL DEFAULT 'default';

                                    ALTER TABLE rc_circuit_breakers
                                    ADD COLUMN IF NOT EXISTS execution_log JSONB;

                                    ALTER TABLE rc_circuit_breakers
                                    ADD PRIMARY KEY (resource_key, namespace);
                                END IF;
                            END $$;
                        """)
                    else:
                        # Table exists with namespace column
                        cur.execute("""
                            CREATE TABLE IF NOT EXISTS rc_circuit_breakers (
                                resource_key VARCHAR(255) NOT NULL,
                                state VARCHAR(50) NOT NULL,
                                failure_count INTEGER NOT NULL DEFAULT 0,
                                open_until TIMESTAMP,
                                execution_log JSONB,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                namespace VARCHAR(255) NOT NULL DEFAULT 'default',
                                PRIMARY KEY (resource_key, namespace)
                            )
                        """)

                        # Add execution_log column if missing (migration for older tables)
                        cur.execute("""
                            ALTER TABLE rc_circuit_breakers
                            ADD COLUMN IF NOT EXISTS execution_log JSONB
                        """)

                    # Create indexes for better performance
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_rc_circuit_breakers_state
                        ON rc_circuit_breakers(state)
                    """)

                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_rc_circuit_breakers_namespace
                        ON rc_circuit_breakers(namespace)
                    """)

                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_rc_circuit_breakers_key_namespace
                        ON rc_circuit_breakers(resource_key, namespace)
                    """)

                    conn.commit()
        except Exception as e:
            logger.error(f"Failed to ensure table exists: {e}")
            raise

    def get_state(self, resource_key: str) -> Optional[Dict[str, Any]]:
        """Get the state for a given resource key within this namespace.

        NOTE: This query uses FOR UPDATE to lock the row
        to ensure this read-call-write cycle is atomic.
        Namespace isolation ensures parallel tests don't conflict.
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT state, failure_count, open_until, execution_log "
                        "FROM rc_circuit_breakers "
                        "WHERE resource_key = %s AND namespace = %s "
                        "FOR UPDATE",
                        (resource_key, self.namespace),
                    )
                    row = cur.fetchone()
                    if row:
                        result = {
                            "state": row[0],
                            "failure_count": row[1],
                            "open_until": row[2].timestamp() if row[2] else 0,
                        }
                        # Add execution_log if present
                        if row[3] is not None:
                            result["execution_log"] = row[3]
                        return result
                    return None
        except Exception as e:
            logger.error(
                f"Failed to get state for {resource_key} (namespace={self.namespace}): {e}"
            )
            raise

    def set_state(
        self,
        resource_key: str,
        state: str,
        failure_count: int,
        open_until: float,
        execution_log: Optional[list] = None,
    ) -> None:
        """Set the state for a given resource key within this namespace.

        Args:
            resource_key: Unique circuit breaker identifier
            state: Circuit state (CLOSED, OPEN, HALF_OPEN)
            failure_count: Number of consecutive failures
            open_until: Timestamp when circuit can transition from OPEN
            execution_log: Optional list of boolean success/failure results for the circular buffer
        """
        try:
            import json

            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # Convert timestamp to PostgreSQL timestamp
                    open_until_ts = None
                    if open_until > 0:
                        open_until_ts = time.strftime(
                            "%Y-%m-%d %H:%M:%S", time.localtime(open_until)
                        )

                    # Serialize execution_log to JSON if provided
                    execution_log_json = (
                        json.dumps(execution_log) if execution_log is not None else None
                    )

                    if execution_log is not None:
                        # Update including execution_log
                        cur.execute(
                            """
                            INSERT INTO rc_circuit_breakers
                                (resource_key, namespace, state, failure_count, open_until, execution_log)
                            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                            ON CONFLICT (resource_key, namespace) DO UPDATE SET
                                state = EXCLUDED.state,
                                failure_count = EXCLUDED.failure_count,
                                open_until = EXCLUDED.open_until,
                                execution_log = EXCLUDED.execution_log,
                                updated_at = CURRENT_TIMESTAMP
                            """,
                            (
                                resource_key,
                                self.namespace,
                                state,
                                failure_count,
                                open_until_ts,
                                execution_log_json,
                            ),
                        )
                    else:
                        # Update without execution_log (preserve existing value)
                        cur.execute(
                            """
                            INSERT INTO rc_circuit_breakers
                                (resource_key, namespace, state, failure_count, open_until)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (resource_key, namespace) DO UPDATE SET
                                state = EXCLUDED.state,
                                failure_count = EXCLUDED.failure_count,
                                open_until = EXCLUDED.open_until,
                                updated_at = CURRENT_TIMESTAMP
                            """,
                            (
                                resource_key,
                                self.namespace,
                                state,
                                failure_count,
                                open_until_ts,
                            ),
                        )
                    conn.commit()
        except Exception as e:
            logger.error(
                f"Failed to set state for {resource_key} (namespace={self.namespace}): {e}"
            )
            raise


def create_storage(namespace: Optional[str] = None) -> CircuitBreakerStorage:
    """Create the appropriate storage backend based on environment.

    Args:
        namespace: Namespace for circuit breaker isolation. If None, uses environment
                  variable RC_NAMESPACE or defaults to "default".
                  Use different namespaces for test isolation (e.g., workflow_run_id).

    Returns:
        CircuitBreakerStorage instance with namespace support
    """
    # Get namespace from parameter or environment
    if namespace is None:
        namespace = os.getenv("RC_NAMESPACE", "default")

    # Check for PostgreSQL connection info in environment
    db_host = os.getenv("RC_DB_HOST")
    db_port = os.getenv("RC_DB_PORT", "5432")
    db_name = os.getenv("RC_DB_NAME", "resilient_circuit_db")
    db_user = os.getenv("RC_DB_USER", "postgres")
    db_password = os.getenv("RC_DB_PASSWORD")

    if db_host and db_password:
        # PostgreSQL storage requested
        connection_string = f"host={db_host} port={db_port} dbname={db_name} user={db_user} password={db_password}"
        try:
            return PostgresStorage(connection_string, namespace=namespace)
        except Exception as e:
            logger.error(f"Failed to create PostgreSQL storage: {e}")
            return InMemoryStorage()
    else:
        # Default to in-memory storage
        return InMemoryStorage()
