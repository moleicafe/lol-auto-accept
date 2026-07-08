from __future__ import annotations

import asyncio
import logging
import threading

from laa.core.engine import Engine
from laa.lcu.catalog import ChampionCatalog
from laa.lcu.connector import LCUConnector
from laa.runes.applier import RuneApplier
from laa.runes.provider import OPGGProvider
from laa.ui.bridge import Bridge
from laa.ui.store import ConfigStore

log = logging.getLogger(__name__)


class LCUWorker(threading.Thread):
    """Hosts the asyncio loop running the connector + engine. Daemon: dies with the app."""

    def __init__(self, store: ConfigStore, bridge: Bridge) -> None:
        super().__init__(daemon=True, name="lcu-worker")
        self._store = store
        self._bridge = bridge

    def run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception:
            log.exception("LCU worker crashed")

    async def _main(self) -> None:
        engine_ref: list[Engine] = []

        async def on_event(event) -> None:
            await engine_ref[0].on_event(event)

        connector = LCUConnector(on_event)
        catalog = ChampionCatalog(connector)
        applier = RuneApplier(connector, OPGGProvider(), self._store.get, catalog.name)

        def notify(text: str) -> None:
            self._bridge.status.emit(text)
            if text == "Connected":
                self._bridge.catalog_ready.emit(catalog.all())

        engine_ref.append(Engine(connector, self._store.get, catalog, applier, notify))
        await connector.run()
