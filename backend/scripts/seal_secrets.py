"""Seal the API keys saved before sealing existed (`tracker.platform.secrets`).

A key saved since then is sealed when it is saved; one saved earlier stays in
the clear until its store writes it again. This writes each such row once,
through its own store, so the price key, every cloud model key and every local
model key end sealed. A sealed key is left as it is, so a rerun changes nothing.

    .venv/bin/python -m scripts.seal_secrets            # which rows hold a key in the clear
    .venv/bin/python -m scripts.seal_secrets --apply    # seal them

Each store writes its own row (`prices.reseal_api_key`, the profile stores'
`reseal`); the price key keeps its `saved_at`. Backups taken before
this run still hold the keys in the clear; rotating a key at its provider is
what makes such a copy harmless.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import AppSetting
from tracker.db.session import session_scope
from tracker.intelligence_runtime import cloud_profiles, local_profiles
from tracker.platform.secrets import is_sealed
from tracker.profiles import prices


def _clear(value: object) -> bool:
    return isinstance(value, str) and bool(value) and not is_sealed(value)


async def _row(session: AsyncSession, key: str) -> dict:
    row = await session.get(AppSetting, key)
    return row.value if row is not None and isinstance(row.value, dict) else {}


async def in_the_clear(session: AsyncSession) -> dict[str, int]:
    """How many keys each settings row holds unsealed."""
    price = await _row(session, prices.PRICE_FEED_KEY)
    found = {prices.PRICE_FEED_KEY: int(_clear(price.get("api_key")))}
    for key in (cloud_profiles.CLOUD_LLM_KEY, local_profiles.LOCAL_LLM_KEY):
        profiles = (await _row(session, key)).get("profiles")
        found[key] = sum(
            1 for p in (profiles if isinstance(profiles, list) else [])
            if isinstance(p, dict) and _clear(p.get("api_key"))
        )
    return found


async def seal_all(session: AsyncSession) -> dict[str, int]:
    """Seal every key still in the clear; returns what was found. Commits nothing."""
    found = await in_the_clear(session)
    if found[prices.PRICE_FEED_KEY]:
        await prices.reseal_api_key(session)
    if found[cloud_profiles.CLOUD_LLM_KEY]:
        await cloud_profiles.reseal(session)
    if found[local_profiles.LOCAL_LLM_KEY]:
        await local_profiles.reseal(session)
    return found


async def _main(apply: bool) -> int:
    async with session_scope() as session:
        found = await (seal_all(session) if apply else in_the_clear(session))
    for key, count in found.items():
        print(f"{key}: {count} key(s) in the clear{' -> sealed' if apply and count else ''}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="seal them (default: only report)")
    return asyncio.run(_main(parser.parse_args().apply))


if __name__ == "__main__":
    raise SystemExit(main())
