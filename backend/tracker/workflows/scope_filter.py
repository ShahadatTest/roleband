"""What your radar looks for, read once for a pass that gates postings.

The pipeline's ingest gate and the directory scan must ask the same
question of a posting, so they read the same filter from one place: the five
scope axes plus the learned team/department exclusions. Two copies of this
assembly would drift the first time an axis is added, and the directory scan
would then promote companies the pipeline goes on to keep nothing from.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.queries.scope import load_scope_exclusions
from tracker.enrich.enricher import ScopeFilter
from tracker.settings_store import (
    get_enabled_bands,
    get_enabled_domains,
    get_enabled_locations,
    get_enabled_roles,
    get_enabled_tracks,
    get_excluded_domains,
    get_excluded_locations,
    get_include_unstated_level,
    get_role_answers,
)


async def load_scope_filter(session: AsyncSession) -> ScopeFilter:
    return ScopeFilter(
        enabled_bands=frozenset(await get_enabled_bands(session)),
        enabled_roles=frozenset(await get_enabled_roles(session)),
        enabled_tracks=frozenset(await get_enabled_tracks(session)),
        enabled_locations=frozenset(await get_enabled_locations(session)),
        enabled_domains=frozenset(await get_enabled_domains(session)),
        # Learned employer-vocabulary exclusions ride the scope so the ingest
        # gate and the saved-scope SQL project the same set.
        company_exclusions=await load_scope_exclusions(session),
        excluded_domains=frozenset(await get_excluded_domains(session)),
        answers=await get_role_answers(session),
        excluded_locations=frozenset(await get_excluded_locations(session)),
        include_unstated_level=await get_include_unstated_level(session),
    )


def _plain(value: object) -> object:
    if isinstance(value, (set, frozenset)):
        return sorted((_plain(item) for item in value), key=repr)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def scope_fingerprint(scope: ScopeFilter) -> str:
    """Which radar a check was made with, as a short stable key.

    Every axis that can ADMIT a posting is in it. The learned team/department
    exclusions are not: a rule only ever takes a posting away, so a check made
    before one cannot have missed a match, and one click of "not this team"
    must not cost a two-hour re-read of every board.
    """
    fields = {
        f.name: _plain(getattr(scope, f.name))
        for f in dataclasses.fields(scope) if f.name != "company_exclusions"
    }
    blob = json.dumps(fields, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]
