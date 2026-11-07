from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from ..errors import ApiError
from .deps import require_session
from .sessions import SESSION_COOKIE, Session, SessionManager
from .users import UsersStore


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6)


def build_auth_router(users: UsersStore, sessions: SessionManager) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])

    @router.post("/login")
    def login(body: LoginRequest, response: Response) -> dict:
        user = users.verify(body.username, body.password)
        if user is None:
            raise ApiError(401, "invalid_credentials", "Неверное имя пользователя или пароль")
        session = sessions.create(user.username, user.role)
        response.set_cookie(
            SESSION_COOKIE,
            session.sid,
            max_age=sessions.timeout_seconds,
            httponly=True,
            secure=True,
            samesite="strict",
        )
        return {
            "username": user.username,
            "role": user.role,
            "default_password": users.has_default_password(user.username),
        }

    @router.post("/logout")
    def logout(request: Request, response: Response) -> dict:
        sid = request.cookies.get(SESSION_COOKIE)
        if sid:
            sessions.revoke(sid)
        response.delete_cookie(SESSION_COOKIE)
        return {"ok": True}

    @router.get("/me")
    def me(session: Session = Depends(require_session)) -> dict:
        return {
            "username": session.username,
            "role": session.role,
            "default_password": users.has_default_password(session.username),
        }

    @router.post("/password")
    def change_password(
        body: PasswordChangeRequest,
        request: Request,
        session: Session = Depends(require_session),
    ) -> dict:
        if users.verify(session.username, body.old_password) is None:
            raise ApiError(400, "wrong_old_password", "Старый пароль указан неверно")
        users.set_password(session.username, body.new_password)
        sessions.revoke_for_user(session.username, keep_sid=request.cookies.get(SESSION_COOKIE))
        return {"ok": True}

    return router
