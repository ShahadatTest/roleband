"""extract_disclosed_comp pass — behavior against an injected fake session.

No DB, no model, and no provider either: the pass is deterministic
end to end. A FakeSession records adds/commits and returns the jobs we hand it
(SQL gating is covered separately in test_intelligence_gating).

What these pin: the pre-filter short-circuit, that a band is persisted only when
it is grounded in the FULL posting, that the derived pay basis beats whatever the
posting's wording suggests, that the pass never touches `content_changed_at`, and
that the core commits nothing: the pass loop and backfill own the commits.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from tracker.db.models import AiTaskLog, Job
from tracker.intelligence.extract import EXTRACTOR
from tracker.intelligence_runtime.disclosed_comp import extract_disclosed_comp
from tracker.pay_disclosure import PAY_PARSER_VERSION

# The OTE sentence is guarded by
# "For sales roles," and this role (Program Manager) is not one, so the posting states
# no basis for its band.
JOB1_DESC = (
    "The annual compensation range for this role is listed below.\xa0\n\n"
    "For sales roles, the range provided is the role’s On Target Earnings "
    '("OTE") range, meaning that the range includes both the sales commissions/'
    "sales bonuses target and annual base salary for the role.\n\n"
    "Annual Salary:\n$210,000—$260,000 USD\n\nLogistics\n"
)

# The bonus and equity are additive, so
# the range is base salary even though the sentence lists them together.
GOOGLE_DESC = (
    "Individual pay is determined by factors including job-related skills, "
    "experience, and relevant education or training."
    "US: $240000 - $334000 (USD) + 25% bonus target + equity + benefits"
    "Learn more aboutbenefits at Google."
)
KEYWORDS_AT = datetime(2026, 7, 13, 10, 0, tzinfo=UTC)


class FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return list(self._items)


class FakeSession:
    def __init__(self, jobs):
        self._jobs = jobs
        self.added = []
        self.commits = 0

    async def get(self, model, key):
        return None  # -> get_active_prompt_version falls back to the code default

    async def scalars(self, stmt):
        return FakeScalars(self._jobs)

    async def execute(self, stmt):
        # `owed_ids` reads narrow columns first; the jobs a test
        # hands over are owed exactly as their stamps say.
        class Rows:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return self._rows

        return Rows([
            SimpleNamespace(
                id=j.id,
                locations=j.locations,
                disclosed_place_key=j.disclosed_place_key,
                stale=j.structured_at is None,
            )
            for j in self._jobs
        ])

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1


def _job(job_id, desc, sections=None):
    j = Job()
    j.id = job_id
    j.title = "Program Manager"
    j.description_text = desc
    j.description_sections = sections
    j.content_changed_at = KEYWORDS_AT
    j.structured_at = None
    j.structured_prompt_version = None
    return j


def _logs(session):
    return [o for o in session.added if isinstance(o, AiTaskLog)]


def _run(jobs, ids=None):
    session = FakeSession(jobs)
    summary = asyncio.run(extract_disclosed_comp(session, ids or [j.id for j in jobs], page_band=None))
    return session, summary


# --------------------------------------------------------------------------- #
# Core outcomes
# --------------------------------------------------------------------------- #


def test_prefilter_miss_marks_processed_without_scanning():
    job = _job(1, "Lead cross-functional programs. No pay stated here.")
    session, summary = _run([job])

    assert summary["prefiltered"] == 1
    assert summary["disclosed"] == 0
    assert job.structured_at is not None  # processed as "none disclosed"
    assert job.disclosed_base_min is None
    assert job.content_changed_at == KEYWORDS_AT  # never touched
    assert _logs(session)[0].meta.get("prefiltered") is True


def test_grounded_success_persists_band():
    job = _job(1, JOB1_DESC)
    session, summary = _run([job])

    assert summary["disclosed"] == 1
    assert job.disclosed_base_min == 210000
    assert job.disclosed_base_max == 260000
    assert job.disclosed_currency == "USD"
    # The posting's only inclusive language is the "For sales roles" boilerplate,
    # which does not apply to this Program Manager role.
    assert job.disclosed_pay_basis == "unclear"
    assert job.structured_at is not None
    # Stamped for the gate with the parser's version, not the prompt's.
    assert job.structured_prompt_version == PAY_PARSER_VERSION
    assert job.disclosed_source == "text"
    assert job.content_changed_at == KEYWORDS_AT  # pass never bumps content_changed_at
    row = _logs(session)[0]
    assert row.validation_result == "ok"
    assert row.meta.get("disclosed") is True


def test_the_text_band_the_posting_defines_per_kind_of_role_follows_the_role():
    """The same Anthropic posting: with no family the band stays unclear (above);
    a program manager's is base and a sales role's total."""
    program = _job(1, JOB1_DESC)
    program.family = "program_management"
    sales = _job(2, JOB1_DESC)
    sales.family, sales.title = "sales_business_development", "Sales Manager, Nonprofit, EMEA"
    _run([program, sales])
    assert (program.disclosed_pay_basis, sales.disclosed_pay_basis) == ("base", "total")
    assert program.disclosed_source == sales.disclosed_source == "text"


def test_rows_are_attributed_to_the_deterministic_extractor():
    """Telemetry must not silently merge these into the historical model rows —
    Settings compares providers, and 'which ran' is the whole question."""
    session, _ = _run([_job(1, JOB1_DESC)])
    assert _logs(session)[0].provider == EXTRACTOR == "deterministic"


def test_additive_google_band_persists_as_base():
    """The derived basis reaches the DB columns. Bonus and equity are listed as
    additions to the range, so the range itself is base salary."""
    job = _job(1, GOOGLE_DESC)
    _, summary = _run([job])

    assert summary["disclosed"] == 1
    assert job.disclosed_base_min == 240000 and job.disclosed_base_max == 334000
    assert job.disclosed_pay_basis == "base"


def test_empty_job_ids_is_noop():
    session = FakeSession([])
    summary = asyncio.run(extract_disclosed_comp(session, [], page_band=None))
    assert summary["processed"] == 0
    assert session.commits == 0


def test_the_extraction_commits_nothing_of_its_own():
    """The core writes; the pass loop and the backfill's batches
    commit (`test_disclosed_comp_backfill_db` holds the batches)."""
    jobs = [_job(1, JOB1_DESC), _job(2, GOOGLE_DESC), _job(3, "no pay here")]
    session, summary = _run(jobs)
    assert summary["processed"] == 3
    assert session.commits == 0


# --------------------------------------------------------------------------- #
# Input selection and grounding
# --------------------------------------------------------------------------- #


def test_pay_section_is_the_input_but_full_text_still_grounds():
    pay = "The base pay range for this role is between $184,700 and $324,800 per year."
    job = _job(
        1,
        f"Long unrelated job description.\n\nPay & Benefits\n{pay}",
        sections=[
            {"key": "description", "title": "Description", "content": "Long unrelated job description."},
            {"key": "pay_and_benefits", "title": "Pay & Benefits", "content": pay},
        ],
    )
    session, summary = _run([job])

    assert summary["disclosed"] == 1
    assert job.disclosed_base_min == 184700 and job.disclosed_base_max == 324800
    assert _logs(session)[0].meta["input_scope"] == "pay_section"


def test_a_band_only_in_the_section_and_absent_from_the_posting_is_refused():
    """The grounding gate is what makes a missed band the only failure mode. A
    section that disagrees with the stored posting must not produce a band."""
    job = _job(
        1,
        "Lead product. Compensation is competitive and salary is reviewed yearly.",
        sections=[
            {
                "key": "pay_and_benefits",
                "title": "Pay",
                "content": "The salary range is $440,000 - $725,000.",
            }
        ],
    )
    _, summary = _run([job])

    assert summary["disclosed"] == 0
    assert job.disclosed_base_min is None
    assert job.structured_at is not None, "still processed; must not loop forever"


def test_a_posting_whose_only_money_is_not_pay_yields_no_band():
    """Passes the pre-filter (it has currency-shaped text) and must still be
    read as disclosing nothing."""
    job = _job(
        1,
        "You will manage datacenter construction projects ranging from "
        "$250,000 to $100 million, and own the delivery schedule.",
    )
    _, summary = _run([job])

    assert summary["prefiltered"] == 0, "the pre-filter let this through"
    assert summary["disclosed"] == 0
    assert job.disclosed_base_min is None


# --------------------------------------------------------------------------- #
# Band formats from real postings
# --------------------------------------------------------------------------- #


def test_amazon_band_without_a_currency_symbol_is_extracted():
    pay = "USA, NY, New York - 126,900.00 - 181,400.00 USD annually"
    job = _job(
        1,
        f"Amazon Operations sits at the heart of the customer experience.\n\n{pay}",
        sections=[{"key": "pay_and_benefits", "title": "Pay", "content": pay}],
    )
    _, summary = _run([job])

    assert summary["disclosed"] == 1
    assert job.disclosed_base_min == 126900 and job.disclosed_base_max == 181400
    assert job.disclosed_currency == "USD"


def test_nvidia_band_with_trailing_currency_codes_is_extracted():
    job = _job(
        1,
        "You will build accelerated systems. Your base salary will be determined "
        "based on your location and experience. The base salary range is "
        "168,000 USD - 258,750 USD. You will also be eligible for equity.",
    )
    _, summary = _run([job])

    assert summary["disclosed"] == 1
    assert job.disclosed_base_min == 168000 and job.disclosed_base_max == 258750


def test_a_two_level_posting_never_stores_a_merged_range():
    """A model can return the low bound of the Level 4 band with the high bound
    of the Level 5 band, a range printed nowhere in the posting. Whatever is stored must be one real band."""
    job = _job(
        1,
        "The base salary range is 168,000 USD - 258,750 USD for Level 4, and "
        "200,000 USD - 322,000 USD for Level 5. You will also be eligible for equity.",
    )
    _, summary = _run([job])

    assert summary["disclosed"] == 1
    stored = (job.disclosed_base_min, job.disclosed_base_max)
    assert stored != (168000, 322000), "merged across two level bands"
    assert stored in {(168000, 258750), (200000, 322000)}


def test_a_band_in_any_currency_the_parser_reads_reaches_the_parser():
    """The parser reads 23 currency codes, and the pass's pre-filter must let
    every one through: otherwise these postings are marked processed with no
    band before the parser runs. Through the whole pass, with the USD control
    beside them and a posting with no money as the negative."""
    jobs = [
        _job(1, "Base: SEK 900000 - 1200000 per year."),
        _job(2, "Range CHF 120000 - 150000 per annum."),
        _job(3, "Monthly PLN 18000 - 24000 per month."),
        _job(4, "Range USD 150000 - 200000 per year."),
        _job(5, "Lead cross-functional programs across 12 countries."),
    ]
    _, summary = _run(jobs)

    stated = {j.id: (j.disclosed_base_min, j.disclosed_base_max, j.disclosed_currency) for j in jobs}
    assert stated == {
        1: (900_000, 1_200_000, "SEK"),
        2: (120_000, 150_000, "CHF"),
        3: (18_000, 24_000, "PLN"),
        4: (150_000, 200_000, "USD"),
        5: (None, None, None),
    }
    assert summary["prefiltered"] == 1
