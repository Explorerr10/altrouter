import ipaddress
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import build_api_router
from .auth.sessions import SessionManager
from .auth.users import UsersStore
from .config import APP_VERSION, default_config_dir
from .errors import install_error_handlers
from .monitor.stats import StatsCollector
from .network.manager import InterfaceManager
from .network.pingcheck import PingChecker
from .system.service import AccessStore, allowed_subnets


def _ping_policies(state: dict) -> dict:
    return {
        iface: policy.ping_check
        for iface, policy in state["wan"].policies.items()
        if policy.ping_check.enabled
    }


def create_app(
    config_dir: Path | None = None, network_manager: InterfaceManager | None = None
) -> FastAPI:
    cfg_dir = config_dir or default_config_dir()
    users = UsersStore(cfg_dir)
    users.load()
    sessions = SessionManager()
    stats = StatsCollector()
    network = network_manager or InterfaceManager(cfg_dir)

    ping_checker = PingChecker(logger=lambda **extra: network.log_event("ping_renew", **extra))
    network.state_listeners.append(lambda state: ping_checker.configure(_ping_policies(state)))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        ping_checker.configure(_ping_policies(network.effective_state()))
        ping_checker.start()
        try:
            yield
        finally:
            ping_checker.stop()

    app = FastAPI(
        title="AltRouter",
        version=APP_VERSION,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    install_error_handlers(app)

    access = AccessStore(cfg_dir)

    @app.middleware("http")
    async def access_guard(request, call_next):
        if network.mgmt and access.load().get("management_only"):
            try:
                ip = ipaddress.ip_address(request.client.host)
            except (ValueError, AttributeError):
                ip = None
            if not (
                ip and (ip.is_loopback or any(ip in net for net in allowed_subnets(network.mgmt)))
            ):
                return JSONResponse(
                    {
                        "detail": "Доступ к панели разрешён только с управляющего интерфейса",
                        "code": "mgmt_only",
                    },
                    status_code=403,
                )
        return await call_next(request)

    app.state.users = users
    app.state.sessions = sessions
    app.state.network = network
    app.state.ping_checker = ping_checker
    app.include_router(
        build_api_router(users, sessions, stats, network, cfg_dir), prefix="/api"
    )

    static_dir = Path(os.environ.get("ALTROUTER_STATIC_DIR", ""))
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

        @app.exception_handler(404)
        async def spa_fallback(request, exc):
            if request.url.path.startswith("/api"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
