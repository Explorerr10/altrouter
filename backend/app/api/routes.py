import asyncio

from fastapi import APIRouter, Depends, WebSocket
from fastapi.websockets import WebSocketDisconnect

from ..auth.deps import require_session
from ..auth.routes import build_auth_router
from ..auth.sessions import SESSION_COOKIE, SessionManager
from ..auth.users import UsersStore
from ..config import APP_VERSION
from ..monitor import clients as clients_mod
from ..monitor import net as net_mod
from ..monitor import system as system_mod
from ..monitor.stats import StatsCollector
from ..network.manager import InterfaceManager
from ..network.routes import build_network_router, build_vpn_router
from ..system.routes import build_system_router


def build_api_router(
    users: UsersStore,
    sessions: SessionManager,
    stats: StatsCollector,
    network: InterfaceManager,
    config_dir,
) -> APIRouter:
    api = APIRouter()

    @api.get("/health")
    async def health() -> dict:
        return {"status": "ok", "version": APP_VERSION}

    @api.get("/system/info")
    def system_info(_session=Depends(require_session)) -> dict:
        return system_mod.system_info()

    @api.get("/interfaces")
    def interfaces(_session=Depends(require_session)) -> list:
        return net_mod.interfaces_snapshot()

    @api.get("/clients")
    def clients(_session=Depends(require_session)) -> list:
        return clients_mod.clients_snapshot()

    @api.websocket("/ws/stats")
    async def ws_stats(websocket: WebSocket) -> None:
        sid = websocket.cookies.get(SESSION_COOKIE)
        session = sessions.get(sid) if sid else None
        if session is None:
            await websocket.accept()
            await websocket.close(code=4401)
            return
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(stats.snapshot())
                await asyncio.sleep(1)
        except (WebSocketDisconnect, RuntimeError):
            return

    api.include_router(build_auth_router(users, sessions))
    api.include_router(build_network_router(network))
    api.include_router(build_vpn_router(network))
    api.include_router(build_system_router(users, sessions, network, config_dir))
    return api
