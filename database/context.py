"""
Per-execution-context identity for audit triggers.

Single source of truth for "who is doing this DML right now".
- HTTP request: set by jwt_required decorator (endpoints/auth.py).
- Airflow task: set explicitly, or left as None (anonymous).
- CLI scripts: set explicitly, or left as None.

Read by the SQLAlchemy "after_begin" event in connector.py, which forwards
both values to PostgreSQL as transaction-scoped GUCs:
    app.current_user_id   <- _current_user_id.get()   (preferred)
    app.current_username  <- _current_username.get()  (fallback)

The trigger resolves identity in order: uid -> username -> NULL.
"""
from contextvars import ContextVar
from typing import Optional

_current_username: ContextVar[Optional[str]] = ContextVar(
    'current_username', default=None
)
_current_user_id: ContextVar[Optional[str]] = ContextVar(
    'current_user_id', default=None
)


def set_current_identity(
    username: Optional[str],
    user_id: Optional[str] = None,
) -> None:
    """Set identity for the current execution context."""
    _current_username.set(username)
    _current_user_id.set(user_id)


def get_current_username() -> Optional[str]:
    return _current_username.get()


def get_current_user_id() -> Optional[str]:
    return _current_user_id.get()


def reset_current_identity() -> None:
    """Reset to anonymous. Use in tests and at the start of Airflow tasks."""
    _current_username.set(None)
    _current_user_id.set(None)
