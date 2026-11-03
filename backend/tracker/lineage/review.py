"""Relationship verdicts: the one command for a duplicate or twin decision, and the way back.

Durable human-judgment writes shared by the lineage/twin review endpoints:
outcome history preservation, counterpart rejection (a pair cannot be both a
confirmed twin and a duplicate), the confirmed-pair upserts, and the way back.

A verdict command (`decide_lineage_link`, `decide_twin_link`) takes
`LINEAGE_LOCK_KEY` before it reads the link, writes, flushes, and commits
nothing: the endpoint rebuilds the lineage projection and commits once, so a
verdict and what it shows are durable together or not at all.

Every write that reaches beyond the reviewed link returns the row it touched
as it was and as the verdict left it (`{"id", "before", "after"}`; `before` is
`None` for a row it inserted). The endpoint stores that list on the reviewed
link's evidence under `undo`, so a `pending` verdict can put the side effects
back. It puts back only a row that still holds what the verdict
wrote: a row decided again since carries a later human decision, and Undo
keeps it and names it (`kept`) rather than deleting or overwriting it.
The detector rewrites only pending rows, so a decided row changes
only by a person's decision.

Writing onto an existing counterpart keeps its evidence: its earlier outcome
moves into `decision_history` and its other keys stay.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import Job, JobLineageLink, JobTwinLink
from tracker.lineage.detect import DETECTOR_VERSION as LINEAGE_DETECTOR_VERSION
from tracker.lineage.lock import LINEAGE_LOCK_KEY
from tracker.lineage.pairs import prior_and_later
from tracker.lineage.twins import DETECTOR_VERSION as TWIN_DETECTOR_VERSION
from tracker.lineage.twins import canonical_pair
from tracker.platform.locks import advisory_xact_lock

# The columns a verdict may change on each table — exactly what a reset writes
# back, and what decides whether a row still holds what the verdict wrote.
# Keyed by table name so the undo record on evidence names its rows.
_RESTORED_COLUMNS = {
    "job_twin_link": ("status", "method", "detector_version", "evidence", "reviewed_at"),
    "job_lineage_link": ("status", "relation", "method", "evidence", "reviewed_at"),
}

#: How a kept row is named on the wire: the kind of relationship it records.
_KIND = {"job_twin_link": "twin", "job_lineage_link": "duplicate"}


class LinkNotFound(LookupError):
    """The reviewed link, or a job it joins, does not exist."""


@dataclass(frozen=True)
class VerdictOutcome:
    """What a verdict command did: the reviewed link as it now stands, the
    rows Undo found decided again and left alone, and the twin a `twin`
    verdict confirmed."""

    link: JobLineageLink | JobTwinLink
    kept: list[dict] = field(default_factory=list)
    twin_link_id: int | None = None

    @property
    def decision(self) -> str | None:
        return (self.link.evidence or {}).get("review_outcome")


def _record_relationship_outcome(evidence: dict | None, outcome: str) -> dict:
    """Preserve prior human judgments when a reviewer changes their mind."""
    updated = dict(evidence or {})
    previous = updated.get("review_outcome")
    if previous and previous != outcome:
        history = list(updated.get("decision_history") or [])
        history.append(
            {
                "decision": previous,
                "changed_at": datetime.now(UTC).isoformat(),
            }
        )
        updated["decision_history"] = history
    updated["review_outcome"] = outcome
    return updated


def _as_dict(value) -> dict | None:
    if isinstance(value, str):
        return json.loads(value)
    return value


async def _locked_rows(session: AsyncSession, table: str, where: str, params: dict) -> list[dict]:
    """The rows matching `where`, as `to_jsonb` renders them, locked until commit."""
    result = await session.execute(
        text(f"SELECT to_jsonb(t) AS row FROM {table} AS t WHERE {where} FOR UPDATE"), params
    )
    return [_as_dict(r.row) for r in result.all()]


async def _write_decision(session: AsyncSession, table: str, before: dict, values: dict) -> dict:
    """Write `values` (and `reviewed_at = now()`) onto an existing row.
    Returns `{"id", "before", "after"}`."""
    sets = ", ".join(
        f"{column} = cast(:{column} AS jsonb)" if column == "evidence" else f"{column} = :{column}"
        for column in values
    )
    params = {**values, "id": before["id"]}
    if "evidence" in params:
        params["evidence"] = json.dumps(params["evidence"])
    result = await session.execute(
        text(
            f"UPDATE {table} AS t SET {sets}, reviewed_at = now() "
            f"WHERE t.id = :id RETURNING to_jsonb(t) AS row"
        ),
        params,
    )
    return {"id": int(before["id"]), "before": before, "after": _as_dict(result.one().row)}


async def _insert_decision(session: AsyncSession, table: str, values: dict) -> dict | None:
    """Insert a decided row; `None` when one appeared for the key meanwhile."""
    columns = ", ".join(values)
    placeholders = ", ".join(
        f"cast(:{column} AS jsonb)" if column == "evidence" else f":{column}" for column in values
    )
    params = {**values, "evidence": json.dumps(values["evidence"])}
    result = await session.execute(
        text(
            f"INSERT INTO {table} AS t ({columns}, reviewed_at, created_at) "
            f"VALUES ({placeholders}, now(), now()) "
            f"ON CONFLICT DO NOTHING RETURNING to_jsonb(t) AS row"
        ),
        params,
    )
    row = result.one_or_none()
    if row is None:
        return None
    after = _as_dict(row.row)
    return {"id": int(after["id"]), "before": None, "after": after}


async def _reject_twin_counterpart(
    session: AsyncSession, left_id: int, right_id: int, *, outcome: str
) -> list[dict]:
    """A pair cannot be both a confirmed twin and one duplicate/unrelated pair.
    Returns each counterpart row touched, as it was and as it was left."""
    a, b = canonical_pair(left_id, right_id)
    rows = await _locked_rows(
        session, "job_twin_link", "job_a_id = :a AND job_b_id = :b", {"a": a, "b": b}
    )
    return [
        await _write_decision(
            session,
            "job_twin_link",
            row,
            {"status": "rejected", "evidence": _record_relationship_outcome(row["evidence"], outcome)},
        )
        for row in rows
    ]


async def _reject_lineage_counterpart(
    session: AsyncSession, left_id: int, right_id: int, *, outcome: str
) -> list[dict]:
    rows = await _locked_rows(
        session,
        "job_lineage_link",
        "(job_id = :left_id AND prior_job_id = :right_id)"
        " OR (job_id = :right_id AND prior_job_id = :left_id)",
        {"left_id": left_id, "right_id": right_id},
    )
    return [
        await _write_decision(
            session,
            "job_lineage_link",
            row,
            {"status": "rejected", "evidence": _record_relationship_outcome(row["evidence"], outcome)},
        )
        for row in rows
    ]


def _decided_evidence(existing: dict | None, evidence: dict) -> dict:
    """A confirmation written onto an existing row: its earlier outcome joins its
    history, its other keys stay, and the confirmation's own keys are set."""
    merged = _record_relationship_outcome(existing, evidence["review_outcome"])
    merged.update({key: value for key, value in evidence.items() if key != "review_outcome"})
    return merged


async def _confirm_pair(
    session: AsyncSession, table: str, key_sql: str, key: dict, insert: dict, update: dict
) -> dict:
    """Upsert a human-confirmed row under `key`: insert `insert`, or write
    `update` onto the row that is there with its evidence merged."""
    for _ in range(2):
        rows = await _locked_rows(session, table, key_sql, key)
        if rows:
            values = {**update, "evidence": _decided_evidence(rows[0]["evidence"], update["evidence"])}
            return await _write_decision(session, table, rows[0], values)
        inserted = await _insert_decision(session, table, {**key, **insert})
        if inserted is not None:
            return inserted
    raise RuntimeError(f"{table} row for {key} neither found nor inserted")


async def _confirm_twin_pair(
    session: AsyncSession,
    left_id: int,
    right_id: int,
    *,
    method: str,
    evidence: dict,
) -> dict:
    """Upsert a human-confirmed symmetric twin pair. Returns `{"id", "before",
    "after"}`; `before` is `None` when the pair was new."""
    a, b = canonical_pair(left_id, right_id)
    decided = {
        "status": "confirmed",
        "method": method,
        "detector_version": TWIN_DETECTOR_VERSION,
        "evidence": evidence,
    }
    return await _confirm_pair(
        session,
        "job_twin_link",
        "job_a_id = :job_a_id AND job_b_id = :job_b_id",
        {"job_a_id": a, "job_b_id": b},
        {**decided, "confidence": "suspected"},
        decided,
    )


async def _confirm_duplicate_pair(
    session: AsyncSession, left: Job, right: Job, *, source_twin_link_id: int
) -> dict:
    """Upsert a human-confirmed duplicate link. Returns `{"id", "before",
    "after"}` like `_confirm_twin_pair`."""
    older, newer = prior_and_later(left, right)
    decided = {
        "relation": "duplicate",
        "method": "twin_review",
        "status": "confirmed",
        "evidence": {
            "review_outcome": "duplicate",
            "source_twin_link_id": source_twin_link_id,
            "reasons": ["human marked a twin proposal as the same opening"],
        },
    }
    return await _confirm_pair(
        session,
        "job_lineage_link",
        "job_id = :job_id AND prior_job_id = :prior_job_id",
        {"job_id": newer.id, "prior_job_id": older.id},
        {**decided, "confidence": "suspected", "detector_version": LINEAGE_DETECTOR_VERSION},
        decided,
    )


def _reviewed_at(value) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _still_as_written(current: dict, entry: dict, columns: tuple[str, ...], decided_at) -> bool:
    """Does the row still hold what the verdict wrote?

    A newer entry carries `after`, and the answer is
    equality on the columns a verdict writes. An older entry has only
    `before`; every human write stamps `reviewed_at`, so a row reviewed after
    the verdict was decided again. With no verdict time to compare, the row is
    kept: an Undo that cannot tell must not delete a decision."""
    after = entry.get("after")
    if after is not None:
        return all(current.get(column) == after.get(column) for column in columns)
    if decided_at is None:
        return False
    reviewed = _reviewed_at(current.get("reviewed_at"))
    return reviewed is None or reviewed <= decided_at


async def _restore_rows(
    session: AsyncSession, table: str, rows: list[dict], *, decided_at: datetime | None
) -> list[dict]:
    """Put rows back as a verdict found them, where they still hold what it
    wrote. A row the verdict inserted (`before` is None) is deleted: it is the
    artifact of a withdrawn verdict, not a verdict — the withdrawn decision
    itself survives in the reviewed link's `decision_history`, so the
    negative-label rule is intact. A row decided again since is left as it is
    and returned, `{"link", "id"}`; a row that is gone has nothing to put back."""
    columns = _RESTORED_COLUMNS[table]
    kept: list[dict] = []
    for row in rows:
        current = await _locked_rows(session, table, "id = :id", {"id": row["id"]})
        if not current:
            continue
        if not _still_as_written(current[0], row, columns, decided_at):
            kept.append({"link": _KIND[table], "id": int(row["id"])})
            continue
        before = row.get("before")
        if before is None:
            await session.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": row["id"]})
            continue
        assignments = ", ".join(
            f"{column} = cast(:{column} AS jsonb)" if column == "evidence" else f"{column} = :{column}"
            for column in columns
        )
        params = {column: before.get(column) for column in columns}
        params["evidence"] = json.dumps(params["evidence"] or {})
        # to_jsonb wrote the timestamp as ISO text; asyncpg wants the datetime back.
        params["reviewed_at"] = _reviewed_at(params.get("reviewed_at"))
        params["id"] = row["id"]
        await session.execute(text(f"UPDATE {table} SET {assignments} WHERE id = :id"), params)
    return kept


async def _withdraw_verdict(
    session: AsyncSession, link: JobLineageLink | JobTwinLink
) -> tuple[dict, list[dict]]:
    """Take the last verdict back: the link returns to `pending` with no
    `reviewed_at`, its outcome moves into `decision_history`, and every row
    the verdict changed beyond the link goes back to how it was, unless it was
    decided again since (`kept`, recorded on the history entry too). A link
    that is already pending is left untouched. Returns the link's new evidence
    and what was kept."""
    evidence = dict(link.evidence or {})
    if link.status == "pending":
        return evidence, []
    undo = evidence.pop("undo", None) or {}
    previous = evidence.pop("review_outcome", None)
    kept: list[dict] = []
    for table in _RESTORED_COLUMNS:
        kept += await _restore_rows(
            session, table, list(undo.get(table) or []), decided_at=link.reviewed_at
        )
    if previous:
        history = list(evidence.get("decision_history") or [])
        entry: dict = {"decision": previous, "changed_at": datetime.now(UTC).isoformat()}
        if kept:
            entry["kept"] = kept
        history.append(entry)
        evidence["decision_history"] = history
    link.status = "pending"
    link.reviewed_at = None
    link.evidence = evidence
    return evidence, kept


async def _fresh(session: AsyncSession, model, link_id: int):
    """The link as committed now, read under the lock."""
    await advisory_xact_lock(session, LINEAGE_LOCK_KEY)
    link = await session.get(model, link_id, populate_existing=True, with_for_update=True)
    if link is None:
        raise LinkNotFound("link not found" if model is JobLineageLink else "twin link not found")
    return link


async def decide_lineage_link(session: AsyncSession, link_id: int, verdict: str) -> VerdictOutcome:
    """Record a verdict on a duplicate proposal: `confirmed`, `rejected`,
    `twin` (a separate opening: the link is rejected and the pair confirmed a
    twin) or `pending` (withdraw the last verdict). Flushes; commits nothing."""
    link = await _fresh(session, JobLineageLink, link_id)
    kept: list[dict] = []
    # Changing a verdict unwinds the one it replaces, first. `evidence["undo"]`
    # is a single slot: a second verdict overwrites it, so without this the FIRST
    # verdict's rows -- a twin it created, a counterpart it rejected -- stop being
    # described by anything and no withdrawal can ever reverse them. The link
    # would end up pending while the pair it touched stayed changed.
    if verdict != "pending" and link.status != "pending":
        _, kept = await _withdraw_verdict(session, link)
    twin_link_id = None
    if verdict == "pending":
        _, kept = await _withdraw_verdict(session, link)
    elif verdict == "twin":
        if await session.get(Job, link.job_id) is None or await session.get(Job, link.prior_job_id) is None:
            raise LinkNotFound("linked job not found")
        evidence = _record_relationship_outcome(link.evidence, "twin")
        twin = await _confirm_twin_pair(
            session,
            link.job_id,
            link.prior_job_id,
            method="duplicate_review",
            evidence={
                "review_outcome": "twin",
                "source_lineage_link_id": link.id,
                "reasons": ["human marked a duplicate proposal as separate twin openings"],
            },
        )
        twin_link_id = twin["id"]
        evidence["undo"] = {"job_twin_link": [twin]}
        link.status = "rejected"
        link.evidence = evidence
        link.reviewed_at = datetime.now(UTC)
    else:
        outcome = "duplicate" if verdict == "confirmed" else "different"
        evidence = _record_relationship_outcome(link.evidence, outcome)
        evidence["undo"] = {
            "job_twin_link": await _reject_twin_counterpart(
                session, link.job_id, link.prior_job_id, outcome=outcome
            )
        }
        link.status = verdict
        link.evidence = evidence
        link.reviewed_at = datetime.now(UTC)
    await session.flush()
    return VerdictOutcome(link=link, kept=kept, twin_link_id=twin_link_id)


async def decide_twin_link(session: AsyncSession, link_id: int, verdict: str) -> VerdictOutcome:
    """Record a verdict on a twin proposal: `confirmed`, `rejected`,
    `duplicate` (the same opening: the twin is rejected and the pair confirmed
    a duplicate) or `pending`. Flushes; commits nothing."""
    link = await _fresh(session, JobTwinLink, link_id)
    kept: list[dict] = []
    if verdict != "pending" and link.status != "pending":
        _, kept = await _withdraw_verdict(session, link)
    if verdict == "pending":
        _, kept = await _withdraw_verdict(session, link)
        await session.flush()
        return VerdictOutcome(link=link, kept=kept)
    left = await session.get(Job, link.job_a_id)
    right = await session.get(Job, link.job_b_id)
    if left is None or right is None:
        raise LinkNotFound("linked job not found")
    if verdict == "duplicate":
        evidence = _record_relationship_outcome(link.evidence, "duplicate")
        duplicate = await _confirm_duplicate_pair(session, left, right, source_twin_link_id=link.id)
        evidence["undo"] = {"job_lineage_link": [duplicate]}
        link.status = "rejected"
    else:
        outcome = "twin" if verdict == "confirmed" else "different"
        evidence = _record_relationship_outcome(link.evidence, outcome)
        evidence["undo"] = {
            "job_lineage_link": await _reject_lineage_counterpart(
                session, link.job_a_id, link.job_b_id, outcome=outcome
            )
        }
        link.status = verdict
    link.evidence = evidence
    link.reviewed_at = datetime.now(UTC)
    await session.flush()
    return VerdictOutcome(link=link, kept=kept)


async def lock_relationships(session: AsyncSession) -> None:
    """Hold `LINEAGE_LOCK_KEY` until commit: for a write that changes a
    relationship outside the verdict commands (a manual link)."""
    await advisory_xact_lock(session, LINEAGE_LOCK_KEY)
