"""The inventory's copy of one scanned posting.

`annotate()` classifies every row a scan reads; `inventory_row` keeps that
classification with the listing facts it was read from, so the row can be
re-derived and gated later without the network. Pure: no session, no I/O.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import astuple, dataclass
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

from tracker.enrich.enricher import Annotation
from tracker.schema import RawJob


def _instant(value: datetime) -> str:
    """One spelling per instant: a stored timestamptz reads back in UTC, so an
    offset the source sent must not make an unchanged row hash differently."""
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class InventoryRow:
    """One posting as the inventory keeps it: listing facts and the
    classification `annotate()` gave it, nothing else.

    Built from an ALLOWLIST of `RawJob` fields by `inventory_row`. Never the
    description, the detail payload or `source_facts`: those are where a
    person (a hiring team, a recruiter) could ride in, and a listing fact is
    all a later scope widening needs.
    """

    dedupe_key: str
    req_id: str
    title: str
    url: str
    department: str | None
    team: str | None
    raw_level: str | None
    locations: tuple[str, ...]
    workplace_type: str
    posted_at: datetime | None
    level_band: str
    level_confidence: str
    level_basis: str
    family: str | None
    track: str
    location_groups: tuple[str, ...]
    domains: tuple[str, ...]

    @property
    def content_hash(self) -> str:
        """sha256 over every field: equal hashes mean nothing to rewrite."""
        facts = [_instant(v) if isinstance(v, datetime) else v for v in astuple(self)]
        return hashlib.sha256(json.dumps(facts, default=list).encode()).hexdigest()


def inventory_row(raw: RawJob, ann: Annotation) -> InventoryRow:
    """The inventory's copy of one scanned posting. Pure; allowlist only."""
    return InventoryRow(
        dedupe_key=raw.dedupe_key(),
        req_id=raw.req_id,
        title=raw.title,
        url=raw.url,
        department=raw.department,
        team=raw.team,
        raw_level=raw.raw_level,
        locations=tuple(raw.locations),
        workplace_type=raw.workplace_type.value,
        posted_at=raw.posted_at,
        level_band=ann.band.value,
        level_confidence=ann.confidence.value,
        level_basis=ann.basis.value,
        family=ann.family,
        track=ann.track.value,
        # As `jobs` stores them (`repo._apply_fields`), so one gate reads both.
        location_groups=tuple(ann.location_groups),
        domains=tuple(ann.domains),
    )


_TRACKER = Path(__file__).resolve().parents[1]
#: What `annotate` reads besides the posting: the classifiers, the taxonomy and
#: its data files, the leveling model, as `annotate` imports them. The
#: model is listed file by file: `levels/pay.py` never decides a band, and a
#: pay-policy edit must not re-annotate every stored posting. A path that does
#: not exist would silently drop out of the hash, so a test checks each one.
CLASSIFIER_SOURCES = (
    "enrich", "taxonomy", "levels/__init__.py", "levels/model.py", "levels/companies.py",
    "levels/ladder.py", "levels/titles.py", "levels/words.py", "levels/vocabulary.py",
    "levels/atlas.py",
    # The cell rules the atlas reads its files by.
    "platform/tables.py",
    # The ladders as data: an edit to a rung or a printed code
    # re-levels the inventory like an edit to the code does. The pay tables are
    # not here: the inventory has no pay.
    "levels/atlas/companies.csv", "levels/atlas/ladders.csv", "levels/atlas/rungs.csv",
    "levels/atlas/printed.csv", "levels/atlas/rung_titles.csv",
)


@cache
def classifier_fingerprint() -> str:
    """sha256 over the classifier's source and data files.

    Re-annotating the whole inventory is slow, so it runs only when this
    changes: a classification can move only when the code or data that
    computes it does.
    """
    digest = hashlib.sha256()
    for entry in CLASSIFIER_SOURCES:
        root = _TRACKER / entry
        files = [root] if root.is_file() else sorted(
            path for path in root.rglob("*")
            if path.is_file() and path.suffix in {".py", ".tsv", ".json"} and "__pycache__" not in path.parts
        )
        for path in files:
            digest.update(str(path.relative_to(_TRACKER)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()
