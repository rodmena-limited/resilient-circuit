import json
import logging
import os
import threading
import time
import warnings
from abc import ABC, abstractmethod
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

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

#: Serializes the once-per-process schema check/migration across threads.
_PG_ENSURE_LOCK = threading.Lock()
#: True once this process has ensured (or migrated) the table. DDL is global
#: to the database, so one check per process is enough.
_PG_SCHEMA_READY = False

#: The single source of truth for the table schema, shared by the runtime
#: migrator and the CLI so the two can never drift apart. All timestamps are
#: timezone-aware (TIMESTAMPTZ); open_until is written as explicit UTC.
_RC_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS rc_circuit_breakers (
    resource_key VARCHAR(255) NOT NULL,
    state VARCHAR(50) NOT NULL,
    failure_count INTEGER NOT NULL DEFAULT 0,
    open_until TIMESTAMPTZ,
    execution_log JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    namespace VARCHAR(255) NOT NULL DEFAULT 'default',
    PRIMARY KEY (resource_key, namespace)
)
"""


class CircuitBreakerStorage(ABC):
    """Abstract base class for circuit breaker storage backends."""

    #: Human-readable identity of the backend. Callers that need to know
    #: whether state is shared across processes (e.g. "postgres") or local
    #: to this process (e.g. "in-memory") can inspect this attribute.
    backend_name: str = "unknown"

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
        execution_log: Optional[List[bool]] = None,
    ) -> bool:
        """Blind (unconditional-intent) write of the state for a resource key.

        Implementations must refuse the write when the stored state is OPEN
        with an unexpired open_until: a blind writer acting on a stale local
        view must never erase a live protection signal, and a later opener
        must never move the stored cooldown end. All writes are accepted once
        the stored open_until has expired, so recovery transitions
        (OPEN -> HALF_OPEN -> CLOSED) are never blocked.

        To overwrite a live OPEN deliberately (administrative reset), use
        update_state() with a mutator that ignores the current state.

        Args:
            execution_log: Optional list of boolean success/failure results

        Returns:
            True if the write was applied, False if it was refused because
            the stored circuit is OPEN with an unexpired cooldown.
        """
        pass

    def delete_state(self, resource_key: str) -> bool:
        """Remove the stored state for a resource key.

        Backends that cannot delete state return False without raising, so
        callers can always invoke this operation safely.

        Args:
            resource_key: Unique circuit breaker identifier

        Returns:
            True if a stored state existed and was removed, False otherwise.
        """
        logger.warning(
            f"{type(self).__name__} does not support delete_state; stored state "
            f"for {resource_key} left in place"
        )
        return False

    def update_state(
        self,
        resource_key: str,
        mutator: Callable[[Optional[Dict[str, Any]]], Optional[Dict[str, Any]]],
    ) -> Optional[Dict[str, Any]]:
        """Atomic read-modify-write of the state for a resource key.

        Loads the current state, passes it to ``mutator`` (which receives
        None when no state exists), and persists the returned dict. The
        mutator returns a dict with keys ``state``, ``failure_count``,
        ``open_until`` and optionally ``execution_log`` — or None to leave
        the stored state unchanged. The mutator must be fast and must not
        perform I/O: concrete backends run it while holding a lock.

        The write is unconditional (no live-OPEN guard): the mutator decided
        from the current stored state, not a stale copy.

        This base implementation is a non-atomic fallback (get, mutate,
        guarded set) for third-party backends; PostgresStorage and
        InMemoryStorage override it with genuinely atomic versions.

        Returns:
            The state dict that is stored after the operation.
        """
        current = self.get_state(resource_key)
        new_state = mutator(dict(current) if current is not None else None)
        if new_state is None:
            return current
        self.set_state(
            resource_key,
            new_state["state"],
            int(new_state.get("failure_count", 0)),
            float(new_state.get("open_until", 0)),
            execution_log=new_state.get("execution_log"),
        )
        return new_state


class InMemoryStorage(CircuitBreakerStorage):
    """In-memory storage implementation for circuit breaker state.

    Thread-safe: reads, guarded writes and read-modify-write cycles are
    serialized on a process-local lock.

    Bounded: the store keeps at most ``max_entries`` resource keys. When the
    cap is reached, the least-recently-used entry that is not a live OPEN is
    evicted (an evicted key simply re-creates as CLOSED on its next use). A
    live OPEN — an unexpired protection signal — is never evicted, even if
    that means the cap is temporarily exceeded.
    """

    backend_name = "in-memory"

    def __init__(self, max_entries: Optional[int] = 8192) -> None:
        if max_entries is not None and max_entries < 1:
            raise ValueError("`max_entries` must be positive (or None for unbounded).")
        self._states: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.max_entries = max_entries

    @staticmethod
    def _is_live_open(stored: Optional[Dict[str, Any]]) -> bool:
        return (
            stored is not None
            and stored.get("state") == "OPEN"
            and float(stored.get("open_until", 0)) > time.time()
        )

    @staticmethod
    def _copy(state_dict: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if state_dict is None:
            return None
        copied = dict(state_dict)
        if "execution_log" in copied and copied["execution_log"] is not None:
            copied["execution_log"] = list(copied["execution_log"])
        return copied

    def get_state(self, resource_key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            state = self._states.get(resource_key)
            if state is not None:
                self._states.move_to_end(resource_key)
            return self._copy(state)

    def _evict_if_needed(self) -> None:
        """Evict the oldest non-live entry while over the entry cap.

        A live OPEN (unexpired ``open_until``) is never evicted: dropping a
        protection signal to reclaim memory is worse than exceeding the cap.
        Evicting a non-live entry is semantically equivalent to first-time
        load — the next read re-creates it as CLOSED.
        """
        if self.max_entries is None:
            return
        while len(self._states) >= self.max_entries:
            for key in list(self._states.keys()):
                if not self._is_live_open(self._states[key]):
                    del self._states[key]
                    break
            else:
                return  # every stored entry is a live protection signal

    def _store(
        self,
        resource_key: str,
        state: str,
        failure_count: int,
        open_until: float,
        execution_log: Optional[List[bool]],
    ) -> None:
        state_dict: Dict[str, Any] = {
            "state": state,
            "failure_count": failure_count,
            "open_until": open_until,
        }
        if execution_log is not None:
            state_dict["execution_log"] = list(execution_log)
        elif (
            resource_key in self._states
            and "execution_log" in self._states[resource_key]
        ):
            # Preserve the existing log when the caller does not provide one,
            # mirroring PostgresStorage behavior.
            state_dict["execution_log"] = self._states[resource_key]["execution_log"]
        self._evict_if_needed()
        self._states[resource_key] = state_dict
        self._states.move_to_end(resource_key)

    def set_state(
        self,
        resource_key: str,
        state: str,
        failure_count: int,
        open_until: float,
        execution_log: Optional[List[bool]] = None,
    ) -> bool:
        with self._lock:
            if self._is_live_open(self._states.get(resource_key)):
                return False
            self._store(resource_key, state, failure_count, open_until, execution_log)
            return True

    def update_state(
        self,
        resource_key: str,
        mutator: Callable[[Optional[Dict[str, Any]]], Optional[Dict[str, Any]]],
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            current = self._copy(self._states.get(resource_key))
            new_state = mutator(current)
            if new_state is None:
                return current
            self._store(
                resource_key,
                new_state["state"],
                int(new_state.get("failure_count", 0)),
                float(new_state.get("open_until", 0)),
                new_state.get("execution_log"),
            )
            return self._copy(self._states[resource_key])

    def delete_state(self, resource_key: str) -> bool:
        with self._lock:
            if resource_key in self._states:
                del self._states[resource_key]
                return True
            return False


class PostgresStorage(CircuitBreakerStorage):
    """PostgreSQL storage implementation for circuit breaker state."""

    backend_name = "postgres"

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
        """Ensure the circuit breaker table exists with the current schema.

        Runs once per process: later PostgresStorage constructions skip the
        DDL. The check and any migration run in one transaction, serialized
        across processes by an advisory lock, and are idempotent — legacy
        tables (pre-namespace single-column PK, naive TIMESTAMP open_until)
        are upgraded in place and their stored state is preserved.
        """
        global _PG_SCHEMA_READY
        with _PG_ENSURE_LOCK:
            if _PG_SCHEMA_READY:
                # DDL already ran this process; still verify reachability so
                # a misconfigured/unreachable database fails construction
                # (and create_storage can fall back) exactly as it did before.
                with self._get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                return
            try:
                with self._get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                            ("rc_circuit_breakers",),
                        )
                        cur.execute("SELECT to_regclass('public.rc_circuit_breakers')")
                        regclass = cur.fetchone()
                        exists = regclass is not None and regclass[0] is not None
                        if not exists:
                            cur.execute(_RC_TABLE_DDL)
                        else:
                            cur.execute(
                                "ALTER TABLE rc_circuit_breakers "
                                "ADD COLUMN IF NOT EXISTS namespace VARCHAR(255) "
                                "NOT NULL DEFAULT 'default'"
                            )
                            cur.execute(
                                "ALTER TABLE rc_circuit_breakers "
                                "ADD COLUMN IF NOT EXISTS execution_log JSONB"
                            )
                            cur.execute(
                                """
                                DO $$
                                BEGIN
                                    IF EXISTS (
                                        SELECT 1 FROM pg_constraint
                                        WHERE conname = 'rc_circuit_breakers_pkey'
                                          AND conrelid = 'rc_circuit_breakers'::regclass
                                          AND conkey = ARRAY[
                                              (SELECT attnum FROM pg_attribute
                                               WHERE attrelid = 'rc_circuit_breakers'::regclass
                                                 AND attname = 'resource_key')
                                          ]
                                    ) THEN
                                        ALTER TABLE rc_circuit_breakers
                                        DROP CONSTRAINT rc_circuit_breakers_pkey;
                                        ALTER TABLE rc_circuit_breakers
                                        ADD PRIMARY KEY (resource_key, namespace);
                                    END IF;
                                END $$;
                                """
                            )
                            cur.execute(
                                """
                                DO $$
                                BEGIN
                                    IF EXISTS (
                                        SELECT 1 FROM information_schema.columns
                                        WHERE table_name = 'rc_circuit_breakers'
                                          AND column_name = 'open_until'
                                          AND data_type = 'timestamp without time zone'
                                    ) THEN
                                        ALTER TABLE rc_circuit_breakers
                                        ALTER COLUMN open_until TYPE TIMESTAMPTZ
                                        USING open_until AT TIME ZONE 'localtime';
                                    END IF;
                                END $$;
                                """
                            )

                        # Create indexes for better performance
                        cur.execute(
                            "CREATE INDEX IF NOT EXISTS "
                            "idx_rc_circuit_breakers_state "
                            "ON rc_circuit_breakers(state)"
                        )
                        cur.execute(
                            "CREATE INDEX IF NOT EXISTS "
                            "idx_rc_circuit_breakers_namespace "
                            "ON rc_circuit_breakers(namespace)"
                        )
                        cur.execute(
                            "CREATE INDEX IF NOT EXISTS "
                            "idx_rc_circuit_breakers_key_namespace "
                            "ON rc_circuit_breakers(resource_key, namespace)"
                        )
                        conn.commit()
                _PG_SCHEMA_READY = True
            except Exception as e:
                logger.error(f"Failed to ensure table exists: {e}")
                raise

    @staticmethod
    def _row_to_state(row: Optional[tuple[Any, ...]]) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        result = {
            "state": row[0],
            "failure_count": row[1],
            "open_until": row[2].timestamp() if row[2] else 0,
        }
        if row[3] is not None:
            result["execution_log"] = row[3]
        return result

    @staticmethod
    def _to_pg_timestamp(epoch: float) -> Optional[str]:
        """Format an epoch as an explicit-UTC TIMESTAMPTZ literal.

        UTC with an explicit offset makes the stored instant independent of
        the writer's and the session's timezone — a peer in any timezone
        reads the same instant. Microseconds are preserved: sub-second
        cooldowns must survive the round-trip.
        """
        if epoch <= 0:
            return None
        return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S.%f%z"
        )

    _STATE_SELECT = (
        "SELECT state, failure_count, open_until, execution_log "
        "FROM rc_circuit_breakers "
        "WHERE resource_key = %s AND namespace = %s"
    )

    def get_state(self, resource_key: str) -> Optional[Dict[str, Any]]:
        """Get the state for a given resource key within this namespace.

        This is a plain read on its own short-lived connection; it takes no
        row locks and provides no cross-call atomicity. For an atomic
        read-modify-write cycle use update_state().
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        self._STATE_SELECT,
                        (resource_key, self.namespace),
                    )
                    return self._row_to_state(cur.fetchone())
        except Exception as e:
            logger.error(
                f"Failed to get state for {resource_key} (namespace={self.namespace}): {e}"
            )
            raise

    # A row whose stored state is OPEN with an unexpired open_until is
    # immutable to blind writers: a stale CLOSED/HALF_OPEN must not erase a
    # live protection signal, and a later opener must not move the stored
    # cooldown end. "Now" is passed as an explicit-UTC instant so the
    # comparison is independent of the writer's or the session's timezone.
    _LIVE_OPEN_GUARD = (
        "NOT (rc_circuit_breakers.state = 'OPEN' "
        "AND COALESCE(rc_circuit_breakers.open_until > %s::timestamptz, FALSE))"
    )

    def _upsert(
        self,
        cur: Any,
        resource_key: str,
        state: str,
        failure_count: int,
        open_until: float,
        execution_log: Optional[List[bool]],
        guarded: bool,
    ) -> bool:
        """Run the upsert on an existing cursor. Returns True if a row was written."""
        open_until_ts = self._to_pg_timestamp(open_until)
        guard = f" WHERE {self._LIVE_OPEN_GUARD}" if guarded else ""

        if execution_log is not None:
            cur.execute(
                f"""
                INSERT INTO rc_circuit_breakers
                    (resource_key, namespace, state, failure_count, open_until, execution_log)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (resource_key, namespace) DO UPDATE SET
                    state = EXCLUDED.state,
                    failure_count = EXCLUDED.failure_count,
                    open_until = EXCLUDED.open_until,
                    execution_log = EXCLUDED.execution_log,
                    updated_at = CURRENT_TIMESTAMP{guard}
                """,
                (
                    resource_key,
                    self.namespace,
                    state,
                    failure_count,
                    open_until_ts,
                    json.dumps(execution_log),
                )
                + ((self._to_pg_timestamp(time.time()),) if guarded else ()),
            )
        else:
            # No execution_log provided: preserve the existing value
            cur.execute(
                f"""
                INSERT INTO rc_circuit_breakers
                    (resource_key, namespace, state, failure_count, open_until)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (resource_key, namespace) DO UPDATE SET
                    state = EXCLUDED.state,
                    failure_count = EXCLUDED.failure_count,
                    open_until = EXCLUDED.open_until,
                    updated_at = CURRENT_TIMESTAMP{guard}
                """,
                (
                    resource_key,
                    self.namespace,
                    state,
                    failure_count,
                    open_until_ts,
                )
                + ((self._to_pg_timestamp(time.time()),) if guarded else ()),
            )
        return bool(cur.rowcount)

    def set_state(
        self,
        resource_key: str,
        state: str,
        failure_count: int,
        open_until: float,
        execution_log: Optional[List[bool]] = None,
    ) -> bool:
        """Blind write of the state for a resource key within this namespace.

        Refused (returns False) when the stored state is OPEN with an
        unexpired open_until — see CircuitBreakerStorage.set_state. Use
        update_state() for read-modify-write cycles or deliberate overrides.

        Args:
            resource_key: Unique circuit breaker identifier
            state: Circuit state (CLOSED, OPEN, HALF_OPEN)
            failure_count: Number of consecutive failures
            open_until: Timestamp when circuit can transition from OPEN
            execution_log: Optional list of boolean success/failure results for the circular buffer

        Returns:
            True if the write was applied, False if refused.
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    applied = self._upsert(
                        cur,
                        resource_key,
                        state,
                        failure_count,
                        open_until,
                        execution_log,
                        guarded=True,
                    )
                    conn.commit()
                    if not applied:
                        logger.warning(
                            f"Refused state write for {resource_key} "
                            f"(namespace={self.namespace}): stored circuit is OPEN "
                            f"with unexpired cooldown; attempted state={state}"
                        )
                    return applied
        except Exception as e:
            logger.error(
                f"Failed to set state for {resource_key} (namespace={self.namespace}): {e}"
            )
            raise

    def update_state(
        self,
        resource_key: str,
        mutator: Callable[[Optional[Dict[str, Any]]], Optional[Dict[str, Any]]],
    ) -> Optional[Dict[str, Any]]:
        """Atomic read-modify-write of the state for a resource key.

        Load, mutate and persist run on one connection inside one
        transaction. A per-key advisory transaction lock serializes
        concurrent update_state cycles even when the row does not exist yet,
        and SELECT ... FOR UPDATE additionally blocks concurrent blind
        writers for the duration of the transaction. The mutator therefore
        sees the current stored state, and its result is written
        unguarded.

        The mutator must be fast and must not perform I/O: it runs while the
        row and advisory locks are held.
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (f"{self.namespace}|{resource_key}",),
                    )
                    cur.execute(
                        self._STATE_SELECT + " FOR UPDATE",
                        (resource_key, self.namespace),
                    )
                    current = self._row_to_state(cur.fetchone())
                    new_state = mutator(dict(current) if current is not None else None)
                    if new_state is None:
                        conn.commit()
                        return current
                    self._upsert(
                        cur,
                        resource_key,
                        new_state["state"],
                        int(new_state.get("failure_count", 0)),
                        float(new_state.get("open_until", 0)),
                        new_state.get("execution_log"),
                        guarded=False,
                    )
                    conn.commit()
                    return new_state
        except Exception as e:
            logger.error(
                f"Failed to update state for {resource_key} "
                f"(namespace={self.namespace}): {e}"
            )
            raise

    def delete_state(self, resource_key: str) -> bool:
        """Remove the stored state for a resource key within this namespace."""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM rc_circuit_breakers "
                        "WHERE resource_key = %s AND namespace = %s",
                        (resource_key, self.namespace),
                    )
                    conn.commit()
                    return bool(cur.rowcount)
        except Exception as e:
            logger.error(
                f"Failed to delete state for {resource_key} "
                f"(namespace={self.namespace}): {e}"
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
            warnings.warn(
                f"PostgreSQL storage was requested (RC_DB_HOST/RC_DB_PASSWORD "
                f"set) but is unavailable: {e}. Falling back to InMemoryStorage "
                f"— circuit breaker state will be process-local and NOT shared "
                f"across instances.",
                RuntimeWarning,
                stacklevel=2,
            )
            return InMemoryStorage()
    else:
        # Default to in-memory storage
        return InMemoryStorage()
