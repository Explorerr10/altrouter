import asyncio
import socket
from pathlib import Path

import psutil
from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ..auth.deps import require_admin, require_session
from ..auth.sessions import Session
from ..errors import ApiError
from . import wireguard as wg_mod
from .errors import ApplyError, NetworkError
from .firewall import DnsRecord, FirewallRule, PortForward
from .manager import InterfaceManager
from .models import InterfaceConfig
from .segments import SegmentConfig, StaticRoute, WanConfig, WanPolicy
from .wireguard import WireguardInterface


class InterfacesPayload(BaseModel):
    items: dict[str, InterfaceConfig]


class SegmentsPayload(BaseModel):
    segments: list[SegmentConfig]


class RoutesPayload(BaseModel):
    routes: list[StaticRoute]


class WanPayload(BaseModel):
    policies: dict[str, WanPolicy]
    mode: str = "failover"


class RulesPayload(BaseModel):
    rules: list[FirewallRule]


class ForwardsPayload(BaseModel):
    forwards: list[PortForward]


class DnsPayload(BaseModel):
    records: list[DnsRecord]


class WireguardPayload(BaseModel):
    items: list[WireguardInterface]


async def run_apply(manager: InterfaceManager, sections: dict, username: str) -> dict:
    if manager.status()["pending"] is not None:
        raise ApiError(
            409, "pending_exists", "Сначала подтвердите или откатите текущие изменения"
        )
    try:
        result = await asyncio.to_thread(manager.apply_sections, sections, username)
    except NetworkError as e:
        raise ApiError(400, "network_invalid", str(e)) from e
    except ApplyError as e:
        raise ApiError(500, "apply_failed", f"Не удалось применить настройки: {e}") from e
    manager.schedule_confirm_timer(result)
    return {"ok": True, "pending": result}


def build_network_router(manager: InterfaceManager) -> APIRouter:
    router = APIRouter(prefix="/network", tags=["network"])

    @router.get("/interfaces/config")
    def config(_session: Session = Depends(require_session)) -> dict:
        return manager.snapshot()

    @router.get("/interfaces/status")
    def status(_session: Session = Depends(require_session)) -> dict:
        return manager.status()

    @router.put("/interfaces/config")
    async def update_config(
        body: InterfacesPayload, session: Session = Depends(require_admin)
    ) -> dict:
        for key, cfg in body.items.items():
            if cfg.name != key:
                raise ApiError(
                    400,
                    "iface_key_mismatch",
                    f"Ключ {key!r} не совпадает с именем интерфейса {cfg.name!r}",
                )
        try:
            manager.validate(body.items)
        except NetworkError as e:
            raise ApiError(400, "network_invalid", str(e)) from e
        return await run_apply(manager,{"items": body.items}, session.username)

    @router.put("/segments")
    async def update_segments(
        body: SegmentsPayload, session: Session = Depends(require_admin)
    ) -> dict:
        return await run_apply(manager,{"segments": body.segments}, session.username)

    @router.put("/routes")
    async def update_routes(
        body: RoutesPayload, session: Session = Depends(require_admin)
    ) -> dict:
        return await run_apply(manager,{"routes": body.routes}, session.username)

    @router.put("/wan")
    async def update_wan(body: WanPayload, session: Session = Depends(require_admin)) -> dict:
        wan = WanConfig(mode=body.mode, policies=body.policies)
        return await run_apply(manager, {"wan": wan}, session.username)

    @router.put("/firewall")
    async def update_firewall(
        body: RulesPayload, session: Session = Depends(require_admin)
    ) -> dict:
        return await run_apply(manager,{"rules": body.rules}, session.username)

    @router.put("/forwards")
    async def update_forwards(
        body: ForwardsPayload, session: Session = Depends(require_admin)
    ) -> dict:
        return await run_apply(manager,{"forwards": body.forwards}, session.username)

    @router.put("/dns")
    async def update_dns(
        body: DnsPayload, session: Session = Depends(require_admin)
    ) -> dict:
        return await run_apply(manager,{"dns": body.records}, session.username)

    @router.get("/wan/status")
    def wan_status(request: Request, _session: Session = Depends(require_session)) -> dict:
        wan = [n for n, cfg in manager.effective_state()["items"].items() if cfg.role == "wan"]
        addrs = psutil.net_if_addrs()
        checker = getattr(request.app.state, "ping_checker", None)
        ping = checker.status() if checker is not None else {}
        items = {}
        for name in wan:
            try:
                oper = Path(f"/sys/class/net/{name}/operstate").read_text().strip()
            except OSError:
                oper = "unknown"
            entry = dict(ping.get(name) or {})
            entry["operstate"] = oper
            entry["ipv4"] = [a.address for a in addrs.get(name, []) if a.family == socket.AF_INET]
            items[name] = entry
        return {"items": items}

    @router.post("/interfaces/confirm")
    async def confirm(_session: Session = Depends(require_admin)) -> dict:
        try:
            return await asyncio.to_thread(manager.confirm)
        except NetworkError as e:
            raise ApiError(409, "txn_conflict", str(e)) from e

    @router.post("/interfaces/rollback")
    async def rollback(_session: Session = Depends(require_admin)) -> dict:
        try:
            return await asyncio.to_thread(manager.rollback)
        except NetworkError as e:
            raise ApiError(409, "txn_conflict", str(e)) from e
        except ApplyError as e:
            raise ApiError(500, "rollback_failed", f"Откат не удалось применить: {e}") from e

    return router


def build_vpn_router(manager: InterfaceManager) -> APIRouter:
    router = APIRouter(prefix="/network/vpn", tags=["vpn"])

    def prepare_keys(items: list[WireguardInterface]) -> None:
        for wg in items:
            if not wg.private_key:
                wg.private_key = wg_mod.generate_keypair()[0]
            if not wg.public_key:
                wg.public_key = wg_mod.derive_public(wg.private_key)
            for peer in wg.peers:
                if peer.private_key and not peer.public_key:
                    peer.public_key = wg_mod.derive_public(peer.private_key)

    @router.put("/wireguard")
    async def update_wireguard(
        body: WireguardPayload, session: Session = Depends(require_admin)
    ) -> dict:
        ids = [wg.id for wg in body.items]
        if len(set(ids)) != len(ids):
            raise ApiError(400, "wg_dup_id", "Идентификатор туннеля повторяется")
        try:
            await asyncio.to_thread(prepare_keys, body.items)
        except RuntimeError as e:
            raise ApiError(500, "wg_keys_failed", str(e)) from e
        return await run_apply(manager,{"wireguard": body.items}, session.username)

    @router.get("/status")
    def status(_session: Session = Depends(require_session)) -> dict:
        return {"items": wg_mod.wg_status()}

    @router.get("/keypair")
    def keypair(_session: Session = Depends(require_session)) -> dict:
        try:
            private, public = wg_mod.generate_keypair()
        except RuntimeError as e:
            raise ApiError(500, "wg_keys_failed", str(e)) from e
        return {"private_key": private, "public_key": public}

    @router.get("/wireguard/{wg_id}/peer/{peer_name}/config")
    def peer_config(
        wg_id: str, peer_name: str, _session: Session = Depends(require_session)
    ) -> PlainTextResponse:
        wg = next((w for w in manager.effective_state()["wireguard"] if w.id == wg_id), None)
        if wg is None:
            raise ApiError(404, "wg_not_found", f"Туннель {wg_id!r} не найден")
        peer = next((p for p in wg.peers if p.name == peer_name), None)
        if peer is None:
            raise ApiError(404, "wg_peer_not_found", f"Пир {peer_name!r} не найден")
        try:
            text = wg_mod.render_client_config(wg, peer)
        except ValueError as e:
            raise ApiError(400, "wg_render_failed", str(e)) from e
        return PlainTextResponse(
            text, headers={"Content-Disposition": f'attachment; filename="wg-{wg_id}.conf"'}
        )

    return router
