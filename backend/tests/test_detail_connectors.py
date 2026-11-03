"""Shared detail-connector contract used by every built-in company."""

import pytest

from tracker.connectors.detail import DETAIL_CONNECTORS, get_detail_connector, structure_job_detail
from tracker.connectors.detail.amazon import AmazonDetailConnector
from tracker.connectors.detail.anthropic import AnthropicDetailConnector
from tracker.connectors.detail.apple import AppleDetailConnector
from tracker.connectors.detail.ashby import AshbyDetailConnector
from tracker.connectors.detail.atlassian import AtlassianDetailConnector
from tracker.connectors.detail.base import (
    HtmlDetailConnector,
    promote_section,
    sections_to_text,
)
from tracker.connectors.detail.base import section_key as _section_key
from tracker.connectors.detail.google import GoogleDetailConnector
from tracker.connectors.detail.lever import LeverDetailConnector
from tracker.connectors.detail.microsoft import MicrosoftDetailConnector
from tracker.connectors.detail.netflix import NetflixDetailConnector
from tracker.connectors.detail.openai import OpenAIDetailConnector
from tracker.connectors.detail.tiktok import TikTokDetailConnector
from tracker.connectors.detail.workday import WorkdayDetailConnector
from tracker.connectors.listing.base import SchemaDriftDetector
from tracker.connectors.listing.google import GoogleAdapter
from tracker.db.models import Job, JobSkillEvidence
from tracker.db.repo import _apply_fields
from tracker.pay_disclosure import PayBasis, derive_pay_basis
from tracker.schema import (
    EnrichedJob,
    JobDescriptionSection,
    LevelBand,
    LevelConfidence,
    RawJob,
    SourceDisclosedComp,
)


def test_every_builtin_company_has_an_independent_connector_entry():
    assert set(DETAIL_CONNECTORS) == {
        "amazon", "apple", "google", "netflix", "openai", "anthropic",
        "nvidia", "microsoft", "spotify",
    }
    assert isinstance(DETAIL_CONNECTORS["amazon"], AmazonDetailConnector)
    assert isinstance(DETAIL_CONNECTORS["google"], GoogleDetailConnector)
    assert isinstance(DETAIL_CONNECTORS["netflix"], NetflixDetailConnector)
    assert isinstance(DETAIL_CONNECTORS["openai"], OpenAIDetailConnector)
    assert isinstance(DETAIL_CONNECTORS["anthropic"], AnthropicDetailConnector)
    assert isinstance(DETAIL_CONNECTORS["microsoft"], MicrosoftDetailConnector)
    # Nvidia is a Workday company; its detail entry is the shared Workday parser.
    assert isinstance(DETAIL_CONNECTORS["nvidia"], WorkdayDetailConnector)


def test_connector_registry_supports_company_override_and_ats_fallback():
    assert isinstance(get_detail_connector("openai", "ashby"), OpenAIDetailConnector)
    assert get_detail_connector("notion", "ashby").source == "ashby"
    assert get_detail_connector("stripe", "greenhouse").source == "greenhouse"


def test_html_connector_preserves_source_headings_and_content_order():
    result = HtmlDetailConnector().parse_html(
        "<h2>About the role</h2><p>Build reliable systems.</p>"
        "<h2>Qualifications</h2><ul><li>10+ years experience</li></ul>"
    )
    assert [(section.title, section.content) for section in result.sections] == [
        ("About the role", "Build reliable systems."),
        ("Qualifications", "10+ years experience"),
    ]
    assert sections_to_text(result.sections) == (
        "About the role\nBuild reliable systems.\n\n"
        "Qualifications\n10+ years experience"
    )


def test_html_connector_keeps_unstructured_posting_as_one_section():
    result = HtmlDetailConnector().parse_html("<p>One complete posting body.</p>")
    assert result.mode == "primary"
    assert [(section.key, section.content) for section in result.sections] == [
        ("job_description", "One complete posting body.")
    ]


def test_google_connector_recovers_flattened_headings_and_isolates_pay():
    raw = (
        "About the jobBuild products used worldwide. Individual pay is determined by experience."
        "US: $192000 - $279000 (USD) + 20% bonus target + equity + benefits"
        "Minimum qualifications:Bachelor's degree.8 years of experience."
        "Preferred qualifications:Cloud product experience."
        "ResponsibilitiesLead launches and customer discovery."
    )
    result = GoogleDetailConnector().parse_html(raw)

    assert result.mode == "primary"
    assert [section.key for section in result.sections] == [
        "about_the_job",
        "pay_and_benefits",
        "minimum_qualifications",
        "preferred_qualifications",
        "responsibilities",
    ]
    assert result.sections[1].content.endswith("+ equity + benefits")
    assert "$192000 - $279000" not in result.sections[0].content
    assert result.source_disclosed_comp is not None
    assert result.source_disclosed_comp.base_min == 192000
    assert result.source_disclosed_comp.base_max == 279000
    assert result.source_disclosed_comp.pay_basis == "base"
    assert result.source_disclosed_comp.bonus_pct == 0.20


# The shape of a Google careers detail page: each section is a block opened by
# an <h3>, both qualifications headings share one block that starts with a
# location tooltip, and "About the job" breaks paragraphs with raw newlines
# inside one text node.
_GOOGLE_DETAIL_PAGE = """<html><head>
<meta name="description" content="Meta description fallback.">
</head><body><div class="DkhPwc"><span><div>
<div class="KwJkGe"><div class="tip"><i>info_outline</i><span>X</span>
<span>In most instances, this position requires in-person interviews.</span></div><br/>
<h3>Minimum qualifications:</h3><ul>
<li>Bachelor's degree, or equivalent practical experience.<br></li>
<li>8 years of experience in software development.<br></li>
</ul><br/><h3>Preferred qualifications:</h3><ul>
<li>Experience with Node.js and Go, e.g., in U.S. data centers.</li>
<li>3.5 years of experience in a matrixed organization.</li>
</ul></div>
<div class="aG5W3"><h3>About the job</h3>As a manager, you guide the way.

With technical expertise, you lead teams across sites.
As a Software Engineering Manager, you grow the team.<br/><br/>
Individual pay is determined by experience.<br/>
US: $207000 - $300000 (USD) + 20% bonus target + equity + benefits<br/>
Learn more about <a href="https://example.com/benefits">benefits at Google</a>.</div>
<div class="BDNOWe"><h3>Responsibilities</h3><ul>
<li>Set team priorities across teams.<br></li>
<li>Set clear expectations with individuals.<br></li>
</ul></div>
</div></span></div></body></html>"""


def test_google_detail_page_keeps_sentence_and_bullet_boundaries():
    raw = GoogleAdapter("google")._extract_description(_GOOGLE_DETAIL_PAGE)
    result = GoogleDetailConnector().parse_html(raw)
    sections = {section.key: section.content for section in result.sections}

    assert result.mode == "primary"
    assert [section.key for section in result.sections] == [
        "minimum_qualifications",
        "preferred_qualifications",
        "about_the_job",
        "pay_and_benefits",
        "responsibilities",
    ]
    # Paragraphs and bullets stay apart instead of running together.
    assert "you guide the way.\n\nWith technical expertise" in sections["about_the_job"]
    assert "the way.With" not in sections["about_the_job"]
    assert [line for line in sections["minimum_qualifications"].split("\n") if line] == [
        "Bachelor's degree, or equivalent practical experience.",
        "8 years of experience in software development.",
    ]
    assert "across teams.\n" in sections["responsibilities"]
    assert "Learn more about benefits at Google." in sections["pay_and_benefits"]
    # Dots inside a sentence are the source's own and come through unchanged.
    assert "Experience with Node.js and Go, e.g., in U.S. data centers." in sections["preferred_qualifications"]
    assert "3.5 years of experience" in sections["preferred_qualifications"]
    # The tooltip in front of the qualifications is page chrome, not posting text.
    assert not any("info_outline" in text or "in-person" in text for text in sections.values())
    assert result.source_disclosed_comp is not None
    assert result.source_disclosed_comp.base_min == 207000
    assert result.source_disclosed_comp.base_max == 300000


def test_google_pay_boilerplate_joined_to_the_blurb_starts_its_own_section():
    # Google's markup has no tag or space between the blurb's last sentence and
    # its pay boilerplate.
    page = """<html><body><div>
<div><h3>About the job</h3>We build with Node.js, e.g., for U.S. teams at 3.5x scale.<br><br>
Our teams offer career pathways for those driven to achieve results through collective effort.Individual pay is determined by factors including job-related skills.  <br><br>
US: $217000 - $236000 (USD) + 15% bonus target + equity + benefits<br><br>
Learn more about <a href="https://example.com/benefits">benefits at Google</a>.</div>
<div><h3>Responsibilities</h3><ul><li>Lead launches.</li></ul></div>
</div></body></html>"""

    result = GoogleDetailConnector().parse_html(GoogleAdapter("google")._extract_description(page))
    sections = {section.key: section.content for section in result.sections}

    assert sections["pay_and_benefits"].startswith("Individual pay is determined by factors")
    assert sections["about_the_job"].endswith("through collective effort.")
    assert "collective effort" not in sections["pay_and_benefits"]
    # Only the boilerplate seam is split; the source's own dots stay where they are.
    assert "We build with Node.js, e.g., for U.S. teams at 3.5x scale." in sections["about_the_job"]
    assert result.source_disclosed_comp is not None
    assert (result.source_disclosed_comp.base_min, result.source_disclosed_comp.base_max) == (217000, 236000)
    assert result.source_disclosed_comp.bonus_pct == 0.15


def test_another_company_on_googles_board_is_parsed_by_the_google_connector():
    # google-deepmind collects through the google adapter but has no company
    # entry of its own; the generic parser neither isolates Google's pay block
    # nor splits its boilerplate seam.
    assert isinstance(get_detail_connector("google-deepmind", "google"), GoogleDetailConnector)
    job = RawJob(
        company="google-deepmind",
        req_id="1",
        title="Product Manager",
        url="https://example.test/job/1",
        description_html=GoogleAdapter("google")._extract_description(
            """<html><body><div><div><h3>About the job</h3>We work through collective
effort.Individual pay is determined by factors including skills.<br><br>
US: $217000 - $236000 (USD) + 15% bonus target + equity + benefits<br><br></div>
<div><h3>Responsibilities</h3><ul><li>Lead launches.</li></ul></div></div></body></html>"""
        ),
    )

    structure_job_detail(job, SchemaDriftDetector("google:google-deepmind"), source="google")

    sections = {section.key: section.content for section in job.description_sections}
    assert sections["pay_and_benefits"].startswith("Individual pay is determined")
    assert sections["about_the_job"].endswith("effort.")
    assert "collective" not in sections["pay_and_benefits"]
    assert job.source_disclosed_comp is not None
    assert (job.source_disclosed_comp.base_min, job.source_disclosed_comp.base_max) == (217000, 236000)


def test_google_detail_page_without_section_headings_falls_back_to_meta_description():
    page = '<html><head><meta name="description" content="Meta only."></head><body><p>Hi</p></body></html>'

    assert GoogleAdapter("google")._extract_description(page) == "Meta only."


def test_netflix_connector_preserves_bold_sections_and_isolates_compensation():
    raw = (
        "<p>Netflix opening.</p><p><b>The Role</b></p><p>Lead the product.</p>"
        "<p><b>What We Offer</b></p><p>Meaningful impact.</p>"
        "<p>Generally, our compensation structure consists solely of an annual salary; "
        "we do not have bonuses. You choose each year how much of your compensation "
        "you want in salary versus stock options. "
        "the range for this role is $440,000.00 - $725,000.00.</p>"
        "<p>Netflix provides comprehensive benefits including Health Plans and a 401(k).</p>"
        "<p>Netflix is a unique culture and environment.</p>"
    )
    result = NetflixDetailConnector().parse_html(raw)

    assert result.mode == "primary"
    assert [section.title for section in result.sections] == [
        "Job description",
        "The Role",
        "What We Offer",
        "Compensation & Benefits",
    ]
    pay = result.sections[-1]
    assert pay.key == "pay_and_benefits"
    assert "$440,000.00 - $725,000.00" in pay.content
    assert "comprehensive benefits" in pay.content
    assert "$440,000.00" not in result.sections[-2].content
    assert result.source_disclosed_comp is not None
    assert result.source_disclosed_comp.base_min == 440000
    assert result.source_disclosed_comp.base_max == 725000
    assert result.source_disclosed_comp.pay_basis == "total"


def test_openai_connector_adds_ashby_structured_compensation_not_present_in_description():
    payload = {
        "descriptionHtml": "<h3>About the Role</h3><p>Secure our systems.</p>",
        "shouldDisplayCompensationOnJobPostings": True,
        "compensation": {
            "compensationTierSummary": "$293K - $385K • Offers Equity",
            "scrapeableCompensationSalarySummary": "$293K - $385K",
            "summaryComponents": [
                {
                    "compensationType": "Salary",
                    "interval": "1 YEAR",
                    "currencyCode": "USD",
                    "minValue": 293000,
                    "maxValue": 385000,
                }
            ],
        },
    }
    result = OpenAIDetailConnector().parse_payload(payload, payload["descriptionHtml"])

    assert result.mode == "primary"
    assert [(section.key, section.title) for section in result.sections] == [
        ("about_the_role", "About the Role"),
        ("pay_and_benefits", "Compensation"),
    ]
    assert result.sections[-1].content == (
        "Base salary range: $293K - $385K USD per year\nEquity: Offers equity."
    )
    assert result.source_disclosed_comp is not None
    assert result.source_disclosed_comp.base_min == 293000
    assert result.source_disclosed_comp.base_max == 385000
    assert result.source_disclosed_comp.pay_basis == "base"
    assert result.source_disclosed_comp.pay_period == "year"


def test_anthropic_connector_extracts_greenhouse_pay_transparency_block():
    raw = (
        "&lt;h2&gt;About the Role&lt;/h2&gt;&lt;p&gt;Build safe systems.&lt;/p&gt;"
        "&lt;div class=&quot;content-pay-transparency&quot;&gt;"
        "&lt;p&gt;The annual compensation range for this role is listed below.&lt;/p&gt;"
        "&lt;div class=&quot;title&quot;&gt;Annual Salary:&lt;/div&gt;"
        "&lt;div class=&quot;pay-range&quot;&gt;&lt;span&gt;$405,000&lt;/span&gt;"
        "&lt;span&gt;&amp;mdash;&lt;/span&gt;&lt;span&gt;$485,000 USD&lt;/span&gt;&lt;/div&gt;&lt;/div&gt;"
        "&lt;h2&gt;Logistics&lt;/h2&gt;&lt;p&gt;Hybrid role.&lt;/p&gt;"
    )
    result = AnthropicDetailConnector().parse_html(raw)

    assert result.mode == "primary"
    assert [section.key for section in result.sections] == [
        "about_the_role",
        "pay_and_benefits",
        "logistics",
    ]
    assert "$405,000" in result.sections[1].content
    assert "$485,000 USD" in result.sections[1].content
    assert result.source_disclosed_comp is not None
    assert result.source_disclosed_comp.base_min == 405000
    assert result.source_disclosed_comp.base_max == 485000


def test_apple_connector_promotes_pay_footer_base_range():
    payload = {
        "res": {
            "selectedLocale": "en_US",
            "jobSummary": "Lead product strategy.",
            "description": "Build learning systems.",
            "minimumQualifications": "10 years of PM experience.",
            "preferredQualifications": "AI experience.",
            "postingFooters": [
                {
                    "localizations": {
                        "en_US": [
                            {
                                "displayOrder": 1,
                                "name": "Pay & Benefits",
                                "content": (
                                    "Base pay: $250,800 - $376,300. "
                                    "Apple employees also have the opportunity to become shareholders."
                                ),
                            }
                        ]
                    }
                }
            ],
        }
    }

    result = AppleDetailConnector().parse_payload(payload)

    assert [section.key for section in result.sections][-1] == "pay_and_benefits"
    assert result.source_disclosed_comp is not None
    assert result.source_disclosed_comp.base_min == 250800
    assert result.source_disclosed_comp.base_max == 376300
    assert result.source_disclosed_comp.pay_basis == "base"


def test_amazon_connector_builds_field_sections_and_grounds_geographic_market_pay():
    payload = {
        "description": (
            "Build large-scale systems.<br/><br/>Our compensation reflects the cost of "
            "labor across several US geographic markets. The base pay for this position "
            "ranges from $151,300/year in our lowest geographic market up to "
            "$261,500/year in our highest geographic market. Pay is based on a number of "
            "factors. Amazon is a total compensation company. Dependent on the position "
            "offered, equity and sign-on payments may be provided."
        ),
        "basic_qualifications": "- 8+ years of experience<br/>- Distributed systems",
        "preferred_qualifications": "- AWS experience",
    }
    result = AmazonDetailConnector().parse_payload(payload, payload["description"])

    assert result.mode == "primary"
    assert [section.key for section in result.sections] == [
        "job_description",
        "pay_and_benefits",
        "basic_qualifications",
        "preferred_qualifications",
    ]
    pay = result.sections[1]
    assert "geographic market" in pay.content
    assert "$151,300" not in result.sections[0].content
    assert result.source_disclosed_comp is not None
    assert result.source_disclosed_comp.base_min == 151300
    assert result.source_disclosed_comp.base_max == 261500
    assert result.source_disclosed_comp.currency == "USD"
    assert result.source_disclosed_comp.pay_basis == "base"
    assert result.source_disclosed_comp.pay_period == "year"


def test_amazon_connector_promotes_listed_salary_from_preferred_qualifications():
    """Amazon's newer transparency form puts an unsigned USD band after the JD."""
    payload = {
        "description": "Lead the wireless systems engineering team.",
        "basic_qualifications": "- 10+ years of experience",
        "preferred_qualifications": (
            "- Deep wireless systems design experience\n\n"
            "The base salary range for this position is listed below. Your Amazon package "
            "will include sign-on payments and restricted stock units (RSUs). Final "
            "compensation depends on experience, qualifications, and location.\n\n"
            "USA, CA, Sunnyvale - 206,600.00 - 279,600.00 USD annually"
        ),
    }

    result = AmazonDetailConnector().parse_payload(payload, payload["description"])

    assert [section.key for section in result.sections] == [
        "job_description",
        "basic_qualifications",
        "preferred_qualifications",
        "pay_and_benefits",
    ]
    pay = result.sections[-1]
    assert "206,600.00 - 279,600.00 USD annually" in pay.content
    assert "206,600.00" not in result.sections[2].content
    assert result.source_disclosed_comp is not None
    assert result.source_disclosed_comp.base_min == 206600
    assert result.source_disclosed_comp.base_max == 279600
    assert result.source_disclosed_comp.currency == "USD"
    assert result.source_disclosed_comp.pay_basis == "base"
    assert result.source_disclosed_comp.pay_period == "year"


def test_amazon_connector_without_pay_block_discloses_nothing():
    payload = {
        "description": "Own the roadmap for a global product. No pay statement here.",
        "basic_qualifications": "- 10 years of PM experience",
        "preferred_qualifications": None,
    }
    result = AmazonDetailConnector().parse_payload(payload, payload["description"])

    assert result.mode == "primary"
    assert [section.key for section in result.sections] == [
        "job_description",
        "basic_qualifications",
    ]
    assert result.source_disclosed_comp is None


# A
# preferred-qualifications list, then the pay paragraph as one <p>, then boilerplate.
# The band the scanner grounds on ($155,800-$277,200) is stated 15 characters into the
# sentence that says what it is, so a quote padded by 50 characters starts INSIDE the
# word "base".
_MICROSOFT_SEVERED_BASE_HTML = (
    "<b>Overview</b><p>Lead the Business Analytics organization.</p>"
    "<b>Qualifications</b>"
    "<ul><li>5+ years people management experience.</li>"
    "<li>Experience with Fabric, PowerBI and/or equivalent data platforms. </li></ul>"
    "<p><span>#CEAIjobs</span></p> <br><br>"
    "<p>Business Analytics M6 - The typical base pay range for this role across the "
    "U.S. is USD $155,800 - $277,200 per year. There is a different range applicable "
    "to specific work locations, within the San Francisco Bay area and New York City "
    "metropolitan area, and the base pay range for this role in those locations is "
    "USD $202,400 - $303,600 per year. </p><p></p> "
    "<p>Certain roles may be eligible for benefits and other compensation.</p>"
)


def test_microsoft_pay_promotion_keeps_the_sentence_that_says_the_band_is_base():
    """Promotion must not cut the pay sentence in half.

    Carving the padded quote out of the body would sever "The typical bas|e pay
    range", and because `description_text` is rebuilt FROM the sections the intact
    sentence would then exist nowhere at all, so the later basis pass, reading the
    stored text, could only answer `unclear`.
    """
    result = MicrosoftDetailConnector().parse_html(_MICROSOFT_SEVERED_BASE_HTML)
    pay = next(s for s in result.sections if s.key == "pay_and_benefits")

    assert "The typical base pay range" in pay.content
    assert "$155,800 - $277,200" in pay.content
    # ...and the body it came out of keeps whole words, not the "bas" stump.
    body = next(s for s in result.sections if s.key == "qualifications")
    assert "bas" not in body.content.split()
    assert not body.content.rstrip().endswith("The typical bas")

    stored_text = sections_to_text(result.sections)
    assert "The typical base pay range" in stored_text
    assert derive_pay_basis(stored_text, [155_800, 277_200]) is PayBasis.base


def test_promotion_does_not_grow_past_the_nearest_sentence_boundary():
    """The grown carve is bounded twice over: it stops at the first sentence boundary,
    and where a run-on block offers none within `_CARVE_PAD_MAX` it does not grow at
    all. Without both bounds a section with no blank line in it is one "paragraph" and
    the whole posting body migrates into Compensation."""
    run_on = "unbroken clause about the team and the roadmap and the platform " * 8
    section = JobDescriptionSection(
        "job_description",
        "Job description",
        f"Team background. {run_on}Pay: $100,000 - $120,000. {run_on}More prose.",
    )
    promoted = JobDescriptionSection(
        "pay_and_benefits", "Compensation", "Pay: $100,000 - $120,000."
    )

    result = promote_section([section], promoted)

    assert [s.key for s in result] == ["job_description", "pay_and_benefits"]
    assert result[1].content == "Pay: $100,000 - $120,000."
    assert result[0].content.startswith("Team background.")
    assert result[0].content.endswith("More prose.")
    assert "$100,000" not in result[0].content


def test_a_promoted_block_spanning_two_sections_keeps_both_halves():
    """Amazon's pay block is matched against the CONCATENATION of its three source
    fields, so the declaration can sit in one section and the market line in another.
    Only the first matching section is carved; the half that lives elsewhere must still
    reach the Compensation section, or the promotion loses the sentence that says what
    the band is — the same loss, by a different route, as the severed carve."""
    sections = [
        JobDescriptionSection(
            "job_description",
            "Job description",
            "Own the roadmap.\n\nThe base salary range for this position is listed below.",
        ),
        JobDescriptionSection(
            "preferred_qualifications",
            "Preferred Qualifications",
            "10 years of PM experience.\n\nUSA, NY, New York - 169,000.00 - 228,600.00 USD annually",
        ),
    ]
    promoted = JobDescriptionSection(
        "pay_and_benefits",
        "Compensation",
        "The base salary range for this position is listed below.\n\n"
        "USA, NY, New York - 169,000.00 - 228,600.00 USD annually",
    )

    result = promote_section(sections, promoted)
    pay = next(s for s in result if s.key == "pay_and_benefits")

    assert "The base salary range for this position is listed below." in pay.content
    assert "169,000.00 - 228,600.00 USD annually" in pay.content
    assert derive_pay_basis(sections_to_text(result), [169000, 228600]) is PayBasis.base


def test_source_schema_change_uses_failover_and_records_drift():
    job = RawJob(
        company="netflix",
        req_id="123",
        title="Director",
        url="https://example.test/job/123",
        description_html="<p>A complete but newly formatted posting.</p>",
    )
    drift = SchemaDriftDetector("eightfold:netflix")

    structure_job_detail(job, drift, source="eightfold")

    assert job.description_sections[0].content == "A complete but newly formatted posting."
    assert drift.alerts[-1]["message"] == "job detail connector entered failover mode"
    assert drift.alerts[-1]["company"] == "netflix"


@pytest.mark.parametrize("connector", [
    AshbyDetailConnector(), AtlassianDetailConnector(), LeverDetailConnector(),
    NetflixDetailConnector(), TikTokDetailConnector(),
], ids=lambda connector: connector.source)
def test_a_payload_of_the_wrong_shape_is_read_from_the_posting_html_as_failover(connector):
    """Every connector that reads a structured payload falls back the same way
    when the payload is not that shape: the HTML the posting holds, surfaced as
    failover. A read that recovered the text is as complete as that text; one
    that found nothing never claims the posting has none."""
    html = "<h2>The role</h2><p>Lead the platform.</p><h2>About you</h2><p>Ten years.</p>"
    read = connector.parse_payload(["not", "an", "object"], html)
    assert read.mode == "failover" and read.reason
    assert [s.content for s in read.sections] == ["Lead the platform.", "Ten years."]
    assert read.complete

    empty = connector.parse_payload(["not", "an", "object"], None)
    assert empty.mode == "failover" and empty.sections == []
    assert not empty.complete


def _enriched(raw: RawJob) -> EnrichedJob:
    return EnrichedJob(
        raw=raw,
        level_band=LevelBand.STAFF,
        level_confidence=LevelConfidence.CONFIRMED,
        family="product_management",
        location_groups=["silicon_valley"],
    )


@pytest.mark.parametrize("family, title, basis", [
    ("product_management", "Principal Product Manager, Adobe Express", "base"),
    ("sales_business_development", "Enterprise Account Executive", "total"),
    ("solutions_sales_eng", "Manager, Forward Deployed Engineering", "unclear"),
])
def test_a_connector_band_the_posting_defines_per_kind_of_role_follows_the_role(family, title, basis):
    """Adobe's connector band says only "pay range"; the posting defines it per kind of
    role two paragraphs away, and the connector writer settles it by the role."""
    raw = RawJob(
        company="adobe", req_id="R1", title=title, url="https://careers.example.test/R1",
        description_html=(
            "<p>The U.S. pay range for this position is $148,100 - $282,100 annually.</p>"
            "<p>At Adobe, for sales roles starting salaries are expressed as total target "
            "compensation (TTC = base + commission), and short-term incentives are in the form "
            "of sales commission plans. Non-sales roles starting salaries are expressed as base "
            "salary and short-term incentives are in the form of the Annual Incentive Plan (AIP).</p>"
        ),
        source_disclosed_comp=SourceDisclosedComp(
            base_min=148_100, base_max=282_100, currency="USD", pay_basis="unclear", pay_period="year",
        ),
    )
    job = Job()
    _apply_fields(job, EnrichedJob(raw=raw, level_band=LevelBand.PRINCIPAL,
                                   level_confidence=LevelConfidence.CONFIRMED, family=family,
                                   location_groups=["united_states"]))
    assert job.disclosed_source == "connector"
    assert job.disclosed_pay_basis == basis


def test_incomplete_failover_does_not_downgrade_existing_full_description():
    job = Job()
    job.id = 745
    job.description_html = "<h2>Pay & Benefits</h2><p>Base pay: $250,800-$376,300.</p>"
    job.description_text = "Pay & Benefits\nBase pay: $250,800-$376,300."
    job.description_sections = [
        {"key": "pay_and_benefits", "title": "Pay & Benefits", "content": "Base pay."}
    ]
    raw = RawJob(
        company="apple",
        req_id="200646926-0836",
        title="Head of Product",
        url="https://jobs.apple.com/example",
        description_html="Short search summary.",
        description_complete=False,
    )

    _apply_fields(job, _enriched(raw))

    assert "$250,800-$376,300" in (job.description_text or "")
    assert job.description_sections[0]["key"] == "pay_and_benefits"


def test_incomplete_failover_is_kept_for_a_new_job_with_no_prior_detail():
    job = Job()
    raw = RawJob(
        company="apple",
        req_id="new-role",
        title="New role",
        url="https://jobs.apple.com/new-role",
        description_html="Short search summary.",
        description_complete=False,
    )

    _apply_fields(job, _enriched(raw))

    assert job.description_text == "Short search summary."


def test_source_disclosed_comp_is_promoted_into_persisted_disclosed_columns():
    raw = RawJob(
        company="openai",
        req_id="33b8effb-b048-4934-a279-87fff192a330",
        title="Product Manager, Core Models",
        url="https://jobs.ashbyhq.com/openai/33b8effb-b048-4934-a279-87fff192a330",
    )
    payload = {
        "descriptionHtml": "<h3>About the Role</h3><p>Build model products.</p>",
        "shouldDisplayCompensationOnJobPostings": True,
        "compensation": {
            "compensationTierSummary": "$347K - $490K • Offers Equity",
            "scrapeableCompensationSalarySummary": "$347K - $490K",
            "summaryComponents": [
                {
                    "compensationType": "Salary",
                    "interval": "1 YEAR",
                    "currencyCode": "USD",
                    "minValue": 347000,
                    "maxValue": 490000,
                },
                {"compensationType": "EquityCashValue", "summary": "Offers Equity"},
            ],
        },
    }
    drift = SchemaDriftDetector("ashby:openai")
    structure_job_detail(raw, drift, payload=payload, source="ashby")
    job = Job()

    _apply_fields(job, _enriched(raw))

    assert job.disclosed_base_min == 347000
    assert job.disclosed_base_max == 490000
    assert job.disclosed_pay_basis == "base"
    assert job.disclosed_pay_period == "year"
    assert job.disclosed_confidence == "high"
    assert job.structured_at is not None


# --- section_key column-width safety -------------------------------------- #
# section_key slugifies a source heading into an identifier stored in the
# String(64) `job_skill_evidence.section_key` column. An un-clamped long heading
# would overflow the column during persistence. These pin the
# clamp to the real column width so a future widening/narrowing keeps them honest.

_SECTION_KEY_WIDTH = JobSkillEvidence.__table__.c.section_key.type.length


def test_section_key_never_exceeds_its_db_column():
    long_heading = (
        "Responsibilities and Key Accountabilities for This Strategic "
        "Cross-Functional Senior Leadership Role Across Regions"
    )
    key = _section_key(long_heading)
    assert len(key) <= _SECTION_KEY_WIDTH
    # A clamp must not leave a dangling separator at the cut.
    assert not key.endswith("_")


def test_section_key_preserves_short_headings_and_known_remap():
    assert _section_key("Overview") == "overview"
    assert _section_key("Responsibilities") == "responsibilities"
    # The pay_benefits -> pay_and_benefits remap still applies (both < width).
    assert _section_key("Pay & Benefits") == "pay_and_benefits"
    assert _section_key("   ") == "job_description"


def test_structure_job_detail_records_the_employer_stated_rung():
    # The plumbing that makes the printed rung reach `map_level`: the detail pass
    # is where the description first exists, and nothing else fills
    # `jobs.raw_level`. Microsoft's real sentence shape.
    html = (
        "<b>Overview</b><p>Build things.</p>"
        "<p>Software Engineering M5 - The typical base pay range for this role "
        "across the U.S. is USD $142,800 - $274,800 per year.</p>"
    )
    job = RawJob(company="microsoft", req_id="1", title="Principal SWE Manager",
                 url="u", locations=["Redmond, WA"], description_html=html)
    structure_job_detail(job, SchemaDriftDetector("microsoft"))
    assert job.raw_level == "M5"


def test_structure_job_detail_leaves_raw_level_unset_when_nothing_is_stated():
    # Every other employer prints no rung; an invented one would carry the
    # employer's authority into a band we guessed.
    html = "<b>Overview</b><p>We are hiring a Staff Engineer for the L5/L6 team.</p>"
    job = RawJob(company="amazon", req_id="1", title="Staff Engineer", url="u",
                 locations=["Seattle, WA"], description_html=html)
    structure_job_detail(job, SchemaDriftDetector("amazon"))
    assert job.raw_level is None


def test_a_rung_from_the_listing_payload_is_not_overwritten_by_prose():
    job = RawJob(company="microsoft", req_id="1", title="Principal PM", url="u",
                 locations=["Redmond, WA"], raw_level="IC6",
                 description_html="<p>Product Management IC4 - The typical base pay "
                                  "range for this role across the U.S. is USD $1 - $2 per year.</p>")
    structure_job_detail(job, SchemaDriftDetector("microsoft"))
    assert job.raw_level == "IC6"


# --------------------------------------------------------------------------- #
# Whether a read looked for pay
# --------------------------------------------------------------------------- #

_GREENHOUSE_PAGE = (
    "<h2>About the role</h2><p>Lead the payments platform.</p>"
    "<div class=\"content-pay-transparency\"><p>Base salary: $180,000 - $240,000 USD</p></div>"
)


def _structured(html: str, *, source: str = "greenhouse", complete: bool = True) -> RawJob:
    job = RawJob(company="acme", req_id="1", title="Staff Engineer", url="https://example.test/1",
                 description_html=html, description_complete=complete)
    structure_job_detail(job, _Drift(), source=source)
    return job


class _Drift:
    def note(self, message: str, **context) -> None:
        self.message = message


def test_a_prose_reader_s_full_read_has_looked_for_pay_band_or_not():
    stated = _structured(_GREENHOUSE_PAGE)
    assert stated.source_disclosed_comp is not None and stated.pay_looked
    # No pay block at all on a page read in full: the posting states no pay.
    silent = _structured("<h2>About the role</h2><p>Lead the payments platform.</p>")
    assert silent.source_disclosed_comp is None and silent.pay_looked


def test_a_read_that_cannot_say_there_is_no_pay_has_not_looked():
    # A partial description, a failover parse and a structured salary reader.
    assert not _structured(_GREENHOUSE_PAGE, complete=False).pay_looked
    broken = _structured("<p>Lead.</p><div class=\"content-pay-transparency\"></div>")
    assert broken.source_disclosed_comp is None and not broken.pay_looked
    assert not _structured("<p>Lead the payments platform.</p>", source="ashby").pay_looked
    assert get_detail_connector("openai").pay_from_text is False
