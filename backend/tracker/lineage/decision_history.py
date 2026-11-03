"""The one thing about a pending link that a detector may not take back.

`review.py` returns an undone verdict to `pending` and moves the decision it
withdrew into `evidence.decision_history`, which `_restore_rows` and the
review surfaces read. Everything else about a pending row belongs to the
detector: it deletes the proposals its current rules do not make and
rewrites the evidence of the ones they do.

Those two rules meet on one row. A person's verdict, even an undone one, is
the only part of that evidence nobody else produced and nothing can recompute,
so the detector passes carry it across both of their writes: the delete skips
a row that holds history, and the upsert merges it back over the evidence it
just built.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, func, true

#: Where `review.py` keeps verdicts a person took back.
HISTORY_KEY = "decision_history"

#: The same test for a raw statement. `jsonb_exists` rather than the `?`
#: operator, which a driver's own parameter style can claim.
HOLDS_HISTORY_SQL = f"jsonb_exists({{column}}, '{HISTORY_KEY}')"

#: Merge for an upsert's `SET evidence`: the detector's fresh evidence, with
#: any history the stored row carries put back on top of it.
MERGE_HISTORY_SQL = """
    CASE WHEN jsonb_exists({stored}, '{key}')
         THEN EXCLUDED.evidence || jsonb_build_object('{key}', {stored} -> '{key}')
         ELSE EXCLUDED.evidence
    END
"""


def holds_history(evidence: ColumnElement) -> ColumnElement[bool]:
    """Whether this row records a verdict somebody took back."""
    return func.jsonb_exists(evidence, HISTORY_KEY)


def without_history(evidence: ColumnElement | None) -> ColumnElement[bool]:
    """The guard a detector's pending-delete carries. `None` disables it, for
    a caller with no evidence column in scope."""
    return true() if evidence is None else ~holds_history(evidence)


def merge_history(stored_column: str) -> str:
    """`SET evidence = ...` for an upsert on `stored_column`'s table."""
    return MERGE_HISTORY_SQL.format(stored=stored_column, key=HISTORY_KEY).strip()


def holds_history_sql(column: str) -> str:
    """The raw-SQL form of `holds_history`, for `text()` statements."""
    return HOLDS_HISTORY_SQL.format(column=column)
