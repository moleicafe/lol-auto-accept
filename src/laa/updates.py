"""Checks GitHub Releases for a newer version. Qt-free; silent on failure."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

RELEASES_URL = "https://api.github.com/repos/moleicafe/lol-auto-accept/releases/latest"


@dataclass(frozen=True)
class UpdateInfo:
    version: str  # dotted, without the leading "v"
    url: str


def parse_version(text: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in text.strip().lstrip("vV").split("."))
    except (ValueError, AttributeError):
        return None


async def check_for_update(current: str,
                           http: httpx.AsyncClient | None = None) -> UpdateInfo | None:
    """Returns UpdateInfo when a newer release exists, else None (incl. on any error)."""
    own_client = http is None
    client = http or httpx.AsyncClient(timeout=5.0)
    try:
        resp = await client.get(RELEASES_URL,
                                headers={"Accept": "application/vnd.github+json"})
        resp.raise_for_status()
        data = resp.json()
        remote = parse_version(data.get("tag_name") or "")
        local = parse_version(current)
        if remote is None or local is None or remote <= local:
            return None
        return UpdateInfo(version=".".join(map(str, remote)),
                          url=data.get("html_url") or RELEASES_URL)
    except Exception as exc:
        log.debug("Update check failed: %s", exc)
        return None
    finally:
        if own_client:
            await client.aclose()
