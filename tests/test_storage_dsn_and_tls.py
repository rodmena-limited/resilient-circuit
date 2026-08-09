"""create_storage() connection-string construction: RC_DB_DSN and TLS options.

The discrete RC_DB_* variables build a conninfo of the form
``host=... port=... dbname=... user=... password=...`` which cannot express
``sslmode``/``sslrootcert``/``sslcert``/``sslkey``. A server that mandates TLS
with client-certificate authentication was therefore unreachable from
environment configuration, even though PostgresStorage passes its connection
string straight to ``psycopg.connect`` and would have accepted one.

These tests assert on the string that would be handed to psycopg, so they need
no database. PostgresStorage is patched out; what is under test is the
construction, not the connection.
"""

import pytest

from resilient_circuit import storage as storage_mod
from resilient_circuit.storage import InMemoryStorage, create_storage

_DB_ENV = (
    "RC_DB_DSN",
    "RC_DB_HOST",
    "RC_DB_PORT",
    "RC_DB_NAME",
    "RC_DB_USER",
    "RC_DB_PASSWORD",
    "RC_DB_SSLMODE",
    "RC_DB_SSLROOTCERT",
    "RC_DB_SSLCERT",
    "RC_DB_SSLKEY",
    "RC_NAMESPACE",
)


@pytest.fixture
def captured(monkeypatch):
    """Capture the conninfo create_storage() would pass to PostgresStorage."""
    for name in _DB_ENV:
        monkeypatch.delenv(name, raising=False)

    seen = {}

    class _Spy:
        backend_name = "postgres"

        def __init__(self, connection_string, namespace="default"):
            seen["connection_string"] = connection_string
            seen["namespace"] = namespace

    monkeypatch.setattr(storage_mod, "PostgresStorage", _Spy)
    return seen


class TestDsnPassthrough:
    def test_rc_db_dsn_is_used_verbatim(self, monkeypatch, captured):
        dsn = (
            "postgresql://cb:secret@pg-nano-01.example:5432/appdb"
            "?sslmode=verify-full&sslrootcert=/etc/ssl/cert.pem"
            "&sslcert=/etc/tls/cb.crt&sslkey=/etc/tls/cb.key"
        )
        monkeypatch.setenv("RC_DB_DSN", dsn)
        create_storage()
        # verbatim: no reformatting, no dropped query parameters
        assert captured["connection_string"] == dsn

    def test_dsn_takes_precedence_over_discrete_vars(self, monkeypatch, captured):
        monkeypatch.setenv("RC_DB_DSN", "postgresql://a:b@dsnhost/dsndb?sslmode=require")
        monkeypatch.setenv("RC_DB_HOST", "discrete-host")
        monkeypatch.setenv("RC_DB_PASSWORD", "discrete-pw")
        create_storage()
        assert "dsnhost" in captured["connection_string"]
        assert "discrete-host" not in captured["connection_string"]

    def test_dsn_alone_is_enough(self, monkeypatch, captured):
        """RC_DB_PASSWORD is not required when a DSN carries the credentials."""
        monkeypatch.setenv("RC_DB_DSN", "postgresql://u:p@h/db")
        result = create_storage()
        assert not isinstance(result, InMemoryStorage)
        assert captured["connection_string"] == "postgresql://u:p@h/db"

    def test_namespace_still_honoured_with_dsn(self, monkeypatch, captured):
        monkeypatch.setenv("RC_DB_DSN", "postgresql://u:p@h/db")
        monkeypatch.setenv("RC_NAMESPACE", "tokengate")
        create_storage()
        assert captured["namespace"] == "tokengate"


class TestDiscreteTlsOptions:
    def test_ssl_options_are_appended(self, monkeypatch, captured):
        monkeypatch.setenv("RC_DB_HOST", "db.example")
        monkeypatch.setenv("RC_DB_PASSWORD", "pw")
        monkeypatch.setenv("RC_DB_SSLMODE", "verify-full")
        monkeypatch.setenv("RC_DB_SSLROOTCERT", "/etc/ssl/cert.pem")
        monkeypatch.setenv("RC_DB_SSLCERT", "/etc/tls/cb.crt")
        monkeypatch.setenv("RC_DB_SSLKEY", "/etc/tls/cb.key")
        create_storage()
        c = captured["connection_string"]
        assert "sslmode=verify-full" in c
        assert "sslrootcert=/etc/ssl/cert.pem" in c
        assert "sslcert=/etc/tls/cb.crt" in c
        assert "sslkey=/etc/tls/cb.key" in c
        # and the base conninfo is still intact
        assert "host=db.example" in c and "password=pw" in c

    def test_unset_ssl_options_are_not_emitted(self, monkeypatch, captured):
        """A plaintext deployment must produce exactly the old string."""
        monkeypatch.setenv("RC_DB_HOST", "localhost")
        monkeypatch.setenv("RC_DB_PASSWORD", "postgres")
        create_storage()
        c = captured["connection_string"]
        assert "ssl" not in c
        assert c == (
            "host=localhost port=5432 dbname=resilient_circuit_db "
            "user=postgres password=postgres"
        )

    def test_partial_ssl_options_emit_only_what_is_set(self, monkeypatch, captured):
        monkeypatch.setenv("RC_DB_HOST", "db.example")
        monkeypatch.setenv("RC_DB_PASSWORD", "pw")
        monkeypatch.setenv("RC_DB_SSLMODE", "require")
        create_storage()
        c = captured["connection_string"]
        assert "sslmode=require" in c
        assert "sslcert=" not in c and "sslkey=" not in c and "sslrootcert=" not in c


class TestBackwardCompatibility:
    def test_no_env_still_yields_in_memory(self, monkeypatch, captured):
        result = create_storage()
        assert isinstance(result, InMemoryStorage)

    def test_host_without_password_still_yields_in_memory(self, monkeypatch, captured):
        """Unchanged: the discrete form requires both host and password."""
        monkeypatch.setenv("RC_DB_HOST", "db.example")
        result = create_storage()
        assert isinstance(result, InMemoryStorage)

    def test_password_without_host_still_yields_in_memory(self, monkeypatch, captured):
        monkeypatch.setenv("RC_DB_PASSWORD", "pw")
        result = create_storage()
        assert isinstance(result, InMemoryStorage)
