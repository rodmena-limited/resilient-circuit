"""
CLI module for Highway Circuit Breaker
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from resilient_circuit.storage import _RC_TABLE_DDL

HAS_PSYCOPG = False
HAS_DOTENV = False
psycopg: Any = None
load_dotenv: Any = None

try:
    import psycopg

    HAS_PSYCOPG = True
except ImportError:
    pass

try:
    from dotenv import load_dotenv

    HAS_DOTENV = True
except ImportError:
    pass


def load_env_vars() -> None:
    """Load environment variables from .env file if available."""
    if HAS_DOTENV and load_dotenv is not None:
        load_dotenv()
    else:
        print("Warning: python-dotenv not found, skipping .env file loading")


def get_db_config_from_env() -> dict[str, Any]:
    """Get database configuration from environment variables."""
    return {
        "host": os.getenv("RC_DB_HOST", "localhost"),
        "port": int(os.getenv("RC_DB_PORT", "5432")),
        "dbname": os.getenv("RC_DB_NAME", "resilient_circuit_db"),
        "user": os.getenv("RC_DB_USER", "postgres"),
        "password": os.getenv("RC_DB_PASSWORD", "postgres"),
    }


def create_postgres_table(config: dict[str, Any]) -> bool:
    """Create the circuit breaker table in PostgreSQL database."""
    if not HAS_PSYCOPG or psycopg is None:
        print(
            "Error: psycopg is required for PostgreSQL setup. Install with: pip install resilient_circuit[postgres]"
        )
        return False

    try:
        # Connect to the database
        conn = psycopg.connect(
            host=config["host"],
            port=config["port"],
            dbname=config["dbname"],
            user=config["user"],
            password=config["password"],
        )

        with conn:
            with conn.cursor() as cur:
                # Check if table already exists
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public'
                        AND table_name = 'rc_circuit_breakers'
                    );
                """)

                result = cur.fetchone()
                table_exists = result[0] if result else False
                if table_exists:
                    print(
                        "ℹ️  Table 'rc_circuit_breakers' already exists, checking for updates..."
                    )

                # Create the circuit breaker table (single source of truth
                # shared with the runtime migrator in resilient_circuit.storage)
                cur.execute(_RC_TABLE_DDL)

                # Create optimized indexes
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_rc_circuit_breakers_state
                    ON rc_circuit_breakers (state);
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_rc_circuit_breakers_open_until
                    ON rc_circuit_breakers (open_until)
                    WHERE open_until IS NOT NULL;
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_rc_circuit_breakers_key_state
                    ON rc_circuit_breakers (resource_key, state);
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_rc_circuit_breakers_state_updated
                    ON rc_circuit_breakers (state, updated_at DESC);
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_rc_circuit_breakers_namespace
                    ON rc_circuit_breakers (namespace);
                """)

                # Create trigger function
                cur.execute("""
                    CREATE OR REPLACE FUNCTION update_rc_circuit_breakers_updated_at_column()
                    RETURNS TRIGGER AS $$
                    BEGIN
                        NEW.updated_at = NOW();
                        RETURN NEW;
                    END;
                    $$ language 'plpgsql' SET search_path = public;
                """)

                # Create trigger
                cur.execute("""
                    DROP TRIGGER IF EXISTS update_rc_circuit_breakers_updated_at
                    ON rc_circuit_breakers;
                """)

                cur.execute("""
                    CREATE TRIGGER update_rc_circuit_breakers_updated_at
                        BEFORE UPDATE ON rc_circuit_breakers
                        FOR EACH ROW
                        WHEN (OLD IS DISTINCT FROM NEW)
                        EXECUTE FUNCTION update_rc_circuit_breakers_updated_at_column();
                """)

                # Add table comments
                cur.execute("""
                    COMMENT ON TABLE rc_circuit_breakers IS
                    'Circuit breaker state storage with performance optimizations';
                """)

                cur.execute("""
                    COMMENT ON COLUMN rc_circuit_breakers.state IS
                    'Current state of the circuit breaker: CLOSED, OPEN, or HALF_OPEN';
                """)

                cur.execute("""
                    COMMENT ON COLUMN rc_circuit_breakers.open_until IS
                    'Timestamp when the circuit breaker should transition from OPEN to HALF_OPEN';
                """)

                cur.execute("""
                    COMMENT ON COLUMN rc_circuit_breakers.failure_count IS
                    'Number of consecutive failures since last reset';
                """)

                cur.execute("""
                    COMMENT ON COLUMN rc_circuit_breakers.execution_log IS
                    'JSON array of boolean success/failure results for the circular buffer';
                """)

                cur.execute("""
                    COMMENT ON COLUMN rc_circuit_breakers.namespace IS
                    'Namespace for circuit breaker isolation (e.g., test isolation)';
                """)

                conn.commit()

                if table_exists:
                    print(
                        f"✅ Successfully updated table in database: {config['dbname']}"
                    )
                else:
                    print(
                        f"✅ Successfully created table in database: {config['dbname']}"
                    )
                return True

    except psycopg.OperationalError as e:
        if "database" in str(e) and "does not exist" in str(e):
            print(f"❌ Error: Database '{config['dbname']}' does not exist.")
            print(
                "💡 Please create the database first or update your RC_DB_NAME in the .env file."
            )
            print(
                f"   You can create it with: createdb -h {config['host']} -p {config['port']} -U {config['user']} {config['dbname']}"
            )
        else:
            print(f"❌ Database connection error: {e}")
        return False
    except Exception as e:
        print(f"❌ Error creating table: {e}")
        return False


def run_pg_setup(args: argparse.Namespace) -> int:
    """Run the PostgreSQL setup command."""
    print("🚀 Highway Circuit Breaker PostgreSQL Setup")
    print()

    load_env_vars()

    # Get config from environment
    config = get_db_config_from_env()

    print("🔧 Using database configuration from environment:")
    print(f"   Host: {config['host']}")
    print(f"   Port: {config['port']}")
    print(f"   Database: {config['dbname']}")
    print(f"   User: {config['user']}")

    if config["dbname"] == "resilient_circuit_db":
        print(f"\n⚠️  Note: Using default database name '{config['dbname']}'.")
        print("   You can customize this by setting RC_DB_NAME in your .env file.")

    if args.dry_run:
        print("\n📝 DRY RUN MODE - No changes will be made to the database")
        print(
            "This command would create the required tables and indexes in your PostgreSQL database."
        )
        return 0

    # Confirm before proceeding
    if not args.yes:
        response = input(
            f"\n⚠️  This will create/update the circuit breaker table in '{config['dbname']}'. Continue? [y/N]: "
        )
        if response.lower() not in ["y", "yes"]:
            print("❌ Setup cancelled by user.")
            return 1

    print("\n📦 Creating PostgreSQL table and indexes...")
    success = create_postgres_table(config)

    if success:
        print("\n✅ PostgreSQL setup completed successfully!")
        print("\n📋 The following have been created/updated:")
        print("   - Table: rc_circuit_breakers")
        print(
            "   - Primary key index: rc_circuit_breakers_pkey (resource_key, namespace)"
        )
        print("   - Index: idx_rc_circuit_breakers_state")
        print("   - Index: idx_rc_circuit_breakers_open_until")
        print("   - Index: idx_rc_circuit_breakers_key_state")
        print("   - Index: idx_rc_circuit_breakers_state_updated")
        print("   - Index: idx_rc_circuit_breakers_namespace")
        print("   - Trigger: update_rc_circuit_breakers_updated_at")
        print("   - Function: update_rc_circuit_breakers_updated_at_column")

        print(
            f"\n💡 The database '{config['dbname']}' is now ready for use with Highway Circuit Breaker!"
        )
        return 0
    else:
        print("\n❌ PostgreSQL setup failed!")
        return 1


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="resilient-circuit-cli",
        description="Highway Circuit Breaker CLI tools",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # PostgreSQL setup command
    pg_setup_parser = subparsers.add_parser(
        "pg-setup", help="Setup PostgreSQL table for circuit breaker state storage"
    )
    pg_setup_parser.add_argument(
        "--yes", action="store_true", help="Skip confirmation prompt"
    )
    pg_setup_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )

    args = parser.parse_args()

    if args.command == "pg-setup":
        return run_pg_setup(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
