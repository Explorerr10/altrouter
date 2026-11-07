from fastapi import Request

from ..errors import ApiError
from .sessions import SESSION_COOKIE, Session


def require_session(request: Request) -> Session:
    sid = request.cookies.get(SESSION_COOKIE)
    session = request.app.state.sessions.get(sid) if sid else None
    if session is None:
        raise ApiError(401, "auth_required", "Требуется вход в систему")
    return session


def require_admin(request: Request) -> Session:
    session = require_session(request)
    if session.role != "admin":
        raise ApiError(403, "admin_required", "Требуются права администратора")
    return session
