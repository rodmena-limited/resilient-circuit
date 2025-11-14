import os
import time
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import logging

try:
    from dotenv import load_dotenv
    load_dotenv()
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False

try:
    import psycopg
    from psycopg import Connection
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
            Dictionary with keys: state, failure_count, open_until
            or None if no state found
        """
        pass
    
    @abstractmethod
    def set_state(self, resource_key: str, state: str, failure_count: int, open_until: float) -> None:
        """Set the state for a given resource key."""
        pass


class InMemoryStorage(CircuitBreakerStorage):
    """In-memory storage implementation for circuit breaker state."""
    
    def __init__(self):
        self._states: Dict[str, Dict[str, Any]] = {}
    
    def get_state(self, resource_key: str) -> Optional[Dict[str, Any]]:
        return self._states.get(resource_key)
    
    def set_state(self, resource_key: str, state: str, failure_count: int, open_until: float) -> None:
        self._states[resource_key] = {
            "state": state,
            "failure_count": failure_count,
            "open_until": open_until
        }


class PostgresStorage(CircuitBreakerStorage):
    """PostgreSQL storage implementation for circuit breaker state."""
    
    def __init__(self, connection_string: str):
        if not HAS_PSYCOPG:
            raise ImportError("psycopg3 is required for PostgreSQL storage. Install with: pip install psycopg[binary]")
        
        self.connection_string = connection_string
        self._ensure_table_exists()
    
    def _get_connection(self) -> Connection:
        """Get a database connection."""
        return psycopg.connect(self.connection_string)
    
    def _ensure_table_exists(self) -> None:
        """Ensure the circuit breaker table exists."""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS hw_circuit_breakers (
                            resource_key VARCHAR(255) PRIMARY KEY,
                            state VARCHAR(50) NOT NULL,
                            failure_count INTEGER NOT NULL DEFAULT 0,
                            open_until TIMESTAMP,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    
                    # Create index for better performance
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_hw_circuit_breakers_state 
                        ON hw_circuit_breakers(state)
                    """)
                    
                    conn.commit()
                    logger.info("PostgreSQL circuit breaker table ensured")
        except Exception as e:
            logger.error(f"Failed to ensure table exists: {e}")
            raise
    
    def get_state(self, resource_key: str) -> Optional[Dict[str, Any]]:
        """Get the state for a given resource key.
        
        NOTE: This query uses FOR UPDATE to lock the row
        to ensure this read-call-write cycle is atomic.
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT state, failure_count, open_until "
                        "FROM hw_circuit_breakers WHERE resource_key = %s "
                        "FOR UPDATE",
                        (resource_key,)
                    )
                    row = cur.fetchone()
                    if row:
                        return {
                            "state": row[0],
                            "failure_count": row[1],
                            "open_until": row[2].timestamp() if row[2] else 0
                        }
                    return None
        except Exception as e:
            logger.error(f"Failed to get state for {resource_key}: {e}")
            raise
    
    def set_state(self, resource_key: str, state: str, failure_count: int, open_until: float) -> None:
        """Set the state for a given resource key."""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # Convert timestamp to PostgreSQL timestamp
                    open_until_ts = None
                    if open_until > 0:
                        open_until_ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(open_until))
                    
                    cur.execute(
                        """
                        INSERT INTO hw_circuit_breakers 
                            (resource_key, state, failure_count, open_until)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (resource_key) DO UPDATE SET
                            state = EXCLUDED.state,
                            failure_count = EXCLUDED.failure_count,
                            open_until = EXCLUDED.open_until,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (resource_key, state, failure_count, open_until_ts)
                    )
                    conn.commit()
        except Exception as e:
            logger.error(f"Failed to set state for {resource_key}: {e}")
            raise


def create_storage() -> CircuitBreakerStorage:
    """Create the appropriate storage backend based on environment."""
    # Check for PostgreSQL connection info in environment
    db_host = os.getenv("HW_DB_HOST")
    db_port = os.getenv("HW_DB_PORT", "5432")
    db_name = os.getenv("HW_DB_NAME", "highway_circutbreaker_db")
    db_user = os.getenv("HW_DB_USER", "postgres")
    db_password = os.getenv("HW_DB_PASSWORD")
    
    if db_host and db_password:
        # PostgreSQL storage requested
        connection_string = f"host={db_host} port={db_port} dbname={db_name} user={db_user} password={db_password}"
        try:
            storage = PostgresStorage(connection_string)
            logger.info(f"Using PostgreSQL storage for circuit breaker: host={db_host}, db={db_name}")
            return storage
        except Exception as e:
            logger.error(f"Failed to create PostgreSQL storage: {e}")
            logger.warning("Falling back to in-memory storage")
            return InMemoryStorage()
    else:
        # Default to in-memory storage
        logger.info("Using in-memory storage for circuit breaker (no PostgreSQL config found)")
        return InMemoryStorage()