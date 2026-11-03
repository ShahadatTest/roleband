"""Grading one `ai_task_log` row, and folding rows into per-tier measurements.

Pure: given rows, it answers whether each counts as a success and what the tiers
look like over the measurement window. Reading and writing those rows needs the
database and lives in `tracker/intelligence_runtime/telemetry.py`;
this half is what `policy.py` reasons about, and it stays down here with it.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from tracker.intelligence.policy import TierMeasurement

#: How far back a tier's record reaches. This bound is what makes a measured
#: veto RECOVERABLE: a vetoed tier is skipped, a skipped tier logs no new rows,
#: so without a window its attempts/ok record could never change again and one
#: bad stretch would lock the tier out permanently: the same self-locking trap as a
#: quarantine whose only exit needs the run quarantine prevents. With the
#: window, the failure rows age out and the tier earns a fresh probe.
MEASUREMENT_WINDOW_DAYS = 14


def measurement_cutoff(now: datetime | None = None) -> datetime:
    """Oldest `created_at` still allowed to influence routing."""
    return (now or datetime.now(UTC)) - timedelta(days=MEASUREMENT_WINDOW_DAYS)


#: Verdict lookup for graded tasks: `(proposal_kind, link_id) -> human status`.
#: Passed IN rather than fetched here so the fold stays DB-free.
Verdicts = dict[tuple[str, int], str]


def grade_row(task_type: str, row, verdicts: Verdicts | None = None) -> bool | None:
    """Did an INDEPENDENT referee agree with this answer?

    `None` means ungraded — no referee evidence either way — and it is the
    common case by design. A referee has to be independent of the model to mean
    anything, so only two exist:

    **`disclosed_comp` -> deterministic grounding.** `find_pay_span` /
    `extract_grounded_band` read the same input text the model read and either
    corroborate or contradict it. Three gradable outcomes:

    * the model claimed a band that failed grounding, recorded as
      `validation_result="invalid"`, `failure_class="validation"`;
    * the model said "no band" and the deterministic extractor then found one
      (`meta.deterministic_recovery`). It is logged `validation_result="ok"`,
      because the response *did* parse, and counting it as a success is
      precisely the confusion this metric exists to end;
    * the model claimed a band and it survived grounding — the referee agreed.

    A model saying "no band" with nothing recovered stays **ungraded**: the
    posting probably has no band, but nothing here can prove it, and inventing a
    verdict from silence would make the metric unfalsifiable.

    **`duplicate_review` -> the human verdict.** `meta` already carries
    `link_id`, `proposal_kind` and `recommendation`, and the model's vocabulary
    (`confirmed`/`rejected`) is the same as the link's human `status`, so the
    comparison is direct. `proposal_kind` is REQUIRED: lineage and twin link ids
    collide (exclusivity means the same pair appears under both), so an
    id alone could be graded against the wrong row's verdict.

    `uncertain` counts as **incorrect**, not ungraded. Treating a hedge as
    unmeasurable would let a model reach perfect accuracy by never committing —
    the same falsifiability rule that made synthetic negative controls
    mandatory. A judge that will not judge did not help.

    Only reviewed links grade. A `pending` link has no verdict yet, and the
    bench script's synthetic controls carry negative ids with no link row at
    all — their ground truth lives in the bench, not the database, so grading
    them here would encode one script's construction into the substrate.
    """
    meta = row.meta if isinstance(getattr(row, "meta", None), dict) else {}

    if task_type.startswith("disclosed_comp"):
        if meta.get("deterministic_recovery"):
            return False
        if row.validation_result == "invalid":
            # Only the referee's own verdict grades. A timeout or SDK error is a
            # mechanical failure that says nothing about the model's judgement.
            return False if row.failure_class == "validation" else None
        if row.validation_result == "ok" and meta.get("disclosed"):
            return True
        return None

    if task_type.startswith("duplicate_review"):
        kind, link_id = meta.get("proposal_kind"), meta.get("link_id")
        recommendation = meta.get("recommendation")
        if not kind or link_id is None or not recommendation:
            return None
        verdict = (verdicts or {}).get((kind, int(link_id)))
        if verdict not in {"confirmed", "rejected"}:
            return None
        return recommendation == verdict

    return None


def fold_measurements(
    rows: Iterable, *, task_type: str | None = None, verdicts: Verdicts | None = None
) -> dict[str, TierMeasurement]:
    """Pure fold of `ai_task_log` rows into per-tier records.

    Each row needs `.provider`, `.validation_result`, `.failure_class`,
    `.latency_ms`, `.meta` — split from the fetch so every routing input is
    unit-testable without a database, matching `policy`'s DB-free rule.

    Two sources of evidence per row, and the split matters:

    - The ANSWERING tier (`row.provider`) is judged by `validation_result` —
      the router's per-attempt "ok" only means "returned parseable fields",
      and a tier whose fields then fail our validator must not count as ok.
    - EARLIER tiers live only in `meta.route_attempts`. A tier that failed and
      escalated leaves no row of its own, so without them its failures would
      be invisible and the veto could never engage in ladder mode. Only their
      `failed` entries count; `skipped` entries are
      runs where the tier was never asked, and the answering tier's own entry
      is already covered by the row itself.

    Accuracy follows the same split, and it has to. A tier whose
    answer was REFUTED never gets a row of its own — the row belongs to
    whichever tier answered after it — so grading only the answering tier means
    a rejected answer is never scored against the tier that gave it, and a
    tier would report perfect accuracy while its refuted answers escalated away.
    """
    attempts: dict[str, int] = {}
    ok: dict[str, int] = {}
    failures: dict[str, dict[str, int]] = {}
    latencies: dict[str, list[int]] = {}
    graded: dict[str, int] = {}
    correct: dict[str, int] = {}

    def record(
        provider: str,
        *,
        is_ok: bool,
        failure_class: str | None,
        latency_ms,
        grade: bool | None = None,
    ) -> None:
        attempts[provider] = attempts.get(provider, 0) + 1
        if is_ok:
            ok[provider] = ok.get(provider, 0) + 1
        elif failure_class:
            per = failures.setdefault(provider, {})
            per[failure_class] = per.get(failure_class, 0) + 1
        if isinstance(latency_ms, int):
            latencies.setdefault(provider, []).append(latency_ms)
        if grade is not None:
            graded[provider] = graded.get(provider, 0) + 1
            if grade:
                correct[provider] = correct.get(provider, 0) + 1

    for row in rows:
        record(
            row.provider,
            is_ok=row.validation_result == "ok",
            failure_class=row.failure_class,
            latency_ms=row.latency_ms,
            # Only the ANSWERING tier is graded. An earlier tier's
            # `route_attempts` entry records that it failed, never what it
            # answered — there is no output for a referee to judge.
            # The answering tier is graded from the row itself; earlier tiers
            # are graded below, from their `route_attempts` entry.
            grade=grade_row(task_type, row, verdicts) if task_type else None,
        )
        meta = row.meta if isinstance(row.meta, dict) else {}
        for attempt in meta.get("route_attempts") or []:
            if not isinstance(attempt, dict):
                continue
            provider = attempt.get("provider")
            if not provider or provider == row.provider:
                continue
            if attempt.get("outcome") != "failed":
                continue
            failure_class = attempt.get("failure_class")
            record(
                provider,
                is_ok=False,
                failure_class=failure_class,
                latency_ms=attempt.get("latency_ms"),
                # `validation` is the one failure class that IS a judgement: the
                # caller's referee saw the tier's answer and refuted it, which
                # is exactly what `grade_row` scores elsewhere. Every other
                # class (timeout, sdk_error) means no answer existed to judge.
                #
                # Without this the metric flatters the tier it was built to
                # expose: a refuted answer only ever appears in
                # `route_attempts` (the row itself belongs to whichever tier
                # answered next), so the tier would report perfect accuracy.
                grade=False if failure_class == "validation" else None,
            )

    return {
        provider: TierMeasurement(
            provider=provider,
            attempts=count,
            ok=ok.get(provider, 0),
            failures=failures.get(provider, {}),
            p50_latency_ms=_percentile(latencies.get(provider), 0.5),
            p90_latency_ms=_percentile(latencies.get(provider), 0.9),
            graded=graded.get(provider, 0),
            correct=correct.get(provider, 0),
        )
        for provider, count in attempts.items()
    }


def _percentile(values: list[int] | None, q: float) -> int | None:
    """`percentile_cont` semantics (linear interpolation), small-list scale."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return int(ordered[low] + (ordered[high] - ordered[low]) * (position - low))
