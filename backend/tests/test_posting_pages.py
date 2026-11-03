"""What a posting's own page adds, and which postings we read it for.

Fixtures are four real Greenhouse posting pages (anthropic,
doordash, figma, coinbase), trimmed to the fields the code reads: each
question's label, required flag and field names/types, and the pay ranges.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.factories import make_job
from tracker.api.serializers.jobs import application_form_view
from tracker.config import get_settings
from tracker.connectors import build_adapter
from tracker.connectors.listing.base import RateLimiter
from tracker.connectors.listing.greenhouse import application_form, pay_tiers
from tracker.db.models import Job, JobLifecycleEvent, TrackedCompany
from tracker.intelligence_runtime.disclosed_comp import extract_disclosed_comp
from tracker.schema import (
    AccessSurface,
    ApplicationFormFacts,
    CompensationFacts,
    PostingPage,
    RetrievalState,
    SourceJobFacts,
    merge_source_facts,
)
from tracker.source_review import SOURCE_REVIEWS
from tracker.workflows.posting_pages import (
    PAGE_PROVIDERS,
    apply_page,
    band_from_page,
    owed_page_clause,
    page_band,
    page_company,
    page_owed,
    read_posting_pages,
    stated_band,
)

FIXTURES = Path(__file__).parent / "fixtures" / "greenhouse_posting"
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def _page(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


# --------------------------------------------------------------------------- #
# The form, as counts
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("name", "required", "written", "choices"), [
    ("anthropic", 9, 1, 8),  # "Why Anthropic?" is the one written answer
    # "Why do you want to join Figma?" (a text box), and two one-line fields:
    # "From where do you intend to work?" and "Do you have experience managing
    # direct reports? If yes, please elaborate in 1-2 sentences".
    ("figma", 5, 3, 2),
    ("doordash", 8, 0, 7),  # its one typed question is a LinkedIn link
    ("coinbase", 13, 0, 12),  # likewise "Linkedin Profile URL"
])
def test_the_form_counts_only_what_the_employer_added(name, required, written, choices):
    form = application_form(_page(name)["questions"], NOW)
    assert form.state is RetrievalState.PRESENT
    assert (form.required, form.written, form.choices) == (required, written, choices)


def test_a_one_line_answer_is_written_unless_it_is_a_link_or_the_pay_ask():
    questions = [
        {"label": "Do you have experience managing direct reports? If yes, please elaborate in "
                  "1-2 sentences", "required": True,
         "fields": [{"name": "question_19648851004", "type": "input_text"}]},
        {"label": "LinkedIn Profile", "required": True,
         "fields": [{"name": "question_63441989", "type": "input_text"}]},
        {"label": "What are your salary expectations?", "required": True,
         "fields": [{"name": "question_9", "type": "input_text"}]},
    ]
    form = application_form(questions, NOW)
    assert (form.required, form.written, form.choices) == (3, 1, 0)
    assert form.asks_expected_pay  # named on its own, not counted twice


def test_the_contact_and_resume_block_is_never_counted():
    # Required, with a text box: but it is Greenhouse's own `resume` field.
    questions = [
        {"label": "Resume/CV", "required": True,
         "fields": [{"name": "resume", "type": "input_file"}, {"name": "resume_text", "type": "textarea"}]},
        {"label": "Cover Letter", "required": True,
         "fields": [{"name": "cover_letter", "type": "input_file"},
                    {"name": "cover_letter_text", "type": "textarea"}]},
    ]
    form = application_form(questions, NOW)
    assert (form.required, form.written) == (0, 0)


def test_an_optional_question_and_an_upload_are_not_written_answers():
    questions = [
        {"label": "Why us?", "required": False,
         "fields": [{"name": "question_1", "type": "textarea"}]},
        {"label": "Portfolio", "required": True,
         "fields": [{"name": "question_2", "type": "input_file"}, {"name": "question_2_text", "type": "textarea"}]},
    ]
    form = application_form(questions, NOW)
    assert (form.required, form.written, form.choices) == (1, 0, 0)


@pytest.mark.parametrize("label", [
    "What are your salary expectations?",
    "What is your desired base salary?",
    "What are your compensation requirements?",
    "What is your desired annual base salary and desired total compensation?",
])
def test_a_required_expected_pay_question_is_named(label):
    questions = [{"label": label, "required": True,
                  "fields": [{"name": "question_9", "type": "input_text"}]}]
    assert application_form(questions, NOW).asks_expected_pay


def test_a_pay_word_that_asks_nothing_is_not_an_expected_pay_question():
    questions = [{"label": "Do you understand the pay range for this role?", "required": True,
                  "fields": [{"name": "question_9", "type": "multi_value_single_select"}]}]
    assert not application_form(questions, NOW).asks_expected_pay


def test_no_questions_key_is_an_answer_that_states_nothing():
    assert application_form(None, NOW).state is RetrievalState.ABSENT_IN_SUCCESSFUL_RESPONSE


# --------------------------------------------------------------------------- #
# Structured pay, through the one period rule
# --------------------------------------------------------------------------- #


def test_structured_pay_carries_a_period_decided_by_size_and_title():
    anthropic = pay_tiers(_page("anthropic")["pay_input_ranges"], NOW)
    (tier,) = anthropic.tiers
    assert (tier.components[0].min, tier.components[0].interval) == (330_000, "year")

    tiers = pay_tiers([
        {"title": "Base Pay:", "min_cents": 1565, "max_cents": 2200, "currency_type": "USD"},
        {"title": "Zone 1 (Menlo Park, CA; New York, NY)", "min_cents": 22280000,
         "max_cents": 30000000, "currency_type": "USD"},
        {"title": "Annual Salary:", "min_cents": 661260000, "max_cents": 942450000,
         "currency_type": "INR"},
        {"title": "Annual Salary:", "min_cents": 300, "max_cents": 400, "currency_type": "USD"},
    ], NOW)
    assert [t.components[0].interval for t in tiers.tiers] == ["hour", "year", "year"]


def test_a_day_or_week_tier_is_could_not_tell_and_never_the_postings_band():
    # "Daily rate" names no period we read: by its size alone a $600 day rate
    # would be stored as hourly and become the posting's stated band.
    tiers = pay_tiers([
        {"title": "Daily rate", "min_cents": 60000, "max_cents": 80000, "currency_type": "USD"},
    ], NOW)
    assert [t.components[0].interval for t in tiers.tiers] == ["unclear"]
    assert stated_band(tiers) is None


def _one_tier(title: str) -> CompensationFacts:
    return pay_tiers([
        {"title": title, "min_cents": 22280000, "max_cents": 30000000, "currency_type": "USD"},
    ], NOW)


def test_a_tier_title_names_its_basis_by_the_text_parsers_rule():
    def basis(title: str) -> str:
        return stated_band(_one_tier(title))["disclosed_pay_basis"]

    # The text parser's reading of the same words (`derive_pay_basis`): a bare
    # `total` word called both of these total.
    assert basis("Base salary range (total compensation also includes equity)") == "base"
    assert basis("Salary range, see Total Rewards below") == "unclear"
    # Controls: the real titles, and the markers both readers share.
    assert basis("Annual base salary range (excluding equity and bonus):") == "base"
    assert basis("Annual Salary:") == "unclear"
    assert basis("OTE range") == "total"


def test_a_page_with_no_pay_field_states_no_pay():
    assert pay_tiers(None, NOW).state is RetrievalState.ABSENT_IN_SUCCESSFUL_RESPONSE
    assert pay_tiers([], NOW).state is RetrievalState.ABSENT_IN_SUCCESSFUL_RESPONSE


# --------------------------------------------------------------------------- #
# The request
# --------------------------------------------------------------------------- #


async def _read(status: int, body: dict) -> tuple[PostingPage | None, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        # Exercise every retry without spending wall time on backoff. Timing
        # belongs to test_platform.py; this fixture tests the page's answer.
        return httpx.Response(status, json=body, headers={"Retry-After": "0"})

    adapter = build_adapter("figma", "greenhouse", board_token="figma")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)
    return await adapter.read_posting_page("6150563004"), seen


@pytest.mark.asyncio
async def test_one_request_asks_for_the_form_and_the_pay_together():
    page, seen = await _read(200, _page("figma"))
    (request,) = seen
    assert request.url.path == "/v1/boards/figma/jobs/6150563004"
    assert request.url.params["questions"] == "true"
    assert request.url.params["pay_transparency"] == "true"
    assert page is not None
    assert page.application_form.required == 5
    assert page.compensation.tiers[0].components[0].interval == "year"


@pytest.mark.asyncio
async def test_a_failed_read_says_so_and_claims_nothing_about_the_form():
    page, _ = await _read(404, {})
    assert page is not None
    assert page.application_form.state is RetrievalState.RETRIEVAL_FAILED
    assert page.compensation.state is RetrievalState.RETRIEVAL_FAILED


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "permanent"), [(404, True), (410, True), (503, False), (429, False)])
async def test_a_page_the_source_says_is_gone_is_a_permanent_failure(status, permanent):
    """A 404 or 410 is the source answering that the page does not exist; a
    5xx or a 429 is a bad minute. Only the second is worth asking again."""
    page, seen = await _read(status, {})
    assert page is not None
    assert page.application_form.failed_at is not None
    assert page.application_form.permanent is permanent
    expected_requests = 1 if permanent else get_settings().scraper_max_retries + 1
    assert len(seen) == expected_requests


# --------------------------------------------------------------------------- #
# Storing a read
# --------------------------------------------------------------------------- #


def _facts(posting_id: str = "6150563004", **over) -> SourceJobFacts:
    return SourceJobFacts(
        provider="greenhouse", access_surface=AccessSurface.PUBLIC_API,
        tenant_identity="figma", posting_id=posting_id, **over,
    )


def _read_form(**over) -> ApplicationFormFacts:
    return ApplicationFormFacts(
        state=RetrievalState.PRESENT, required=5, written=1, choices=2, observed_at=NOW, **over
    )


@pytest.mark.parametrize("state", [RetrievalState.NOT_REQUESTED, RetrievalState.RETRIEVAL_FAILED])
def test_a_listing_scan_keeps_the_form_an_earlier_page_read_found(state):
    stored = _facts(application_form=_read_form()).as_dict()
    incoming = _facts(application_form=ApplicationFormFacts(state=state))
    assert merge_source_facts(stored, incoming)["application_form"]["required"] == 5


def test_a_listing_scan_keeps_a_failed_reads_cool_down():
    """The listing never asks for the form, so its `not_requested` is no news
    about the page: resetting a failure to it made the row owed again after
    every scan, whatever the cool-down said."""
    stored = _facts(application_form=ApplicationFormFacts.failed(NOW, permanent=True)).as_dict()
    merged = merge_source_facts(stored, _facts())["application_form"]
    assert merged["state"] == "retrieval_failed"
    assert merged["failed_at"] == NOW.isoformat()
    assert merged["permanent"] is True


def _row(**over) -> Job:
    return make_job("page", source_facts=_facts().as_dict(), **over)


def test_a_single_yearly_tier_becomes_the_postings_stated_band():
    job = _row()
    page = PostingPage(_read_form(), pay_tiers(_page("figma")["pay_input_ranges"], NOW))
    assert apply_page(job, page)
    assert (job.disclosed_base_min, job.disclosed_base_max) == (235_000, 317_000)
    assert (job.disclosed_pay_period, job.disclosed_pay_basis) == ("year", "base")
    assert job.source_facts["application_form"]["required"] == 5


_ANTHROPIC_TEXT = (
    "For sales roles, the range provided is the role’s On Target Earnings (\"OTE\") range, "
    "meaning that the range includes both the sales commissions/sales bonuses target and "
    "annual base salary for the role.\n\nAnnual Salary:\n$305,000—$385,000 USD"
)


@pytest.mark.parametrize("family, title, basis", [
    ("product_management", "Product Manager, Enterprise Privacy", "base"),
    ("sales_business_development", "Sales Manager, Nonprofit, EMEA", "total"),
    ("solutions_sales_eng", "Manager, Forward Deployed Engineering", "unclear"),
])
def test_a_page_band_the_posting_defines_per_kind_of_role_follows_the_role(family, title, basis):
    """Anthropic's page tier says only "Annual Salary:", which states no basis; its
    posting defines the range per kind of role, and the role decides."""
    job = _row(description_text=_ANTHROPIC_TEXT, family=family, title=title)
    tier = pay_tiers([{"title": "Annual Salary:", "min_cents": 30500000, "max_cents": 38500000,
                       "currency_type": "USD"}], NOW)
    assert apply_page(job, PostingPage(_read_form(), tier))
    assert job.disclosed_pay_basis == basis


def test_several_tiers_or_a_band_already_read_from_the_text_are_left_alone():
    zones = pay_tiers([
        {"title": "Zone 1", "min_cents": 22280000, "max_cents": 30000000, "currency_type": "USD"},
        {"title": "Zone 2", "min_cents": 20000000, "max_cents": 27000000, "currency_type": "USD"},
    ], NOW)
    assert stated_band(zones) is None  # never merged into an invented span

    # A band the text pass stored always carries the words that ground it.
    job = _row(disclosed_base_min=200_000, disclosed_base_max=250_000,
               disclosed_snippet="The base salary range for this role is $200,000 - $250,000.")
    assert not apply_page(job, PostingPage(_read_form(), pay_tiers(_page("figma")["pay_input_ranges"], NOW)))
    assert job.disclosed_base_min == 200_000
    assert not band_from_page(job)


def test_a_page_band_quotes_nothing_and_rounds_as_the_text_pass_does():
    """The page states numbers in a field. A snippet is shown as the employer's
    words, so none is written; and "$15.65" is stored as 15, as the text pass
    stores it, never displayed as 16 beside a stored 15."""
    job = _row()
    hourly = pay_tiers([{"title": "Base Pay:", "min_cents": 1565, "max_cents": 2050,
                         "currency_type": "USD"}], NOW)
    assert apply_page(job, PostingPage(_read_form(), hourly))
    assert (job.disclosed_base_min, job.disclosed_base_max, job.disclosed_pay_period) == (15, 20, "hour")
    assert job.disclosed_snippet is None
    assert band_from_page(job)


def test_a_page_band_follows_the_page():
    job = _row()
    figma = pay_tiers(_page("figma")["pay_input_ranges"], NOW)
    apply_page(job, PostingPage(_read_form(), figma))

    raised = pay_tiers([{"title": "Annual Base Salary Range:", "min_cents": 25000000,
                         "max_cents": 33000000, "currency_type": "USD"}], NOW)
    apply_page(job, PostingPage(_read_form(), raised))
    assert (job.disclosed_base_min, job.disclosed_base_max) == (250_000, 330_000)

    failed = RetrievalState.RETRIEVAL_FAILED
    apply_page(job, PostingPage(ApplicationFormFacts(state=failed), CompensationFacts(state=failed)))
    assert job.disclosed_base_min == 250_000  # a failed read is a fact about us

    zones = pay_tiers([
        {"title": "Zone 1", "min_cents": 22280000, "max_cents": 30000000, "currency_type": "USD"},
        {"title": "Zone 2", "min_cents": 20000000, "max_cents": 27000000, "currency_type": "USD"},
    ], NOW)
    apply_page(job, PostingPage(_read_form(), zones))
    assert (job.disclosed_base_min, job.disclosed_base_max) == (None, None)


def test_a_failed_read_erases_nothing_an_earlier_read_found():
    job = _row()
    apply_page(job, PostingPage(_read_form(), pay_tiers(_page("figma")["pay_input_ranges"], NOW)))
    failed = RetrievalState.RETRIEVAL_FAILED
    apply_page(job, PostingPage(ApplicationFormFacts(state=failed), CompensationFacts(state=failed)))
    assert job.source_facts["application_form"]["state"] == "present"
    assert job.source_facts["compensation"]["tiers"]


def test_a_failed_read_beside_a_kept_form_is_recorded_and_a_later_read_clears_it():
    job = _row()
    apply_page(job, PostingPage(_read_form(), CompensationFacts(state=RetrievalState.PRESENT)))
    later = NOW + timedelta(days=2)
    failed = RetrievalState.RETRIEVAL_FAILED
    apply_page(job, PostingPage(ApplicationFormFacts.failed(later, permanent=True),
                                CompensationFacts(state=failed, observed_at=later)))
    form = job.source_facts["application_form"]
    assert (form["state"], form["required"], form["observed_at"]) == ("present", 5, NOW.isoformat())
    assert (form["failed_at"], form["permanent"]) == (later.isoformat(), True)

    apply_page(job, PostingPage(_read_form(), CompensationFacts(state=RetrievalState.PRESENT)))
    form = job.source_facts["application_form"]
    assert (form["failed_at"], form["permanent"]) == (None, False)


def test_the_screen_sees_a_form_only_once_a_read_answered():
    assert application_form_view(None) is None
    assert application_form_view(_facts().as_dict()) is None  # never asked
    failed = _facts(application_form=ApplicationFormFacts(state=RetrievalState.RETRIEVAL_FAILED))
    assert application_form_view(failed.as_dict()) is None
    view = application_form_view(_facts(application_form=_read_form(asks_expected_pay=True)).as_dict())
    assert view == {"required": 5, "written": 1, "choices": 2, "asks_expected_pay": True,
                    "read_at": NOW.isoformat()}


# --------------------------------------------------------------------------- #
# The queue
# --------------------------------------------------------------------------- #


def _company(slug: str, **over) -> TrackedCompany:
    row = {"slug": slug, "display": slug.title(), "adapter": "greenhouse", "board_token": slug,
           "status": "active", "enabled": True}
    row.update(over)
    return TrackedCompany(**row)


def _at(slug: str, key: str, **over) -> Job:
    return make_job(key, company=slug, dedupe_key=f"{slug}:{key}", **over)


def _failed_form(at: datetime) -> dict:
    return _facts(application_form=ApplicationFormFacts(
        state=RetrievalState.RETRIEVAL_FAILED, observed_at=at)).as_dict()


def _kept_form_then_failed(read: datetime, failed: datetime, *, permanent: bool = False) -> dict:
    return _facts(application_form=ApplicationFormFacts(
        state=RetrievalState.PRESENT, observed_at=read, failed_at=failed, permanent=permanent,
    )).as_dict()


@pytest.mark.asyncio
async def test_the_queue_is_radar_postings_whose_text_states_no_pay_at_companies_we_collect(db_session):
    changed = NOW - timedelta(days=1)
    read_after = _facts(application_form=_read_form()).as_dict()  # read NOW, after the change
    read_before = _facts(application_form=ApplicationFormFacts(
        state=RetrievalState.PRESENT, observed_at=changed - timedelta(days=5))).as_dict()
    ashby = {**_facts().as_dict(), "provider": "ashby"}
    no_id = {**_facts().as_dict(), "posting_id": ""}
    base = dict(structured_at=NOW, content_changed_at=changed)
    companies = [
        _company("figma"),
        # Owed rows on companies followed once and switched off would eat the
        # drain's limit every run.
        _company("opentable", enabled=False),
        _company("google"),  # walled by its robots file; no consent given
    ]
    rows = [
        _at("figma", "owed", source_facts=_facts().as_dict(), **base),
        _at("figma", "read-since", source_facts=read_after, **base),
        _at("figma", "text-changed", source_facts=read_before, **base),
        _at("figma", "has-pay", source_facts=_facts().as_dict(), disclosed_base_min=1,
            disclosed_base_max=2, **base),
        _at("figma", "not-checked", source_facts=_facts().as_dict(), content_changed_at=changed),
        _at("figma", "off-radar", source_facts=_facts().as_dict(), in_scope=False, **base),
        _at("figma", "closed", source_facts=_facts().as_dict(), status="closed", **base),
        _at("figma", "ashby", source_facts=ashby, **base),
        _at("figma", "no-posting-id", source_facts=no_id, **base),
        _at("figma", "failed-an-hour-ago", source_facts=_failed_form(NOW - timedelta(hours=1)), **base),
        _at("figma", "failed-yesterday", source_facts=_failed_form(NOW - timedelta(days=1)), **base),
        # A 404 after the text last changed, past the cool-down: still gone.
        _at("figma", "gone", source_facts=_facts(application_form=ApplicationFormFacts.failed(
            NOW - timedelta(hours=12), permanent=True)).as_dict(), **base),
        # A 404 before the text last changed: the posting may be back.
        _at("figma", "gone-then-changed", source_facts=_facts(application_form=ApplicationFormFacts.failed(
            changed - timedelta(days=1), permanent=True)).as_dict(), **base),
        # Read before the text changed, so owed; a re-read failed an hour ago.
        _at("figma", "kept-failed-an-hour-ago", source_facts=_kept_form_then_failed(
            changed - timedelta(days=5), NOW - timedelta(hours=1)), **base),
        _at("figma", "kept-failed-yesterday", source_facts=_kept_form_then_failed(
            changed - timedelta(days=5), NOW - timedelta(hours=12)), **base),
        _at("figma", "kept-gone", source_facts=_kept_form_then_failed(
            changed - timedelta(days=5), NOW - timedelta(hours=12), permanent=True), **base),
        _at("opentable", "switched-off", source_facts=_facts().as_dict(), **base),
        _at("google", "walled", source_facts=_facts().as_dict(), **base),
    ]
    db_session.add_all([*companies, *rows])
    await db_session.commit()

    collected = [row.slug for row in companies if page_company(row)]
    assert collected == ["figma"]
    owed = (await db_session.scalars(
        select(Job.req_id).where(owed_page_clause(collected, now=NOW))
    )).all()
    assert sorted(owed) == [
        "failed-yesterday", "gone-then-changed", "kept-failed-yesterday", "owed", "text-changed",
    ]

    # The open's own gate is the same rule in Python: it must agree with the
    # query on every row the queue's radar and pay conditions admit.
    for job in rows:
        if job.company == "figma" and job.in_scope and job.structured_at and job.disclosed_base_min is None:
            assert page_owed(job, now=NOW) is (job.req_id in owed), job.req_id


def test_no_page_provider_is_user_directed():
    """A user-directed source is collected only when the user starts it,
    and the posting-page drain is automatic work. It cannot check
    that itself without becoming a new reader of the review register, which
    needs its own decision (`test_source_review`); so the day a user-directed source
    learns to read posting pages, this fails and asks for that decision."""
    directed = [name for name in PAGE_PROVIDERS if SOURCE_REVIEWS[name].user_directed]
    assert directed == []


# --------------------------------------------------------------------------- #
# The text pass keeps a band only the page stated
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_re_extracting_the_text_keeps_a_band_only_the_page_stated(db_session):
    """A prompt-version move or a `--force` backfill re-runs the text pass on
    a posting whose text states no pay. The page is not owed again (read after
    the text last changed), so a band the pass erased would be gone for good."""
    job = _at(
        "figma", "page-band", source_facts=_facts().as_dict(),
        description_text="Staff Designer. Competitive pay, equity and benefits.",
        content_changed_at=NOW - timedelta(days=1), structured_at=NOW,
        structured_prompt_version="an-older-prompt",
    )
    apply_page(job, PostingPage(_read_form(), pay_tiers(_page("figma")["pay_input_ranges"], NOW)))
    db_session.add(job)
    await db_session.commit()

    summary = await extract_disclosed_comp(db_session, [job.id], page_band=page_band)

    assert summary["processed"] == 1
    row = await db_session.get(Job, job.id, populate_existing=True)
    assert (row.disclosed_base_min, row.disclosed_base_max) == (235_000, 317_000)
    assert (row.disclosed_pay_period, row.disclosed_snippet) == ("year", None)
    assert band_from_page(row)


@pytest.mark.asyncio
async def test_a_page_band_read_before_the_text_is_on_every_pay_reader(db_session, api_client):
    """Opening a posting reads its page whatever the text pass has done
    (`readable_on_open`), and the band it states is stored. A reader that asks
    for the text pass's stamp first would say "not read yet" on the detail, and
    the filter and the transparency rate would leave the posting out. A stored
    band is evidence on its own."""
    job = _at("figma", "page-first", source_facts=_facts().as_dict(), structured_at=None)
    assert apply_page(job, PostingPage(_read_form(), pay_tiers(_page("figma")["pay_input_ranges"], NOW)))
    silent = _at("figma", "unread", structured_at=None)  # the control: nothing read, nothing known
    db_session.add_all([job, silent])
    await db_session.commit()

    detail = (await api_client.get(f"/api/jobs/{job.id}")).json()["disclosed_comp"]
    assert (detail["disclosed"], detail["base_min"], detail["base_max"]) == (True, 235_000, 317_000)
    assert (detail["from_pay_field"], detail["checked_at"]) == (True, None)
    assert (await api_client.get(f"/api/jobs/{silent.id}")).json()["disclosed_comp"] is None

    listed = (await api_client.get("/api/jobs", params={"discloses_pay": "true"})).json()
    assert [row["id"] for row in listed["items"]] == [job.id]

    rate = (await api_client.get("/api/statistics/compensation", params={"days": 0})).json()["disclosure"]["overall"]
    assert (rate["checked"], rate["disclosed"]) == (1, 1)


@pytest.mark.asyncio
async def test_the_text_read_after_a_page_band_keeps_it(db_session):
    """Page first, text second, the text stating no pay: the page's band
    stays, now beside a real text read."""
    job = _at(
        "figma", "page-then-text", source_facts=_facts().as_dict(), structured_at=None,
        description_text="Staff Designer. Competitive pay, equity and benefits.",
        content_changed_at=NOW - timedelta(days=1),
    )
    apply_page(job, PostingPage(_read_form(), pay_tiers(_page("figma")["pay_input_ranges"], NOW)))
    db_session.add(job)
    await db_session.commit()

    assert (await extract_disclosed_comp(db_session, [job.id], page_band=page_band))["processed"] == 1
    row = await db_session.get(Job, job.id, populate_existing=True)
    assert (row.disclosed_base_min, row.disclosed_source) == (235_000, "page")
    assert row.structured_at is not None


@pytest.mark.asyncio
async def test_text_that_now_states_a_band_replaces_the_page_band_and_is_read_once(db_session):
    """The page is read once, while the text states no pay, and the queue
    never reads a posting that has a band again. When the text later states
    one (the employer added it, or the parser learned to read it), the text's
    band is the posting's current word: it replaces the page's, quotes the
    employer, and the read is recorded so the next run does not read it again."""
    job = _at(
        "figma", "page-then-priced", source_facts=_facts().as_dict(), structured_at=NOW - timedelta(days=2),
        description_text="Staff Designer. Competitive pay, equity and benefits.",
        content_changed_at=NOW - timedelta(days=3),
    )
    assert apply_page(job, PostingPage(_read_form(), pay_tiers(_page("figma")["pay_input_ranges"], NOW)))
    job.description_text = (
        "Staff Designer. The base salary range for this role is $180,000 - $220,000 USD."
    )
    job.content_changed_at = NOW - timedelta(days=1)
    db_session.add(job)
    await db_session.commit()

    first = await extract_disclosed_comp(db_session, [job.id], page_band=page_band)
    await db_session.commit()
    row = await db_session.get(Job, job.id, populate_existing=True)
    assert (first["processed"], first["disclosed"]) == (1, 1)
    assert (row.disclosed_base_min, row.disclosed_base_max, row.disclosed_source) == (180_000, 220_000, "text")
    assert "$180,000 - $220,000" in row.disclosed_snippet
    assert not band_from_page(row)

    again = await extract_disclosed_comp(db_session, [job.id], page_band=page_band)
    assert again["processed"] == 0, "a read that wrote is stamped, so the row is not owed every run"


@pytest.mark.asyncio
async def test_a_text_band_the_text_withdraws_gives_way_to_the_page(db_session):
    """A page read never replaces a text band, but it still records the
    page's pay. When the text later states none, the text's band goes and the
    page's fills the gap, rather than the posting showing no pay."""
    job = _at(
        "figma", "priced-then-silent", source_facts=_facts().as_dict(), structured_at=NOW - timedelta(days=2),
        description_text="Staff Designer. The base salary range for this role is $180,000 - $220,000 USD.",
        content_changed_at=NOW - timedelta(days=3),
        disclosed_base_min=180_000, disclosed_base_max=220_000, disclosed_currency="USD",
        disclosed_pay_period="year", disclosed_pay_basis="base", disclosed_source="text",
        disclosed_snippet="$180,000 - $220,000 USD",
    )
    assert not apply_page(job, PostingPage(_read_form(), pay_tiers(_page("figma")["pay_input_ranges"], NOW)))
    assert (job.disclosed_base_min, job.disclosed_source) == (180_000, "text")
    job.description_text = "Staff Designer. Competitive pay, equity and benefits."
    job.content_changed_at = NOW - timedelta(days=1)
    db_session.add(job)
    await db_session.commit()

    await extract_disclosed_comp(db_session, [job.id], page_band=page_band)
    await db_session.commit()
    row = await db_session.get(Job, job.id, populate_existing=True)
    assert (row.disclosed_base_min, row.disclosed_base_max) == (235_000, 317_000)
    assert band_from_page(row) and row.disclosed_snippet is None
    events = (await db_session.scalars(select(JobLifecycleEvent).where(JobLifecycleEvent.job_id == job.id))).all()
    assert [e.detail["disclosed_base"]["from"]["min"] for e in events] == [180_000], (
        "one move, from the text's band to the page's"
    )


# --------------------------------------------------------------------------- #
# The background drain
# --------------------------------------------------------------------------- #


@pytest.fixture
def pages(monkeypatch):
    """Greenhouse posting pages by posting id: the figma page, except one that
    answers a body that is not JSON (a proxy's error page)."""
    state = type("Pages", (), {"asked": [], "broken": set(), "gone": set(), "down": set(), "during": None})()

    async def handler(request):
        posting_id = request.url.path.rsplit("/", 1)[-1]
        state.asked.append(posting_id)
        if state.during is not None:
            await state.during()
        if posting_id in state.broken:
            return httpx.Response(200, content=b"<html>Bad gateway</html>")
        if posting_id in state.gone:
            return httpx.Response(404, json={"status": 404, "error": "Job not found"})
        if posting_id in state.down:
            return httpx.Response(503, json={})
        return httpx.Response(200, json=_page("figma"))

    monkeypatch.setattr(
        "tracker.connectors.listing.base.make_tier_client",
        lambda *a, **k: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(get_settings(), "scraper_min_delay_seconds", 0)
    return state


def _owed(slug: str, key: str, posting_id: str, days_ago: int) -> Job:
    return _at(slug, key, source_facts=_facts(posting_id=posting_id).as_dict(),
               structured_at=NOW, first_seen=NOW - timedelta(days=days_ago))


@pytest.mark.asyncio
async def test_the_drain_reads_only_what_it_may_and_isolates_a_broken_page(db_session, pages):
    db_session.add_all([
        _company("figma"), _company("opentable", enabled=False), _company("google"),
        # Newest first, so rows the drain may not read would take the limit.
        _owed("opentable", "switched-off", "2001", 0),
        _owed("google", "walled", "3001", 0),
        _at("figma", "cooling", source_facts=_failed_form(datetime.now(UTC) - timedelta(hours=1)),
            structured_at=NOW, first_seen=NOW),
        _owed("figma", "a", "1001", 1),
        _owed("figma", "b", "1002", 2),
        _owed("figma", "c", "1003", 3),
        _owed("figma", "d", "1004", 4),
    ])
    await db_session.commit()
    pages.broken = {"1002"}

    counts = await read_posting_pages(db_session, limit=3)

    assert pages.asked == ["1001", "1002", "1003"]
    assert counts == {"read": 2, "failed": 1, "pay_found": 2, "skipped": 0}
    stored = {
        job.req_id: job for job in (await db_session.scalars(
            select(Job).where(Job.company == "figma").execution_options(populate_existing=True)
        )).all()
    }
    assert stored["a"].source_facts["application_form"]["state"] == "present"
    assert stored["b"].source_facts["application_form"]["state"] == "retrieval_failed"

    # The next run: the broken page is cooling down, the read ones have a band.
    counts = await read_posting_pages(db_session, limit=3)
    assert pages.asked[3:] == ["1004"]
    assert counts == {"read": 1, "failed": 0, "pay_found": 1, "skipped": 0}


@pytest.mark.asyncio
async def test_the_drain_moves_past_pages_that_are_gone(db_session, pages):
    """The drain takes the newest owed rows first. Postings whose page answers
    404, retried every cool-down, would take its limit from the head of the
    queue and leave every older page waiting forever."""
    db_session.add_all([
        _company("figma"),
        _owed("figma", "gone-1", "9001", 0),
        _owed("figma", "gone-2", "9002", 0),
        _owed("figma", "gone-3", "9003", 0),
        _owed("figma", "a", "1001", 1),
        _owed("figma", "b", "1002", 2),
    ])
    await db_session.commit()
    pages.gone = {"9001", "9002", "9003"}

    # Each run a day past the one before: far beyond any cool-down.
    for day in range(1, 4):
        await read_posting_pages(db_session, limit=2, now=datetime.now(UTC) + timedelta(days=day))

    assert sorted(pages.asked) == ["1001", "1002", "9001", "9002", "9003"]
    stored = {
        job.req_id: job.source_facts["application_form"] for job in (await db_session.scalars(
            select(Job).execution_options(populate_existing=True)
        )).all()
    }
    assert stored["gone-1"]["permanent"] is True
    assert stored["a"]["state"] == "present"


@pytest.mark.asyncio
async def test_pages_that_keep_failing_never_starve_older_pages(db_session, pages, monkeypatch):
    """The cool-down is not fairness. On drains further
    apart than `posting_page_retry_hours`, the newest pages failing with a 503
    have all cooled down before every selection, and newest-first would take
    the whole limit with them each time: an older readable page never gets a turn.
    A page never tried goes before one that failed, and failures retry oldest
    attempt first. The 404 is the control: a permanent failure stays unasked."""
    monkeypatch.setattr(get_settings(), "scraper_max_retries", 0)
    db_session.add_all([
        _company("figma"),
        _owed("figma", "down-1", "8001", 0),
        _owed("figma", "down-2", "8002", 0),
        _owed("figma", "gone", "9001", 0),
        _owed("figma", "older-1", "1001", 5),
        _owed("figma", "older-2", "1002", 6),
    ])
    await db_session.commit()
    pages.down, pages.gone = {"8001", "8002"}, {"9001"}

    hours = get_settings().posting_page_retry_hours
    for drain in range(3):
        later = datetime.now(UTC) + timedelta(hours=drain * (hours + 1))
        await read_posting_pages(db_session, limit=3, now=later)

    stored = {
        job.req_id: job.source_facts["application_form"]["state"] for job in (await db_session.scalars(
            select(Job).execution_options(populate_existing=True)
        )).all()
    }
    assert (stored["older-1"], stored["older-2"]) == ("present", "present")
    assert pages.asked.count("9001") == 1, "a page that is gone is asked once"


@pytest.mark.asyncio
async def test_a_listing_scan_between_drains_does_not_make_a_failed_page_owed(db_session, pages):
    db_session.add_all([_company("figma"), _owed("figma", "gone", "9001", 0)])
    await db_session.commit()
    pages.gone = {"9001"}
    await read_posting_pages(db_session, limit=5)

    job = (await db_session.scalars(select(Job).where(Job.req_id == "gone"))).one()
    job.source_facts = merge_source_facts(job.source_facts, _facts(posting_id="9001"))
    await db_session.commit()

    await read_posting_pages(db_session, limit=5, now=datetime.now(UTC) + timedelta(days=3))
    assert pages.asked == ["9001"]


@pytest.mark.parametrize("read", ["form-and-pay", "gone"])
@pytest.mark.asyncio
async def test_a_scan_holding_an_older_copy_never_erases_a_page_read_since(db_session, read):
    """The run's writer caches a company's rows when it starts writing and
    keeps them across its commits. Merging a listing's facts into that copy and
    writing the whole field back would erase a page read committed in between
    (someone opened the posting): its form, its pay tiers, or the failure that
    keeps it from being asked again."""
    from tests.factories import make_enriched
    from tracker.db.models import ScrapeRun
    from tracker.db.repo import load_company_jobs, upsert_job

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    db_session.add_all([_company("figma"), _owed("figma", "b", "6150563004", 1)])
    await db_session.commit()
    failed = RetrievalState.RETRIEVAL_FAILED
    page = (
        PostingPage(_read_form(), pay_tiers(_page("figma")["pay_input_ranges"], NOW))
        if read == "form-and-pay"
        else PostingPage(ApplicationFormFacts.failed(NOW, permanent=True), CompensationFacts(state=failed))
    )

    async with factory() as scan:
        run = ScrapeRun(status="running")
        scan.add(run)
        await scan.commit()
        cached = await load_company_jobs(scan, "figma")
        await scan.commit()  # the writer commits between rows; its copies stay
        async with factory() as reader:
            row = (await reader.scalars(select(Job).where(Job.req_id == "b").with_for_update())).one()
            apply_page(row, page)
            await reader.commit()
        listed = make_enriched(company="figma", req_id="b", title=cached["figma:b"].title)
        listed.raw.source_facts = _facts(posting_id="6150563004", observed_at=NOW + timedelta(hours=1))
        await upsert_job(scan, run, listed, cached)
        await scan.commit()

    stored = (await db_session.scalars(
        select(Job).where(Job.req_id == "b").execution_options(populate_existing=True)
    )).one().source_facts
    assert stored["observed_at"] == (NOW + timedelta(hours=1)).isoformat(), "the listing's facts are written"
    if read == "form-and-pay":
        assert (stored["application_form"]["state"], stored["application_form"]["required"]) == ("present", 5)
        assert stored["compensation"]["tiers"]
    else:
        assert (stored["application_form"]["state"], stored["application_form"]["permanent"]) == (
            "retrieval_failed", True)


@pytest.mark.asyncio
async def test_the_drain_commits_each_posting_and_holds_nothing_across_a_request(db_session, pages):
    db_session.add_all([_company("figma"), _owed("figma", "a", "1001", 1), _owed("figma", "b", "1002", 2)])
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    seen: list[tuple[str | None, int]] = []

    async def look():
        async with factory() as other:
            first = await other.scalar(
                select(Job.source_facts["application_form"]["state"].astext).where(Job.req_id == "a")
            )
            idle = await other.scalar(text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND state = 'idle in transaction'"
            ))
            seen.append((first, idle))

    pages.during = look
    await read_posting_pages(db_session, limit=2)

    # While posting b is asked for, posting a's read is already committed.
    assert seen == [("not_requested", 0), ("present", 0)]


@pytest.mark.asyncio
async def test_a_host_refusing_the_drain_stops_being_asked(db_session, pages, monkeypatch):
    """Two requests end in the same 503 with no Retry-After: the breaker reads
    a block and the drain's third posting is not asked."""
    monkeypatch.setattr(get_settings(), "scraper_max_retries", 0)
    db_session.add_all([_company("figma"), *(_owed("figma", k, f"100{n}", n) for n, k in enumerate("abc"))])
    await db_session.commit()

    def handler(request):
        pages.asked.append(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(503, json={})

    monkeypatch.setattr(
        "tracker.connectors.listing.base.make_tier_client",
        lambda *a, **k: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    counts = await read_posting_pages(db_session, limit=3)

    assert len(pages.asked) == 2
    assert counts == {"read": 0, "failed": 3, "pay_found": 0, "skipped": 0}


@pytest.mark.asyncio
async def test_a_drain_with_nothing_it_may_read_asks_nothing(db_session, pages):
    db_session.add_all([_company("opentable", enabled=False), _owed("opentable", "a", "2001", 1)])
    await db_session.commit()
    assert await read_posting_pages(db_session, limit=5) == {
        "read": 0, "failed": 0, "pay_found": 0, "skipped": 0
    }
    assert await read_posting_pages(db_session, limit=0) == {
        "read": 0, "failed": 0, "pay_found": 0, "skipped": 0
    }
    assert pages.asked == []
