Command Line Interface
======================

The Resilient Circuit CLI provides utility commands for managing your circuit breaker setup.

Installation
------------

After installing Resilient Circuit, the CLI is available as ``resilient-circuit-cli``.

PostgreSQL Setup
----------------

The main command is ``pg-setup`` which creates the necessary database table and indexes for PostgreSQL shared storage.

Basic Usage
~~~~~~~~~~~

.. code-block:: bash

   resilient-circuit-cli pg-setup

This command will:

1. Load database configuration from environment variables (or .env file)
2. Connect to the specified PostgreSQL database
3. Create the ``rc_circuit_breakers`` table if it doesn't exist
4. Create optimized indexes for performance
5. Set up triggers for automatic timestamp updates

Options
~~~~~~~

The ``pg-setup`` command supports several options:

--yes
   Skip the confirmation prompt and proceed with the setup directly.

   .. code-block:: bash

      resilient-circuit-cli pg-setup --yes

--dry-run
   Show what would be done without making any actual changes to the database.

   .. code-block:: bash

      resilient-circuit-cli pg-setup --dry-run

Environment Variables
~~~~~~~~~~~~~~~~~~~~~

The CLI reads database configuration from environment variables:

- ``RC_DB_HOST``: PostgreSQL host (default: localhost)
- ``RC_DB_PORT``: PostgreSQL port (default: 5432)
- ``RC_DB_NAME``: Database name (default: resilient_circuit_db)
- ``RC_DB_USER``: Database user (default: postgres)
- ``RC_DB_PASSWORD``: Database password

Example Configuration
~~~~~~~~~~~~~~~~~~~~~

Create a ``.env`` file:

.. code-block:: ini

   RC_DB_HOST=localhost
   RC_DB_PORT=5432
   RC_DB_NAME=my_circuit_breaker_db
   RC_DB_USER=myuser
   RC_DB_PASSWORD=mypassword

Then run the setup:

.. code-block:: bash

   resilient-circuit-cli pg-setup