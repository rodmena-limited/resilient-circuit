Installation
============

You can install Resilient Circuit using pip:

Basic Installation
------------------

.. code-block:: bash

   pip install resilient-circuit

PostgreSQL Support
------------------

To install with PostgreSQL support for shared storage:

.. code-block:: bash

   pip install resilient-circuit[postgres]

This includes the ``psycopg[binary]`` and ``python-dotenv`` packages needed for PostgreSQL storage.

Development Installation
------------------------

For development and contribution:

.. code-block:: bash

   pip install resilient-circuit[dev]

This includes development tools like black, isort, mypy, pytest, and ruff.