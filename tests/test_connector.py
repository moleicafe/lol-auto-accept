import asyncio
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from laa.lcu import events
from laa.lcu.connector import LCUConnector, LCUError
from laa.lcu.discovery import LCUCredentials


async def make_fake_lcu():
    async def ws_handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        msg = await ws.receive_json()
        assert msg == [5, "OnJsonApiEvent"]
        await ws.send_json(
            [8, "OnJsonApiEvent",
             {"uri": "/lol-gameflow/v1/gameflow-phase", "eventType": "Update", "data": "Lobby"}]
        )
        async for _ in ws:  # stay open until client/server closes
            pass
        return ws

    async def phase(request):
        return web.json_response("Lobby")

    app = web.Application()
    app.router.add_get("/", ws_handler)
    app.router.add_get("/lol-gameflow/v1/gameflow-phase", phase)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server(shutdown_timeout=0.1)
    return server


async def test_connect_receive_event_request_and_disconnect():
    server = await make_fake_lcu()
    received: list = []
    connected = asyncio.Event()
    disconnected = asyncio.Event()

    async def on_event(ev):
        received.append(ev)
        if isinstance(ev, events.Connected):
            connected.set()
        if isinstance(ev, events.Disconnected):
            disconnected.set()

    creds = LCUCredentials(port=server.port, token="testtoken")
    conn = LCUConnector(on_event, find_creds=lambda: creds, poll_interval=0.05, secure=False)
    task = asyncio.create_task(conn.run())
    try:
        await asyncio.wait_for(connected.wait(), 5)
        # request helper works while connected
        assert await conn.get("/lol-gameflow/v1/gameflow-phase") == "Lobby"
        # parsed websocket event arrives
        await asyncio.wait_for(_wait_for_phase(received), 5)
        # server death -> Disconnected
        await server.close()
        await asyncio.wait_for(disconnected.wait(), 5)
    finally:
        task.cancel()

    with pytest.raises(LCUError):
        await conn.get("/anything")


async def _wait_for_phase(received):
    while not any(isinstance(e, events.GameflowPhase) and e.phase == "Lobby" for e in received):
        await asyncio.sleep(0.01)


async def test_request_while_disconnected_raises():
    conn = LCUConnector(lambda e: None, find_creds=lambda: None, secure=False)
    with pytest.raises(LCUError):
        await conn.get("/lol-summoner/v1/current-summoner")
