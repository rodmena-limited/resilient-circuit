Installation
============

You can install Highway Circuit Breaker using pip:

Basic Installation
------------------

.. code-block:: bash

   pip install highway-circutbreaker

PostgreSQL Support
------------------

To install with PostgreSQL support for shared storage:

.. code-block:: bash

   pip install highway-circutbreaker[postgres]

This includes the ``psycopg[binary]`` and ``python-dotenv`` packages needed for PostgreSQL storage.

Development Installation
------------------------

For development and contribution:

.. code-block:: bash

   pip install highway-circutbreaker[dev]

This includes development tools like black, isort, mypy, pytest, and ruff.