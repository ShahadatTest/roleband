"""The matching-model switch: representable states, honest estimates, safe stop.

Without these, one click starts a long job with no way to stop it, no
estimate, and no state for "it stopped halfway", which would render as
*settled* while half the corpus is on the other model.
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from tests.factories import Upserted
from tracker.semantic.embed import stale_predicate
from tracker.semantic.matching import INT8_RATE_RATIO, estimate_seconds

# Every test here reaches code that starts or signals a process on this
# machine, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")


def _sql(clause) -> str:
    return str(clause.compile(dialect=postgresql.dialect()))


class _Session:
    """Answers only `get_embed_measurements`'s row read."""

    def __init__(self, value):
        self.value = value

    async def get(self, _model, _key):
        if self.value is None:
            return None

        class Row:
            pass

        row = Row()
        row.value = self.value
        return row


# --------------------------------------------------------------------------- #
# The column that makes a half-finished switch representable.


def test_stale_predicate_catches_rows_from_the_other_model():
    sql = _sql(stale_predicate("fp32"))
    # Never-embedded and changed-content rows both remain owed...
    assert "embedded_at IS NULL" in sql
    assert "content_changed_at > jobs.embedded_at" in sql
    # ...plus the one that makes a tier switch a property of each row rather
    # than a bulk UPDATE someone has to remember to run.
    assert "embedded_tier IS DISTINCT FROM" in sql


def test_stale_predicate_is_tier_specific():
    # A row embedded by the big model is stale for the small one and vice
    # versa; without this, switching back and forth could not be cheap. The
    # tier travels as a BOUND parameter, never inlined into the SQL.
    for tier in ("fp32", "int8"):
        compiled = stale_predicate(tier).compile(dialect=postgresql.dialect())
        assert tier in compiled.params.values()


# --------------------------------------------------------------------------- #
# Estimates come from measurement, or they do not exist.


#: What `get_embed_measurements` returns: rows and seconds per tier. The
#: estimator is pure, so these are the whole input.
FP32_MEASURED = {"fp32": {"rows": 1000, "seconds": 500.0}}  # 2 rows/s


def test_no_measurement_means_no_estimate():
    # Without a recorded rate, an estimated duration would be an invented figure.
    assert estimate_seconds({}, "fp32", 4548) is None
    assert estimate_seconds({"fp32": {}}, "fp32", 4548) is None
    assert estimate_seconds({"fp32": {"rows": 0, "seconds": 0.0}}, "fp32", 4548) is None


def test_estimate_uses_this_computers_own_rate():
    # 1,000 rows in 500 s = 2 rows/s, so 4,000 rows is 2,000 s.
    assert estimate_seconds(FP32_MEASURED, "fp32", 4000) == 2000


def test_estimate_scales_across_tiers_when_only_one_is_measured():
    # Only the big model has ever run here; the small one is estimated from it
    # by the measured rate ratio, never by guessing.
    scaled = estimate_seconds(FP32_MEASURED, "int8", 4000)

    assert scaled == int(4000 / (2.0 * INT8_RATE_RATIO))
    # The small model is slower per row, so its estimate must be LONGER.
    assert scaled > 2000


def test_a_direct_measurement_beats_a_scaled_one():
    measured = FP32_MEASURED | {"int8": {"rows": 1000, "seconds": 1000.0}}  # 1 row/s

    assert estimate_seconds(measured, "int8", 4000) == 4000


def test_nothing_owed_means_nothing_to_estimate():
    assert estimate_seconds(FP32_MEASURED, "fp32", 0) is None
    assert estimate_seconds(FP32_MEASURED, None, 4000) is None


# --------------------------------------------------------------------------- #
# Recording: a pass too small to mean anything must not become the estimate.


@pytest.mark.asyncio
async def test_tiny_passes_are_not_recorded():
    from tracker.settings_store import record_embed_measurement

    executed = []

    class Recorder(_Session):
        async def execute(self, stmt):
            executed.append(stmt)
            return Upserted(stmt)

    session = Recorder({})
    # A three-row nightly top-up is dominated by model load; using it as the
    # rate would put a 4,500-row estimate out by an order of magnitude.
    await record_embed_measurement(session, tier="fp32", rows=3, seconds=40.0)
    assert executed == []

    await record_embed_measurement(session, tier="fp32", rows=500, seconds=250.0)
    assert len(executed) == 1


# --------------------------------------------------------------------------- #
# Script-entry ordering.


def test_helpers_are_defined_before_the_script_entry():
    """Everything `_run_locked` calls must be defined ABOVE `if __name__`.

    A module-level `def` placed after that guard does not exist when the file
    is run as a script: the guard executes `main()` at that point in the file,
    and the interpreter has not yet reached the definition. A full pass would
    complete and then die with `NameError` while recording how long it took,
    losing the very measurement that makes the estimate honest.
    """
    from pathlib import Path

    import tracker.semantic.backfill as backfill

    source = Path(backfill.__file__).read_text(encoding="utf-8")
    guard = source.index('if __name__ == "__main__":')
    for name in ("_peak_rss_bytes", "_MIN_NOTIFY_ROWS"):
        assert name in dir(backfill), f"{name} is not importable"
        definition = source.index(f"\n{name}" if name.isupper() else f"\ndef {name}")
        assert definition < guard, f"{name} is defined after the script entry point"
