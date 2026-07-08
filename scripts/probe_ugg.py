"""Live check of the U.GG endpoint constants. Usage: python scripts/probe_ugg.py [champion_id] [role]"""
import asyncio
import sys

sys.path.insert(0, "src")
from laa.runes.provider import UGGProvider  # noqa: E402


async def main() -> None:
    cid = int(sys.argv[1]) if len(sys.argv) > 1 else 103  # Ahri
    role = sys.argv[2] if len(sys.argv) > 2 else "middle"
    build = await UGGProvider().get_build(cid, role)
    print(build)
    if build is None:
        raise SystemExit("FAILED - endpoint or payload shape changed; adjust provider constants")


asyncio.run(main())
