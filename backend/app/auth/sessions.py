import secrets
import time
from dataclasses import dataclass

SESSION_COOKIE = "altrouter_session"


@dataclass
class Session:
    sid: str
    username: str
    role: str
    expires: float


class SessionManager:
    def __init__(self, timeout_seconds: int = 8 * 3600):
        self.timeout_seconds = timeout_seconds
        self._sessions: dict[str, Session] = {}

    def create(self, username: str, role: str) -> Session:
        session = Session(
            sid=secrets.token_urlsafe(32),
            username=username,
            role=role,
            expires=time.time() + self.timeout_seconds,
        )
        self._sessions[session.sid] = session
        return session

    def get(self, sid: str) -> Session | None:
        session = self._sessions.get(sid)
        if session is None:
            return None
        if time.time() > session.expires:
            del self._sessions[sid]
            return None
        session.expires = time.time() + self.timeout_seconds
        return session

    def revoke(self, sid: str) -> None:
        self._sessions.pop(sid, None)

    def revoke_for_user(self, username: str, keep_sid: str | None = None) -> None:
        for sid in [s.sid for s in self._sessions.values() if s.username == username]:
            if sid != keep_sid:
                self.revoke(sid)
