import asyncio
import ipaddress
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator, model_validator

from ..auth.deps import require_admin, require_session
from ..auth.sessions import Session, SessionManager
from ..auth.users import UsersStore
from ..errors import ApiError
from ..network.manager import InterfaceManager
from . import service
from .service import AccessStore, SystemError


class UserIn(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,32}$")
    password: str = Field(min_length=6)
    role: Literal["admin", "viewer"] = "viewer"


class UserPatch(BaseModel):
    password: str | None = Field(default=None, min_length=6)
    role: Literal["admin", "viewer"] | None = None


class PingIn(BaseModel):
    host: str
    count: int = Field(default=4, ge=1, le=10)


class HostIn(BaseModel):
    host: str


class TcpdumpIn(BaseModel):
    iface: str
    filter: str = ""
    seconds: int = Field(default=10, ge=5, le=60)


class SshIn(BaseModel):
    enabled: bool


class SshConfigIn(BaseModel):
    port: int = Field(ge=1, le=65535)
    allow_subnet: str | None = None
    password_auth: bool = True

    @field_validator("allow_subnet", mode="before")
    @classmethod
    def _strip(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def _check(self) -> "SshConfigIn":
        if self.port == 9000:
            raise ValueError("Порт 9000 занят панелью управления")
        if self.allow_subnet:
            try:
                net = ipaddress.ip_network(self.allow_subnet)
            except ValueError as e:
                raise ValueError(f"Некорректная подсеть: {self.allow_subnet!r}") from e
            if net.version != 4:
                raise ValueError("Подсеть должна быть IPv4")
            self.allow_subnet = str(net)
        return self


class SshKeyIn(BaseModel):
    user: str = Field(pattern=r"^[a-z_][a-z0-9_-]{0,31}$")
    key: str = Field(min_length=20, max_length=4096)


class TlsIn(BaseModel):
    cert: str
    key: str


class TlsGenerateIn(BaseModel):
    hosts: list[str] = Field(min_length=1, max_length=64)


class AccessIn(BaseModel):
    management_only: bool


class PowerIn(BaseModel):
    action: Literal["reboot", "poweroff"]


def _http(status: int, message: str, code: str) -> ApiError:
    return ApiError(status, code, message)


def build_system_router(
    users: UsersStore, sessions: SessionManager, network: InterfaceManager, config_dir
) -> APIRouter:
    router = APIRouter(prefix="/system", tags=["system"])
    config_dir = Path(config_dir)

    def log(action: str, session: Session, **extra) -> None:
        network.journal_entry(action, session.username, **extra)

    # ---------- пользователи панели ----------

    def find(username: str):
        return next((u for u in users.load() if u.username == username), None)

    @router.get("/users")
    def list_users(_admin: Session = Depends(require_admin)) -> list:
        return [{"username": u.username, "role": u.role} for u in users.load()]

    @router.post("/users", status_code=201)
    def add_user(body: UserIn, session: Session = Depends(require_admin)) -> dict:
        try:
            user = users.create(body.username, body.password, body.role)
        except ValueError as e:
            raise _http(400, str(e), "user_invalid") from e
        log("user_created", session, target=body.username, role=body.role)
        return {"username": user.username, "role": user.role}

    @router.put("/users/{username}")
    def edit_user(
        username: str, body: UserPatch, session: Session = Depends(require_admin)
    ) -> dict:
        if body.role and username == session.username:
            raise _http(400, "Нельзя менять роль собственной учётной записи", "self_role")
        target = find(username)
        if target is None:
            raise _http(404, f"Пользователь {username!r} не найден", "user_not_found")
        if (
            body.role == "viewer"
            and target.role == "admin"
            and users.count_admins() <= 1
        ):
            raise _http(400, "Должен остаться хотя бы один администратор", "last_admin")
        changed = False
        if body.password:
            changed = users.set_password(username, body.password) or changed
        if body.role:
            changed = users.set_role(username, body.role) or changed
        if not changed:
            raise _http(400, "Нечего изменять", "nothing_changed")
        if body.password:
            sessions.revoke_for_user(username)
        log("user_updated", session, target=username)
        return {"ok": True}

    @router.delete("/users/{username}")
    def delete_user(username: str, session: Session = Depends(require_admin)) -> dict:
        if username == session.username:
            raise _http(400, "Нельзя удалить собственную учётную запись", "self_delete")
        target = find(username)
        if target is None:
            raise _http(404, f"Пользователь {username!r} не найден", "user_not_found")
        if target.role == "admin" and users.count_admins() <= 1:
            raise _http(400, "Должен остаться хотя бы один администратор", "last_admin")
        users.remove(username)
        sessions.revoke_for_user(username)
        log("user_deleted", session, target=username)
        return {"ok": True}

    # ---------- резервная копия конфигурации ----------

    @router.get("/backup")
    def download_backup(_admin: Session = Depends(require_admin)) -> Response:
        data = service.backup_pack(config_dir)
        filename = f"altrouter-backup-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz"
        return Response(
            data,
            media_type="application/gzip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.put("/backup")
    async def upload_backup(request: Request, session: Session = Depends(require_admin)) -> dict:
        data = await request.body()
        if not data:
            raise _http(400, "Пустое тело запроса — ожидается архив .tar.gz", "backup_empty")
        try:
            restored = service.backup_restore(config_dir, data)
        except SystemError as e:
            raise _http(400, str(e), "backup_invalid") from e
        log("backup_restored", session, files=restored)
        return {"ok": True, "restored": restored}

    # ---------- журнал применённых изменений ----------

    @router.get("/journal")
    def get_journal(limit: int = 100, _s: Session = Depends(require_session)) -> list:
        return network.journal(max(1, min(1000, limit)))

    # ---------- диагностика ----------

    @router.post("/diag/ping")
    async def diag_ping(body: PingIn, _s: Session = Depends(require_session)) -> dict:
        try:
            return {"output": await asyncio.to_thread(service.diag_ping, body.host, body.count)}
        except SystemError as e:
            raise _http(400, str(e), "diag_failed") from e

    @router.post("/diag/traceroute")
    async def diag_traceroute(body: HostIn, _s: Session = Depends(require_session)) -> dict:
        try:
            return {"output": await asyncio.to_thread(service.diag_traceroute, body.host)}
        except SystemError as e:
            raise _http(400, str(e), "diag_failed") from e

    @router.post("/diag/tcpdump")
    async def diag_tcpdump(body: TcpdumpIn, _admin: Session = Depends(require_admin)) -> dict:
        try:
            output = await asyncio.to_thread(
                service.diag_tcpdump, body.iface, body.filter, body.seconds
            )
        except SystemError as e:
            raise _http(400, str(e), "diag_failed") from e
        return {"output": output}

    # ---------- системный журнал ----------

    @router.get("/logs")
    def get_logs(
        unit: str = "altrouter", lines: int = 200, _s: Session = Depends(require_session)
    ) -> dict:
        try:
            return {"output": service.system_log(unit, lines)}
        except SystemError as e:
            raise _http(400, str(e), "logs_failed") from e

    # ---------- доступ: SSH, TLS, интерфейс ----------

    @router.get("/ssh")
    def ssh_status(_s: Session = Depends(require_session)) -> dict:
        return service.ssh_status()

    @router.put("/ssh")
    def ssh_set(body: SshIn, session: Session = Depends(require_admin)) -> dict:
        try:
            service.ssh_set(body.enabled)
        except SystemError as e:
            raise _http(500, str(e), "ssh_failed") from e
        log("ssh_enabled" if body.enabled else "ssh_disabled", session)
        return service.ssh_status()

    @router.put("/ssh/config")
    def ssh_config(body: SshConfigIn, session: Session = Depends(require_admin)) -> dict:
        try:
            service.ssh_apply(body.port, body.allow_subnet, body.password_auth)
        except SystemError as e:
            raise _http(500, str(e), "ssh_failed") from e
        log(
            "ssh_config",
            session,
            port=body.port,
            allow_subnet=body.allow_subnet,
            password_auth=body.password_auth,
        )
        return service.ssh_status()

    @router.get("/ssh/users")
    def ssh_users(_admin: Session = Depends(require_admin)) -> list:
        return service.ssh_users()

    def ssh_user_exists(name: str) -> bool:
        return any(u["username"] == name for u in service.ssh_users())

    @router.get("/ssh/keys")
    def ssh_keys_list(user: str, _admin: Session = Depends(require_admin)) -> list:
        if not ssh_user_exists(user):
            raise _http(404, f"Пользователь {user!r} не найден", "user_not_found")
        try:
            return service.ssh_keys_list(user)
        except SystemError as e:
            raise _http(400, str(e), "ssh_failed") from e

    @router.put("/ssh/keys")
    def ssh_key_add(body: SshKeyIn, session: Session = Depends(require_admin)) -> dict:
        if body.user == "root":
            raise _http(400, "SSH-ключ для root добавлять нельзя", "root_key_forbidden")
        if not ssh_user_exists(body.user):
            raise _http(404, f"Пользователь {body.user!r} не найден", "user_not_found")
        try:
            fingerprint = service.ssh_key_add(body.user, body.key)
        except SystemError as e:
            raise _http(400, str(e), "ssh_failed") from e
        log("ssh_key_added", session, target=body.user, fingerprint=fingerprint)
        return {"ok": True, "fingerprint": fingerprint}

    @router.delete("/ssh/keys/{user}/{index}")
    def ssh_key_del(
        user: str, index: int, session: Session = Depends(require_admin)
    ) -> dict:
        if not ssh_user_exists(user):
            raise _http(404, f"Пользователь {user!r} не найден", "user_not_found")
        try:
            service.ssh_key_del(user, index)
        except SystemError as e:
            raise _http(400, str(e), "ssh_failed") from e
        log("ssh_key_deleted", session, target=user)
        return {"ok": True}

    @router.get("/tls")
    def tls_info(_s: Session = Depends(require_session)) -> dict:
        cert_path, _ = service.tls_paths()
        try:
            return service.tls_info(cert_path)
        except SystemError as e:
            return {"error": str(e)}

    @router.put("/tls")
    def tls_set(body: TlsIn, session: Session = Depends(require_admin)) -> dict:
        cert_path, key_path = service.tls_paths()
        try:
            service.tls_set(body.cert, body.key, cert_path, key_path)
        except SystemError as e:
            raise _http(400, str(e), "tls_failed") from e
        log("tls_updated", session)
        return {"ok": True, "need_restart": True}

    @router.post("/tls/generate")
    def tls_generate(body: TlsGenerateIn, session: Session = Depends(require_admin)) -> dict:
        cert_path, key_path = service.tls_paths()
        try:
            service.tls_generate(body.hosts, cert_path, key_path)
        except SystemError as e:
            raise _http(400, str(e), "tls_failed") from e
        log("tls_generated", session, hosts=body.hosts)
        return {"ok": True, "need_restart": True}

    @router.get("/access")
    def access_get(_s: Session = Depends(require_session)) -> dict:
        data = AccessStore(config_dir).load()
        return {"management_only": bool(data.get("management_only")), "iface": network.mgmt}

    @router.put("/access")
    def access_put(body: AccessIn, session: Session = Depends(require_admin)) -> dict:
        if body.management_only and not network.mgmt:
            raise _http(400, "Управляющий интерфейс не задан", "no_mgmt_iface")
        AccessStore(config_dir).save({"management_only": body.management_only})
        log("access_updated", session, management_only=body.management_only)
        return {"ok": True}

    # ---------- обновление системы и питание ----------

    @router.get("/updates")
    def updates(_admin: Session = Depends(require_admin)) -> dict:
        try:
            return {"count": service.updates_count()}
        except SystemError as e:
            raise _http(500, str(e), "updates_failed") from e

    @router.post("/updates/apply")
    def updates_apply(session: Session = Depends(require_admin)) -> dict:
        try:
            output = service.updates_apply()
        except SystemError as e:
            raise _http(500, str(e), "updates_failed") from e
        log("system_updated", session)
        return {"ok": True, "output": output}

    @router.post("/power")
    def power(body: PowerIn, session: Session = Depends(require_admin)) -> dict:
        log(body.action, session)
        try:
            service.power(body.action)
        except SystemError as e:
            raise _http(500, str(e), "power_failed") from e
        return {"ok": True}

    return router
