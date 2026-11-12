# pylint: disable=too-many-lines
# pylint: disable=line-too-long
# pylint: disable=wrong-import-position
"""
Flask API for Database User Management.

This module provides a REST API for creating and managing PostgreSQL users
with different privilege levels through Flask endpoints.

Endpoints:
    POST /api/users/create - Create a new user with specified role
    GET /api/users/test-connection/<username> - Test user connection
    GET /api/users/list - Get list of all users
    DELETE /api/users/delete/<username> - Delete a user

Components used:
    - Flask: Web framework for creating API
    - SQLAlchemy: For executing administrative SQL queries
    - user_roles.py: User role management module

Usage example:
    Creating an administrator:
    POST /api/users/create
    {
        "username": "sys_admin",
        "password": "secure_password_123",
        "role": "admin",
        "description": "System administrator"
    }

    Testing connection:
    GET /api/users/test-connection/sys_admin

    Getting user list:
    GET /api/users/list

    Deleting a user:
    DELETE /api/users/delete/sys_admin

Environment requirements:
    - Installed libraries: Flask, SQLAlchemy, python-dotenv, psycopg2-binary
    - Configured .env file with database connection parameters
    - Access to PostgreSQL with administrative privileges

Version: 1.0.0
Compatibility: Python 3.14.4+, Flask 6.0.2+
Maintainer: PLD Engineering Center
Created: 2025
Last Modified: 2025
License: MIT
Status: Production
"""
# Standard library imports
from pathlib import Path
import sys
import os

# Third-party imports
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from sqlalchemy import create_engine, text, or_
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError, OperationalError, ProgrammingError, IntegrityError
from werkzeug.security import generate_password_hash

# The relative path to the root project directory
try:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
except NameError:
    PROJECT_ROOT = Path("/opt/airflow")

# Add the project path to sys.path
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load environment variables
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)

# Local imports
from config import get_logger
from database.user_roles import DatabaseAdmin, DatabaseEditor, DatabaseViewer
from database.database import UserData, UserRoleData, DepartmentData
from endpoints.auth import jwt_required, role_required, ROLES

# Logger setup
logger = get_logger(__name__)


# Create Flask application
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

# Configuration from environment variables
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'mft_db')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD')


def get_admin_engine():
    """Create connection with administrative privileges"""
    try:
        connection_string = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        engine = create_engine(connection_string, isolation_level="AUTOCOMMIT")
        return engine
    except OperationalError as e:
        logger.error("Database connection error: %s", e)
        return None
    except Exception as e:
        logger.error("Unexpected error creating engine: %s", e)
        return None


def get_db_session() -> Session:
    """Create a session for application database (user_data)"""
    engine = get_admin_engine()
    if not engine:
        raise RuntimeError("Failed to connect to application database")
    SessionMaker = sessionmaker(bind=engine)
    return SessionMaker()


@app.route('/api/users/create', methods=['POST'])
@jwt_required
@role_required([ROLES['ADMIN']])
def create_user():
    """
    Create a new database user (syncs pg_roles and user_data)
    """
    try:
        # Check JSON
        if not request.is_json:
            return jsonify({
                'success': False,
                'error': 'Content-Type must be application/json'
            }), 415

        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'JSON request body is required'
            }), 400

        # Added 'email' to required fields because UserData requires it
        required_fields = ['username', 'password', 'role', 'email']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400

        username = data['username'].strip()
        password = data['password']
        role = data['role'].lower().strip()
        email = data['email'].strip()
        description = data.get('description', '')
        department_code = data.get('department_code')

        # User name validation
        if not username or len(username) > 50:
            return jsonify({
                'success': False,
                'error': 'Username must be between 1 and 50 characters'
            }), 400

        # Password validation
        if not password:
            return jsonify({
                'success': False,
                'error': 'Password cannot be empty'
            }), 400

        # Role validation
        valid_roles = ['admin', 'editor', 'viewer']
        if role not in valid_roles:
            return jsonify({
                'success': False,
                'error': f'Invalid role. Valid values: {", ".join(valid_roles)}'
            }), 400

        # 1. Create Postgres Role
        if role == 'admin':
            user = DatabaseAdmin(username, password, description)
        elif role == 'editor':
            user = DatabaseEditor(username, password, description)
        else:  # viewer
            user = DatabaseViewer(username, password, description)

        result = user.create_db_user()

        if not result:
            logger.error("Failed to create PG user '%s'", username)
            return jsonify({
                'success': False,
                'error': f'Failed to create PG user {username}'
            }), 500

        # 2. Sync to Application Database (user_data)
        try:
            session = get_db_session()
        except RuntimeError as e:
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

        try:
            # Check if user already exists in app db
            existing_user_by_name = session.query(UserData).filter_by(username=username).first()
            existing_user_by_email = session.query(UserData).filter_by(email=email).first()

            if existing_user_by_name or existing_user_by_email:
                session.rollback()
                return jsonify({
                    'success': False,
                    'error': 'User with this username or email already exists in application DB'
                }), 409

            # Find role_id
            user_role = session.query(UserRoleData).filter_by(role_code=role).first()

            if not user_role:
                session.rollback()
                return jsonify({
                    'success': False,
                    'error': f'Role {role} not found in user_role_data. Please run DB initializer.'
                }), 500

            # Find department_id (optional)
            dept_id = None
            if department_code:
                dept = session.query(DepartmentData).filter_by(department_code=department_code).first()
                if dept:
                    dept_id = dept.department_id

            # Create app user record
            new_app_user = UserData()
            new_app_user.username = username
            new_app_user.email = email
            new_app_user.hashed_password = generate_password_hash(password)
            new_app_user.role_id = user_role.role_id
            new_app_user.department_id = dept_id
            new_app_user.full_name = description
            new_app_user.is_active = True

            session.add(new_app_user)
            session.commit()
            logger.info("Application user '%s' successfully created in user_data", username)

        except Exception as db_error:
            session.rollback()
            logger.error("Error creating application user '%s': %s", username, db_error)
            return jsonify({
                'success': False,
                'error': f'PG Role created, but failed to sync to application DB: {str(db_error)}'
            }), 500
        finally:
            session.close()

        return jsonify({
            'success': True,
            'message': f'User {username} created successfully (PG + App)',
            'user': {
                'username': username,
                'email': email,
                'role': role,
                'description': description,
                'connection_string': user.get_connection_string()
            }
        }), 201

    except Exception as e:
        logger.error("Unexpected error creating user: %s", e)
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500


@app.route('/api/users/test-connection/<username>', methods=['GET'])
@jwt_required
@role_required([ROLES['ADMIN']])
def test_user_connection(username: str):
    """
    Test user connection to database
    """
    engine = None
    try:
        if not username or not username.strip():
            return jsonify({
                'success': False,
                'error': 'Username is required'
            }), 400

        username = username.strip()

        engine = get_admin_engine()
        if not engine:
            return jsonify({
                'success': False,
                'error': 'Failed to connect to database'
            }), 500

        with engine.connect() as connection:
            query = text("""
                SELECT 
                    rolname,
                    rolsuper,
                    rolcanlogin,
                    rolcreatedb,
                    rolcreaterole
                FROM pg_roles 
                WHERE rolname = :username
            """)
            result = connection.execute(query, {'username': username})
            user_info = result.fetchone()

            if not user_info:
                return jsonify({
                    'success': False,
                    'error': f'User {username} not found'
                }), 404

            user_info_dict = {
                'rolname': user_info[0],
                'rolsuper': user_info[1],
                'rolcanlogin': user_info[2],
                'rolcreatedb': user_info[3],
                'rolcreaterole': user_info[4]
            }

            if not user_info_dict['rolcanlogin']:
                return jsonify({
                    'success': False,
                    'error': f'User {username} does not have login permission'
                }), 400

            return jsonify({
                'success': True,
                'message': f'User {username} exists and can connect',
                'user_info': {
                    'username': user_info_dict['rolname'],
                    'is_superuser': user_info_dict['rolsuper'],
                    'can_login': user_info_dict['rolcanlogin'],
                    'can_create_db': user_info_dict['rolcreatedb'],
                    'can_create_roles': user_info_dict['rolcreaterole']
                }
            })

    except OperationalError as e:
        logger.error("Database connection error testing user %s: %s", username, e)
        return jsonify({
            'success': False,
            'error': 'Database connection failed'
        }), 500

    except ProgrammingError as e:
        logger.error("SQL error testing user %s: %s", username, e)
        return jsonify({
            'success': False,
            'error': 'Database query error'
        }), 500

    except Exception as e:
        logger.error("Unexpected error testing user %s: %s", username, e)
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

    finally:
        if engine:
            engine.dispose()


@app.route('/api/users/list', methods=['GET'])
@jwt_required
@role_required([ROLES['ADMIN']])
def list_users():
    """
    Get list of all database users
    """
    engine = None
    try:
        connection_string = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        engine = create_engine(connection_string)

        with engine.connect() as connection:
            query = text("""
                SELECT 
                    rolname as username,
                    rolsuper as is_superuser,
                    rolcanlogin as can_login,
                    rolcreatedb as can_create_db,
                    rolcreaterole as can_create_roles,
                    rolconnlimit as connection_limit,
                    rolvaliduntil as password_valid_until
                FROM pg_roles 
                WHERE rolcanlogin = true 
                ORDER BY rolname
            """)
            result = connection.execute(query)
            users = []

            for row in result:
                users.append({
                    'username': row[0],
                    'is_superuser': row[1],
                    'can_login': row[2],
                    'can_create_db': row[3],
                    'can_create_roles': row[4],
                    'connection_limit': row[5],
                    'password_valid_until': str(row[6]) if row[6] else None
                })

            return jsonify({
                'success': True,
                'users': users,
                'count': len(users)
            })

    except OperationalError as e:
        logger.error("Database connection error getting user list: %s", e)
        return jsonify({
            'success': False,
            'error': 'Database connection failed'
        }), 500

    except ProgrammingError as e:
        logger.error("SQL error getting user list: %s", e)
        return jsonify({
            'success': False,
            'error': 'Database query error'
        }), 500

    except Exception as e:
        logger.error("Unexpected error getting user list: %s", e)
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

    finally:
        if engine:
            engine.dispose()


@app.route('/api/users/delete/<username>', methods=['DELETE'])
@jwt_required
@role_required([ROLES['ADMIN']])
def delete_user(username: str):
    """
    Delete a database user (PG + soft delete in App DB)
    """
    engine = None

    try:
        if not username or not username.strip():
            return jsonify({
                'success': False,
                'error': 'Username is required'
            }), 400

        username = username.strip()

        # Check for protected users
        protected_users = [DB_USER, 'postgres']
        if username in protected_users:
            return jsonify({
                'success': False,
                'error': f'Cannot delete system user {username}'
            }), 400

        # 1. Soft delete from application DB (user_data)
        try:
            session = get_db_session()
            app_user = session.query(UserData).filter_by(username=username).first()
            if app_user:
                app_user.is_active = False
                session.commit()
                logger.info("Application user '%s' soft-deleted (is_active=False)", username)
        except RuntimeError as e:
            logger.warning("Could not connect to application DB for soft delete: %s", e)
        finally:
            if session:
                session.close()

        # 2. Drop role from PostgreSQL
        engine = get_admin_engine()
        if not engine:
            return jsonify({
                'success': False,
                'error': 'Failed to connect to database'
            }), 500

        with engine.connect() as connection:
            # Verifying the user's existence
            check_query = text("SELECT 1 FROM pg_roles WHERE rolname = :username")
            result = connection.execute(check_query, {'username': username})

            if not result.fetchone():
                return jsonify({
                    'success': True,
                    'message': f'User {username} not found in PostgreSQL, but App DB updated if existed.'
                })

            try:
                # Revocation of privileges
                revoke_query = text(f"REVOKE ALL PRIVILEGES FROM {username}")
                connection.execute(revoke_query)

                # Deleting a role
                delete_query = text(f"DROP ROLE IF EXISTS {username}")
                connection.execute(delete_query)

            except ProgrammingError as e:
                error_msg = str(e)
                if "cannot be dropped" in error_msg and "has dependent objects" in error_msg:
                    return jsonify({
                        'success': False,
                        'error': f'Cannot delete PG role {username} because they own database objects.'
                    }), 409
                elif "cannot be dropped" in error_msg and "active sessions" in error_msg:
                    return jsonify({
                        'success': False,
                        'error': f'Cannot delete PG role {username} because they have active sessions.'
                    }), 409
                else:
                    raise

            logger.info("PG User '%s' successfully deleted", username)
            return jsonify({
                'success': True,
                'message': f'User {username} successfully deleted (PG dropped, App DB disabled)'
            })

    except OperationalError as e:
        logger.error("Database connection error deleting user %s: %s", username, e)
        return jsonify({'success': False, 'error': 'Database connection failed'}), 500
    except Exception as e:
        logger.error("Unexpected error deleting user %s: %s", username, e)
        return jsonify({'success': False, 'error': 'Internal server error'}), 500
    finally:
        if session:
            session.close()
        if engine:
            engine.dispose()


@app.route('/api/health', methods=['GET'])
def health_check():
    """Check API and database connection health"""
    engine = None
    try:
        connection_string = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        engine = create_engine(connection_string)

        with engine.connect() as connection:
            result = connection.execute(text("SELECT version(), current_timestamp, current_database()"))
            row = result.fetchone()
            db_version = row[0]
            timestamp = row[1]
            db_name = row[2]

            return jsonify({
                'status': 'healthy',
                'message': 'API and database are working normally',
                'database': {
                    'available': True,
                    'version': db_version,
                    'name': db_name,
                    'timestamp': str(timestamp)
                }
            })

    except OperationalError as e:
        logger.error("Database connection health check failed: %s", e)
        return jsonify({
            'status': 'degraded',
            'message': 'Database connection failed',
            'database': {
                'available': False,
                'error': str(e)
            }
        }), 500

    except Exception as e:
        logger.error("Health check error: %s", e)
        return jsonify({
            'status': 'error',
            'message': 'Internal server error',
            'database': 'unknown'
        }), 500

    finally:
        if engine:
            engine.dispose()

@app.errorhandler(404)
def not_found(_error):
    """Handler for non-existent endpoints"""
    return jsonify({
        'success': False,
        'error': 'Endpoint not found'
    }), 404


@app.errorhandler(405)
def method_not_allowed(_error):
    """Handler for invalid HTTP methods"""
    return jsonify({
        'success': False,
        'error': 'Method not allowed for this endpoint'
    }), 405

if __name__ == '__main__':
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port_str = os.getenv('FLASK_PORT', '5000')
    port = int(port_str)
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

    logger.info("Starting User Manager API on %s:%s", host, port)
    logger.info("Debug mode: %s", debug)
    logger.info("Database connection: %s:%s/%s", DB_HOST, DB_PORT, DB_NAME)

    app.run(host=host, port=port, debug=debug)
