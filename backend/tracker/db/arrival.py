"""How a role arrived: whether our first sighting of a posting dates it.

A role's first sighting S is the earlier of its creation here and the
inventory's `first_seen_at` for the same posting (a read that held it out of
scope, or a "Count now"). `first_seen` becomes S.

The sighting dates the posting only if the company was already known at S:

- a read of it that saw its whole listing (`list_complete`, or a board proven
  `empty`) finished before S, inside the retention window before S. A company
  followed again after the window starts over, as its inventory rows did.
- a source that has never completed a read is known after two earlier reads
  that kept postings and stopped only at our own ceilings or a few unreadable
  records (`truncated`, `bounded`, `lossy`). Operator caps, a sleeping host and
  a broken source are not evidence of what the board held.

`finished_at < S` excludes the read that produced S: its source-run row is
written after its upserts and its inventory write.

Then `arrival` is `first_read` when the company was not known at S,
`already_listed` when the posting was on the board before we stored it (S
before creation, or admitted from the inventory), and `new` otherwise
(`schema.Arrival`).

One statement classifies a batch, and every writer of `jobs` calls it on the
rows it created, in the same transaction: no reader sees an unclassified role
the writer made. Commits nothing.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key

from tracker.connectors.recipes.outcome import SourceOutcome
from tracker.db.models import Job
from tracker.schema import Arrival
from tracker.settings_store import get_retention_days

#: Reads that saw the listing up to our own ceiling or all but a few records:
#: a source whose reads always end this way is known after two of them.
_PARTIAL_EVIDENCE = (SourceOutcome.TRUNCATED, SourceOutcome.BOUNDED, SourceOutcome.LOSSY)
_KNOWN_AFTER_PARTIAL_READS = 2

_CLASSIFY = """
WITH target AS (
    SELECT j.id, j.company, j.first_seen AS created,
           least(j.first_seen, inv.first_seen_at) AS sighted,
           EXISTS (
               SELECT 1 FROM job_lifecycle_events e
               WHERE e.job_id = j.id AND e.event_type = 'added'
           ) AS admitted
    FROM jobs j
    LEFT JOIN posting_inventory inv ON inv.dedupe_key = j.dedupe_key
    WHERE j.id = ANY(CAST(:ids AS bigint[]))
),
known AS (
    SELECT t.*, (
        SELECT max(r.finished_at) FROM scrape_source_runs r
        WHERE r.company_slug = t.company
          AND (r.list_complete OR r.outcome = 'empty')
          AND r.finished_at < t.sighted
    ) AS complete_before
    FROM target t
),
classified AS (
    SELECT k.id, k.sighted,
        CASE
            WHEN k.complete_before IS NOT NULL
                 AND (CAST(:window_days AS integer) IS NULL
                      OR k.complete_before >= k.sighted
                         - make_interval(days => CAST(:window_days AS integer)))
                THEN TRUE
            WHEN k.complete_before IS NULL THEN (
                SELECT count(*) FROM scrape_source_runs r
                WHERE r.company_slug = k.company
                  AND r.outcome = ANY(CAST(:partial AS text[]))
                  AND r.kept > 0
                  AND r.finished_at < k.sighted
                  AND (CAST(:window_days AS integer) IS NULL
                       OR r.finished_at >= k.sighted
                          - make_interval(days => CAST(:window_days AS integer)))
            ) >= :partial_reads
            ELSE FALSE
        END AS known,
        k.admitted OR k.sighted < k.created AS listed_before
    FROM known k
)
UPDATE jobs j
SET first_seen = c.sighted,
    arrival = CASE
        WHEN NOT c.known THEN :first_read
        WHEN c.listed_before THEN :already_listed
        ELSE :new
    END
FROM classified c
WHERE j.id = c.id
RETURNING j.id, j.first_seen, j.arrival
"""


async def classify_arrivals(session: AsyncSession, job_ids: Sequence[int]) -> list[int]:
    """Classify the given roles, typically the ones the caller just created.
    Returns their ids, sorted."""
    if not job_ids:
        return []
    # A text statement does not autoflush, and the rule reads the caller's
    # pending rows and events.
    await session.flush()
    window_days = await get_retention_days(session)
    rows = (await session.execute(
        text(_CLASSIFY),
        {
            "ids": list(job_ids),
            "window_days": window_days,
            "partial": [outcome.value for outcome in _PARTIAL_EVIDENCE],
            "partial_reads": _KNOWN_AFTER_PARTIAL_READS,
            "first_read": Arrival.FIRST_READ.value,
            "already_listed": Arrival.ALREADY_LISTED.value,
            "new": Arrival.NEW.value,
        },
    )).all()
    # The statement bypasses the ORM: a role the caller still holds takes the
    # stored values, so it neither reads nor flushes its creation time.
    for job_id, first_seen, arrival in rows:
        held = session.identity_map.get(identity_key(Job, job_id))
        if held is not None:
            set_committed_value(held, "first_seen", first_seen)
            set_committed_value(held, "arrival", arrival)
    return sorted(job_id for job_id, _first_seen, _arrival in rows)
