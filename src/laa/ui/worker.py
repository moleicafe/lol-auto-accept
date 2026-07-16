from __future__ import annotations

import asyncio
import logging
import threading

from laa import __version__
from laa.core.engine import Engine
from laa.core.scout import LobbyScout
from laa.lcu.catalog import ChampionCatalog
from laa.lcu.connector import LCUConnector
from laa.runes.applier import BuildApplier
from laa.runes.provider import OPGGProvider
from laa.ui.bridge import Bridge
from laa.ui.store import ConfigStore
from laa.updates import check_for_update

log = logging.getLogger(__name__)


class LCUWorker(threading.Thread):
    """Hosts the asyncio loop running the connector + engine. Daemon: dies with the app."""

    def __init__(self, store: ConfigStore, bridge: Bridge) -> None:
        super().__init__(daemon=True, name="lcu-worker")
        self._store = store
        self._bridge = bridge
        self._loop: asyncio.AbstractEventLoop | None = None
        self._scout: LobbyScout | None = None

    def request_multisearch(self) -> None:
        """Thread-safe: called from the Qt thread; result arrives via the bridge."""
        loop, scout = self._loop, self._scout
        if loop is None or scout is None:
            log.info("Scout lobby: worker not ready")
            return

        def done(fut) -> None:
            try:
                url = fut.result()
            except Exception:
                log.exception("Scout lobby failed")
                return
            if url:
                self._bridge.multisearch_ready.emit(url)
            else:
                log.info("Scout lobby: no lobby names available yet")

        asyncio.run_coroutine_threadsafe(scout.build_url(), loop).add_done_callback(done)

    def run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception:
            log.exception("LCU worker crashed")
            self._bridge.status.emit("Stopped - please restart the app")

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        engine_ref: list[Engine] = []

        async def on_event(event) -> None:
            await engine_ref[0].on_event(event)

        connector = LCUConnector(on_event)
        catalog = ChampionCatalog(connector)
        applier = BuildApplier(connector, OPGGProvider(), self._store.get, catalog.name)
        self._scout = LobbyScout(connector, self._store.get)

        def notify(text: str) -> None:
            self._bridge.status.emit(text)
            if text == "Connected":
                self._bridge.catalog_ready.emit(catalog.all())

        engine_ref.append(Engine(connector, self._store.get, catalog, applier, notify,
                                 scout=self._scout,
                                 on_multisearch=self._bridge.multisearch_ready.emit))

        async def heartbeat() -> None:
            # Proves both the worker loop and the log sinks are alive; if
            # heartbeats stop while the UI works, a sink died (field bug).
            while True:
                await asyncio.sleep(60)
                log.info("heartbeat: phase=%s", engine_ref[0].phase or "-")

        async def update_check() -> None:
            await asyncio.sleep(3)  # let startup settle first
            if not self._store.get().check_updates:
                return
            info = await check_for_update(__version__)
            if info is not None:
                log.info("Update available: v%s", info.version)
                self._bridge.update_available.emit(info.version, info.url)

        heartbeat_task = asyncio.create_task(heartbeat())
        update_task = asyncio.create_task(update_check())
        try:
            await connector.run()
        finally:
            heartbeat_task.cancel()
            update_task.cancel()
