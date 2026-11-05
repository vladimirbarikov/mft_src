# pyright: basic
# pyright: reportOptionalMemberAccess=false
# pyright: reportOptionalContextManager=false
# pyright: reportOptionalSubscript=false
# pyright: reportOptionalIterable=false

# pylint: disable=wrong-import-position
"""
Database connection module for Material Flow Table Database with SQLAlchemy 1.4.

This module is responsible ONLY for establishing connections to PostgreSQL.
Database initialization (creating the database, creating tables, health checks,
metadata reporting) lives in `initializer.py`; this module deliberately does
NOT import the ORM models.

Key Features:
    - Environment-based configuration with .env file support
    - Intelligent host detection with multiple fallback strategies
    - Secure connection-string building (password never logged)
    - Engine creation with connection pooling
    - Retry logic with configurable attempts and delays
    - Lightweight connectivity check (`check_connection`)

Architecture:
    This module implements the *connection layer*:
        1. Configuration Layer: environment variable parsing and validation
        2. Detection Layer: automatic host and network configuration detection
        3. Connection Layer: engine creation with retry logic
    Schema and health-check layers live in `initializer.py`.

Dependencies:
    - SQLAlchemy 1.4.54+: ORM and database abstraction layer
    - python-dotenv 1.2.1: Environment variable management (optional but recommended)
    - PostgreSQL 12+: Target database system

Performance Considerations:
    - Connection pooling with configurable pool size and recycling
    - Cached host resolution (one DNS lookup per `get_public_db_config()` call)
    - Configurable retry logic with fixed delay (set `DB_RETRY_DELAY`)

Security Notes:
    - Passwords are never logged: `get_connection_string()` logs a masked URL
    - Public config (`get_public_db_config`) never includes the password
    - Private config (`get_private_db_config`) must never be logged
    - Database credentials are read from .env or environment variables

Error Handling:
    - `ConnectionError` raised after exhausting all retry attempts
    - `SQLAlchemyError` re-raised for database-specific errors
    - Host-resolution failures are logged at DEBUG and do not raise
    - Detailed error messages without exposing sensitive data

Integration Notes:
    - Used by `initializer.py` (database setup), `loader.py` (data loading),
      and `mft_dag.py` (DAG tasks) to obtain an `Engine`
    - Never creates the database or its tables; callers use `initializer.py`
      for that
    - Supports both development (Docker) and production environments
    - Airflow-compatible: engine is safe to create per task

Host Detection Strategy (order):
    1. Environment variable DB_HOST (if resolvable)
    2. localhost (127.0.0.1) for local development
    3. Docker service names (postgres_mft_db, postgres)
    4. host.docker.internal for Docker Desktop
    5. Fallback to localhost with a warning

    A hostname that fails DNS resolution is skipped, not raised. This lets the
    same code run inside Docker (where `db`/`postgres` resolve) and on the host
    (where only `localhost` resolves).

Connection Pool Configuration:
    - pool_size: 5 concurrent connections
    - max_overflow: 10 temporary connections
    - pool_recycle: 3600 seconds (1 hour)
    - pool_pre_ping: True (validate connections before use)
    - connect_timeout: 10 seconds

Environment Variables:
    DB_HOST:        Database hostname (optional, auto-detected)
    DB_PORT:        Database port (default: 5432)
    DB_NAME:        Database name (default: mft_db)
    DB_USER:        Database user (default: mft_user)
    DB_PASSWORD:    Database password (default: mft_password)
    DB_MAX_RETRIES: Connection attempts on initialization (default: 5)
    DB_RETRY_DELAY: Delay between retries in seconds (default: 2)

    Note: DB_MAX_RETRIES / DB_RETRY_DELAY are consumed by `initializer.py`
    when it calls `connect_to_database()`; they are not read here directly.

Note:
    This module is specifically designed for PostgreSQL databases in
    manufacturing data warehouse environments. For other database systems,
    connection strings and SQL dialects would need adjustment.

Usage Example:
    from dags.tasks.connector import connect_to_database, check_connection

    # Get an engine (retry logic included)
    engine = connect_to_database(max_retries=5, retry_delay=2)

    # Lightweight health probe
    if check_connection(engine):
        print("PostgreSQL is reachable")

    # Remember to dispose when done
    engine.dispose()

Maintainer: PLD Engineering Center
Version: 1.0.0
Compatibility: Python 3.14.4+, SQLAlchemy 1.4.54+, PostgreSQL 12+
Created: 2026-01-05
Last Modified: 2026-11-04
License: MIT
Status: Production
"""
# Standard library imports
from pathlib import Path
import os
import sys
import socket
import time
from typing import cast

# Third-party imports
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.engine import Engine

# The relative path to the root project directory
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Add the project path to sys.path
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Local imports
from config import get_logger

# Logger setup
logger = get_logger(__name__)

# Load environment variables
try:
    env_path = PROJECT_ROOT / '.env'

    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
        logger.info("The environment variables are loaded from %s", env_path)
    else:
        logger.debug(".env not found, using system environment")

except (PermissionError, ValueError, UnicodeDecodeError) as e:
    logger.critical("Corrupted .env file: %s", e)
    raise RuntimeError("Invalid .env file") from e

except Exception as unexpected_error:
    logger.critical("Unexpected error: %s", unexpected_error, exc_info=True)
    raise RuntimeError("Environment setup failed") from unexpected_error


def can_resolve_host(host: str) -> bool:
    """
    Check if a hostname can be resolved to an IP address.

    Args:
        host: Hostname or IP address to resolve.

    Returns:
        True if host can be resolved, False otherwise.
    """
    try:
        socket.gethostbyname(host)
        logger.debug("Host %s resolved successfully", host)
        return True
    except socket.gaierror as e:
        logger.debug("Failed to resolve host %s: %s", host, e)
        return False


def determine_db_host() -> str:
    """
    Determine the correct database host using multiple detection strategies.

    Order:
        1. DB_HOST environment variable (if resolvable)
        2. localhost / 127.0.0.1
        3. Docker service names (postgres_mft_db, postgres)
        4. host.docker.internal
        5. Fallback: localhost

    Returns:
        Resolved hostname as a string.
    """
    explicit_host = os.getenv('DB_HOST')
    if explicit_host:
        if can_resolve_host(explicit_host):
            logger.info("Using host from DB_HOST: %s", explicit_host)
            return explicit_host
        logger.warning(
            "Host from DB_HOST (%s) is not available. Switching to automatic detection.",
            explicit_host
        )

    logger.info("Automatic database host detection...")

    test_hosts = [
        'localhost',
        '127.0.0.1',
        'postgres_mft_db',
        'postgres',
        'host.docker.internal',
    ]

    for host in test_hosts:
        if can_resolve_host(host):
            logger.info("Host available: %s", host)
            return host

    logger.warning("Could not determine available host, using localhost")
    return 'localhost'


def get_public_db_config() -> dict:
    """
    Create a safe database configuration for logging (without password).

    Returns:
        Dictionary with keys: host, port, database, user.
    """
    public_config = {
        'host': determine_db_host(),
        'port': os.getenv('DB_PORT', '5432'),
        'database': os.getenv('DB_NAME', 'mft_db'),
        'user': os.getenv('DB_USER', 'mft_user'),
    }

    logger.debug(
        "Public DB config: host=%s, port=%s, database=%s, user=%s",
        public_config['host'], public_config['port'],
        public_config['database'], public_config['user']
    )

    return public_config


def get_private_db_config() -> dict:
    """
    Create a complete database configuration including the password.

    Warning:
        This dictionary contains the password and should never be logged.
    """
    public_config = get_public_db_config()

    private_config = {
        **public_config,
        'password': os.getenv('DB_PASSWORD', 'mft_password'),
    }

    return private_config


def get_connection_string(config: dict | None = None) -> str:
    """
    Build a PostgreSQL connection string from a configuration dictionary.

    Args:
        config: Config dict with 'user', 'password', 'host', 'port', 'database'.
                If None, uses `get_private_db_config()`.

    Returns:
        Connection string in format:
        postgresql+psycopg2://user:password@host:port/database
    """
    if config is None:
        config = get_private_db_config()

    conn_str = (
        f"postgresql+psycopg2://{config['user']}:{config['password']}@"
        f"{config['host']}:{config['port']}/{config['database']}"
    )

    safe_conn_str = (
        f"postgresql+psycopg2://{config['user']}:******@"
        f"{config['host']}:{config['port']}/{config['database']}"
    )
    logger.debug("Connection string: %s", safe_conn_str)

    return conn_str


def connect_to_database(
    max_retries: int = 3,
    retry_delay: int = 2,
) -> Engine:
    """
    Establish a database connection with retry logic.

    This function does NOT create the database or its tables. If the database
    does not exist yet, use `initializer.initialize_database()` first.

    Args:
        max_retries: Maximum number of connection attempts.
        retry_delay: Delay in seconds between retry attempts.

    Returns:
        SQLAlchemy Engine object configured with connection pooling.

    Raises:
        ConnectionError: After exhausting all retry attempts.
        SQLAlchemyError: For database-specific errors during connection.
        RuntimeError: For unexpected errors during connection setup.
    """
    public_config = get_public_db_config()
    private_config = get_private_db_config()

    logger.info(
        "Connecting to PostgreSQL: %s:%s/%s",
        public_config['host'], public_config['port'], public_config['database']
    )
    logger.info("Parameters: attempts=%d, delay=%ds", max_retries, retry_delay)

    for attempt in range(max_retries):
        try:
            logger.info("Connection attempt %d/%d", attempt + 1, max_retries)

            connection_string = get_connection_string(private_config)

            engine: Engine = cast(
                Engine,
                create_engine(
                    connection_string,
                    echo=False,
                    pool_pre_ping=True,
                    pool_size=5,
                    max_overflow=10,
                    pool_recycle=3600,
                    connect_args={'connect_timeout': 10},
                ),
            )

            connection = None
            try:
                connection = engine.connect()
                result = connection.execute(text("SELECT 1"))
                if result.scalar() == 1:
                    logger.info(
                        "Database connection successful (attempt %d/%d)",
                        attempt + 1, max_retries
                    )
                    return engine
                else:
                    logger.warning(
                        "Unexpected result from SELECT 1 on attempt %d/%d",
                        attempt + 1, max_retries
                    )
            finally:
                if connection:
                    connection.close()

        except OperationalError as e:
            logger.warning("Attempt %d/%d failed: %s", attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                logger.info("Retrying in %d seconds...", retry_delay)
                time.sleep(retry_delay)
            else:
                logger.error("Failed to connect to database after all attempts")
                raise ConnectionError(
                    f"Failed to connect to database after {max_retries} attempts"
                ) from e

        except SQLAlchemyError as e:
            logger.error("SQLAlchemy connection error: %s", e)
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                raise

        except Exception as unexpected_error:
            logger.error("Unexpected error: %s", unexpected_error)
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                raise

    raise ConnectionError("Failed to connect to database")


def check_connection(engine: Engine) -> bool:
    """
    Lightweight connectivity check for an already-built Engine.

    Args:
        engine: SQLAlchemy engine.

    Returns:
        True if a simple `SELECT 1` succeeds, False otherwise.
    """
    connection = None
    try:
        connection = engine.connect()
        result = connection.execute(text("SELECT 1"))
        return result.scalar() == 1
    except SQLAlchemyError as e:
        logger.error("Connectivity check failed: %s", e)
        return False
    finally:
        if connection:
            connection.close()
