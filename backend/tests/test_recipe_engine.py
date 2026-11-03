"""Recipe engine v1: schema corpus + replay fixtures.

The schema corpus holds valid and malicious/invalid recipes; the replay fixtures
prove extraction, pagination, duplicate IDs, empty page, malformed payload,
cross-host rejection and unconfirmed-empty closure suppression.

No live fetching: a `ReplayContext` returns canned `FetchResponse`s keyed by URL,
so pagination and cross-host behavior are exercised deterministically.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime

import pytest

from tracker.connectors.recipes import (
    RecipeError,
    apply_transforms,
    compile_recipe,
    run_plan,
    runtime_problems,
)
from tracker.connectors.recipes.transforms import TransformError
from tracker.connectors.sdk import FetchResponse

# --------------------------------------------------------------------------- #
# A valid baseline recipe every test mutates from
# --------------------------------------------------------------------------- #

VALID_HTML_RECIPE = {
    "format_version": 1,
    "kind": "job_listing",
    "id": "example-careers",
    "match": {"domains": ["careers.example.com"]},
    "transport": {"mode": "static_http", "delay_ms": 1000},
    "listing": {
        "start_url": "https://careers.example.com/jobs",
        "response": "html",
        "item": "article.job",
        "fields": {
            "req_id": {"attr": "data-job-id", "required": True},
            "title": {"css": "h2", "text": True, "required": True},
            "url": {"css": "a", "attr": "href", "absolute": True, "required": True},
            "locations": {"css_all": ".location", "text": True},
        },
    },
    "pagination": {"mode": "next_link", "selector": "a[rel=next]", "max_pages": 100},
    "validation": {"required_field_ratio": 0.9},
}

VALID_JSON_RECIPE = {
    "format_version": 1,
    "kind": "job_listing",
    "id": "example-api",
    "match": {"domains": ["api.example.com"]},
    "transport": {"mode": "static_http"},
    "listing": {
        "start_url": "https://api.example.com/v1/jobs",
        "response": "json",
        "item": "data.jobs",
        "fields": {
            "req_id": {"json_path": "id", "required": True},
            "title": {"json_path": "name", "required": True},
            "url": {"json_path": "absolute_url", "required": True},
            "locations": {"json_path": "location.name"},
        },
    },
    "pagination": {"mode": "offset", "param": "offset", "size": 2, "max_pages": 50},
}


class ReplayContext:
    """Fake ConnectorContext: replays canned responses by URL."""

    def __init__(self, by_url: dict[str, FetchResponse], default=None):
        self._by_url = by_url
        self._default = default
        self.requested: list[str] = []

    async def fetch(self, request):
        self.requested.append(request.url)
        if request.url in self._by_url:
            return self._by_url[request.url]
        if self._default is not None:
            return self._default
        return FetchResponse(status=404, final_url=request.url, headers={}, content=b"")


def html_response(url: str, body: str, status: int = 200) -> FetchResponse:
    return FetchResponse(status=status, final_url=url, headers={}, content=body.encode())


def json_response(url: str, obj, status: int = 200) -> FetchResponse:
    return FetchResponse(
        status=status, final_url=url, headers={}, content=json.dumps(obj).encode()
    )


# =========================================================================== #
# Schema corpus: valid
# =========================================================================== #


def test_valid_html_recipe_compiles():
    plan = compile_recipe(VALID_HTML_RECIPE)
    assert plan.recipe_id == "example-careers"
    assert plan.response == "html"
    assert plan.domains == ("careers.example.com",)


def test_valid_json_recipe_compiles():
    plan = compile_recipe(VALID_JSON_RECIPE)
    assert plan.response == "json"
    assert plan.item == "data.jobs"


# =========================================================================== #
# Schema corpus: malicious / invalid — each must be REJECTED
# =========================================================================== #


def _reject(mutate) -> RecipeError:
    doc = copy.deepcopy(VALID_HTML_RECIPE)
    mutate(doc)
    with pytest.raises(RecipeError) as exc:
        compile_recipe(doc)
    return exc.value


def test_raw_xpath_field_is_rejected():
    err = _reject(lambda d: d["listing"]["fields"]["title"].update({"xpath": "//h2"}))
    assert any("xpath" in p.lower() or "additional" in p.lower() for p in err.problems)


def test_xpath_anywhere_is_rejected_even_if_schema_missed_it():
    # Belt-and-suspenders: a top-level stray xpath key.
    err = _reject(lambda d: d.update({"xpath": "//a"}))
    assert err.problems


def test_unknown_top_level_key_is_rejected():
    err = _reject(lambda d: d.update({"execute": "rm -rf /"}))
    assert any("additional" in p.lower() or "execute" in p for p in err.problems)


def test_unknown_field_modifier_is_rejected():
    err = _reject(lambda d: d["listing"]["fields"]["title"].update({"eval": "1+1"}))
    assert err.problems


def test_unknown_transform_op_is_rejected():
    err = _reject(
        lambda d: d["listing"]["fields"]["title"].update(
            {"transforms": [{"op": "os_system"}]}
        )
    )
    assert err.problems


def test_start_url_host_outside_declared_domains_is_rejected():
    err = _reject(lambda d: d["listing"].update({"start_url": "https://evil.com/jobs"}))
    assert any("start_url" in p and "domains" in p for p in err.problems)


def test_missing_required_core_field_is_rejected():
    err = _reject(lambda d: d["listing"]["fields"].pop("url"))
    assert err.problems


def test_bad_transport_mode_is_rejected():
    err = _reject(lambda d: d["transport"].update({"mode": "ftp"}))
    assert err.problems


def test_post_is_rejected_even_with_a_body_and_even_when_stored():
    """The guarded transport sends GET only, so no POST recipe can ever run."""
    err = _reject(lambda d: d["listing"].update({"method": "POST", "body": {"q": "x"}}))
    assert any("method" in p for p in err.problems)
    doc = copy.deepcopy(VALID_HTML_RECIPE)
    doc["listing"].update({"method": "POST", "body": {"q": "x"}})
    with pytest.raises(RecipeError) as stored:
        compile_recipe(doc, stored=True)
    assert stored.value.problems == [
        "semantic: listing.method=POST has no runtime; a recipe fetches with GET"
    ]
    explicit_get = copy.deepcopy(VALID_HTML_RECIPE)
    explicit_get["listing"]["method"] = "GET"
    assert compile_recipe(explicit_get).method == "GET"


@pytest.mark.parametrize("domain", ["com", "co", "localhost", ".example.com", "example.com."])
def test_a_domain_without_an_inner_dot_is_rejected_even_when_stored(domain):
    """A domain admits its subdomains: a bare suffix would admit a whole TLD."""
    doc = copy.deepcopy(VALID_HTML_RECIPE)
    doc["match"]["domains"] = [domain, "careers.example.com"]
    with pytest.raises(RecipeError) as exc:
        compile_recipe(doc)
    assert any(p.startswith("schema: match/domains/0:") for p in exc.value.problems)
    with pytest.raises(RecipeError) as stored:
        compile_recipe(doc, stored=True)
    assert any(p.startswith("schema: match/domains/0:") for p in stored.value.problems)


def test_a_dotted_domain_still_admits_its_subdomains():
    doc = copy.deepcopy(VALID_HTML_RECIPE)
    doc["match"]["domains"] = ["example.co.uk"]
    doc["listing"]["start_url"] = "https://jobs.example.co.uk/list"
    plan = compile_recipe(doc)
    assert plan.host_allowed("https://jobs.example.co.uk/next")
    assert not plan.host_allowed("https://other.co.uk/next")


def test_an_unknown_field_name_is_refused_by_the_contract_but_a_stored_one_loads():
    """A typo would be dropped by the runner, so the contract names it; a stored
    revision that carries one still compiles, and the runner skips the field."""
    doc = copy.deepcopy(VALID_HTML_RECIPE)
    doc["listing"]["fields"]["locaitons"] = doc["listing"]["fields"].pop("locations")
    with pytest.raises(RecipeError) as exc:
        compile_recipe(doc)
    assert any("'locaitons' is not one of" in p for p in exc.value.problems)
    assert "locaitons" in compile_recipe(doc, stored=True).fields


@pytest.mark.parametrize("mode", ["static_impersonate", "render"])
def test_a_reserved_transport_is_refused_by_the_contract_and_by_the_runtime(mode):
    doc = copy.deepcopy(VALID_HTML_RECIPE)
    doc["transport"]["mode"] = mode
    with pytest.raises(RecipeError) as exc:
        compile_recipe(doc)
    assert any(p.startswith("schema: transport/mode:") for p in exc.value.problems)
    stored = compile_recipe(doc, stored=True)
    assert runtime_problems(stored) == [
        f"transport: mode {mode!r} has no runtime; a recipe runs static_http"
    ]
    assert runtime_problems(compile_recipe(VALID_HTML_RECIPE)) == []


def test_next_link_without_selector_is_rejected():
    err = _reject(lambda d: d.update({"pagination": {"mode": "next_link", "max_pages": 10}}))
    assert any("selector" in p for p in err.problems)


def test_wrong_format_version_is_rejected():
    err = _reject(lambda d: d.update({"format_version": 2}))
    assert err.problems


def test_all_problems_reported_at_once():
    doc = copy.deepcopy(VALID_HTML_RECIPE)
    doc["transport"]["mode"] = "ftp"
    doc["id"] = "BAD ID WITH SPACES"
    with pytest.raises(RecipeError) as exc:
        compile_recipe(doc)
    assert len(exc.value.problems) >= 2  # one round-trip, not one-at-a-time


# =========================================================================== #
# Replay: HTML extraction
# =========================================================================== #

_HTML_PAGE = """
<html><body>
  <article class="job" data-job-id="A1"><h2>Staff Engineer</h2>
    <a href="/jobs/a1">apply</a><span class="location">Zurich</span></article>
  <article class="job" data-job-id="A2"><h2>Senior SRE</h2>
    <a href="/jobs/a2">apply</a><span class="location">Remote</span></article>
</body></html>
"""


@pytest.mark.asyncio
async def test_html_extraction_builds_rawjobs():
    plan = compile_recipe(VALID_HTML_RECIPE)
    ctx = ReplayContext({plan.start_url: html_response(plan.start_url, _HTML_PAGE)})
    result = await run_plan(plan, ctx, "example")

    assert result.list_complete
    assert [j.req_id for j in result.jobs] == ["A1", "A2"]
    assert result.jobs[0].title == "Staff Engineer"
    # `absolute: true` resolved the relative href against the page URL.
    assert result.jobs[0].url == "https://careers.example.com/jobs/a1"
    assert result.jobs[0].locations == ["Zurich"]


@pytest.mark.asyncio
async def test_html_missing_required_field_drops_the_item_not_the_run():
    broken = _HTML_PAGE.replace('data-job-id="A2"', "")  # A2 loses its req_id
    plan = compile_recipe(VALID_HTML_RECIPE)
    ctx = ReplayContext({plan.start_url: html_response(plan.start_url, broken)})
    result = await run_plan(plan, ctx, "example")

    assert [j.req_id for j in result.jobs] == ["A1"]
    assert result.diagnostics["dropped"] == 1


# =========================================================================== #
# Replay: JSON extraction + offset pagination + natural termination
# =========================================================================== #


@pytest.mark.asyncio
async def test_json_extraction_and_offset_pagination():
    plan = compile_recipe(VALID_JSON_RECIPE)
    page0 = {
        "data": {
            "jobs": [
                {"id": "1", "name": "PM", "absolute_url": "https://x/1", "location": {"name": "NYC"}},
                {"id": "2", "name": "EM", "absolute_url": "https://x/2", "location": {"name": "SF"}},
            ]
        }
    }
    page1 = {
        "data": {"jobs": [{"id": "3", "name": "TL", "absolute_url": "https://x/3"}]}
    }
    empty = {"data": {"jobs": []}}
    ctx = ReplayContext(
        {
            "https://api.example.com/v1/jobs": json_response("https://api.example.com/v1/jobs", page0),
            "https://api.example.com/v1/jobs?offset=2": json_response("u", page1),
            "https://api.example.com/v1/jobs?offset=4": json_response("u", empty),
        }
    )
    result = await run_plan(plan, ctx, "example")

    assert [j.req_id for j in result.jobs] == ["1", "2", "3"]
    assert result.jobs[0].locations == ["NYC"]
    assert result.list_complete  # ended on a natural empty page


@pytest.mark.asyncio
async def test_posted_at_is_read_through_parse_date():
    doc = copy.deepcopy(VALID_HTML_RECIPE)
    doc["listing"]["fields"]["posted_at"] = {
        "css": "time", "attr": "datetime", "transforms": [{"op": "parse_date"}],
    }
    plan = compile_recipe(doc)
    page = _HTML_PAGE.replace("<h2>Staff Engineer</h2>", '<h2>Staff Engineer</h2><time datetime="2026-09-30T12:00:00Z">x</time>')
    ctx = ReplayContext({plan.start_url: html_response(plan.start_url, page)})
    result = await run_plan(plan, ctx, "example")
    dated, undated = result.jobs
    assert dated.posted_at == datetime(2026, 9, 30, 12, tzinfo=UTC)
    assert undated.posted_at is None  # no date on the page: kept, undated


@pytest.mark.asyncio
async def test_posted_at_reads_an_epoch_or_text_without_a_transform():
    doc = copy.deepcopy(VALID_JSON_RECIPE)
    doc["listing"]["fields"]["posted_at"] = {"json_path": "posted"}
    plan = compile_recipe(doc)
    page = {"data": {"jobs": [
        {"id": "1", "name": "PM", "absolute_url": "https://x/1", "posted": 1759233600},
        {"id": "2", "name": "EM", "absolute_url": "https://x/2", "posted": "2026-09-30"},
        {"id": "3", "name": "TL", "absolute_url": "https://x/3", "posted": "soon"},
    ]}}
    ctx = ReplayContext({plan.start_url: json_response(plan.start_url, page)},
                        default=json_response("u", {"data": {"jobs": []}}))
    result = await run_plan(plan, ctx, "example")
    assert [j.posted_at for j in result.jobs] == [
        datetime(2025, 9, 30, 12, tzinfo=UTC), datetime(2026, 9, 30, tzinfo=UTC), None,
    ]


# =========================================================================== #
# Replay: the closure-safety cases
# =========================================================================== #


@pytest.mark.asyncio
async def test_duplicate_ids_are_deduped():
    dup = _HTML_PAGE.replace('data-job-id="A2"', 'data-job-id="A1"')
    plan = compile_recipe(VALID_HTML_RECIPE)
    ctx = ReplayContext({plan.start_url: html_response(plan.start_url, dup)})
    result = await run_plan(plan, ctx, "example")
    assert [j.req_id for j in result.jobs] == ["A1"]


@pytest.mark.asyncio
async def test_empty_first_page_is_complete_but_yields_nothing():
    plan = compile_recipe(VALID_HTML_RECIPE)
    empty = "<html><body></body></html>"
    ctx = ReplayContext({plan.start_url: html_response(plan.start_url, empty)})
    result = await run_plan(plan, ctx, "example")
    assert result.jobs == []
    assert result.list_complete  # structurally empty, not an error


def _paged(job_id: str, next_href: str) -> str:
    return (
        f'<html><body><article class="job" data-job-id="{job_id}"><h2>T</h2>'
        f'<a href="/j/{job_id}">a</a></article><a rel="next" href="{next_href}">n</a></body></html>'
    )


@pytest.mark.asyncio
async def test_hitting_max_pages_marks_incomplete():
    """A recipe that never stops paginating must not claim completeness."""
    doc = copy.deepcopy(VALID_HTML_RECIPE)
    doc["pagination"] = {"mode": "next_link", "selector": "a[rel=next]", "max_pages": 3}
    plan = compile_recipe(doc)
    # Every page has a NEW item and a next link -> pagination never terminates.
    base = "https://careers.example.com"
    ctx = ReplayContext({
        f"{base}/jobs": html_response(f"{base}/jobs", _paged("X0", "/p1")),
        f"{base}/p1": html_response(f"{base}/p1", _paged("X1", "/p2")),
        f"{base}/p2": html_response(f"{base}/p2", _paged("X2", "/p3")),
    })
    result = await run_plan(plan, ctx, "example")
    assert len(ctx.requested) == 3  # bounded
    assert [j.req_id for j in result.jobs] == ["X0", "X1", "X2"]
    assert not result.list_complete  # bound hit -> closure suppressed
    assert result.diagnostics["errors"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("pagination", [
    {"mode": "next_link", "selector": "a[rel=next]", "max_pages": 1000},
    {"mode": "page_number", "param": "page", "max_pages": 1000},
], ids=["next_link", "page_number"])
async def test_a_page_of_repeats_stops_paging_and_marks_incomplete(pagination):
    """A site that ignores the page parameter serves its first page again: the
    run stops at the first page that adds nothing, not at `max_pages`."""
    doc = copy.deepcopy(VALID_HTML_RECIPE)
    doc["pagination"] = pagination
    del doc["validation"]
    plan = compile_recipe(doc)
    ctx = ReplayContext({}, default=html_response(plan.start_url, _paged("X", "/next")))
    result = await run_plan(plan, ctx, "example")
    assert len(ctx.requested) == 2
    assert [j.req_id for j in result.jobs] == ["X"]
    assert not result.list_complete
    assert result.diagnostics["errors"] == [
        "page 1: no new posting (every item repeated or was dropped); stopped paging"
    ]


@pytest.mark.asyncio
async def test_a_page_whose_every_item_drops_is_not_a_complete_listing():
    """Items the recipe cannot read are not an empty board, even with no
    `required_field_ratio` to catch them."""
    doc = copy.deepcopy(VALID_HTML_RECIPE)
    del doc["validation"]
    plan = compile_recipe(doc)
    unreadable = _HTML_PAGE.replace('data-job-id="A1"', "").replace('data-job-id="A2"', "")
    ctx = ReplayContext({plan.start_url: html_response(plan.start_url, unreadable)})
    result = await run_plan(plan, ctx, "example")
    assert result.jobs == [] and result.diagnostics["dropped"] == 2
    assert not result.list_complete


@pytest.mark.asyncio
async def test_max_items_cap_marks_incomplete():
    plan = compile_recipe(VALID_HTML_RECIPE)
    ctx = ReplayContext({plan.start_url: html_response(plan.start_url, _HTML_PAGE)})
    result = await run_plan(plan, ctx, "example", max_items=1)
    assert len(result.jobs) == 1
    assert not result.list_complete  # capped == incomplete, same rule as --max-list


@pytest.mark.asyncio
async def test_cross_host_pagination_is_blocked_and_incomplete():
    plan = compile_recipe(VALID_HTML_RECIPE)
    page = (
        '<html><body><article class="job" data-job-id="A1"><h2>T</h2>'
        '<a href="/j">a</a></article>'
        '<a rel="next" href="https://evil.com/steal">n</a></body></html>'
    )
    ctx = ReplayContext({plan.start_url: html_response(plan.start_url, page)})
    result = await run_plan(plan, ctx, "example")
    assert [j.req_id for j in result.jobs] == ["A1"]  # first page kept
    assert "evil.com" not in " ".join(ctx.requested)  # never fetched
    assert not result.list_complete
    assert any("cross-host" in e for e in result.diagnostics["errors"])


@pytest.mark.asyncio
async def test_malformed_json_payload_degrades_to_error_not_crash():
    plan = compile_recipe(VALID_JSON_RECIPE)
    bad = FetchResponse(status=200, final_url=plan.start_url, headers={}, content=b"{not json")
    ctx = ReplayContext({plan.start_url: bad})
    result = await run_plan(plan, ctx, "example")
    assert result.jobs == []
    assert not result.list_complete
    assert result.diagnostics["errors"]


@pytest.mark.asyncio
async def test_non_200_page_marks_incomplete():
    plan = compile_recipe(VALID_HTML_RECIPE)
    ctx = ReplayContext({plan.start_url: html_response(plan.start_url, "", status=503)})
    result = await run_plan(plan, ctx, "example")
    assert not result.list_complete


@pytest.mark.asyncio
async def test_required_field_ratio_violation_marks_incomplete():
    doc = copy.deepcopy(VALID_HTML_RECIPE)
    doc["validation"] = {"required_field_ratio": 0.99}
    plan = compile_recipe(doc)
    # One of two items is missing its req_id -> 0.5 kept ratio < 0.99.
    page = _HTML_PAGE.replace('data-job-id="A2"', "")
    ctx = ReplayContext({plan.start_url: html_response(plan.start_url, page)})
    result = await run_plan(plan, ctx, "example")
    assert not result.list_complete


# =========================================================================== #
# Transforms
# =========================================================================== #


def test_transform_pipeline_runs_in_order():
    out = apply_transforms(
        "  Senior   Engineer  ", [{"op": "trim"}, {"op": "collapse_whitespace"}, {"op": "lower"}], {}
    )
    assert out == "senior engineer"


def test_regex_capture_extracts_group():
    out = apply_transforms("job-12345-x", [{"op": "regex_capture", "pattern": r"job-(\d+)"}], {})
    assert out == "12345"


def test_resolve_url_uses_base():
    out = apply_transforms("/jobs/1", [{"op": "resolve_url"}], {"base_url": "https://x.com/list"})
    assert out == "https://x.com/jobs/1"


def test_a_pattern_that_can_backtrack_without_end_is_refused_when_the_recipe_is_checked():
    """Python's re has no timeout and runs on the event loop: a repeat inside a
    repeat stalls the whole process on text it almost matches."""
    doc = copy.deepcopy(VALID_HTML_RECIPE)
    doc["listing"]["fields"]["title"]["transforms"] = [{"op": "regex_capture", "pattern": r"(\w+\s?)+$"}]
    with pytest.raises(RecipeError) as refused:
        compile_recipe(doc)
    assert any("listing.fields.title" in problem and "backtrack" in problem for problem in refused.value.problems)
    with pytest.raises(TransformError, match="backtrack"):
        apply_transforms("a" * 40 + "!", [{"op": "regex_capture", "pattern": r"(a+)+$"}], {})


def test_a_pattern_reads_at_most_the_first_two_thousand_characters():
    tail = "x" * 2500 + "job-77"
    assert apply_transforms(tail, [{"op": "regex_capture", "pattern": r"job-(\d+)"}], {}) == ""
    assert apply_transforms("job-77" + tail, [{"op": "regex_capture", "pattern": r"job-(\d+)"}], {}) == "77"


def test_regex_capture_rejects_overlong_pattern():
    with pytest.raises(TransformError):
        apply_transforms("x", [{"op": "regex_capture", "pattern": "a" * 500}], {})


def test_join_collapses_a_list():
    assert apply_transforms(["a", "b", "c"], [{"op": "join", "sep": ", "}], {}) == "a, b, c"
