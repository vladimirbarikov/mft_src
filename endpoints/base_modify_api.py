# pylint: disable=too-many-lines
# pylint: disable=line-too-long
# pylint: disable=wrong-import-position
"""
Base Modify API Module for Material Flow Table Database.

This module provides a base class with common functionality for all modification APIs:
- Database connection management
- Error handling
- Virtual breakpoint creation (MANYYNNNNN)
- Audit field population
- Flask app setup

The BaseModifyService class is designed to be inherited by specific modification APIs:
    - MFTModifyAPI: ****
    - BPModifyAPI: ****

Version: 1.0.0
Compatibility: Python 3.14.4+, Flask 6.0.2+, SQLAlchemy 1.4.54+
Maintainer: PLD Engineering Center
Created: 2026-11-12
Last Modified: 2026-11-12
License: MIT
Status: Development
"""

# Standard library imports
from pathlib import Path
import sys
import os
from datetime import datetime
from functools import wraps, lru_cache
from typing import Any, Optional
import zoneinfo

# Third-party imports
from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

# The relative path to the root project directory
try:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
except NameError:
    PROJECT_ROOT = Path("/opt/airflow")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load environment variables
env_path = PROJECT_ROOT / '.env'
load_dotenv(dotenv_path=env_path)

# Local imports
from config import get_logger
from dags.tasks.connector import connect_to_database
from database.database import BreakpointData
from endpoints.auth import get_current_user_id

# Logger setup
logger = get_logger(__name__)

# ========== TIMEZONE ==========
MOSCOW_TZ = zoneinfo.ZoneInfo("Europe/Moscow")

# ========== CONFIGURATION ==========
FLASK_SECRET_KEY = os.getenv('FLASK_SECRET_KEY')
if not FLASK_SECRET_KEY:
    raise RuntimeError("FLASK_SECRET_KEY must be set in .env file")

FLASK_ENV = os.getenv('FLASK_ENV', 'development')
IS_PRODUCTION = FLASK_ENV == 'production'

ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', '*')
RATE_LIMIT = os.getenv('RATE_LIMIT', '10 per minute')
RATE_LIMIT_STORAGE_URL = os.getenv('RATE_LIMIT_STORAGE_URL', 'memory://')

# ========== RATE LIMITING ==========
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=RATE_LIMIT_STORAGE_URL,
    default_limits=["200 per day", "50 per hour"],
    strategy="fixed-window"
)

def rate_limit(limit_string: Optional[str] = None):
    """Decorator factory for applying rate limits to endpoints."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            return limiter.limit(limit_string or RATE_LIMIT)(f)(*args, **kwargs)
        return wrapped
    return decorator

# ========== DATABASE ==========
@lru_cache(maxsize=1)
def get_engine():
    """Return the process-wide engine (created lazily, cached)."""
    return connect_to_database(
        max_retries=int(os.getenv('DB_MAX_RETRIES', '5')),
        retry_delay=int(os.getenv('DB_RETRY_DELAY', '2')),
    )

def get_db_session() -> Session:
    """Get a database session bound to the process-wide engine."""
    return Session(get_engine())

# ========== DECORATORS ==========
def handle_api_response(f):
    """Decorator to handle API responses and errors."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            result = f(*args, **kwargs)
            if isinstance(result, tuple):
                return result
            if isinstance(result, dict):
                if result.get('error'):
                    status_code = result.get('status_code', 500)
                    return jsonify(result), status_code
                return jsonify(result)
            return result

        except ValueError as e:
            return jsonify({
                'success': False,
                'error': str(e)
            }), 400

        except RuntimeError as e:
            logger.error("Runtime error: %s", e)
            return jsonify({
                'success': False,
                'error': 'Service error'
            }), 503

        except Exception as e:
            logger.error("Unexpected error: %s", e, exc_info=True)
            return jsonify({
                'success': False,
                'error': 'Internal server error'
            }), 500

    return wrapper

# ========== BASE SERVICE ==========
class BaseModifyService:
    """Base service for manual modifications."""

    def __init__(self, session: Session):
        self.session = session

    def create_virtual_breakpoint(
        self,
        description: str,
        change_domain: str,
        change_nature: str,
        changed_by: str
    ) -> BreakpointData:
        """
        Create a virtual breakpoint (MANYYNNNNN) for manual changes.
        """
        yy = datetime.now(MOSCOW_TZ).strftime('%y')  # e.g., '26'

        count_query = text("""
            SELECT COUNT(*)
            FROM breakpoint_data
            WHERE breakpoint_number LIKE :pattern
        """)
        pattern = f"MAN{yy}%"
        count = self.session.execute(count_query, {'pattern': pattern}).scalar() or 0
        seq = str(count + 1).zfill(5)
        breakpoint_number = f"MAN{yy}{seq}"  # e.g. MAN2600001

        bp = BreakpointData()
        bp.breakpoint_number = breakpoint_number
        bp.breakpoint_status = 'closed'
        bp.breakpoint_date = datetime.now(MOSCOW_TZ)
        bp.description = description.strip()
        bp.solution = f"Manual change by {changed_by}"
        bp.change_domain = change_domain
        bp.change_nature = change_nature

        # Set audit fields if the user ID is available
        try:
            user_id = get_current_user_id()
            if user_id:
                bp.created_by_user_id = user_id
                bp.updated_by_user_id = user_id
        except (ImportError, RuntimeError):
            pass

        self.session.add(bp)
        self.session.flush()

        logger.info(
            "Created virtual breakpoint %s (domain=%s, nature=%s)",
            breakpoint_number, change_domain, change_nature
        )

        return bp

    def apply_audit_fields(self, instance: Any, is_update: bool = False):
        """
        Automatically set audit fields (created_by/updated_by) on a model instance.
        """
        try:
            user_id = get_current_user_id()
            if user_id:
                if not is_update:
                    instance.created_by_user_id = user_id
                instance.updated_by_user_id = user_id
        except (ImportError, RuntimeError):
            # Fail silently if outside request context or auth not available
            pass

# ========== FLASK APP SETUP ==========
def create_modify_app(blueprint, service_name: str) -> Flask:
    """Create and configure the Flask application instance for a modify API."""
    app = Flask(__name__)
    app.secret_key = FLASK_SECRET_KEY

    # CORS
    if ALLOWED_ORIGINS == "*":
        CORS(app)
    else:
        origins = [origin.strip() for origin in ALLOWED_ORIGINS.split(',')]
        CORS(app, origins=origins, supports_credentials=True)

    # Security headers
    @app.after_request
    def add_security_headers(response):
        if IS_PRODUCTION:
            response.headers.add('X-Content-Type-Options', 'nosniff')
            response.headers.add('X-Frame-Options', 'DENY')
            response.headers.add('X-XSS-Protection', '1; mode=block')
        return response

    # Register blueprint
    app.register_blueprint(blueprint)

    # Rate limiting
    limiter.init_app(app)

    # Error handlers
    @app.errorhandler(404)
    def not_found(_):
        return jsonify({'success': False, 'error': 'Resource not found'}), 404

    @app.errorhandler(429)
    def ratelimit_handler(_):
        return jsonify({
            'success': False,
            'error': 'Rate limit exceeded. Please try again later.'
        }), 429

    logger.info("%s Flask app created", service_name)
    return app
