"""Listing-connector contracts, parametrized over ADAPTER_REGISTRY.

Every adapter must (1) own a fixtures directory + harness (failure names the
adapter, blueprint-style), (2) parse its fixtures into valid RawJobs, (3)
terminate when the source serves the same page forever, (4) degrade a mangled
payload to drift instead of crashing, and (5) survive a 429 + Retry-After via
the shared retry path. These pins protect the CURRENT connector behavior: a
refactor must keep them green unchanged.
"""

from __future__ import annotations

import asyncio
from functools import partial

import pytest

from tests.contracts import conftest as harnesses
from tests.contracts.artifacts import missing_artifacts
from tests.contracts.conftest import (
    MODE_BROKEN,
    MODE_FLAKY_429,
    MODE_NORMAL,
    MODE_REPEAT,
    REQUEST_CAP,
    build_harness,
    run_fetch,
)
from tracker.connectors import ADAPTER_REGISTRY, build_adapter
from tracker.connectors.listing.base import BaseAdapter, DriftError
from tracker.platform.paging import StopReason
from tracker.schema import RawJob, dedupe_key_for

ADAPTER_NAMES = sorted(ADAPTER_REGISTRY)
#: Adapters that claim a newest-first listing, and so a discovery frontier.
FRONTIER_ORDERED = [name for name in ADAPTER_NAMES if ADAPTER_REGISTRY[name].discovery_frontier_ordered]


def test_every_registry_adapter_has_fixtures_and_harness():
    """Blueprint-style completeness gate: failures name the adapter."""
    problems = missing_artifacts(ADAPTER_NAMES)
    assert not problems, "listing contract artifacts missing:\n" + "\n".join(problems)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ADAPTER_NAMES)
async def test_fixtures_parse_into_valid_rawjobs(name):
    adapter = build_harness(name, MODE_NORMAL)
    jobs = await run_fetch(adapter)

    assert jobs, f"{name}: fixtures yielded no RawJobs"
    for job in jobs:
        assert isinstance(job, RawJob)
        assert isinstance(job.req_id, str) and job.req_id.strip(), f"{name}: empty req_id"
        assert isinstance(job.title, str) and job.title.strip(), f"{name}: empty title"
        assert isinstance(job.company, str) and job.company.strip()
        assert isinstance(job.url, str) and job.url.strip(), f"{name}: empty url"
        assert isinstance(job.locations, list)
        assert all(isinstance(loc, str) and loc for loc in job.locations)
    # Clean fixtures must not trip the drift detector.
    assert adapter.drift.listing_complete is True, f"{name}: drift on clean fixtures"
    assert adapter.drift.alerts == [], f"{name}: alerts on clean fixtures: {adapter.drift.alerts}"


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ADAPTER_NAMES)
async def test_repeated_listing_page_terminates(name):
    """A source cycling the same page forever must not hang fetch().

    The harness serves page1 for every listing request; the mock transport
    asserts the request count stays under REQUEST_CAP, so an unbounded
    pagination loop fails here instead of hanging the suite.
    """
    adapter = build_harness(name, MODE_REPEAT)
    jobs = await run_fetch(adapter)

    assert isinstance(jobs, list)
    assert adapter.contract_requests.count <= REQUEST_CAP


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ADAPTER_NAMES)
async def test_broken_payload_degrades_to_drift(name):
    """A structurally mangled payload is drift, never an unhandled crash."""
    adapter = build_harness(name, MODE_BROKEN)
    try:
        await run_fetch(adapter)
    except DriftError:
        # Controlled failure path: an adapter may raise the domain error.
        return

    assert not adapter.drift.listing_complete or adapter.drift.alerts, (
        f"{name}: mangled payload was neither invalidated nor alerted"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ADAPTER_NAMES)
async def test_429_with_retry_after_recovers(name, monkeypatch):
    """First response 429 (Retry-After: 0) -> retry runs -> fetch still succeeds."""
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    adapter = build_harness(name, MODE_FLAKY_429)
    jobs = await run_fetch(adapter)

    assert jobs, f"{name}: fetch yielded nothing after a retryable 429"
    assert adapter.contract_requests.count >= 2, f"{name}: the 429 was never retried"
    assert adapter.drift.listing_complete is True
    assert adapter.drift.alerts == []


# --------------------------------------------------------------------------- #
# Discovery frontier contract.
#
# `discovery_frontier_ordered` promises that a probe stops at the first page
# holding a posting we already have. The stop compares what `fetch_page`
# returns, which for many adapters is the raw search row, not a RawJob. An
# adapter that never keys those rows reads every probe to its page backstop,
# and the claim goes silently unkept.
# --------------------------------------------------------------------------- #


def _discovery_probe(name: str, known: set[str], monkeypatch: pytest.MonkeyPatch) -> BaseAdapter:
    """The harness for `name`, built as a discovery probe holding `known`."""
    monkeypatch.setattr(
        harnesses, "build_adapter", partial(build_adapter, discovery=True, known_keys=known)
    )
    return build_harness(name, MODE_NORMAL)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", FRONTIER_ORDERED)
async def test_a_discovery_probe_stops_at_every_row_it_already_holds(name, monkeypatch):
    held = await run_fetch(build_harness(name, MODE_NORMAL))
    assert held, f"{name}: fixtures yielded no RawJobs"

    for job in held:
        adapter = _discovery_probe(name, {job.dedupe_key()}, monkeypatch)
        await run_fetch(adapter)
        reasons = {o.stop_reason for o in adapter.query_observations}
        assert reasons == {StopReason.FRONTIER}, (
            f"{name}: a probe holding {job.req_id!r} ended {sorted(r.value for r in reasons)}"
        )

    # Negative control: a probe that holds none of these rows has no frontier.
    adapter = _discovery_probe(name, {dedupe_key_for(held[0].company, "not-on-this-board")}, monkeypatch)
    await run_fetch(adapter)
    assert adapter.query_observations
    assert all(o.stop_reason is not StopReason.FRONTIER for o in adapter.query_observations)


# --------------------------------------------------------------------------- #
# Domain-signal metadata contract.
#
# The domain axis reads department/team as its authoritative signal, so WHICH
# fields an adapter populates is a contract, not an accident of fixture data:
# a connector change that silently drops a category field would starve the
# classifier for every company on that source while titles keep parsing fine.
# Both directions are pinned — a field appearing is as much drift as one
# vanishing (it means the declaration, and the classifier's expectations,
# are stale). meta and workday are the deliberately metadata-poor rows: they
# prove the title-only path stays honest (`[]`, never a guess).
# --------------------------------------------------------------------------- #

METADATA_FIELDS: dict[str, set[str]] = {
    "amazon": {"department", "team"},
    "apple": {"team"},
    "ashby": {"department", "team"},
    "eightfold": {"department", "team"},
    "google": {"team"},
    "greenhouse": {"department"},
    "lever": {"department", "team"},
    "meta": set(),  # title-only: exercises the domain gate's fail-open path
    "microsoft": {"department"},
    "workday": set(),  # title-only
    # `department` only. Workable also states a `function` ("Engineering"),
    # but it is a BROADER fixed taxonomy than `department` rather than a
    # team inside it, and it is empty on many rows — so the adapter
    # leaves it in `detail_payload` instead of inverting the two fields.
    "workable": {"department"},
    # The board lists title, link and location group only; department lives
    # on neither the group page nor the posting's microdata.
    "smartrecruiters": set(),
    # The Posting API states `department.label` on every row.
    "smartrecruiters_api": {"department"},
    # `category` ("Sales", "Engineering") on every row, read as department.
    "atlassian": {"department"},
    # The listing carries no category; `Category` arrives with the detail, so
    # listing-time classification is title-only, like workday.
    "oracle": set(),
    # The practice area ("Tax", "Advisory") on every card, read as department.
    "kpmg": {"department"},
    # `jobFamilyGroup` -> department, on every row (`businessArea` is empty on
    # some real rows and is not a team, so it is not promoted).
    "accenture": {"department"},
    # `list-item-department` ("People Experience & Workplaces") on every card.
    "avature": {"department"},
    # TSMC's cards carry place, employment type and posted date; the career
    # area (department) arrives only with the detail.
    "avature_tls": set(),
    # `category[0]` (" Engineering", stripped) on every row.
    "jibe": {"department"},
    # Arm's JSON-LD carries no `occupationalCategory` and no team: the title is
    # the only domain signal this family publishes.
    "radancy": set(),
    # Klarna's JSON-LD carries no `occupationalCategory` and no team.
    "deel": set(),
    # `job_category.en_name` ("R&D", "Sales") on every row.
    "tiktok": {"department"},
    # The results table carries title, link and place only.
    "successfactors": set(),
    # `discipline` ("Sales", "Engineering & Data") on every role, as `teamName`
    # is on every Ashby record.
    "shopify": {"department"},
}


def test_every_adapter_declares_its_metadata_fields():
    missing = [name for name in ADAPTER_NAMES if name not in METADATA_FIELDS]
    assert not missing, (
        "adapters missing a METADATA_FIELDS declaration (which domain-signal "
        f"fields do their fixtures populate?): {missing}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ADAPTER_NAMES)
async def test_metadata_fields_and_domain_classification_match_declaration(name):
    from tracker.enrich.classify import classify_domains
    from tracker.taxonomy.domains import all_slugs

    declared = METADATA_FIELDS[name]
    adapter = build_harness(name, MODE_NORMAL)
    jobs = await run_fetch(adapter)
    valid_domains = set(all_slugs())

    for field in ("department", "team"):
        populated = [job for job in jobs if getattr(job, field)]
        if field in declared:
            assert len(populated) == len(jobs), (
                f"{name}: declared metadata field {field!r} missing on some fixture "
                "rows — connector drift or a stale declaration"
            )
        else:
            assert not populated, (
                f"{name}: fixture rows populate undeclared field {field!r} — update "
                "METADATA_FIELDS and check the domain classifier's expectations"
            )

    for job in jobs:
        domains = classify_domains(job)
        assert isinstance(domains, list)
        assert set(domains) <= valid_domains, f"{name}: unknown domain slug in {domains}"
    if not declared:
        # Title-only sources must reach the gate as honestly-unclassified or
        # title-classified — either way a plain list, never an exception. The
        # domain gate's fail-open rule is what protects these rows downstream.
        assert all(isinstance(classify_domains(job), list) for job in jobs)


@pytest.mark.asyncio
async def test_google_url_is_the_job_path_without_listing_state():
    """A Google card's href echoes the results page's query (`page`, `sort_by`,
    `location`). Stored as-is, the URL changes whenever the listing shifts and
    never equals the shared link, so URL search cannot resolve the posting. The
    adapter keeps only the job path; the fixtures carry the live href shape.
    """
    adapter = build_harness("google", MODE_NORMAL)
    jobs = await run_fetch(adapter)

    base = "https://www.google.com/about/careers/applications/jobs/results/"
    assert {job.url for job in jobs} == {
        base + "109876543210987654-senior-staff-software-engineer-spanner",
        base + "123450987612345098-engineering-manager-ii-youtube-ads",
        base + "567890123456789012-staff-software-engineer-search-infrastructure",
    }
