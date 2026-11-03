"""The fixture scrubber: what it keeps, what it never writes.

The committed listing fixtures are its output, so the first test is the gate:
a capture committed without going through `scripts.scrub_fixtures` fails here
by name. The rest hold the passes on small tables and pages, each with the
case a plausible broken version would get wrong.
"""

from __future__ import annotations

import json

import pytest

from scripts.scrub_fixtures import (
    FIXTURES,
    GTM_PLACEHOLDER,
    ZERO_UUID,
    _same_but_people,
    process,
    prune_table,
    reduce_react_router,
    reduce_sf_detail,
    scrub_text,
)
from tracker.connectors.extract.turbo_stream import decode_turbo_stream


def test_every_committed_listing_fixture_is_already_reduced_and_scrubbed():
    stale = [
        path.relative_to(FIXTURES).as_posix()
        for path in sorted(p for p in FIXTURES.rglob("*") if p.is_file())
        if process(path) != path.read_text(encoding="utf-8")
    ]
    assert stale == [], "run `.venv/bin/python -m scripts.scrub_fixtures` and commit the result"


def test_container_ids_and_csrf_values_are_replaced_in_any_quoting():
    page = (
        "(window,document,'script','dataLayer','GTM-T4RLV4B');"
        ' src="https://www.googletagmanager.com/ns.html?id=GTM-NHMTHSDB"'
        ' headers : { "X-CSRF-Token" : "6f1c2a0e-1111-2222-3333-444455556666" }'
        r' {\"X-CSRF-Token\" : \"abc-123\"}'
    )
    out = scrub_text(page)
    assert "T4RLV4B" not in out and "NHMTHSDB" not in out and out.count(GTM_PLACEHOLDER) == 2
    assert "6f1c2a0e" not in out and "abc-123" not in out and out.count(ZERO_UUID) == 2
    assert scrub_text(out) == out, "a second pass changes nothing"


def test_a_job_title_that_merely_contains_gtm_is_left_alone():
    """Synopsys lists a "UIGTM-Analytics" role: a title, not a container id."""
    url = "/careers/JobDetail/UIGTM-Analytics-Executive-Director-18377/18377"
    assert scrub_text(url) == url


# A turbo-stream table (`extract.turbo_stream`): index 0 the root, "_N" keys
# name the string at N, values are indices. One posting row whose ATS record
# names its internal title and a hiring team of one person, who is also the
# author (one shared entry), next to a route the adapter does not read.
TABLE = [
    {"_1": 2, "_20": 21},                          # 0 root: loaderData, actionData
    "loaderData",                                  # 1
    {"_3": 4, "_17": 18},                          # 2 loaderData: careers, root
    "careers",                                     # 3
    {"_5": 6, "_15": 16},                          # 4 careers: rows, translations
    "rows",                                        # 5
    [7],                                           # 6
    {"_8": 9, "_10": 11},                          # 7 row: title, job
    "title",                                       # 8
    "Staff Engineer",                              # 9
    "job",                                         # 10
    {"_8": 22, "_12": 13, "_23": 24},              # 11 job: title, hiringTeam, author
    "hiringTeam",                                  # 12
    [14],                                          # 13
    {"_25": 26, "_27": 28, "_29": 30, "_31": 32},  # 14 person
    "translations",                                # 15
    {"_8": 9},                                     # 16 not read by the adapter
    "root",                                        # 17
    {"_8": 33},                                    # 18 another route
    "unused",                                      # 19
    "actionData",                                  # 20
    -7,                                            # 21
    "Staff Engineer II (req 4411, backfill for Ana)",  # 22 the internal title
    "author",                                      # 23
    14,                                            # 24 (unused slot)
    "userId",                                      # 25
    "6a7467c7-ba20-4713-a045-e40a09ed61ed",        # 26
    "firstName",                                   # 27
    "Ana",                                         # 28
    "lastName",                                    # 29
    "Real-Surname",                                # 30
    "email",                                       # 31
    "ana@shopify.com",                             # 32
    "Navigation",                                  # 33
]
# The author is the same person record as the hiring team member.
TABLE[11]["_23"] = 14


def _page(table: list) -> str:
    stream = json.dumps(table, separators=(",", ":")) + "\n"
    return f"<script>window.__reactRouterContext.streamController.enqueue({json.dumps(stream)});</script>"


def test_pruning_keeps_the_route_read_and_never_writes_a_person():
    pruned = prune_table(TABLE, {"loaderData": {"careers": {"rows": None}}})
    flat = json.dumps(pruned)
    for original in ("6a7467c7", "Ana", "Real-Surname", "ana@shopify.com", "backfill for Ana"):
        assert original not in flat, f"{original} was written"
    assert "translations" not in flat and "Navigation" not in flat and "actionData" not in flat
    root = decode_turbo_stream(_page(pruned))
    row = root["loaderData"]["careers"]["rows"][0]
    assert list(root) == ["loaderData"] and list(root["loaderData"]) == ["careers"]
    assert row["title"] == "Staff Engineer", "a public title is not an internal one"
    job = row["job"]
    assert job["title"] == "Internal job title"
    member = job["hiringTeam"][0]
    assert member == {
        "userId": "00000000-0000-4000-8000-000000000001",
        "firstName": "Given", "lastName": "Family", "email": "person@example.com",
    }
    assert job["author"] is member, "one shared record stays one record"


def test_pruning_is_idempotent():
    keep = {"loaderData": {"careers": {"rows": None}}}
    once = prune_table(TABLE, keep)
    assert prune_table(once, keep) == once


def test_a_reduction_that_changes_what_the_adapter_reads_refuses():
    before = {"rows": [{"title": "Staff Engineer", "job": {"hiringTeam": [], "title": "x"}}]}
    _same_but_people(before, {"rows": [{"title": "Staff Engineer", "job": {"hiringTeam": [], "title": "Internal job title"}}]})
    with pytest.raises(ValueError, match="became"):
        _same_but_people(before, {"rows": [{"title": "Staff Engineer (edited)", "job": {"hiringTeam": [], "title": "Internal job title"}}]})
    with pytest.raises(ValueError, match="length changed"):
        _same_but_people(before, {"rows": []})


def test_a_react_router_page_reduces_to_its_route_and_its_links():
    page = '<html><body><a href="/careers/staff-engineer_1">Staff <b>Engineer</b></a><a href="/pricing">Pricing</a>' + _page(TABLE)
    reduced = reduce_react_router(page, "careers", ("rows",), links="/careers/")
    assert '<a href="/careers/staff-engineer_1">Staff Engineer</a>' in reduced
    assert "/pricing" not in reduced
    assert reduce_react_router(reduced, "careers", ("rows",), links="/careers/") == reduced


def test_a_posting_page_keeps_its_microdata_properties_verbatim_and_nothing_else():
    page = (
        "<html><head><script>var gtm='GTM-AAAAAAA';</script></head><body><nav>Menu</nav>"
        '<div itemscope itemtype="http://schema.org/JobPosting"><h1>Chrome heading</h1>'
        '<meta itemprop="datePosted" content="Sat Sep 26 02:00:00 UTC 2026">'
        '<span itemprop="jobLocation" itemscope itemtype="http://schema.org/Place">'
        '<span itemprop="address" itemscope itemtype="http://schema.org/PostalAddress">'
        '<meta itemprop="addressLocality" content="Rochester"></span></span>'
        '<div itemprop="description"><p>About EY</p></div></div></body></html>'
    )
    reduced = reduce_sf_detail(page)
    assert "Menu" not in reduced and "Chrome heading" not in reduced and "GTM-" not in reduced
    assert '<meta itemprop="addressLocality" content="Rochester">' in reduced
    assert '<div itemprop="description"><p>About EY</p></div>' in reduced
    assert reduced.count('itemprop="jobLocation"') == 1, "a nested property is not lifted out"
    assert reduce_sf_detail(reduced) == reduced
    with pytest.raises(ValueError):
        reduce_sf_detail("<html><body>no microdata</body></html>")
