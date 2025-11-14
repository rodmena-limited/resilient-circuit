"""
CLI module for Highway Circuit Breaker
"""

import argparse
import os
import sys
from typing import Optional

try:
    import psycopg
except ImportError:
    psycopg = None

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def load_env_vars():
    """Load environment variables from .env file if available."""
    if load_dotenv:
        load_dotenv()
    else:
        print("Warning: python-dotenv not found, skipping .env file loading")


def get_db_config_from_env() -> dict:
    """Get database configuration from environment variables."""
    return {
        'host': os.getenv('HW_DB_HOST', 'localhost'),
        'port': int(os.getenv('HW_DB_PORT', '5432')),
        'dbname': os.getenv('HW_DB_NAME', 'highway_circutbreaker_db'),
        'user': os.getenv('HW_DB_USER', 'postgres'),
        'password': os.getenv('HW_DB_PASSWORD', 'postgres')
    }


def create_postgres_table(config: dict) -> bool:
    """Create the circuit breaker table in PostgreSQL database."""
    if not psycopg:
        print("Error: psycopg is required for PostgreSQL setup. Install with: pip install highway_circutbreaker[postgres]")
        return False

    try:
        # Connect to the database
        conn = psycopg.connect(
            host=config['host'],
            port=config['port'],
            dbname=config['dbname'],
            user=config['user'],
            password=config['password']
        )

        with conn:
            with conn.cursor() as cur:
                # Check if table already exists
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public'
                        AND table_name = 'hw_circuit_breakers'
                    );
                """)

                table_exists = cur.fetchone()[0]
                if table_exists:
                    print(f"ℹ️  Table 'hw_circuit_breakers' already exists, checking for updates...")

                # Create the circuit breaker table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS hw_circuit_breakers (
                        resource_key VARCHAR(255) NOT NULL,
                        state VARCHAR(20) NOT NULL CHECK (state IN ('CLOSED', 'OPEN', 'HALF_OPEN')),
                        failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0 AND failure_count <= 2147483647),
                        open_until TIMESTAMPTZ,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (resource_key)
                    );
                """)

                # Create optimized indexes
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_hw_circuit_breakers_state
                    ON hw_circuit_breakers (state);
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_hw_circuit_breakers_open_until
                    ON hw_circuit_breakers (open_until)
                    WHERE open_until IS NOT NULL;
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_hw_circuit_breakers_key_state
                    ON hw_circuit_breakers (resource_key, state);
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_hw_circuit_breakers_state_updated
                    ON hw_circuit_breakers (state, updated_at DESC);
                """)

                # Create trigger function
                cur.execute("""
                    CREATE OR REPLACE FUNCTION update_hw_circuit_breakers_updated_at_column()
                    RETURNS TRIGGER AS $$
                    BEGIN
                        NEW.updated_at = NOW();
                        RETURN NEW;
                    END;
                    $$ language 'plpgsql' SET search_path = public;
                """)

                # Create trigger
                cur.execute("""
                    DROP TRIGGER IF EXISTS update_hw_circuit_breakers_updated_at
                    ON hw_circuit_breakers;
                """)

                cur.execute("""
                    CREATE TRIGGER update_hw_circuit_breakers_updated_at
                        BEFORE UPDATE ON hw_circuit_breakers
                        FOR EACH ROW
                        WHEN (OLD IS DISTINCT FROM NEW)
                        EXECUTE FUNCTION update_hw_circuit_breakers_updated_at_column();
                """)

                # Add table comments
                cur.execute("""
                    COMMENT ON TABLE hw_circuit_breakers IS
                    'Circuit breaker state storage with performance optimizations';
                """)

                cur.execute("""
                    COMMENT ON COLUMN hw_circuit_breakers.state IS
                    'Current state of the circuit breaker: CLOSED, OPEN, or HALF_OPEN';
                """)

                cur.execute("""
                    COMMENT ON COLUMN hw_circuit_breakers.open_until IS
                    'Timestamp when the circuit breaker should transition from OPEN to HALF_OPEN';
                """)

                cur.execute("""
                    COMMENT ON COLUMN hw_circuit_breakers.failure_count IS
                    'Number of consecutive failures since last reset';
                """)

                conn.commit()

                if table_exists:
                    print(f"✅ Successfully updated table in database: {config['dbname']}")
                else:
                    print(f"✅ Successfully created table in database: {config['dbname']}")
                return True

    except psycopg.OperationalError as e:
        if "database" in str(e) and "does not exist" in str(e):
            print(f"❌ Error: Database '{config['dbname']}' does not exist.")
            print("💡 Please create the database first or update your HW_DB_NAME in the .env file.")
            print(f"   You can create it with: createdb -h {config['host']} -p {config['port']} -U {config['user']} {config['dbname']}")
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

    print(f"🔧 Using database configuration from environment:")
    print(f"   Host: {config['host']}")
    print(f"   Port: {config['port']}")
    print(f"   Database: {config['dbname']}")
    print(f"   User: {config['user']}")

    if config['dbname'] == 'highway_circutbreaker_db':
        print(f"\n⚠️  Note: Using default database name '{config['dbname']}'.")
        print("   You can customize this by setting HW_DB_NAME in your .env file.")

    if args.dry_run:
        print("\n📝 DRY RUN MODE - No changes will be made to the database")
        print("This command would create the required tables and indexes in your PostgreSQL database.")
        return 0

    # Confirm before proceeding
    if not args.yes:
        response = input(f"\n⚠️  This will create/update the circuit breaker table in '{config['dbname']}'. Continue? [y/N]: ")
        if response.lower() not in ['y', 'yes']:
            print("❌ Setup cancelled by user.")
            return 1

    print("\n📦 Creating PostgreSQL table and indexes...")
    success = create_postgres_table(config)

    if success:
        print("\n✅ PostgreSQL setup completed successfully!")
        print("\n📋 The following have been created/updated:")
        print("   - Table: hw_circuit_breakers")
        print("   - Primary key index: hw_circuit_breakers_pkey")
        print("   - Index: idx_hw_circuit_breakers_state")
        print("   - Index: idx_hw_circuit_breakers_open_until")
        print("   - Index: idx_hw_circuit_breakers_key_state")
        print("   - Index: idx_hw_circuit_breakers_state_updated")
        print("   - Trigger: update_hw_circuit_breakers_updated_at")
        print("   - Function: update_hw_circuit_breakers_updated_at_column")

        print(f"\n💡 The database '{config['dbname']}' is now ready for use with Highway Circuit Breaker!")
        return 0
    else:
        print("\n❌ PostgreSQL setup failed!")
        return 1


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog='highway-circutbreaker-cli',
        description='Highway Circuit Breaker CLI tools'
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # PostgreSQL setup command
    pg_setup_parser = subparsers.add_parser(
        'pg-setup',
        help='Setup PostgreSQL table for circuit breaker state storage'
    )
    pg_setup_parser.add_argument(
        '--yes',
        action='store_true',
        help='Skip confirmation prompt'
    )
    pg_setup_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )

    args = parser.parse_args()

    if args.command == 'pg-setup':
        return run_pg_setup(args)
    else:
        parser.print_help()
        return 1

if __name__ == '__main__':
    sys.exit(main())