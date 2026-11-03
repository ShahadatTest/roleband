"""Catalog board-token verification.

The live probe belongs in `scripts.check_catalog_tokens` — tests never touch the
network, and a hiring freeze at one company must not fail the build. What IS
testable offline is the part with judgment in it: how a board response is
classified, and whether every catalog entry is verifiable at all.

The distinction these tests exist to protect is **empty is not dead**. A board
answering `{"jobs": []}` has a CORRECT token and no open roles; a board
answering 404 has a token pointing at nothing. Collapsing the two in either
direction is a real cost — call empty "dead" and someone replaces a correct
token with a guess; call dead "empty" and a broken token stays invisible.
"""

from __future__ import annotations

import inspect
import json
import sys
from urllib.parse import urlparse

import httpx
import pytest

from scripts.check_catalog_tokens import (
    BOTH,
    CATALOG_ONLY,
    CONFIRMED,
    DEAD,
    DENIED,
    EMPTY,
    LIVE,
    MISMATCH,
    SELF_NAMED,
    TRACKED_ONLY,
    UNCHECKABLE,
    UNKNOWN,
    UNSTATED,
    Probe,
    _posting_count,
    board_probe_for,
    build_probes,
    check_probe,
    exit_code,
    identity_matches,
)
from tracker.company_catalog import CATALOG
from tracker.connectors import ADAPTER_REGISTRY
from tracker.source_review import SOURCE_REVIEWS


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _probe(adapter: str = "ashby", token: str = "Acme") -> Probe:
    return Probe("acme", adapter, token, CATALOG_ONLY)


async def _state(response: httpx.Response, adapter: str = "ashby") -> dict:
    async with _client(lambda _req: response) as client:
        return await check_probe(client, _probe(adapter))


# -- classification ----------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_board_with_postings_is_live():
    result = await _state(httpx.Response(200, json={"jobs": [{"id": 1}, {"id": 2}]}))
    assert result["state"] == LIVE
    assert result["count"] == 2


@pytest.mark.asyncio
async def test_an_empty_board_is_not_dead():
    """Vercel's real response. The token is right; the company is not
    hiring. Reporting this as dead invites someone to 'fix' a correct token."""
    result = await _state(httpx.Response(200, json={"jobs": [], "apiVersion": "1"}))
    assert result["state"] == EMPTY
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_a_404_board_is_dead():
    """A missing board must be reported dead rather than empty."""
    result = await _state(httpx.Response(404, text="not found"))
    assert result["state"] == DEAD
    assert "404" in result["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503, 502, 504, 408])
async def test_a_throttled_or_unavailable_board_is_unknown_not_dead(status):
    """A healthy board can answer 429, and must not be reported DEAD. A rate limit or a maintenance page says "not now", not "no such board"; a
    false DEAD is how a correct token gets replaced with a guess. The run is
    inconclusive (3), never wrong (1)."""
    result = await _state(httpx.Response(status, headers={"Retry-After": "120"}))
    assert result["state"] == UNKNOWN
    assert str(status) in result["detail"] and "Retry-After: 120" in result["detail"]
    assert exit_code([{"state": LIVE}, result]) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 410, 403, 401])
async def test_a_definitive_refusal_is_still_dead(status):
    """The other side of the line above: a missing or refused board is a real
    answer about the token, and must keep failing the run."""
    result = await _state(httpx.Response(status, text="gone"))
    assert result["state"] == DEAD
    assert exit_code([{"state": LIVE}, result]) == 1


@pytest.mark.asyncio
async def test_a_200_that_is_not_a_board_is_dead_not_empty():
    """A token that redirects to a marketing page answers 200 with HTML or some
    unrelated JSON. The adapter would parse nothing from it, so it is dead —
    checking only the status code would pass this."""
    assert (await _state(httpx.Response(200, text="<html>careers</html>")))["state"] == DEAD
    assert (await _state(httpx.Response(200, json={"error": "gone"})))["state"] == DEAD


@pytest.mark.asyncio
async def test_a_network_failure_is_unknown_not_dead():
    """An unreachable network says nothing about a token. Reporting it as dead
    would have a maintainer delete working entries after a flaky run."""

    def handler(_request):
        raise httpx.ConnectError("no route to host")

    async with _client(handler) as client:
        result = await check_probe(client, _probe())

    assert result["state"] == UNKNOWN


@pytest.mark.asyncio
async def test_an_adapter_with_no_known_board_root_is_uncheckable_not_a_pass():
    """An entry the checker cannot verify must not be counted as verified —
    silence about an entry is not a clean bill of health. It is `uncheckable`
    rather than `unknown` because the cause is permanent (no board root for that
    adapter), not a transient network failure."""
    async with _client(lambda _r: httpx.Response(200, json={"jobs": [{"id": 1}]})) as client:
        # Workday declares one; `recipe` boards are per-company
        # and have no family root at all.
        result = await check_probe(client, _probe(adapter="recipe", token="x"))

    assert result["state"] == UNCHECKABLE
    assert result["state"] != UNKNOWN


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"jobs": [1, 2, 3]}, 3),
        ({"postings": []}, 0),
        ({"jobs": None}, None),
        ({}, None),
        # A bare array IS a board: Lever answers one, with no envelope at all.
        # Reading `[]` as "not a board" misclassifies an empty Lever
        # board as DEAD and invites replacing a correct token with a guess.
        ([], 0),
        ([{"id": "a"}], 1),
        # Eightfold: v2 answers `positions` at the top, PCSX inside `data`.
        ({"count": 481, "positions": [{"id": 1}] * 10}, 10),
        ({"data": {"count": 291, "positions": []}}, 0),
        ({"data": None}, None),
        ("nope", None),
    ],
)
def test_posting_count_reads_both_board_shapes_and_rejects_the_rest(payload, expected):
    assert _posting_count(payload) == expected


# -- the catalog is verifiable at all ----------------------------------------- #


def test_every_catalog_entry_uses_an_adapter_the_checker_can_verify():
    """Every catalog entry must be verifiable: a missing board root cannot
    silently count as a verified token."""
    unverifiable = {
        slug: entry["adapter"] for slug, entry in CATALOG.items()
        if board_probe_for(entry["adapter"]) is None
    }
    assert unverifiable == {}, (
        "declare a BoardProbe on the adapter class, "
        "or keep the company out of the one-click catalog"
    )


def test_a_declared_board_probe_targets_the_route_its_adapter_fetches():
    """The drift this declaration exists to make impossible. A probe that points
    somewhere the adapter does not fetch verifies the wrong thing, and a
    hand-copied table has no way to notice a listing URL moving.

    Checked on the RESOLVED url rather than on the template: a regional
    family templates its host, so `jobs_url` does not contain a
    literal one. Host and path prefix are asserted separately, and every
    declared region is resolved — an EU host that appeared only in the probe
    and never in the adapter would mean the checker probing a deployment we do
    not collect from.
    """
    for name, cls in ADAPTER_REGISTRY.items():
        probe = cls.board_probe
        if probe is None or probe.tenant_url is not None:
            continue  # composite tokens: proven by fetching, below
        assert "{token}" in probe.jobs_url, name
        source = inspect.getsource(sys.modules[cls.__module__])
        regions = list(probe.region_hosts) or [None]
        for region in regions:
            resolved = urlparse(probe.url_for("TOKEN", region))
            assert resolved.hostname, f"{name}/{region}: probe resolved no host"
            assert resolved.hostname in source, (
                f"{name}: probe host {resolved.hostname} appears nowhere in the adapter"
            )
            prefix = resolved.path.split("TOKEN")[0].rstrip("/")
            # A board at the host root (`careers.smartrecruiters.com/{token}`)
            # has no path before the token; the host above is then
            # the whole claim, and it was asserted.
            if resolved.path.startswith("/TOKEN"):
                continue
            assert prefix and prefix in source, (
                f"{name}: probe path {prefix} appears nowhere in the adapter"
            )


def _tokens_for(adapter_name: str) -> list[tuple[str, str]]:
    probe = ADAPTER_REGISTRY[adapter_name].board_probe
    built_in = [(slug, token) for slug, token in probe.tenants._mapping.items()]
    catalog = [(slug, row["board_token"]) for slug, row in CATALOG.items()
               if row.get("adapter") == adapter_name and row.get("board_token")]
    return built_in + catalog


@pytest.mark.parametrize(
    ("adapter_name", "company", "token"),
    [
        (name, company, token)
        for name, cls in ADAPTER_REGISTRY.items()
        if cls.board_probe is not None and cls.board_probe.tenant_url is not None
        for company, token in _tokens_for(name)
    ],
)
@pytest.mark.asyncio
async def test_a_composite_probe_is_the_first_request_its_adapter_makes(
    adapter_name, company, token,
):
    """A composite token (Eightfold's `host|domain|pcsx`) cannot be checked by
    reading a template, so it is checked by DOING it: for every real
    tenant of the family, the probe URL must be the route the adapter requests
    first — same host, same path, and every probe parameter sent with the same
    value. A tenant probed on v2 but collected on PCSX would read DEAD (v2
    answers 403) while its listing is healthy."""
    from tracker.connectors import build_adapter

    requested: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url)
        return httpx.Response(404)  # not retryable: ends the listing at once

    adapter = build_adapter(company, adapter_name, board_token=token)
    # A walled family refuses before it requests anything, which would leave
    # this test asserting nothing. The consent is the fixture's, not a user's:
    # the transport is a mock and no request leaves the process.
    walled = SOURCE_REVIEWS.get(adapter_name)
    if walled is not None and walled.wall is not None:
        adapter.collection_consent = walled.wall_fingerprint
    # One query, never the family's whole manifest: this test is about the
    # FIRST request's route, and a Workday tenant would otherwise walk every
    # location term in the manifest (14s each) to prove one URL.
    if adapter.location_queries:
        queries = adapter.location_queries
        first_terms = (queries.get("united_states") or next(iter(queries.values())))[:1]
        adapter.location_queries = {"united_states": first_terms}
        adapter._enabled_locations = frozenset({"united_states"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter._client = client
        _ = [job async for job in adapter.fetch()]

    assert requested, f"{company}: the adapter requested nothing"
    first, probe = requested[0], httpx.URL(ADAPTER_REGISTRY[adapter_name].board_probe.url_for(token))
    assert (first.host, first.path) == (probe.host, probe.path), company
    for key, value in probe.params.items():
        assert first.params.get(key) == value, f"{company}: probe sends {key}={value}"


def test_every_region_a_probe_declares_is_one_its_adapter_can_reach():
    """The two maps must agree in BOTH directions. A region the probe knows and
    the adapter does not would be probed and never collected; the reverse would
    be collected and never verified."""
    from tracker.connectors.listing.lever import REGION_HOSTS

    probe = ADAPTER_REGISTRY["lever"].board_probe
    assert probe.region_hosts is REGION_HOSTS, (
        "the probe must share the adapter's map object, not a copy of it"
    )
    for region, host in REGION_HOSTS.items():
        adapter = ADAPTER_REGISTRY["lever"]("acme", board_region=region)
        assert adapter._host() == host
        assert urlparse(probe.url_for("acme", region)).hostname == host


def test_only_a_family_that_states_its_name_claims_to_verify_identity():
    """Greenhouse's board root answers `{"name": ...}`;
    Ashby answers `{jobs, apiVersion}` and Lever a bare array. Claiming identity
    for the latter two would be the check asserting something it never read.

    Workable's account payload is
    `{"name": "Hugging Face", "description": ..., "jobs": [...]}`, so one
    request settles both questions this module asks — how many postings, and
    whose board. The set is asserted whole, in both directions: a family that
    stops naming its tenant must lose the claim as surely as a new one gains it.
    """
    stated = {
        name for name, cls in ADAPTER_REGISTRY.items()
        if cls.board_probe is not None and cls.board_probe.identity_url is not None
    }
    # SmartRecruiters, both routes: the board page says "Careers at {Name}"
    # and the API's company record has `name`. Jibe: every row names its employer in
    # `hiring_organization`; the check reads the one most page-1 rows name.
    assert stated == {"greenhouse", "workable", "smartrecruiters", "smartrecruiters_api", "jibe"}


def test_every_catalog_entry_declares_a_non_empty_board_token():
    missing = [slug for slug, entry in CATALOG.items() if not (entry.get("board_token") or "").strip()]
    assert missing == []


def test_the_removed_dead_boards_have_not_crept_back():
    """`benchling` and `cruise` stay out: no token variant resolves. They are
    named here so a well-meaning re-add has to confront the measurement rather
    than repeat it. A re-add is fine, but only with a token
    `check_catalog_tokens` reports LIVE.

    A company whose token is re-measured LIVE leaves this list. The guard is
    for tokens nobody has re-measured, and keeping a company on it after the
    measurement changed would make it a superstition rather than a record.
    """
    assert not ({"benchling", "cruise"} & set(CATALOG))


#: (adapter, token) pairs that are LIVE, complete and belong to somebody else.
#: A separate register from the dead ones because it is a separate failure: a
#: dead token is loud (404 -> `failed` -> nightly anomaly), while this one
#: passes every run-quality gate and quietly files another company's postings
#: under our slug. Keyed by token for the same reason `MEASURED_DEAD_TOKENS` is
#: — the hazard is not the name `figure`, it is the token, and any slug could
#: carry it back.
MEASURED_WRONG_COMPANY_TOKENS = {
    # figure.ai's slug is `figure`, so this is the guess anyone makes first.
    # The board is Figure Lending's: complete and healthy. figure.ai's own
    # board is `figureai`.
    ("greenhouse", "figure"): "Figure Lending",
    # Tempting because it is live where `runwayml` 404s. Its
    # postings describe "a collaborative business planning platform"; Runway
    # AI's careers page links `runway-ml`.
    ("ashby", "Runway"): "Runway (business planning)",
}


def test_no_catalog_entry_uses_a_token_measured_to_be_another_company():
    in_use = {(entry["adapter"], entry["board_token"]): slug for slug, entry in CATALOG.items()}
    collisions = {
        in_use[pair]: owner for pair, owner in MEASURED_WRONG_COMPANY_TOKENS.items()
        if pair in in_use
    }
    assert collisions == {}, "this board belongs to the company named, not to ours"


#: Every (adapter, token) pair measured DEAD. Slug-level guards miss the real
#: hazard: the danger is not the name `mistral`, it is the token `mistral`,
#: which any slug could carry back in.
MEASURED_DEAD_TOKENS = {
    ("ashby", "mistral"),
    ("ashby", "mistralai"),
    ("ashby", "mistral-ai"),
    ("ashby", "perplexity-ai"),
    ("ashby", "runwayml"),
    ("ashby", "amilabs"),
}


def test_no_catalog_entry_uses_a_token_measured_dead():
    in_use = {(entry["adapter"], entry["board_token"]) for entry in CATALOG.values()}
    assert not (in_use & MEASURED_DEAD_TOKENS)


def test_mistral_is_catalogued_on_the_tenant_that_actually_resolves():
    """The dot is the whole bug: `mistral` 404s, `mistral.ai` serves the board."""
    assert CATALOG["mistral"]["board_token"] == "mistral.ai"


def test_runway_is_catalogued_on_the_board_its_careers_page_links():
    """The hyphen is the bug: `runwayml` 404s, and the live `Runway` board is
    another company's. runway.com/careers links `runway-ml`."""
    assert CATALOG["runway"]["board_token"] == "runway-ml"


# -- the probe set is the roster, not just the catalog ------------------------- #

_CATALOG = {"acme": {"display": "Acme", "adapter": "ashby", "board_token": "Acme"}}


def test_a_tracked_token_that_disagrees_with_the_catalog_is_probed_separately():
    """The `mistral` shape: the catalog is corrected while the already-seeded
    row keeps the dead token. Deduplicating by slug would check only the fixed
    one and report clean while the roster stayed broken."""
    probes = build_probes(_CATALOG, [("acme", "ashby", "stale-token")])

    assert {(p.token, p.origin) for p in probes} == {
        ("Acme", CATALOG_ONLY),
        ("stale-token", TRACKED_ONLY),
    }


def test_a_tracked_row_matching_its_catalog_entry_is_one_probe_not_two():
    probes = build_probes(_CATALOG, [("acme", "ashby", "Acme")])

    assert len(probes) == 1
    assert probes[0].origin == BOTH


def test_a_tracked_token_with_no_catalog_entry_at_all_is_still_probed():
    """Removing a catalog entry must not exclude its stored roster token
    from verification; that token can still be used by collection."""
    probes = build_probes({}, [("ghost", "ashby", "ghost-token")])

    assert [(p.slug, p.token, p.origin) for p in probes] == [("ghost", "ghost-token", TRACKED_ONLY)]


@pytest.mark.parametrize("row", [("apple", "apple", None), ("amazon", "amazon", None),
                                 ("odd", None, "token")])
def test_a_row_with_no_token_to_rot_is_skipped_entirely(row):
    """A source that really does hard-code its listing URL declares no board
    probe. Reporting those as unverifiable would bury the real findings under a
    dozen permanent non-answers."""
    assert build_probes({}, [row]) == []


@pytest.mark.parametrize("slug,adapter,expected", [
    ("spotify", "lever", "spotify"),      # built-in module map
    ("anthropic", "greenhouse", "anthropic"),
    ("openai", "ashby", "openai"),
    ("newco", "greenhouse", "newco"),     # no map entry: TenantMap falls back to the slug
])
def test_a_built_in_with_no_stored_token_is_probed_on_its_effective_one(slug, adapter, expected):
    """Why a missing stored token is never a reason to skip.

    `TenantMap.resolve` falls back to the module map and then to the slug, so
    these rows scrape a real multi-tenant URL — `.../boards/anthropic/jobs` —
    whose token can rot exactly like a catalog token. A rule of "no stored
    `board_token` means nothing to check" would skip all of them, leaving the
    built-in public boards the only tokens on the roster never verified.
    """
    probes = build_probes({}, [(slug, adapter, None)])

    assert [(p.slug, p.token, p.origin) for p in probes] == [(slug, expected, TRACKED_ONLY)]


# -- what the exit code is allowed to mean ------------------------------------- #


def test_a_dead_token_fails():
    assert exit_code([{"state": LIVE}, {"state": DEAD}]) == 1


def test_a_network_failure_is_unverified_not_a_pass():
    assert exit_code([{"state": LIVE}, {"state": UNKNOWN}]) == 3


def test_uncheckable_alone_does_not_fail_the_run():
    """Permanent and structural: failing on it leaves the check red forever,
    which trains everyone to ignore the one signal that matters."""
    assert exit_code([{"state": LIVE}, {"state": UNCHECKABLE}]) == 0


def test_a_catalog_only_pass_never_reports_clean():
    """If the tracked rows could not be read, the tokens actually being scraped
    went unchecked. Exiting 0 there is the failure mode this check exists to
    prevent, restated one layer up."""
    assert exit_code([{"state": LIVE}], db_error="OperationalError: connection refused") == 3


# -- identity: whose board is this? -------------------------------- #
#
# A binding earns closure authority from
# a complete `ok` listing, and a wrong-but-live board token produces exactly
# that, so identity verification requires an independently known employer
# compared with the name the board declares.


@pytest.mark.parametrize("declared,candidates", [
    ("Anthropic", ["anthropic"]),                 # the common case: exactly
    ("Scale AI", ["scaleai"]),                    # punctuation and case normalized away
    ("Gusto, Inc.", ["gusto"]),                   # the legal form is not identity
    ("Wiz, Inc.", ["Wiz", "wiz"]),                # a real board; three letters
    ("Rocket Lab Corporation", ["Rocket Lab"]),   # a real board
    ("Stripe", ["Stripe Payments", "stripe"]),    # any candidate may match
])
def test_a_board_naming_this_company_confirms_identity(declared, candidates):
    assert identity_matches(declared, candidates) is True


@pytest.mark.parametrize("declared,candidates", [
    ("Anthropic", ["stripe"]),        # the failure this exists for
    ("Databricks", ["dropbox"]),      # two real tokens, both live, different boards
    ("", ["anthropic"]),
    (None, ["anthropic"]),
    ("Anthropic", [""]),
])
def test_a_board_naming_someone_else_is_never_a_match(declared, candidates):
    assert identity_matches(declared, candidates) is False


@pytest.mark.parametrize("declared,candidates", [
    # Greenhouse `figure` IS this board. Under substring containment it would
    # CONFIRM the catalog's `figure` row, because
    # "figure" is inside "figurelending" — the wrong-company case this module
    # exists for, passing its own check.
    ("Figure Lending", ["Figure", "figure"]),
    # The same shape between two companies the discovery catalog lists
    # separately, so the damage is not hypothetical: `citadel` and
    # `citadel-securities` are different slugs with different boards.
    ("Citadel Securities", ["Citadel", "citadel"]),
    # Suffix stripping must not run away with the name: "Holdings" states a
    # corporate structure, not a legal form, and XAI Holdings is not xAI.
    ("XAI Holdings", ["xai"]),
    ("Meta", ["met"]),
])
def test_a_longer_name_containing_ours_is_a_different_company(declared, candidates):
    """The rule is equality once a trailing legal form is off both sides, never
    containment. "Our name appears inside theirs" is the relationship
    a subsidiary, a spin-off and an unrelated namesake all have with us, and a
    check that reads it as identity is measuring nothing on exactly the boards
    it was built to fail."""
    assert identity_matches(declared, candidates) is False


def test_a_curated_alias_is_one_of_our_names_and_settles_the_board():
    """Greenhouse `imc` declares "IMC"; our display is "IMC Trading" and the
    slug is `imc-trading`, so neither settles it and a correct token reports
    `mismatch` — a false wrong-company, which costs what a false dead costs.
    The alias is the name a human already wrote down for this company, and it
    is admitted for that reason and no other: the board must never be able to
    supply the evidence that confirms it."""
    probe = Probe("imc-trading", "greenhouse", "imc", CATALOG_ONLY, display="IMC Trading")

    assert "IMC" in probe.identity_candidates
    assert "imc" not in [c.lower() for c in probe.identity_candidates if c != "IMC"]
    assert identity_matches("IMC", probe.identity_candidates) is True
    assert identity_matches("IMC Health Systems", probe.identity_candidates) is False


def test_the_same_string_shape_decided_by_us_and_not_by_the_board():
    """The pair that shows why the alias is the right place for this knowledge.

    Both boards are live, complete and declare our name plus a qualifier:
    greenhouse `doordashusa` says "DoorDash USA" and greenhouse `figure` says
    "Figure Lending". One is our company's own regional board, the other is an
    unrelated lender. NO comparison of the two strings can separate them —
    which is what substring containment would try, and why it confirms both.
    What separates them is a person having checked, and
    the record of that check is the curated alias.
    """
    doordash = Probe("doordash", "greenhouse", "doordashusa", CATALOG_ONLY, display="DoorDash")
    figure = Probe("figure", "greenhouse", "figure", CATALOG_ONLY, display="Figure")

    assert identity_matches("DoorDash USA", doordash.identity_candidates) is True
    assert identity_matches("Figure Lending", figure.identity_candidates) is False


def test_a_company_that_renamed_its_board_is_settled_by_the_name_we_wrote_down():
    """Greenhouse `xai` declares "SpaceXSI", the name its own postings use, while
    our display is "SpaceXAI". Without the alias the live check reports the right
    board as `mismatch`; "XAI Holdings" stays a different company either way."""
    probe = Probe("xai", "greenhouse", "xai", CATALOG_ONLY, display="SpaceXAI")

    assert identity_matches("SpaceXSI", probe.identity_candidates) is True
    assert identity_matches("XAI Holdings", probe.identity_candidates) is False


def test_aliases_come_from_the_discovery_catalog_not_from_the_token():
    """The negative control for the line above. A probe for a slug nobody has
    curated gets no aliases, so a wrong-but-live board cannot acquire a name
    that would confirm it."""
    probe = Probe("not-a-real-company", "greenhouse", "stripe", CATALOG_ONLY)

    assert probe.identity_candidates == ("not-a-real-company",)
    assert identity_matches("Stripe", probe.identity_candidates) is False


def test_amd_legal_name_confirms_its_jibe_board_without_accepting_a_different_employer():
    probe = Probe("amd", "jibe", "careers.amd.com", CATALOG_ONLY, display="AMD")
    assert identity_matches("Advanced Micro Devices, Inc", probe.identity_candidates) is True
    assert identity_matches("Advanced Micro Systems, Inc", probe.identity_candidates) is False


def _routed(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _greenhouse_board(name: str | None, jobs: int = 2):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json={"jobs": [{"id": i} for i in range(jobs)]})
        return httpx.Response(200, json={} if name is None else {"name": name})
    return handler


@pytest.mark.asyncio
async def test_a_live_board_belonging_to_another_company_fails_the_check():
    """A complete, healthy, 200 listing — every run-quality gate passes. The
    board's own name is the only thing that says it is the wrong company."""
    probe = Probe("anthropic", "greenhouse", "stripe", TRACKED_ONLY)
    async with _routed(_greenhouse_board("Stripe")) as client:
        result = await check_probe(client, probe)

    assert result["state"] == MISMATCH
    assert result["identity"] == MISMATCH
    assert "Stripe" in result["detail"] and "anthropic" in result["detail"]
    assert exit_code([{"state": LIVE}, result]) == 1


@pytest.mark.asyncio
async def test_the_right_board_is_live_and_records_the_name_it_declared():
    probe = Probe("anthropic", "greenhouse", "anthropic", TRACKED_ONLY)
    async with _routed(_greenhouse_board("Anthropic")) as client:
        result = await check_probe(client, probe)

    assert result["state"] == LIVE
    assert result["identity"] == CONFIRMED
    assert result["declared"] == "Anthropic"


@pytest.mark.asyncio
async def test_a_family_that_states_no_name_is_unstated_not_confirmed():
    """Ashby's payload names no tenant. Reporting `confirmed` here would be the
    check claiming an identity it never read — and a wrong Ashby token is
    precisely the `mistral` rot, which no probe can catch."""
    async with _routed(lambda _r: httpx.Response(200, json={"jobs": [{"id": 1}], "apiVersion": "1"})) as client:
        result = await check_probe(client, Probe("acme", "ashby", "acme", TRACKED_ONLY))

    assert result["state"] == LIVE
    assert result["identity"] == UNSTATED
    assert "declared" not in result


@pytest.mark.asyncio
async def test_an_empty_board_still_has_its_identity_checked():
    """`empty` means the token is CORRECT and the company is not hiring. That
    claim is only safe if the board is also the right company's."""
    async with _routed(_greenhouse_board("Stripe", jobs=0)) as client:
        wrong = await check_probe(client, Probe("anthropic", "greenhouse", "stripe", BOTH))
    assert wrong["state"] == MISMATCH

    async with _routed(_greenhouse_board("Anthropic", jobs=0)) as client:
        right = await check_probe(client, Probe("anthropic", "greenhouse", "anthropic", BOTH))
    assert right["state"] == EMPTY
    assert right["identity"] == CONFIRMED


@pytest.mark.asyncio
async def test_a_dead_board_costs_no_identity_request():
    """The identity route is only worth asking about a board that answered."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(404)

    async with _routed(handler) as client:
        result = await check_probe(client, Probe("acme", "greenhouse", "acme", BOTH))

    assert result["state"] == DEAD
    assert len(seen) == 1 and seen[0].endswith("/jobs")


@pytest.mark.asyncio
async def test_an_unreadable_identity_route_is_unverified_not_a_mismatch():
    """A board that answers its listing but not its root has not been shown to
    be the wrong company. Calling that `mismatch` would send someone to replace
    a token that may be perfectly correct."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json={"jobs": [{"id": 1}]})
        return httpx.Response(503)

    async with _routed(handler) as client:
        result = await check_probe(client, Probe("acme", "greenhouse", "acme", BOTH))

    assert result["state"] == UNKNOWN
    assert exit_code([result]) == 3


@pytest.mark.asyncio
async def test_a_board_that_states_no_name_is_not_a_mismatch():
    """Greenhouse declares a name today. If a board ever omits it, that is
    silence, not a different company."""
    async with _routed(_greenhouse_board(None)) as client:
        result = await check_probe(client, Probe("acme", "greenhouse", "acme", BOTH))

    assert result["state"] == LIVE
    assert result["identity"] == UNSTATED


# -- directory companies: named by their own board ----------------- #


def _listed(slug: str, display: str, token: str, named_by: str = "board"):
    from tracker.company_directory import DirectoryCompany

    return DirectoryCompany(slug=slug, display=display, named_by=named_by, adapter="greenhouse",
                            board_token=token, board_region=None, rank=0)


@pytest.fixture
def listed(monkeypatch):
    """Four boards with suffixed slugs, and the unsuffixed rows
    whose names they collided with, as `company_directory.json` records them."""
    from tracker import company_directory

    rows = {r.slug: r for r in [
        _listed("current", "Current", "current"),
        _listed("current-greenhouse", "Current", "current81"),
        _listed("liminal-greenhouse", "Liminal", "liminalai"),
        _listed("stepstone-group-greenhouse", "StepStone Group", "stepstone"),
        _listed("referrals-only", "Referrals Only", "thoughtworksreferral"),
        _listed("sandboxaq", "Sandboxaq", "sandboxaq", named_by="address"),
    ]}
    monkeypatch.setattr(company_directory, "directory", lambda: rows)
    return rows


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("slug", "token", "declared"),
    [
        ("current-greenhouse", "current81", "Current"),
        ("liminal-greenhouse", "liminalai", "Liminal"),
        ("stepstone-group-greenhouse", "stepstone", "StepStone Group"),
    ],
)
async def test_a_directory_board_whose_slug_took_a_suffix_is_not_wrong(listed, slug, token, declared):
    """Each board declares exactly the name the directory read from it. The slug
    takes `-greenhouse` when another board of the same name has the plain one,
    and a tracked row carries no display, so comparing the slug alone would
    read every such row WRONG."""
    async with _routed(_greenhouse_board(declared)) as client:
        result = await check_probe(client, Probe(slug, "greenhouse", token, TRACKED_ONLY))

    assert result["state"] == LIVE
    assert result["identity"] == SELF_NAMED
    assert result["declared"] == declared
    assert exit_code([result]) == 0


@pytest.mark.asyncio
async def test_a_directory_board_is_never_confirmed_by_the_name_it_gave_us(listed):
    """The circular case the other way: `referrals-only` is Thoughtworks'
    referral board, and its slug is made from the board's own name, so the
    slug would "confirm" it with nothing independent compared."""
    async with _routed(_greenhouse_board("Referrals Only")) as client:
        result = await check_probe(
            client, Probe("referrals-only", "greenhouse", "thoughtworksreferral", TRACKED_ONLY)
        )

    assert result["identity"] == SELF_NAMED
    assert result["identity"] != CONFIRMED


@pytest.mark.asyncio
async def test_a_directory_board_renamed_since_the_build_is_wrong(listed):
    """The one comparison a directory row still allows: the board against the
    name it gave at build time. A token now answering for somebody else is the
    quiet failure this check exists for."""
    async with _routed(_greenhouse_board("Stripe")) as client:
        result = await check_probe(
            client, Probe("current-greenhouse", "greenhouse", "current81", TRACKED_ONLY)
        )

    assert result["state"] == MISMATCH
    assert "Stripe" in result["detail"] and "Current" in result["detail"]
    assert exit_code([result]) == 1


@pytest.mark.asyncio
async def test_a_directory_name_read_off_the_address_is_not_one_to_compare(listed):
    """`named_by="address"`: the name is the token, spelled out. The board
    naming itself differently later is no evidence either way."""
    async with _routed(_greenhouse_board("SandboxAQ Inc.")) as client:
        result = await check_probe(client, Probe("sandboxaq", "greenhouse", "sandboxaq", TRACKED_ONLY))

    assert result["identity"] == SELF_NAMED
    assert result["state"] == LIVE


@pytest.mark.asyncio
async def test_a_curated_company_is_still_judged_by_our_own_names(listed):
    """The control: outside the directory, a board naming someone else fails."""
    async with _routed(_greenhouse_board("Current")) as client:
        result = await check_probe(client, Probe("anthropic", "greenhouse", "current", TRACKED_ONLY))

    assert result["state"] == MISMATCH


# -- collection policy --------------------------------------------- #


@pytest.mark.asyncio
async def test_a_denied_provider_is_never_requested(monkeypatch):
    """This script builds its own httpx client, so none of the transport-level
    gates see it, and it must check the policy itself or the monthly check
    probes a denied provider's board. Denial is our decision, so it is reported and does not fail the run."""
    from tracker.config import get_settings

    monkeypatch.setattr(get_settings(), "sync_policy_denied_providers", frozenset({"greenhouse"}))
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, json={"jobs": [{"id": 1}]})

    async with _routed(handler) as client:
        result = await check_probe(client, Probe("acme", "greenhouse", "acme", BOTH))

    assert result["state"] == DENIED
    assert requested == []
    assert exit_code([{"state": LIVE}, result]) == 0


@pytest.mark.asyncio
async def test_an_allowed_provider_is_still_probed(monkeypatch):
    """The negative control: without it, a gate that denied everything would
    pass the test above."""
    from tracker.config import get_settings

    monkeypatch.setattr(get_settings(), "sync_policy_denied_providers", frozenset({"meta"}))
    async with _routed(_greenhouse_board("Acme")) as client:
        result = await check_probe(client, Probe("acme", "greenhouse", "acme", BOTH))

    assert result["state"] == LIVE


# -- Lever's payload shape ---------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_bare_array_is_a_board_not_a_dead_token():
    """Lever answers a top-level array with no envelope. Requiring a dict read a
    healthy board as DEAD, and a false dead is how a correct token gets replaced
    with a guess."""
    async with _routed(lambda _r: httpx.Response(200, json=[{"id": "a"}, {"id": "b"}])) as client:
        result = await check_probe(client, Probe("spotify", "lever", "spotify", TRACKED_ONLY))

    assert result["state"] == LIVE
    assert result["count"] == 2
    assert result["identity"] == UNSTATED


@pytest.mark.asyncio
async def test_an_empty_lever_board_is_empty_not_dead():
    async with _routed(lambda _r: httpx.Response(200, json=[])) as client:
        result = await check_probe(client, Probe("spotify", "lever", "spotify", TRACKED_ONLY))

    assert result["state"] == EMPTY
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_a_capped_probe_reports_presence_rather_than_a_size():
    """Lever's probe asks for `limit=1`, so its count proves the board serves
    roles and says nothing about how many. Printing "1 postings" for a board of
    fifty would be the verification tool inventing a measurement."""
    async with _routed(lambda _r: httpx.Response(200, json=[{"id": "a"}])) as client:
        lever = await check_probe(client, Probe("spotify", "lever", "spotify", TRACKED_ONLY))
    assert lever["capped"] is True
    assert "serves roles" in lever["detail"]

    async with _routed(_greenhouse_board("Acme", jobs=7)) as client:
        whole = await check_probe(client, Probe("acme", "greenhouse", "acme", BOTH))
    assert "capped" not in whole
    assert whole["count"] == 7


# -- regional identity --------------------------------------------- #


@pytest.mark.parametrize("region,host", [
    (None, "api.lever.co"),          # every pre-region row
    ("global", "api.lever.co"),
    ("eu", "api.eu.lever.co"),
])
def test_a_regional_probe_asks_the_host_that_tenant_lives_on(region, host):
    """The whole point of carrying the region. Lever's deployments have separate
    tenant namespaces and answer the SAME 404 for a wrong region as for a wrong
    site name, so probing an EU board against the global host would report a
    healthy board DEAD and get its correct token replaced with a guess."""
    probe = Probe("someco", "lever", "someco", TRACKED_ONLY, region=region)
    url = ADAPTER_REGISTRY["lever"].board_probe.url_for(probe.token, probe.region)

    assert urlparse(url).hostname == host


def test_the_same_site_name_on_two_deployments_is_two_probes():
    """Region is part of a board's identity, not a rendering detail. Collapsing
    these would check one host and report the other clean."""
    probes = build_probes({}, [
        ("someco", "lever", "someco", "global"),
        ("someco-eu", "lever", "someco", "eu"),
    ])

    assert len(probes) == 2
    assert {p.region for p in probes} == {"global", "eu"}


def test_a_three_tuple_row_still_builds_a_probe_with_no_region():
    """Single-host families never carry one, and a pre-region Lever row reads
    correctly as the global deployment."""
    (probe,) = build_probes({}, [("anthropic", "greenhouse", None)])

    assert probe.region is None
    assert urlparse(
        ADAPTER_REGISTRY["greenhouse"].board_probe.url_for(probe.token, probe.region)
    ).hostname == "boards-api.greenhouse.io"


@pytest.mark.asyncio
async def test_an_eu_probe_is_sent_to_the_eu_host():
    """End to end through `check_probe`: the request URL, not just the template."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=[{"id": "a"}])

    async with _routed(handler) as client:
        result = await check_probe(
            client, Probe("someco", "lever", "someco", TRACKED_ONLY, region="eu")
        )

    assert result["state"] == LIVE
    assert len(seen) == 1
    assert urlparse(seen[0]).hostname == "api.eu.lever.co"


# -- one request per board, one verdict per company ---------------- #


def test_a_company_pointed_at_another_companys_board_keeps_its_own_probe():
    """The wrong-token case, and it must not be deduplicated away.

    `acme -> greenhouse/stripe` while the catalog already offers
    `stripe -> greenhouse/stripe`. Keying probes on `(adapter, token, region)`
    alone would collapse these into one, keep the CATALOG slug, and throw away
    the only association that can fail, so the surviving probe would ask
    Stripe's board whether it is Stripe's and confirm. The check exists to catch
    a readable board belonging to the wrong company, including when the wrong
    token is one we already know.
    """
    catalog = {"stripe": {"display": "Stripe", "adapter": "greenhouse",
                          "board_token": "stripe"}}
    probes = build_probes(catalog, [("acme", "greenhouse", "stripe")])

    assert {(p.slug, p.token) for p in probes} == {("stripe", "stripe"), ("acme", "stripe")}


def test_two_tracked_companies_on_one_token_are_both_probed():
    """The later row is probed too, with its own
    `collection_access(company=...)` evaluated."""
    probes = build_probes({}, [("acme", "greenhouse", "shared"),
                               ("zeta", "greenhouse", "shared")])

    assert [(p.slug, p.origin) for p in probes] == [("acme", TRACKED_ONLY),
                                                    ("zeta", TRACKED_ONLY)]


@pytest.mark.asyncio
async def test_one_board_two_claimants_one_confirms_and_one_does_not():
    """The point of keeping both: the same response, judged per company."""
    async with _routed(_greenhouse_board("Stripe")) as client:
        right = await check_probe(client, Probe("stripe", "greenhouse", "stripe", BOTH,
                                                display="Stripe"))
        wrong = await check_probe(client, Probe("acme", "greenhouse", "stripe", TRACKED_ONLY,
                                                display="Acme"))

    assert (right["state"], right["identity"]) == ("live", "confirmed")
    assert (wrong["state"], wrong["identity"]) == ("mismatch", "mismatch")
    assert "Stripe" in wrong["detail"] and "acme" in wrong["detail"]


@pytest.mark.asyncio
async def test_a_second_claimant_costs_no_second_request():
    """Deduplicate the REQUEST, never the assertion. Two companies mapped to one
    board are still one board, and a maintenance pass should not double the load
    on a public API to say so twice, which is why the dedup lives in the
    transport."""
    from scripts.check_catalog_tokens import _DedupTransport

    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path.endswith("/jobs"):
            return httpx.Response(200, json={"jobs": [{"id": 1}]})
        return httpx.Response(200, json={"name": "Stripe"})

    transport = _DedupTransport(httpx.MockTransport(handler))
    async with httpx.AsyncClient(transport=transport) as client:
        first = await check_probe(client, Probe("stripe", "greenhouse", "stripe", BOTH,
                                                display="Stripe"))
        second = await check_probe(client, Probe("acme", "greenhouse", "stripe", TRACKED_ONLY))

    # Board root + jobs route, once each, for two probes.
    assert len(requested) == 2
    assert len(set(requested)) == 2
    # And the replayed response is still readable — a shared, already-consumed
    # stream would have made the second probe unreadable rather than a mismatch.
    assert first["state"] == "live" and second["state"] == "mismatch"


@pytest.mark.asyncio
async def test_a_replayed_response_is_not_decompressed_twice():
    """Compressed responses must remain replayable. `aread()` returns decoded
    bytes, so retaining `content-encoding: gzip` would make httpx decompress
    them twice and report a decoding failure. The mock sets that header to
    exercise the same response shape."""
    import gzip

    from scripts.check_catalog_tokens import _DedupTransport

    body = gzip.compress(b'{"jobs": [{"id": 1}]}')

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body,
                              headers={"content-encoding": "gzip",
                                       "content-type": "application/json"})

    async with httpx.AsyncClient(transport=_DedupTransport(httpx.MockTransport(handler))) as c:
        first = await c.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs")
        second = await c.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs")

    assert first.json() == second.json() == {"jobs": [{"id": 1}]}
    # The surviving headers must still describe the body we actually hand over.
    assert "content-encoding" not in second.headers
    assert second.headers["content-type"] == "application/json"


@pytest.mark.asyncio
async def test_a_probe_body_is_encoded_the_way_its_adapter_sends_it():
    """Probes carry form bodies (Accenture) beside JSON ones (Workday). A probe
    encoded the other way is a request the adapter never makes: Workday's CXS
    route would read a form as a bad request and report a live board DEAD."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.headers.get("content-type") != "application/json":
            return httpx.Response(400)
        return httpx.Response(200, json={"total": 42, "jobPostings": [{"title": "x"}]})

    token = CATALOG["salesforce"]["board_token"]
    async with _routed(handle) as client:
        result = await check_probe(client, Probe("salesforce", "workday", token, CATALOG_ONLY))

    assert result["state"] == LIVE and result["count"] == 42, result
    assert [r.method for r in seen] == ["POST"]
    assert json.loads(seen[0].content) == dict(board_probe_for("workday").probe_body)


def test_accenture_findjobs_data_array_is_a_board():
    # `data` as the posting array (Accenture), beside `data` as an envelope
    # (Eightfold); neither may read as "no jobs/postings array".
    assert _posting_count({"data": [{"id": 1}, {"id": 2}], "totalHits": {"total": 888}}) == 2
    assert _posting_count({"data": {"positions": [{"id": 1}]}}) == 1
    assert _posting_count({"data": "not a board"}) is None
