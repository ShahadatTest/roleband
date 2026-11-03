"""The source review register.

Two jobs. **Completeness**: a new listing adapter must arrive with a register
row, because a source with no recorded basis is one nobody can account for.
**Honesty**: the register
must not be able to drift into claiming approvals nobody made, or into becoming
a second enforcement path beside `source_policy`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from tracker.config import COMPANIES, get_settings
from tracker.connectors import ADAPTER_REGISTRY, route_family_of
from tracker.source_review import (
    COMPANY_REVIEWS,
    SOURCE_REVIEWS,
    AccessClass,
    ReviewResult,
    RobotsStatus,
    declared_adapter,
    effective_review,
    source_review,
    unreviewed_providers,
)

# -- completeness -------------------------------------------------------------- #


def test_every_listing_adapter_has_a_register_row():
    """The gate. A source that can make an outbound request with no recorded
    access basis fails here by name."""
    missing = sorted(set(ADAPTER_REGISTRY) - set(SOURCE_REVIEWS))

    assert missing == [], (
        f"add a SOURCE_REVIEWS entry for {missing} in the same change as the adapter"
    )


def test_the_register_names_no_source_that_does_not_exist():
    """The opposite drift: a row outlasting its adapter is a claim about
    nothing, and it inflates every count taken off this register."""
    assert sorted(set(SOURCE_REVIEWS) - set(ADAPTER_REGISTRY)) == []


@pytest.mark.parametrize("provider", sorted(SOURCE_REVIEWS))
def test_every_row_records_a_surface_a_request_identity_and_robots_evidence(provider):
    entry = SOURCE_REVIEWS[provider]

    assert entry.provider == provider
    assert entry.listing_surface.strip()
    assert entry.request_identity.strip()
    assert isinstance(entry.access_class, AccessClass)
    assert isinstance(entry.robots.status, RobotsStatus)
    # A verdict about a file must say when it was read; silence must not.
    if entry.robots.status is RobotsStatus.UNVERIFIED:
        assert entry.robots.checked is None
        assert entry.robots.note, "unverified must say why nothing was read"
    else:
        assert entry.robots.checked is not None


@pytest.mark.parametrize("provider", sorted(SOURCE_REVIEWS))
def test_a_measured_verdict_carries_the_bytes_and_the_rule_that_decided_it(provider):
    """A verdict nobody can re-check is indistinguishable from a current one —
    `allowed` with no rule is legitimate (permitted by
    absence), so what is required is the hash and the evaluated target, not a
    rule."""
    robots = SOURCE_REVIEWS[provider].robots
    if robots.status not in (RobotsStatus.ALLOWED, RobotsStatus.DISALLOWED):
        pytest.skip(f"{provider} serves no robots file")

    assert robots.sha256 and len(robots.sha256) == 64
    assert robots.target and robots.target.startswith("/")
    assert robots.robots_url


def test_a_source_serving_no_robots_file_records_no_hash():
    """`not_served` is a weaker claim than `allowed` and must not borrow its
    evidence: there were no bytes to hash."""
    for provider, entry in SOURCE_REVIEWS.items():
        if entry.robots.status is RobotsStatus.NOT_SERVED:
            assert entry.robots.sha256 is None, provider
            assert entry.robots.note, provider


# -- honesty ------------------------------------------------------------------- #


def test_the_only_approval_names_its_reviewer_date_and_condition():
    """Recording an approval nobody made is the failure this register exists to
    end — so an approval that IS here must carry who made it, when, and what it
    permits. Workday's is the only one: collection approved, conditioned on
    the user directing it.

    Two things it deliberately does not do. It grants no COMPANY — the rule
    that approving an ATS approves no employer on it, which `effective_review`
    enforces by still answering UNREVIEWED for every tenant. And it follows
    nobody: every company on the source starts off the curated list and is
    scanned only when its user asks."""
    approved = {k: v for k, v in SOURCE_REVIEWS.items() if v.review is ReviewResult.APPROVED}

    assert list(approved) == ["workday"]
    workday = approved["workday"]
    assert (workday.reviewer, workday.review_date) == ("owner", date(2026, 9, 23))
    # The condition is `user_directed`, not a wall: the source asks nothing of
    # us, so there is no consent to take.
    assert workday.user_directed and workday.wall is None
    assert effective_review("workday") is ReviewResult.APPROVED
    assert effective_review("workday", company="nvidia") is ReviewResult.UNREVIEWED
    assert COMPANY_REVIEWS == {}, "no employer was approved by approving its ATS"


def test_an_unreviewed_source_lists_no_approved_modes():
    """An approved-mode list on an unreviewed source is an approval by another
    name."""
    for provider, entry in SOURCE_REVIEWS.items():
        if entry.review is ReviewResult.UNREVIEWED:
            assert entry.approved_modes == (), provider


def test_the_registers_denials_agree_with_what_actually_enforces_them():
    """The anti-competing-system gate. `sync_policy_denied_providers` is
    the only thing that refuses a request; this register carries the
    REASON. If the two disagree, one of them is lying to a reader — a row saying
    `denied` for a provider that still collects, or a denied provider whose
    reason nobody wrote down."""
    settings = get_settings()
    register_denied = {k for k, v in SOURCE_REVIEWS.items() if v.review is ReviewResult.DENIED}
    enforced = set(settings.sync_policy_denied_providers) & set(SOURCE_REVIEWS)

    assert register_denied == enforced, (
        "update tracker/source_review.py and Settings.sync_policy_denied_providers together"
    )


def test_unreviewed_is_not_approval():
    """The rule "Unknown review status is not evidence of approval."
    Asserted as behavior so it cannot decay into a
    comment."""
    assert effective_review("greenhouse") is ReviewResult.UNREVIEWED
    assert effective_review("greenhouse") is not ReviewResult.APPROVED


def test_a_denied_provider_is_denied_however_it_is_reached(monkeypatch):
    """A recipe naming itself cannot present as an unregistered source: the
    company's declared adapter resolves, mirroring `collection_access`.

    The denied provider is SYNTHETIC. The denial mechanism has to keep working
    when no tracked company happens to be denied, which is exactly when a regression
    here would go unnoticed.
    """
    denied = replace(SOURCE_REVIEWS["ashby"], provider="denied-ats",
                     review=ReviewResult.DENIED)
    monkeypatch.setitem(SOURCE_REVIEWS, "denied-ats", denied)
    monkeypatch.setitem(COMPANIES, "denied-co", {"adapter": "denied-ats"})

    assert effective_review("denied-ats") is ReviewResult.DENIED
    assert effective_review("recipe", company="denied-co") is ReviewResult.DENIED


def test_approving_a_provider_does_not_approve_its_tenants(monkeypatch):
    """The rule, expressed rather than commented: "do not approve one
    employer by approving its whole ATS." Both levels must approve, so a
    Greenhouse approval leaves every Greenhouse employer unreviewed until it is
    listed on its own."""
    approved = replace(SOURCE_REVIEWS["greenhouse"], review=ReviewResult.APPROVED)
    monkeypatch.setitem(SOURCE_REVIEWS, "greenhouse", approved)

    assert effective_review("greenhouse") is ReviewResult.APPROVED       # the ATS
    assert effective_review("greenhouse", company="anthropic") is ReviewResult.UNREVIEWED

    monkeypatch.setitem(COMPANY_REVIEWS, "anthropic", ReviewResult.APPROVED)
    assert effective_review("greenhouse", company="anthropic") is ReviewResult.APPROVED


def test_an_unregistered_provider_is_unreviewed_never_approved():
    assert source_review("nonexistent") is None
    assert effective_review("nonexistent") is ReviewResult.UNREVIEWED


# -- the declared provider ------------------------------------------------ #


def test_each_routes_family_is_the_one_its_adapter_declares():
    assert {key: row.route_family for key, row in SOURCE_REVIEWS.items()} == {
        key: route_family_of(key) for key in SOURCE_REVIEWS
    }


def test_a_named_company_declares_its_provider_however_it_is_named():
    assert declared_adapter("google") == "google", "a built-in"
    assert declared_adapter("tsmc") == "avature_tls", "a catalog company"
    assert declared_adapter("google-deepmind") == "google", "a connector family's company"
    assert declared_adapter("acme-added-by-url") is None
    assert declared_adapter(None) is None
    # The route a company moved to within its family answers for itself;
    # any other path still answers to the declared provider.
    assert declared_adapter("wise", "smartrecruiters") is None
    assert declared_adapter("wise", "recipe") == "smartrecruiters_api"
    assert declared_adapter("tsmc", "greenhouse") == "avature_tls", "another family is not a route of it"


def _paths_to(slug: str) -> list[str]:
    """Every provider a named company can be collected through: its declared
    one, a route of the same family, and a recipe."""
    declared = declared_adapter(slug)
    family = route_family_of(declared)
    siblings = [key for key in SOURCE_REVIEWS if family is not None and route_family_of(key) == family]
    return sorted({declared, *siblings, "recipe"} - {None})


def test_the_follow_time_and_collect_time_wall_agree_for_every_named_company():
    """`company_wall` (what the follow dialog asks about) and
    `collection_access` (what a scan is refused by) resolve a company alike,
    on every path it can be collected through, so a recipe bound to a catalog
    company on a walled source still needs the user's consent."""
    from types import SimpleNamespace

    from tracker.company_discovery import company_wall, named_companies
    from tracker.source_policy import collection_access

    disagree = [
        (slug, stored)
        for slug in sorted(named_companies())
        for stored in _paths_to(slug)
        if (company_wall(slug, SimpleNamespace(adapter=stored)) is not None)
        != collection_access(stored, company=slug).walled
    ]
    assert disagree == []
    assert collection_access("recipe", company="tsmc").walled, "the case that broke it"


# -- the impact enumeration ----------------------------------------------- #


def test_the_enumeration_names_every_provider_a_review_gate_would_pause():
    """Before review decisions gate collection, the active bindings, review
    decisions and feeds that would pause must be enumerated. That is every
    provider except the one denied and the one approved — which argues the
    gate must NOT be switched on in the same change that records it."""
    pausable = unreviewed_providers()

    assert set(pausable) == set(SOURCE_REVIEWS) - {"meta", "workday"}
    # Every provider but `meta` (denied) and `workday` (approved, the one row
    # to leave this list by decision rather than by never having joined it).
    # The count rises with every new family, which is the measurement: a gate
    # switched on would pause the entire fleet bar two.
    assert len(pausable) == 23


def test_the_register_is_read_only_by_the_wall_gate_and_its_report():
    """The register is a gate because robots and bot walls gate on the user's
    consent; its affected bindings are `google` and `google-deepmind`, the only
    companies on a walled source. It is read for its WALL facts only, by
    tracker modules: `source_policy` (the single gate), `company_discovery`
    (which tells the screen a company is walled) and `workflows/scheduler`,
    which keeps a `user_directed` source out of AUTOMATIC work. Review
    decisions still gate nothing.

    The user-directed rule's affected bindings: every company on `workday`,
    never curated and never scanned on a timer, none of which anyone follows
    until a user says so.

    `workflows/schedule_status` reads the same two facts through
    `waits_for_user`, the one rule `collectable_now` calls, so the status
    roster never counts a company automatic work never collects as overdue.
    It reports and collects nothing. Affected bindings: every company on
    `workday`, plus any walled company without consent.

    A new consumer is still a new gate: it needs its own decision and
    enumeration before it joins this list.

    Asserted on imports, via the AST, rather than on the text `source_review`
    appearing in a file: a text match would catch `platform/robots.py`, which
    only mentions the register in a docstring. A prose reference is not a
    consumer.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    importers = set()
    for folder in ("tracker", "scripts"):
        for path in (root / folder).rglob("*.py"):
            if path.name == "source_review.py":
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom) and node.module == "tracker.source_review":
                    importers.add(path.relative_to(root).as_posix())
                elif isinstance(node, ast.Import) and any(
                    alias.name == "tracker.source_review" for alias in node.names
                ):
                    importers.add(path.relative_to(root).as_posix())

    assert sorted(importers) == [
        "scripts/check_source_review.py",
        # Renders the register into docs/sources.md; reads, gates nothing.
        "scripts/gen_sources_doc.py",
        "tracker/company_discovery.py",
        "tracker/source_policy.py",
        "tracker/workflows/schedule_status.py",
        "tracker/workflows/scheduler.py",
    ], (
        "a new consumer of the review register is a gate: it needs an owner "
        "decision and the affected-binding enumeration first"
    )


def test_review_decisions_still_gate_nothing():
    """The WALL is a gate; the review decision is not one. An
    unreviewed or even denied review must not change `collection_access`."""
    from dataclasses import replace

    from tracker.source_policy import collection_access

    row = SOURCE_REVIEWS["greenhouse"]
    for review in ReviewResult:
        SOURCE_REVIEWS["greenhouse"] = replace(row, review=review)
        try:
            assert not collection_access("greenhouse", company="stripe").denied
        finally:
            SOURCE_REVIEWS["greenhouse"] = row


# -- the evidence re-check (scripts.check_source_review) ----------------------- #
#
# The drift detector is what keeps a recorded verdict from becoming a claim
# nobody can check. Tested offline against a mocked transport: the register's
# own hashes came from a live read, and re-reading live in pytest would make the
# suite depend on other people's web servers.


@pytest.fixture
def evidence_probe(monkeypatch):
    """Re-check one provider against a robots body we control."""
    import httpx

    from scripts.check_source_review import check_evidence
    from tracker import source_review as register

    async def run(provider: str, body: str, status: int = 200):
        recorded = SOURCE_REVIEWS[provider]

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, text=body)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monkeypatch.setitem(register.SOURCE_REVIEWS, provider, recorded)
            return await check_evidence(client, provider)

    return run


ALLOWING = "User-agent: *\nDisallow: /embed/\n"


@pytest.mark.asyncio
async def test_an_unchanged_file_holds(evidence_probe):
    """`greenhouse`'s recorded hash is of the real file, so a different body
    with the SAME verdict must report `moved`, not `holds` — which is what makes
    this fixture's negative cases meaningful."""
    result = await evidence_probe("greenhouse", ALLOWING)

    assert result["state"] == "moved"
    assert result["now"] == "allowed"
    assert "same verdict" in result["detail"]


@pytest.mark.asyncio
async def test_a_changed_verdict_is_drift_and_fails(evidence_probe):
    """The finding that matters: the operator now refuses the route we record as
    permitted."""
    from scripts.check_source_review import exit_code

    result = await evidence_probe(
        "greenhouse", "User-agent: *\nDisallow: /v1/boards/\n"
    )

    assert result["state"] == "drifted"
    assert result["now"] == "disallowed"
    assert "allowed -> disallowed" in result["detail"]
    assert exit_code([result]) == 1


@pytest.mark.asyncio
async def test_a_changed_rule_with_the_same_verdict_is_still_drift(evidence_probe):
    """Permitted by absence of a rule and permitted by an explicit `Allow:` are
    different records. A register saying "no matching rule" when the operator
    has since written one is stale even though the answer is unchanged."""
    result = await evidence_probe(
        "greenhouse", "User-agent: *\nDisallow: /\nAllow: /v1/boards/\n"
    )

    assert result["state"] == "drifted"
    assert result["now"] == "allowed"
    assert "rule None ->" in result["detail"]


@pytest.mark.asyncio
async def test_a_robots_file_appearing_where_none_was_served_is_drift(evidence_probe):
    """`ashby` answers 401 today. A file appearing there is new information about
    a source we recorded as silent."""
    result = await evidence_probe("ashby", ALLOWING)

    assert result["state"] == "drifted"
    assert result["now"] == "served"


@pytest.mark.asyncio
async def test_a_host_still_serving_no_file_holds(evidence_probe):
    result = await evidence_probe("ashby", "not found", status=404)

    assert result["state"] == "holds"


@pytest.mark.asyncio
async def test_an_app_shell_is_not_a_robots_file(evidence_probe):
    """`jobs.apple.com` answers 404 with 111KB of markup. A 200 carrying markup
    is the same non-answer, and reading it as a robots file would parse a web
    page into directives."""
    result = await evidence_probe("apple", "<!doctype html><html><body>app</body></html>")

    assert result["state"] == "holds"
    assert "unserved" in result["detail"]


@pytest.mark.asyncio
async def test_a_denied_provider_is_never_fetched_even_to_re_verify_it(monkeypatch):
    """Denial is absolute: zero outbound requests for a denied provider,
    including a request that would only confirm why it is denied. The register
    keeps `unverified`, which is the truthful state. Synthetic provider, for the
    reason given on the test above."""
    import httpx

    from scripts.check_source_review import check_evidence

    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, text=ALLOWING)

    # The clone keeps ashby's SERVED robots record, so the only thing that can
    # suppress the fetch is the policy denial — without the denylist entry this
    # provider is re-read and the state comes back `drifted`.
    denied = replace(SOURCE_REVIEWS["ashby"], provider="denied-ats",
                     review=ReviewResult.DENIED)
    monkeypatch.setitem(SOURCE_REVIEWS, "denied-ats", denied)
    monkeypatch.setattr(
        get_settings(), "sync_policy_denied_providers", frozenset({"denied-ats"})
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await check_evidence(client, "denied-ats")

    assert result["state"] == "skipped"
    assert requested == []


@pytest.mark.asyncio
async def test_a_network_failure_is_unknown_not_a_finding():
    """A verdict must not be revised because someone's server was briefly down —
    the direction `check_catalog_tokens` already established for `unknown`."""
    import httpx

    from scripts.check_source_review import check_evidence, exit_code

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await check_evidence(client, "greenhouse")

    assert result["state"] == "unknown"
    assert exit_code([result]) == 3


def test_a_moved_file_alone_does_not_fail_the_run():
    """Cosmetic churn in a robots file whose verdict for our route is unchanged
    is not something to act on, and failing on it trains everyone to ignore the
    one signal that matters."""
    from scripts.check_source_review import exit_code

    assert exit_code([{"state": "holds"}, {"state": "moved"}, {"state": "skipped"}]) == 0


@pytest.mark.asyncio
async def test_a_missing_file_can_still_confirm_a_missing_file(evidence_probe):
    """404 is an answer ABOUT the file: it really is not there, as recorded."""
    result = await evidence_probe("ashby", "", status=404)

    assert result["state"] == "holds"
    assert "404" in result["detail"]


@pytest.mark.asyncio
async def test_a_broken_server_does_not_re_confirm_a_missing_file(evidence_probe):
    """A 5xx is not evidence about robots.txt.

    RFC 9309 §2.3.1.4 gives "unreachable" its own class — the file is undefined
    and a crawler must assume complete disallow — as against 404, which says the
    file genuinely is absent. Collapsing them would report a 503 as `holds` /
    "still unserved", re-confirming "nothing restricts us" on the strength of a
    server having fallen over: an outage read as renewed permission. `unknown`
    keeps the prior evidence and exits 3, so someone re-reads it when the host
    is back.
    """
    from scripts.check_source_review import exit_code

    result = await evidence_probe("ashby", "", status=503)

    assert result["state"] == "unknown"
    assert "503" in result["detail"]
    assert exit_code([result]) == 3


@pytest.mark.asyncio
async def test_a_broken_server_does_not_erase_recorded_rules_either(evidence_probe):
    """Same rule from the other starting point: a provider whose file we HAVE
    read must not have its verdict re-derived from an error page."""
    result = await evidence_probe("greenhouse", "", status=500)

    assert result["state"] == "unknown"
    assert "now" not in result


@pytest.mark.asyncio
async def test_a_file_with_an_empty_disallow_holds_against_its_own_record(evidence_probe):
    """`apply.workable.com/robots.txt` as the check's client receives it, the
    bytes the register hashed. An empty `Disallow:` matches no path, so the
    matcher names no deciding rule; a record that names one can never hold and
    reports drift on a file that never changed."""
    body = "User-agent: *\nContent-Signal: search=yes, ai-input=yes, ai-train=no\nDisallow: "

    result = await evidence_probe("workable", body)

    assert result["sha256"] == SOURCE_REVIEWS["workable"].robots.sha256
    assert result["state"] == "holds", result["detail"]


@pytest.mark.asyncio
async def test_a_source_that_refuses_the_identified_client_is_not_asked_with_it():
    """TSMC's portal answers the identified client with a Cloudflare challenge,
    robots file included, which the register records. Asking again only
    re-reads the challenge as `now HTTP 403` drift, and the check may not
    escalate to the walled tier itself: the tier is released by a user's
    consent and nowhere else. So the row is skipped, with no request."""
    import httpx

    from scripts.check_source_review import check_evidence, exit_code

    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(403, text="<!doctype html><title>Just a moment...</title>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await check_evidence(client, "avature_tls")

    assert requested == []
    assert result["state"] == "skipped"
    assert "identified client" in result["detail"]
    assert exit_code([result]) == 0
