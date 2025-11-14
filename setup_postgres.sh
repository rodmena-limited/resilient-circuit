#!/bin/bash
# Database setup script for highway_circutbreaker PostgreSQL storage

# Default values
DB_NAME="highway_circutbreaker_db"
DB_USER="postgres"
DB_PASSWORD="postgres"
DB_HOST="localhost"
DB_PORT="5432"

# Function to display usage
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -d, --database NAME     Database name (default: highway_circutbreaker_db)"
    echo "  -u, --user USER         Database user (default: postgres)"
    echo "  -p, --password PASS     Database password (required)"
    echo "  -h, --host HOST         Database host (default: localhost)"
    echo "  -P, --port PORT         Database port (default: 5432)"
    echo "  --help                  Show this help message"
    echo ""
    echo "Example:"
    echo "  $0 -p mypassword"
    echo "  $0 -u myuser -p mypassword -d mydb -h localhost -P 5433"
    exit 1
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--database)
            DB_NAME="$2"
            shift 2
            ;;
        -u|--user)
            DB_USER="$2"
            shift 2
            ;;
        -p|--password)
            DB_PASSWORD="$2"
            shift 2
            ;;
        -h|--host)
            DB_HOST="$2"
            shift 2
            ;;
        -P|--port)
            DB_PORT="$2"
            shift 2
            ;;
        --help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

# Check if password is provided
if [ -z "$DB_PASSWORD" ]; then
    echo "Error: Database password is required"
    echo "Use -p or --password to provide the password"
    usage
fi

# Export password for psql
export PGPASSWORD="$DB_PASSWORD"

echo "Setting up PostgreSQL database for highway_circutbreaker..."
echo "Database: $DB_NAME"
echo "User: $DB_USER"
echo "Host: $DB_HOST"
echo "Port: $DB_PORT"
echo ""

# Check if database exists
echo "Checking if database '$DB_NAME' exists..."
DB_EXISTS=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" 2>/dev/null)

if [ "$DB_EXISTS" = "1" ]; then
    echo "Database '$DB_NAME' already exists."
    read -p "Do you want to drop and recreate it? (y/N): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Dropping database '$DB_NAME'..."
        dropdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" 2>/dev/null
        if [ $? -ne 0 ]; then
            echo "Error: Failed to drop database '$DB_NAME'"
            exit 1
        fi
        echo "Database dropped successfully."
        
        echo "Creating database '$DB_NAME'..."
        createdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" 2>/dev/null
        if [ $? -ne 0 ]; then
            echo "Error: Failed to create database '$DB_NAME'"
            exit 1
        fi
        echo "Database created successfully."
    else
        echo "Using existing database."
    fi
else
    echo "Database '$DB_NAME' does not exist. Creating it..."
    createdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "Error: Failed to create database '$DB_NAME'"
        exit 1
    fi
    echo "Database created successfully."
fi

# Create the circuit breaker table
echo ""
echo "Creating circuit breaker table..."
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" <<EOF
-- Create table for circuit breaker state
CREATE TABLE IF NOT EXISTS hw_circuit_breakers (
    resource_key VARCHAR(255) PRIMARY KEY,
    state VARCHAR(50) NOT NULL CHECK (state IN ('CLOSED', 'OPEN', 'HALF_OPEN')),
    failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    open_until TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create index for better performance on state queries
CREATE INDEX IF NOT EXISTS idx_hw_circuit_breakers_state 
ON hw_circuit_breakers(state);

-- Create index for better performance on open_until queries
CREATE INDEX IF NOT EXISTS idx_hw_circuit_breakers_open_until 
ON hw_circuit_breakers(open_until) 
WHERE open_until IS NOT NULL;

-- Create function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS \$\$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
\$\$ language 'plpgsql';

-- Create trigger to automatically update updated_at
DROP TRIGGER IF EXISTS update_hw_circuit_breakers_updated_at 
ON hw_circuit_breakers;

CREATE TRIGGER update_hw_circuit_breakers_updated_at 
BEFORE UPDATE ON hw_circuit_breakers 
FOR EACH ROW 
EXECUTE FUNCTION update_updated_at_column();

-- Grant permissions (optional - uncomment if needed)
-- GRANT ALL PRIVILEGES ON TABLE hw_circuit_breakers TO $DB_USER;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO $DB_USER;

-- Insert a test record (optional - uncomment if you want to test)
-- INSERT INTO hw_circuit_breakers (resource_key, state, failure_count, open_until)
-- VALUES ('test_service', 'CLOSED', 0, NULL)
-- ON CONFLICT (resource_key) DO NOTHING;

-- Show table structure
\d hw_circuit_breakers

-- Show indexes
\di hw_circuit_breakers*

-- Show table contents (if any)
SELECT * FROM hw_circuit_breakers LIMIT 5;
EOF

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Database setup completed successfully!"
    echo ""
    echo "You can now use the PostgreSQL storage with highway_circutbreaker."
    echo ""
    echo "Environment variables to set in your .env file:"
    echo "HW_DB_HOST=$DB_HOST"
    echo "HW_DB_PORT=$DB_PORT"
    echo "HW_DB_NAME=$DB_NAME"
    echo "HW_DB_USER=$DB_USER"
    echo "HW_DB_PASSWORD=$DB_PASSWORD"
    echo ""
    echo "Install the required dependencies:"
    echo "pip install highway_circutbreaker[postgres]"
    echo ""
    echo "Or install psycopg3 and python-dotenv separately:"
    echo "pip install psycopg[binary] python-dotenv"
    echo ""
    echo "Example usage in Python:"
    echo ""
    cat << 'EOF'
from highway_circutbreaker import CircuitProtectorPolicy
from datetime import timedelta
from fractions import Fraction

# Create a circuit breaker with PostgreSQL storage
circuit_breaker = CircuitProtectorPolicy(
    resource_key="my_service",
    cooldown=timedelta(seconds=30),
    failure_limit=Fraction(3, 5),  # 60% failure rate
    success_limit=Fraction(2, 3)   # 66% success rate
)

# Use it as a decorator
@circuit_breaker
def my_function():
    # Your code here
    pass

# Or use it directly
try:
    result = circuit_breaker(my_function)()
except Exception as e:
    print(f"Call failed: {e}")
EOF
else
    echo ""
    echo "❌ Database setup failed!"
    exit 1
fi

# Unset password
unset PGPASSWORD