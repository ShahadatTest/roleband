"""The coverage report: followed companies not scanned in full lately.

What must hold, each a plausible way to get it wrong:

1. **Why is read from what the run recorded.** An errored run, or a page that
   answered an HTTP error status, was unreachable even when it scanned
   nothing; a page that answered and gave no rows was unreadable; a run that
   read some rows read part of the board; only the `empty` outcome is an empty
   page. The shapes come from the real adapters answering a mocked transport,
   not from hand-made dicts.
2. **A full scan is `ok`, `empty` or `lossy`.** The clock is the newest of
   those; the cause is the newest reconcile SINCE it that was none of them,
   and a deferral (`unattempted`) is no evidence either way.
3. **Stale is 3 days without a full scan**, counted from the binding's
   creation when there never was one: a company followed yesterday is not
   stale.
4. **Only followed companies, only their active binding**, never a retired
   one; an empty board is flagged however fresh.
5. **Counts cover every followed company even when the list is cut**, and an
   outage is five or more stale companies that are half or more of the ones
   scanned automatically.
6. **A board gone from its address leaves the status alone unless its provider
   is failing**: five or more of one provider's automatic boards, and half or
   more of them, answering "no such board". Companies moving their boards a
   few at a time across a large roster never add up to a provider failing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from tests.company_contract_seed import company_job
from tests.test_empty_board_proof import SR_NO_OPENINGS
from tracker.config import Settings
from tracker.connectors import build_adapter
from tracker.connectors.listing.base import RateLimiter
from tracker.connectors.recipes.outcome import classify_source_outcome
from tracker.db.models import ScrapeRun, ScrapeSourceRun, SourceBinding, TrackedCompany
from tracker.db.queries.binding_attention import (
    CAUSE_BOARD_MISSING,
    CAUSE_EMPTY_LISTING,
    CAUSE_PARTIAL,
    CAUSE_UNKNOWN,
    CAUSE_UNREACHABLE,
    CAUSE_UNREADABLE,
    FULL_SCAN_OUTCOMES,
    OUTAGE_MIN,
    FollowedBinding,
    attention_item,
    binding_attention,
    boards_gone,
    cause_of,
    followed_bindings,
    is_outage,
    missing_burst,
)
from tracker.source_review import SOURCE_REVIEWS
from tracker.workflows.collection_types import empty_stats

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
#: The shipped default (`Settings.coverage_stale_after_days`); the router and
#: the notice pass read the setting and hand it in.
STALE_AFTER = timedelta(days=Settings.model_fields["coverage_stale_after_days"].default)

# --------------------------------------------------------------------------- #
# 1. Pure: cause, the full-scan set, stale, outage
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("outcome", "scanned", "errors", "expected"),
    [
        # google/microsoft ReadError rows: nothing scanned BECAUSE nothing was read.
        ("failed", 0, ["ReadError: "], CAUSE_UNREACHABLE),
        ("blocked", 0, ["HTTP 403"], CAUSE_UNREACHABLE),
        # A degraded run with an error is still unreachable in part: the error wins.
        ("degraded", 212, ["HTTP 500 page 3"], CAUSE_UNREACHABLE),
        ("degraded", 212, [], CAUSE_PARTIAL),
        # Our own ceilings read part of a board that answered.
        ("bounded", 900, [], CAUSE_PARTIAL),
        ("truncated", 1000, [], CAUSE_PARTIAL),
        # Nothing scanned and nothing said: the page answered, unreadably.
        ("failed", 0, [], CAUSE_UNREADABLE),
        (None, None, [], CAUSE_UNKNOWN),
    ],
)
def test_cause_is_read_from_the_run_structure(outcome, scanned, errors, expected):
    assert cause_of(outcome, scanned, errors, []) == expected


@pytest.mark.parametrize("message", ["empty job list", "empty job board"])
def test_a_zero_the_board_could_not_prove_is_never_an_empty_board(message):
    """The families that can prove an empty board call `board_empty`; the ones
    saying "empty job list" are exactly those that cannot tell empty from
    broken (atlassian, avature, kpmg, shopify, smartrecruiters, successfactors,
    tiktok). A quarantined KPMG must not tell the user it stopped hiring."""
    assert cause_of("failed", 0, [], [{"message": message}]) == CAUSE_UNREADABLE


async def _listing(adapter_name: str, respond, *, token: str | None = None) -> tuple[str, int, list, list]:
    """One listing read by the REAL adapter over a mocked transport, recorded
    the way `collection.collect_source` records it."""
    adapter = build_adapter(f"probe-{adapter_name}", adapter_name, token)
    if adapter_name == "workday":
        adapter.collection_consent = SOURCE_REVIEWS["workday"].wall_fingerprint
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    adapter._limiter = RateLimiter(0.0)
    async with adapter._client:
        scanned = len([job async for job in adapter.fetch()])
    adapter.drift.settle_listing(scanned=scanned)
    stats = {
        **empty_stats(),
        "scanned": scanned,
        "records_dropped": adapter.drift.records_dropped,
        "listing_invalidated": adapter.drift.listing_invalidated,
        "empty_proven": adapter.drift.empty_proven,
        "list_complete": adapter.drift.listing_complete,
    }
    return classify_source_outcome(stats).value, scanned, stats["errors"], list(adapter.drift.alerts)


_WORKDAY = "example.wd1.myworkdayjobs.com|External"
_KPMG_ZERO = (
    '<html><body><div class="eyebrow text-blue search--showing hide-for-favorite">'
    '<span data-action="count">0</span> Results</div></body></html>'
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter_name", "token", "status", "body", "outcome", "expected"),
    [
        # The board answered and listed nothing.
        ("ashby", None, 200, {"jobs": []}, "empty", CAUSE_EMPTY_LISTING),
        ("greenhouse", None, 200, {"jobs": []}, "empty", CAUSE_EMPTY_LISTING),
        # A SmartRecruiters board with no openings: its notice, no page count.
        ("smartrecruiters", "Dailymotion", 200, SR_NO_OPENINGS, "empty", CAUSE_EMPTY_LISTING),
        # A board root answering 404 is never an empty careers page, and not a
        # page that is down either: the board's own address says no such
        # board, the answer a made-up token gets (as when a company moves its
        # board). Each family's board root.
        ("ashby", None, 404, {"error": "not found"}, "failed", CAUSE_BOARD_MISSING),
        ("greenhouse", None, 404, {"status": 404, "error": "Job board not found"}, "failed",
         CAUSE_BOARD_MISSING),
        ("lever", None, 404, {"ok": False, "error": "Document not found"}, "failed", CAUSE_BOARD_MISSING),
        ("workable", None, 404, {"error": "Not found"}, "failed", CAUSE_BOARD_MISSING),
        # The control: a board root refusing us is a page that is not answering.
        ("ashby", None, 403, {"error": "forbidden"}, "failed", CAUSE_UNREACHABLE),
        # A body with no `jobs` array, a maintenance page, a payload missing
        # its array: the page answered and we could not read it. Never empty.
        ("ashby", None, 200, {"apiVersion": "1"}, "failed", CAUSE_UNREADABLE),
        ("workday", _WORKDAY, 200, "<html>down for maintenance</html>", "failed", CAUSE_UNREADABLE),
        ("workday", _WORKDAY, 200, {"total": 12}, "failed", CAUSE_UNREADABLE),
        # KPMG's own search page answering "0 Results" with no postings: a
        # zero its family cannot prove ("empty job list"), so never empty.
        ("kpmg", None, 200, _KPMG_ZERO, "failed", CAUSE_UNREADABLE),
    ],
    ids=["ashby-empty", "greenhouse-empty", "smartrecruiters-no-openings", "ashby-404", "greenhouse-404", "lever-404", "workable-404",
         "ashby-403", "ashby-no-array", "workday-non-json", "workday-no-array",
         "kpmg-zero-results"],
)
async def test_empty_needs_the_board_to_say_so(adapter_name, token, status, body, outcome, expected):
    def respond(_request: httpx.Request) -> httpx.Response:
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)

    recorded, scanned, errors, drift = await _listing(adapter_name, respond, token=token)
    assert (recorded, scanned) == (outcome, 0)
    assert cause_of(recorded, scanned, errors, drift) == expected, drift


def test_a_full_scan_is_one_that_read_the_whole_board():
    assert set(FULL_SCAN_OUTCOMES) == {"ok", "empty", "lossy"}


def _row(slug: str, *, full_ago: timedelta | None = timedelta(hours=5), automatic: bool = True,
         made_ago: timedelta = timedelta(days=60), held_open: int = 0,
         empty_since: datetime | None = None) -> FollowedBinding:
    return FollowedBinding(
        binding_id=sum(map(ord, slug)), company_slug=slug, display=slug.title(), provider="ashby",
        connector_kind="adapter", automatic=automatic, created_at=NOW - made_ago,
        last_full_scan_at=NOW - full_ago if full_ago is not None else None,
        last_attempted_at=NOW, held_open=held_open, empty_since=empty_since,
    )


def test_stale_is_three_days_without_a_full_scan_counted_from_creation_when_never_scanned():
    report = binding_attention([
        _row("fresh", full_ago=STALE_AFTER - timedelta(minutes=1)),
        _row("stale", full_ago=STALE_AFTER),
        _row("never", full_ago=None),
        _row("newco", full_ago=None, made_ago=timedelta(days=1)),
    ], NOW, stale_after=STALE_AFTER)
    by = {i["company"]: i for i in report["items"]}
    assert set(by) == {"stale", "never"}, "fresh and a company followed yesterday are not flagged"
    assert (by["stale"]["days_since_full_scan"], by["never"]["never_scanned"]) == (3.0, True)
    assert by["never"]["days_since_full_scan"] == 60.0


def test_the_stale_boundary_is_the_callers(monkeypatch):
    """The projection reads no settings: the bound it is handed decides."""
    report = binding_attention(
        [_row("four", full_ago=timedelta(days=4))], NOW, stale_after=timedelta(days=5)
    )
    assert report["items"] == []
    report = binding_attention(
        [_row("four", full_ago=timedelta(days=4))], NOW, stale_after=STALE_AFTER
    )
    assert [i["company"] for i in report["items"]] == ["four"]


def test_an_empty_board_is_flagged_however_fresh():
    report = binding_attention(
        [_row("emptyco", empty_since=NOW - timedelta(hours=3))], NOW, stale_after=STALE_AFTER
    )
    (item,) = report["items"]
    assert (item["stale"], item["cause"], item["days_empty"]) == (False, CAUSE_EMPTY_LISTING, 0.1)


def test_order_and_counts_survive_the_cut():
    rows = [
        _row("zeta", full_ago=timedelta(days=9), automatic=False, held_open=4),
        _row("alpha", full_ago=timedelta(days=4), held_open=1),
        _row("beta", full_ago=timedelta(days=6), held_open=2),
        _row("fine"),
    ]
    report = binding_attention(rows, NOW, stale_after=STALE_AFTER, max_items=2)
    assert [i["company"] for i in report["items"]] == ["beta", "alpha"], (
        "the automatic first, longest without a full scan first; Workday-like zeta last"
    )
    assert (report["followed"], report["automatic"], report["flagged"], report["stale"]) == (4, 3, 3, 3)
    assert (report["held_open"], report["outage"]) == (7, False)


def test_an_outage_is_many_stale_at_once_and_half_or_more_of_the_automatic():
    def items(stale: int, fresh: int, *, automatic: bool = True) -> list[dict]:
        rows = [_row(f"s{i}", full_ago=timedelta(days=4), automatic=automatic) for i in range(stale)]
        rows += [_row(f"f{i}") for i in range(fresh)]
        return binding_attention(rows, NOW, stale_after=STALE_AFTER)["items"]

    assert is_outage(items(5, 5), 10)
    assert not is_outage(items(4, 0), 4), "four is a few companies' own trouble"
    assert not is_outage(items(5, 6), 11), "under half of the automatic"
    assert not is_outage(items(6, 0, automatic=False), 0), "Workday companies are never an outage"
    empty = [_row(f"e{i}", empty_since=NOW) for i in range(5)]
    assert not is_outage(binding_attention(empty, NOW, stale_after=STALE_AFTER)["items"], 5), "an empty board is its own news"


#: What the boards of companies that moved answered (Ashby: plain text).
_ASHBY_GONE = (404, "Not Found")
_GREENHOUSE_GONE = (404, {"status": 404, "error": "Job not found"})


async def _read(adapter_name: str, status: int, body) -> tuple[str, int, list, list]:
    # A retried status is retried at once: what a read is called, not the
    # client's backoff, is the contract here.
    headers = {"Retry-After": "0"}

    def respond(_request: httpx.Request) -> httpx.Response:
        if isinstance(body, str):
            return httpx.Response(status, text=body, headers=headers)
        return httpx.Response(status, json=body, headers=headers)

    return await _listing(adapter_name, respond)


def _followed(binding_id: int, provider: str, read: tuple[str, int, list, list] | None = None, *,
              automatic: bool = True) -> FollowedBinding:
    """A followed company read in full five hours ago, or, given `read`, read in
    full four days ago and since then read as `read` says."""
    outcome, scanned, errors, drift = read or (None, None, [], [])
    return FollowedBinding(
        binding_id=binding_id, company_slug=f"{provider}-{binding_id}", display=f"Co {binding_id}",
        provider=provider, connector_kind="adapter", automatic=automatic, created_at=NOW - timedelta(days=60),
        last_full_scan_at=NOW - (timedelta(days=4) if read else timedelta(hours=5)), last_attempted_at=NOW,
        held_open=0, cause_outcome=outcome, cause_at=NOW if read else None, cause_scanned=scanned,
        cause_errors=errors, cause_drift=drift,
    )


def _roster(**providers: tuple[int, int, tuple]) -> tuple[list[FollowedBinding], set[int]]:
    """provider=(followed, gone, read): `followed` automatic boards of which
    `gone` were last read as `read`. The ids of the gone ones come back too."""
    rows: list[FollowedBinding] = []
    gone: set[int] = set()
    for provider, (followed, missing, read) in providers.items():
        for n in range(followed):
            binding_id = len(rows) + 1
            if n < missing:
                gone.add(binding_id)
            rows.append(_followed(binding_id, provider, read if n < missing else None))
    return rows, gone


def _items(rows: list[FollowedBinding]) -> list[dict]:
    """Every followed company's item, as `coverage.coverage_report` builds them."""
    return [{**attention_item(r, NOW, stale_after=STALE_AFTER), "binding_id": r.binding_id} for r in rows]


@pytest.mark.asyncio
async def test_companies_moving_their_boards_a_few_at_a_time_leave_the_status_however_many_add_up():
    """The case that held a 3,000-company roster "Stale" for a week: thirteen
    boards gone over several days across three providers, none of them more
    than a sliver of its provider's boards. A count over the whole roster
    called that a provider outage and left every one holding the status."""
    ashby, greenhouse = await _read("ashby", *_ASHBY_GONE), await _read("greenhouse", *_GREENHOUSE_GONE)
    workable = await _read("workable", 404, {"error": "Not found"})
    rows, gone = _roster(greenhouse=(40, 8, greenhouse), ashby=(40, 4, ashby), workable=(10, 1, workable))
    assert len(gone) == 13 >= OUTAGE_MIN
    assert boards_gone(rows) == gone
    assert missing_burst(_items(rows)) is False


@pytest.mark.asyncio
async def test_a_provider_answering_no_such_board_for_half_or_more_of_its_boards_is_failing():
    """The control: that is the provider's answer, so each board keeps the status
    stale like any unreachable page, and the bell waits for the outage notice."""
    gone_read = await _read("greenhouse", *_GREENHOUSE_GONE)

    def burst(followed: int, missing: int) -> bool:
        rows, gone = _roster(greenhouse=(followed, missing, gone_read), ashby=(40, 0, ()))
        verdict = missing_burst(_items(rows))
        assert boards_gone(rows) == (frozenset() if verdict else gone), "the status and the bell agree"
        return verdict

    assert burst(10, 6)
    assert burst(10, 5), "half is enough"
    assert not burst(11, 5), "under half"
    assert not burst(4, 4), "four boards are a few companies' own news, however small the provider"


@pytest.mark.asyncio
async def test_a_board_that_is_down_is_never_gone_from_its_address():
    """A 503 is a page not answering today, not a company that moved: it waits
    to go stale like any unreachable page."""
    down = await _read("greenhouse", 503, {"error": "Service Unavailable"})
    assert cause_of(*down) == CAUSE_UNREACHABLE
    rows, _ = _roster(greenhouse=(10, 1, down))
    assert boards_gone(rows) == frozenset()


@pytest.mark.asyncio
async def test_boards_scanned_only_on_request_never_make_a_provider_failing():
    gone_read = await _read("ashby", *_ASHBY_GONE)
    rows = [_followed(n, "workday", gone_read, automatic=False) for n in range(1, 7)]
    assert missing_burst(_items(rows)) is False
    assert boards_gone(rows) == frozenset(range(1, 7))


# --------------------------------------------------------------------------- #
# 2. The query, on seeded Postgres rows
# --------------------------------------------------------------------------- #


def _company(slug: str, *, enabled: bool = True, adapter: str = "ashby") -> TrackedCompany:
    return TrackedCompany(slug=slug, display=slug.title(), adapter=adapter, status="active",
                          enabled=enabled, visible=True, source="catalog")


def _run(run_id: int, binding: int, slug: str, outcome: str, *, hours_ago: float, scanned: int = 0,
         errors: list | None = None, drift: list | None = None) -> ScrapeSourceRun:
    started = NOW - timedelta(hours=hours_ago)
    return ScrapeSourceRun(
        run_id=run_id, binding_id=binding, company_slug=slug, provider_key=f"ashby:{slug}",
        scan_mode="reconcile", outcome=outcome, started_at=started, finished_at=started + timedelta(seconds=5),
        scanned=scanned, errors=errors or [], drift=drift or [],
    )


@pytest.mark.asyncio
async def test_the_query_reads_each_followed_companys_active_binding_from_its_runs(db_session):
    db_session.add_all([
        _company("downco"),                 # full scan 4 days ago, failures since
        _company("emptyco"),                # newest reconcile proved the board empty
        _company("fineco"),                 # lossy read 2h ago: a full scan
        _company("dirco", enabled=False),   # unfollowed: not in the report at all
        _company("movedco"),                # its only binding is RETIRED
        _company("twinco"),                 # stable binding + a newer proposal
        _company("wdco", adapter="workday"),
        _company("oldco"),                  # failed, then a full scan, then nothing for 4 days
    ])
    await db_session.flush()
    made = NOW - timedelta(days=30)

    def binding(id_: int, slug: str, **over) -> SourceBinding:
        row = dict(id=id_, company_slug=slug, connector_kind="adapter", connector_id="ashby",
                   status="stable", closure_capability="authoritative", created_at=made)
        row.update(over)
        return SourceBinding(**row)

    db_session.add_all([
        binding(11, "downco"), binding(12, "emptyco"), binding(13, "fineco"), binding(14, "dirco"),
        binding(15, "movedco", status="retired", retired_at=NOW - timedelta(days=1)),
        binding(16, "twinco"), binding(17, "twinco", connector_id="lever", status="proposed",
                                       closure_capability="none", created_at=NOW),
        binding(18, "wdco", connector_id="workday"),
        binding(19, "oldco"),
    ])
    await db_session.flush()
    for run_id in range(1, 9):
        db_session.add(ScrapeRun(id=run_id, started_at=NOW - timedelta(hours=run_id), status="partial"))
    await db_session.flush()
    db_session.add_all([
        # downco: full scan 4 days ago; then an errored run, then a newer
        # bounded one (read in part) and a newer deferral (no evidence).
        _run(8, 11, "downco", "ok", hours_ago=96, scanned=40),
        _run(4, 11, "downco", "failed", hours_ago=10, errors=["ReadError: "]),
        _run(3, 11, "downco", "bounded", hours_ago=5, scanned=30),
        _run(2, 11, "downco", "unattempted", hours_ago=1),
        # emptyco: listed 88, then empty twice. The streak is its OWN: another
        # binding's newer non-empty scan (fineco's) must not end it.
        _run(7, 12, "emptyco", "ok", hours_ago=72, scanned=88),
        _run(6, 12, "emptyco", "empty", hours_ago=48),
        _run(5, 12, "emptyco", "empty", hours_ago=4),
        _run(7, 13, "fineco", "ok", hours_ago=100, scanned=10),
        _run(1, 13, "fineco", "lossy", hours_ago=2, scanned=1200),
        _run(8, 14, "dirco", "ok", hours_ago=900, scanned=3),
        _run(8, 15, "movedco", "failed", hours_ago=96),
        _run(8, 16, "twinco", "ok", hours_ago=6, scanned=5),
        _run(8, 18, "wdco", "ok", hours_ago=120, scanned=9),
        # oldco: the failure is OLDER than the full scan, so it explains nothing now.
        _run(7, 19, "oldco", "failed", hours_ago=150, errors=["ReadError: "]),
        _run(6, 19, "oldco", "ok", hours_ago=100, scanned=7),
    ])
    db_session.add_all([
        company_job("downco", "d1"), company_job("downco", "d2"), company_job("downco", "d3", status="closed"),
        company_job("emptyco", "e1"),
    ])
    await db_session.commit()

    workday = {"wdco"}
    rows = await followed_bindings(db_session, automatic=lambda _p, slug, _c: slug not in workday)
    assert [(r.company_slug, r.binding_id) for r in rows] == [
        ("downco", 11), ("emptyco", 12), ("fineco", 13), ("oldco", 19), ("twinco", 16), ("wdco", 18),
    ], "followed only, the active binding only (twinco's stable one, never movedco's retired one)"
    report = binding_attention(rows, NOW, stale_after=STALE_AFTER)
    by = {i["company"]: i for i in report["items"]}
    assert set(by) == {"downco", "emptyco", "oldco", "wdco"}, "fineco's lossy read and twinco's ok are full scans"
    old = by["oldco"]
    assert (old["stale"], old["cause"], old["cause_outcome"]) == (True, CAUSE_UNKNOWN, None), (
        "a failure before the last full scan is not why it is stale now"
    )

    down = by["downco"]
    assert (down["stale"], down["days_since_full_scan"], down["held_open"]) == (True, 4.0, 2)
    assert (down["cause"], down["cause_outcome"], down["cause_at"]) == (
        CAUSE_PARTIAL, "bounded", NOW - timedelta(hours=5),
    ), "the newest run since the full scan, never the newer deferral"
    assert down["last_attempted_at"] == NOW - timedelta(hours=5)
    empty = by["emptyco"]
    assert (empty["stale"], empty["cause"], empty["empty_since"], empty["listed_before"]) == (
        False, CAUSE_EMPTY_LISTING, NOW - timedelta(hours=48), 88,
    )
    wd = by["wdco"]
    assert (wd["automatic"], wd["stale"]) == (False, True)
    assert [i["company"] for i in report["items"]] == ["oldco", "downco", "emptyco", "wdco"]
    assert (report["followed"], report["automatic"], report["stale"], report["empty"]) == (6, 5, 3, 1)
