# pyright: basic
# pyright: reportOptionalMemberAccess=false
# pyright: reportOptionalContextManager=false
# pyright: reportOptionalSubscript=false
# pyright: reportOptionalIterable=false

# pylint: disable=wrong-import-position
"""
Database initialization module for Material Flow Table Database (SQLAlchemy 1.4).

This module owns everything *around* an already-known database location:
verifying that the database exists, ensuring the ORM schema is in place,
performing health checks, and reporting metadata about tables and rows.

Key Features:
    - Database existence verification with automatic creation
    - Schema management: create all tables from SQLAlchemy ORM models
    - Health check: PostgreSQL version + presence of all expected tables
    - Metadata report: database size, per-table column list and row count
    - Model availability checker with retry-safe state
    - CLI entry point (`python -m dags.tasks.initializer`) for CI/compose

Architecture:
    This module implements the *schema layer* and the orchestrator:
        1. Model Layer: `make_models_checker` + `check_models_available`
        2. Schema Layer: `ensure_database_exists`, `create_database_tables`
        3. Monitoring Layer: `check_database_health`, `get_database_info`
        4. Orchestration: `initialize_database` (calls `connector.py` for the engine)
    Connection management (engine creation, host detection, retries) lives in
    `connector.py`.

Dependencies:
    - SQLAlchemy 1.4.54+: ORM and database abstraction layer
    - SQLAlchemy-Utils 0.42.0+: database_exists / create_database utilities
    - PostgreSQL 12+: Target database system

Performance Considerations:
    - Intended for one-shot runs (container start, CI, manual), not hot paths
    - Single pass over tables: one `get_columns()` + one `COUNT(*)` per table
    - Row counting uses `SELECT COUNT(*)`; for very large tables consider
      replacing with `pg_class.reltuples` (approximate, O(1)) if needed

Security Notes:
    - Passwords are obtained via `connector.get_private_db_config()` and are
      never logged by this module
    - `get_connection_string()` masks the password in every log line
    - `ensure_database_exists()` creates the target database through
      `sqlalchemy_utils`, which connects to the system `postgres` database
    - Database creation requires the `CREATEDB` privilege on the configured user

Error Handling:
    - `ConnectionError`: PostgreSQL server unreachable
    - `RuntimeError`: SQLAlchemy failures, missing Base, or unexpected errors
    - `ValueError`: incomplete configuration (missing config keys)
    - `PermissionError`: insufficient privileges to create the database
    - `initialize_database()` returns `None` (never raises) on failure: it
      catches `ConnectionError` and any unexpected exception. Lower-level
      exceptions (`RuntimeError`, `ValueError`, `PermissionError`) may
      originate in `ensure_database_exists()` / `create_database_tables()`
      but are caught by the top-level handler in `initialize_database()`.
    - `main()` translates `None` into exit code 1

Integration Notes:
    - Uses `connector.connect_to_database()` to obtain the engine
    - Called by the `db_initializer` service in docker-compose
    - Can also be invoked manually: `python -m dags.tasks.initializer`
    - Safe to run repeatedly (idempotent): existing objects are left intact
    - `loader.py` and `mft_dag.py` should call `connect_to_database()` from
      `connector.py` directly; they do NOT need `initializer.py`

Initialization Sequence (`initialize_database`):
    1. Verify ORM models are importable
    2. Ensure the target database exists (create if missing)
    3. Connect via `connector.connect_to_database()`
    4. Create missing tables from `Base.metadata`
    5. Create/replace database views from `database.views`
    6. Run health check (PostgreSQL version + schema completeness)
    7. Collect and log per-table metadata (columns + rows)

Table Report Format (`get_database_info`):
    {
        'db_name': str,
        'db_user': str,
        'server_ip': str | None,
        'server_port': int,
        'db_size_mb': float,
        'tables_count': int,
        'tables': {
            '<table_name>': {
                'columns': [str, ...],
                'rows': int,
            },
            ...
        },
    }

Environment Variables:
    DB_HOST:        Database hostname (optional, auto-detected by connector)
    DB_PORT:        Database port (default: 5432)
    DB_NAME:        Database name (default: mft_db)
    DB_USER:        Database user (default: mft_user)
    DB_PASSWORD:    Database password (default: mft_password)
    DB_MAX_RETRIES: Connection attempts during initialization (default: 5)
    DB_RETRY_DELAY: Delay between retries in seconds (default: 2)

Note:
    This module targets PostgreSQL (template0, UTF-8). For other database
    systems, `ensure_database_exists` would need to be adapted.

Usage Example:
    # As a library
    from dags.tasks.initializer import initialize_database

    engine = initialize_database()
    if engine is None:
        raise SystemExit("DB initialization failed")
    engine.dispose()

    # As a CLI (used by docker-compose db_initializer service)
    # $ python -m dags.tasks.initializer
    # $ echo $?    # 0 on success, 1 on failure

Maintainer: PLD Engineering Center
Version: 1.0.0
Compatibility: Python 3.14.4+, SQLAlchemy 1.4.54+, PostgreSQL 12+
Created: 2026-11-04
Last Modified: 2026-11-04
License: MIT
Status: Production
"""
# Standard library imports
from pathlib import Path
import os
import sys
import socket
from typing import Any, Callable, Optional, Tuple, Type, cast

# Third-party imports
from sqlalchemy import inspect as sqlalchemy_inspect, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.engine import Engine
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy_utils import database_exists, create_database

# The relative path to the root project directory
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Add the project path to sys.path
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Local imports
from config import get_logger
from database.database import Base as DatabaseBase
from database.views import create_views
from dags.tasks.connector import (
    connect_to_database,
    get_connection_string,
    get_private_db_config,
)

# Logger setup
logger = get_logger(__name__)


# ============================================
# Model availability checker
# ============================================

def make_models_checker() -> Tuple[
    Callable[[], bool],
    Callable[[], Optional[Type[Any]]],
    Callable[[], None],
]:
    """
    Factory for functions that manage database model availability state.

    Returns:
        Tuple of:
        - models_available(): True if models are loaded and valid.
        - get_base(): Base class if available, else None.
        - reset(): Reset internal state (for testing).
    """
    _base: Optional[Type[Any]] = None
    _has_database_models = False
    _attempted = False

    def models_available() -> bool:
        nonlocal _base, _has_database_models, _attempted

        if _has_database_models:
            return True
        if _attempted:
            return False

        _attempted = True

        try:
            _base = DatabaseBase
            if hasattr(_base, 'metadata'):
                _has_database_models = True
                logger.info("Database models imported successfully")
                return True
            logger.warning("Base imported but has no 'metadata' attribute")
            _base = None
            return False
        except NameError as e:
            logger.warning("Database models not found: %s", e)
            return False
        except AttributeError as e:
            logger.warning("Database models incomplete: %s", e)
            _base = None
            return False
        except Exception as unexpected_error:
            logger.error(
                "Unexpected error importing database models: %s",
                unexpected_error,
            )
            return False

    def get_base() -> Optional[Type[Any]]:
        nonlocal _base
        if models_available():
            return _base
        return None

    def reset() -> None:
        nonlocal _base, _has_database_models, _attempted
        _base = None
        _has_database_models = False
        _attempted = False
        logger.debug("Database models state reset")

    return models_available, get_base, reset


check_models_available, get_base_model, reset_models = make_models_checker()


# ============================================
# Database existence
# ============================================

def ensure_database_exists() -> None:
    """
    Ensure the target database exists, creating it if necessary.

    Connects to the PostgreSQL system database ('postgres') to check for
    and create the target database.

    Raises:
        ConnectionError: If PostgreSQL server is unreachable.
        RuntimeError: For SQLAlchemy or database operation errors.
        ValueError: For incomplete database configuration.
        PermissionError: If the user lacks CREATE DATABASE privilege.
    """
    try:
        private_config = get_private_db_config()

        target_db_url = get_connection_string(private_config)
        target_database = private_config['database']

        if not database_exists(target_db_url):
            logger.warning(
                "Database '%s' does not exist. Creating...", target_database
            )
            create_database(target_db_url, encoding='utf8', template='template0')
            logger.info("Database '%s' created successfully", target_database)
        else:
            logger.info("Database '%s' already exists", target_database)

    except OperationalError as e:
        logger.error("Database connection error: %s", e)
        raise ConnectionError(
            f"Failed to connect to PostgreSQL server: {e}"
        ) from e
    except SQLAlchemyError as e:
        logger.error("SQLAlchemy error during database check: %s", e)
        raise RuntimeError(f"Database operation failed: {e}") from e
    except socket.gaierror as e:
        logger.error("Host resolution error: %s", e)
        raise ConnectionError(f"Cannot resolve database host: {e}") from e
    except KeyError as e:
        logger.error("Missing configuration key: %s", e)
        raise ValueError(
            f"Database configuration incomplete. Missing key: {e}"
        ) from e
    except PermissionError as e:
        logger.error("Permission denied: %s", e)
        raise PermissionError(
            f"Insufficient permissions to create database: {e}"
        ) from e
    except Exception as unexpected_error:
        logger.critical(
            "Unexpected error ensuring database exists: %s",
            unexpected_error,
            exc_info=True,
        )
        raise RuntimeError(
            f"Unexpected error during database setup: {unexpected_error}"
        ) from unexpected_error


# ============================================
# Table creation and health
# ============================================

def create_database_tables(engine: Engine) -> list[str]:
    """
    Create all database tables from SQLAlchemy ORM models.

    Args:
        engine: SQLAlchemy engine connected to the target database.

    Returns:
        List of table names present in the database.

    Raises:
        ImportError: If database models are not available.
        RuntimeError: On errors during creation or inspection.
        ValueError: If engine is None.
    """
    if not check_models_available():
        logger.error("Cannot create tables: database models not available")
        raise ImportError(
            "Database models not available or incomplete. "
            "Please check database.py file."
        )

    try:
        if engine is None:
            raise ValueError("Database engine is None")

        base = get_base_model()
        if base is None:
            raise RuntimeError("Base is None despite models being available")

        base.metadata.create_all(bind=engine)
        logger.info("Tables created successfully using Base.metadata")

        inspector_obj = sqlalchemy_inspect(engine)
        if inspector_obj is None:
            raise RuntimeError("Failed to create SQLAlchemy inspector")
        inspector: Inspector = cast(Inspector, inspector_obj)

        tables: list[str] = inspector.get_table_names()

        logger.info("Found %d tables in database", len(tables))
        logger.info("Table list: %s", ', '.join(sorted(tables)))

        for table_name in tables:
            columns = inspector.get_columns(table_name)
            column_names = [col['name'] for col in columns]
            logger.debug(
                "Table '%s': %s", table_name, ', '.join(column_names)
            )

        return tables

    except AttributeError as e:
        logger.error("Attribute error: %s", e, exc_info=True)
        raise RuntimeError(
            f"Database models structure error: {e}"
        ) from e
    except SQLAlchemyError as e:
        logger.error("SQLAlchemy error creating tables: %s", e, exc_info=True)
        raise RuntimeError(
            f"SQLAlchemy error during table creation: {e}"
        ) from e
    except Exception as unexpected_error:
        logger.error(
            "Unexpected error during table verification: %s",
            unexpected_error,
            exc_info=True,
        )
        raise RuntimeError(
            f"Failed to verify database tables: {unexpected_error}"
        ) from unexpected_error


def check_database_health(engine: Engine) -> bool:
    """
    Perform a health check on the database connection and schema.

    Verifies connectivity, PostgreSQL version, and that all tables declared
    in ORM models exist in the database.

    Args:
        engine: SQLAlchemy engine object with an active connection.

    Returns:
        True if database is healthy, False otherwise.
    """
    connection = None
    try:
        connection = engine.connect()

        result = connection.execute(text("SELECT version()"))
        version = result.scalar()
        if version is None:
            logger.warning("Could not retrieve PostgreSQL version")
            return False
        logger.info("PostgreSQL version: %s", version)

        if check_models_available():
            base = get_base_model()
            inspector_obj = sqlalchemy_inspect(engine)
            if inspector_obj is None:
                raise RuntimeError("Failed to create SQLAlchemy inspector")
            inspector: Inspector = cast(Inspector, inspector_obj)
            existing_tables = set(inspector.get_table_names())
            expected_tables = set(base.metadata.tables.keys())

            missing_tables = expected_tables - existing_tables
            if missing_tables:
                logger.warning("Missing tables: %s", missing_tables)
                return False
            logger.info("All tables present (%d tables)", len(expected_tables))

        return True

    except SQLAlchemyError as e:
        logger.error("Error checking database health: %s", e)
        return False
    finally:
        if connection:
            connection.close()


# ============================================
# Metadata reporting
# ============================================

def get_database_info(engine: Engine) -> dict:
    """
    Collect information about the database and its tables.

    Args:
        engine: SQLAlchemy engine connected to the target database.

    Returns:
        Dictionary with database metadata:
            {
                'db_name': str,
                'db_user': str,
                'server_ip': str | None,
                'server_port': int,
                'db_size_mb': float,
                'tables_count': int,
                'tables': {
                    '<name>': {'columns': [...], 'rows': int},
                    ...
                },
            }
        Empty dict on failure.
    """
    info: dict = {}
    connection = None

    try:
        connection = engine.connect()

        result = connection.execute(text("""
            SELECT
                current_database() as db_name,
                current_user as db_user,
                inet_server_addr() as server_ip,
                inet_server_port() as server_port,
                pg_database_size(current_database()) as db_size_bytes
        """))
        row = result.fetchone()

        if row:
            info['db_name'] = row[0] if row[0] is not None else 'unknown'
            info['db_user'] = row[1] if row[1] is not None else 'unknown'
            info['server_ip'] = str(row[2]) if row[2] else None
            info['server_port'] = row[3] if row[3] else 0
            info['db_size_mb'] = (
                round(cast(int, row[4]) / (1024 * 1024), 2)
                if row[4] else 0.0
            )

        inspector_obj = sqlalchemy_inspect(engine)
        if inspector_obj is None:
            raise RuntimeError("Failed to create SQLAlchemy inspector")
        inspector: Inspector = cast(Inspector, inspector_obj)
        tables = inspector.get_table_names()

        info['tables_count'] = len(tables)
        info['tables'] = {}

        for table in tables:
            columns = [col['name'] for col in inspector.get_columns(table)]
            try:
                count_result = connection.execute(
                    text(f'SELECT COUNT(*) FROM "{table}"')
                )
                rows = count_result.scalar() or 0
            except SQLAlchemyError:
                rows = 0

            info['tables'][table] = {
                'columns': columns,
                'rows': rows,
            }

        logger.info(
            "Database info: %s (%d tables, %s MB)",
            info.get('db_name', 'unknown'),
            info.get('tables_count', 0),
            info.get('db_size_mb', 0),
        )
        return info

    except SQLAlchemyError as e:
        logger.error("Error getting database information: %s", e)
        return {}
    finally:
        if connection:
            connection.close()


# ============================================
# Orchestration
# ============================================

def initialize_database() -> Optional[Engine]:
    """
    Primary entry point for database initialization.

    Steps:
        1. Verify ORM models are importable.
        2. Ensure the target database exists (create if missing).
        3. Connect via `connector.connect_to_database()`.
        4. Create missing tables from `Base.metadata`.
        5. Create/replace database views from `database.views`.
        6. Run health check.
        7. Collect and log metadata (per-table columns and row counts).

    Returns:
        SQLAlchemy Engine on success, None otherwise.
    """
    logger.info("=" * 60)
    logger.info("DATABASE INITIALIZATION")
    logger.info("=" * 60)

    # 1. Verify ORM models are importable
    if not check_models_available():
        logger.error(
            "Database models file (database.py) not found or cannot be imported!"
        )
        logger.error(
            "Check if database.py exists and contains valid SQLAlchemy models."
        )
        return None

    try:
        # 2. Ensure the database itself exists
        ensure_database_exists()

        # 3. Connect (retry logic lives in connector.py)
        engine = connect_to_database(
            max_retries=int(os.getenv('DB_MAX_RETRIES', '5')),
            retry_delay=int(os.getenv('DB_RETRY_DELAY', '2')),
        )

        # 4. Create tables from models
        logger.info("Creating/verifying tables from models in database.py...")
        created_tables = create_database_tables(engine)
        logger.info("Tables verified: %d", len(created_tables))

        # 5. Create views (v_active_parts_full, v_part_history, ...)
        logger.info("Creating/verifying database views...")
        try:
            create_views(engine, drop_existing=False)
            logger.info("Views created successfully")
        except Exception as views_error:
            logger.error(
                "Failed to create views: %s", views_error, exc_info=True
            )
            return None

        # 6. Health check
        if not check_database_health(engine):
            logger.error("Database health check FAILED")
            return None
        logger.info("Database health check passed")

        # 7. Report
        db_info = get_database_info(engine)
        if db_info:
            logger.info("Database '%s' ready for use", db_info.get('db_name'))
            logger.info("Tables: %d", db_info.get('tables_count', 0))
            logger.info("Size: %s MB", db_info.get('db_size_mb', 0))

            tables_info = db_info.get('tables', {})
            if tables_info:
                logger.info("Per-table report:")
                for table_name, meta in tables_info.items():
                    logger.info(
                        "  - %-30s columns=%d rows=%d",
                        table_name,
                        len(meta.get('columns', [])),
                        meta.get('rows', 0),
                    )

        logger.info("=" * 60)
        logger.info("INITIALIZATION COMPLETED SUCCESSFULLY")
        logger.info("=" * 60)
        return engine

    except ConnectionError as e:
        logger.error("Critical connection error: %s", e)
        return None
    except Exception as unexpected_error:
        logger.error(
            "Unexpected error: %s", unexpected_error, exc_info=True
        )
        return None


# ============================================
# CLI entry point (for docker-compose `db_initializer` service)
# ============================================

def main() -> int:
    """
    CLI entry point. Returns process exit code (0 = success, 1 = failure).
    """
    try:
        engine = initialize_database()
    except Exception as unexpected_error:
        logger.critical(
            "Fatal error during initialization: %s",
            unexpected_error,
            exc_info=True,
        )
        return 1

    if engine is None:
        logger.error("Database initialization failed")
        return 1

    engine.dispose()
    logger.info("Initializer exiting with success")
    return 0


if __name__ == "__main__":
    sys.exit(main())
