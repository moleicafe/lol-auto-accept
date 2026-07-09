from __future__ import annotations

import asyncio
import base64
import json
import logging
import ssl
from typing import Any, Awaitable, Callable

import httpx
import websockets

from . import events
from .discovery import LCUCredentials, find_credentials

log = logging.getLogger(__name__)

EventCallback = Callable[["events.LCUEvent"], Awaitable[None] | None]


class LCUError(Exception):
    """Any failure talking to the League client."""


def _parse_message(raw: str | bytes) -> events.LCUEvent | None:
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(msg, list) or len(msg) < 3 or msg[0] != 8 or not isinstance(msg[2], dict):
        return None
    payload = msg[2]
    if payload.get("eventType") == "Delete":
        return None
    uri = payload.get("uri")
    data = payload.get("data")
    if uri == "/lol-gameflow/v1/gameflow-phase" and isinstance(data, str):
        return events.GameflowPhase(phase=data)
    if uri == "/lol-matchmaking/v1/ready-check" and isinstance(data, dict):
        return events.ReadyCheckUpdate(
            state=data.get("state", ""), player_response=data.get("playerResponse", "")
        )
    if uri == "/lol-champ-select/v1/session" and isinstance(data, dict):
        return events.ChampSelectUpdate(session=data)
    return None


class LCUConnector:
    """Finds the League client, pumps websocket events, exposes request helpers."""

    def __init__(
        self,
        on_event: EventCallback,
        find_creds: Callable[[], LCUCredentials | None] = find_credentials,
        poll_interval: float = 2.0,
        secure: bool = True,
    ) -> None:
        self._on_event = on_event
        self._find_creds = find_creds
        self._poll_interval = poll_interval
        self._secure = secure
        self._client: httpx.AsyncClient | None = None

    async def run(self) -> None:
        while True:
            creds = self._find_creds()
            if creds is None:
                await asyncio.sleep(self._poll_interval)
                continue
            try:
                await self._session(creds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.info("LCU connection lost: %s", exc)
            await self._emit(events.Disconnected())
            await asyncio.sleep(self._poll_interval)

    async def _emit(self, event: "events.LCUEvent") -> None:
        result = self._on_event(event)
        if asyncio.iscoroutine(result):
            await result

    async def _session(self, creds: LCUCredentials) -> None:
        scheme = "https" if self._secure else "http"
        async with httpx.AsyncClient(
            base_url=f"{scheme}://127.0.0.1:{creds.port}",
            auth=("riot", creds.token),
            verify=False,
            timeout=10.0,
        ) as client:
            self._client = client
            try:
                await self._pump(creds)
            finally:
                self._client = None

    async def _pump(self, creds: LCUCredentials) -> None:
        ws_scheme = "wss" if self._secure else "ws"
        kwargs: dict[str, Any] = {"max_size": 2**24}
        if self._secure:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            kwargs["ssl"] = ctx
        basic = base64.b64encode(f"riot:{creds.token}".encode()).decode()
        kwargs["additional_headers"] = {"Authorization": f"Basic {basic}"}
        async with websockets.connect(f"{ws_scheme}://127.0.0.1:{creds.port}/", **kwargs) as ws:
            await ws.send(json.dumps([5, "OnJsonApiEvent"]))
            await self._emit(events.Connected())
            async for raw in ws:
                event = _parse_message(raw)
                if event is not None:
                    await self._emit(event)

    async def request(self, method: str, path: str, json_body: Any = None) -> Any:
        if self._client is None:
            raise LCUError("not connected to League client")
        try:
            resp = await self._client.request(method, path, json=json_body)
        except httpx.HTTPError as exc:
            raise LCUError(f"{method} {path}: {exc}") from exc
        if resp.status_code >= 400:
            raise LCUError(f"{method} {path} -> {resp.status_code}: {resp.text[:200]}")
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    async def get(self, path: str) -> Any:
        return await self.request("GET", path)

    async def post(self, path: str, json_body: Any = None) -> Any:
        return await self.request("POST", path, json_body)

    async def patch(self, path: str, json_body: Any = None) -> Any:
        return await self.request("PATCH", path, json_body)

    async def put(self, path: str, json_body: Any = None) -> Any:
        return await self.request("PUT", path, json_body)

    async def delete(self, path: str) -> Any:
        return await self.request("DELETE", path)
