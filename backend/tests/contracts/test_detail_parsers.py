"""Detail-parser contracts, parametrized over the connector registries.

Every entry in DETAIL_CONNECTORS (per-company) and SOURCE_CONNECTORS (per-ATS)
must (1) own a realistic payload spec here (failure names the registry key,
blueprint-style), (2) parse that payload into non-empty JobDescriptionSections
on the primary path, and (3) return [] — never raise — on garbage payloads.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tracker.connectors import DETAIL_CONNECTORS, SOURCE_CONNECTORS
from tracker.connectors.detail.base import PAY_RANGE_RE, sections_to_text
from tracker.intelligence_runtime.disclosed_comp import pay_input_text
from tracker.pay_disclosure import extract_grounded_band
from tracker.schema import JobDescriptionSection

# Realistic detail inputs per registry key, mirrored from the captured payload
# shapes pinned in tests/test_adapter_*.py and tests/test_detail_connectors.py.
# `payload` feeds parse_payload; `raw_html` covers connectors whose detail is an
# HTML/text blob rather than a structured object.

_ASHBY_POSTING = {
    "descriptionHtml": (
        "<h2>About the team</h2><p>Applied AI brings research to production.</p>"
        "<h2>About the role</h2><p>Lead a team of engineers shipping applied models.</p>"
    ),
    "shouldDisplayCompensationOnJobPostings": True,
    "compensation": {
        "compensationTierSummary": "$310K – $460K • Offers Equity",
        "scrapeableCompensationSalarySummary": "$310K - $460K",
        "summaryComponents": [
            {
                "compensationType": "Salary",
                "interval": "1 YEAR",
                "currencyCode": "USD",
                "minValue": 310000,
                "maxValue": 460000,
            }
        ],
    },
}

_GREENHOUSE_HTML = (
    "<h2>About the role</h2><p>Own reliability for our serving stack.</p>"
    "<h2>Requirements</h2><ul><li>10+ years running distributed systems.</li></ul>"
    '<div class="content-pay-transparency"><p>Annual Salary: '
    "$320,000 - $405,000 USD</p></div>"
)

_WORKDAY_DETAIL = {
    "jobDescription": (
        "<p>Build large-scale platform systems at Nvidia.</p>"
        "<h2>Compensation</h2>"
        "<p>The base salary range for this role is $200,000 - $280,000 USD "
        "annually, depending on location and experience.</p>"
    ),
    "location": "US, CA, Santa Clara",
    "startDate": "2026-07-01",
    "jobReqId": "JR2021162",
}

_LEVER_POSTING = {
    "description": "<p>Build the Spotify app for Android.</p>",
    "lists": [
        {"text": "What You'll Do", "content": "\n<li>Ship Android features.</li>"},
        {"text": "Who You Are", "content": "\n<li>5+ years of Android.</li>"},
    ],
    # Lever tenants put the pay-transparency sentence in the closing block.
    "additional": (
        "<p>The United States base range for this position is $107,483 - $153,547 "
        "plus equity. The benefits available for this position include health "
        "insurance and a 401(k) retirement plan.</p>"
    ),
}

_ATLASSIAN_ROW = next(
    row for row in json.loads(
        (Path(__file__).parents[1] / "fixtures/listings/atlassian/page1.json").read_text()
    ) if row.get("payRanges")
)

#: One real TikTok row plus the pay block its posting page states,
#: as the listing adapter's hydrate isolates it.
_TIKTOK_ROW = json.loads(
    (Path(__file__).parents[1] / "fixtures/listings/tiktok/page1.json").read_text()
)["data"]["job_post_list"][0]
_TIKTOK_PAYLOAD = {
    "description": _TIKTOK_ROW["description"],
    "requirement": _TIKTOK_ROW["requirement"],
    "pay": "The base salary range for this position in the selected city is $115200 - $180000 annually.",
}

REALISTIC_DETAILS: dict[str, dict] = {
    "company:amazon": {
        "payload": {
            "description": (
                "Design distributed systems at scale.<br/><br/>Our compensation "
                "reflects the cost of labor across several US geographic markets. "
                "The base pay for this position ranges from $151,300/year in our "
                "lowest geographic market up to $261,500/year in our highest "
                "geographic market. Amazon is a total compensation company."
            ),
            "basic_qualifications": "- 8+ years of experience",
            "preferred_qualifications": "- AWS experience",
        }
    },
    "company:apple": {
        "payload": {
            "res": {
                "jobSummary": "Summary text.",
                "description": "Description body.",
                "minimumQualifications": "5+ years shipping software.",
                "preferredQualifications": "Distributed systems depth.",
                "selectedLocale": "en_US",
                "postingFooters": [
                    {
                        "localizations": {
                            "en_US": [
                                {
                                    "displayOrder": 1,
                                    "name": "Pay & Benefits",
                                    "content": (
                                        "The base pay range for this role is between "
                                        "$250,800 and $376,300.<br><br>Apple employees "
                                        "may receive equity."
                                    ),
                                }
                            ]
                        }
                    }
                ],
            }
        }
    },
    "company:google": {
        "raw_html": (
            "About the jobBuild products used worldwide. Individual pay is "
            "determined by experience."
            "US: $192000 - $279000 (USD) + 20% bonus target + equity + benefits"
            "Minimum qualifications:Bachelor's degree.8 years of experience."
            "Preferred qualifications:Cloud product experience."
            "ResponsibilitiesLead launches and customer discovery."
        )
    },
    # The blocks the google adapter hands over for any company on Google's
    # board: each section's markup from its heading on.
    "source:google": {
        "raw_html": (
            "<h3>Minimum qualifications:</h3><ul><li>Bachelor's degree.<br></li>"
            "<li>8 years of experience.</li></ul>"
            "<h3>About the job</h3>Advance AI research.<br><br>We work through "
            "collective effort.Individual pay is determined by experience.  <br><br>"
            "US: $217000 - $236000 (USD) + 15% bonus target + equity + benefits<br><br>"
            "<h3>Responsibilities</h3><ul><li>Lead launches.<br></li></ul>"
        )
    },
    # A real PCSX `position_details` payload (PayPal):
    # the key is `jobDescription`, not v2's `job_description`.
    "source:eightfold": {
        "payload": json.loads(
            (Path(__file__).resolve().parents[1] / "fixtures" / "listings" / "eightfold"
             / "pcsx_detail.json").read_text()
        )["data"],
    },
    "company:netflix": {
        "payload": {
            "job_description": (
                "<p>Netflix opening.</p><p><b>The Role</b></p><p>Lead the product.</p>"
                "<p><b>What We Offer</b></p><p>Meaningful impact.</p>"
                "<p>Generally, our compensation structure consists solely of an "
                "annual salary; we do not have bonuses. "
                "the range for this role is $440,000.00 - $725,000.00.</p>"
            )
        }
    },
    "company:openai": {"payload": _ASHBY_POSTING},
    "company:anthropic": {"raw_html": _GREENHOUSE_HTML},
    "company:microsoft": {
        "raw_html": (
            "<b>Overview</b><br><p>Lead customer opportunities across the field.</p>"
            "<br><br><b>Responsibilities</b><br><ul><li>Drive pipeline.</li></ul>"
            "<br><br><b>Qualifications</b><br><ul><li>8+ years experience.</li></ul>"
            "<br><p>The typical base pay range for this role across the U.S. is "
            "USD $130,900 - $251,900 per year.</p>"
        )
    },
    "company:nvidia": {"payload": _WORKDAY_DETAIL},
    "company:spotify": {"payload": _LEVER_POSTING},
    "source:ashby": {"payload": _ASHBY_POSTING},
    "source:lever": {"payload": _LEVER_POSTING},
    # One real listing row: sections are its fields, pay its
    # `payRanges` block.
    "source:atlassian": {"payload": _ATLASSIAN_ROW},
    "source:greenhouse": {"raw_html": _GREENHOUSE_HTML},
    "source:tiktok": {"payload": _TIKTOK_PAYLOAD},
    "source:workday": {"payload": _WORKDAY_DETAIL},
}

REGISTRY = {
    **{f"company:{name}": connector for name, connector in DETAIL_CONNECTORS.items()},
    **{f"source:{name}": connector for name, connector in SOURCE_CONNECTORS.items()},
}

GARBAGE_PAYLOADS = [
    pytest.param({}, id="empty-dict"),
    pytest.param({"unexpected": ["structure"]}, id="wrong-keys"),
    pytest.param("", id="empty-string"),
    pytest.param(42, id="wrong-type-int"),
    pytest.param(["not", "a", "mapping"], id="wrong-type-list"),
]


def test_every_registry_entry_has_a_realistic_payload_spec():
    """Blueprint-style gate: a new connector fails here by name until covered."""
    missing = sorted(set(REGISTRY) - set(REALISTIC_DETAILS))
    stale = sorted(set(REALISTIC_DETAILS) - set(REGISTRY))
    problems = [f"{key}: add a REALISTIC_DETAILS entry" for key in missing]
    problems += [f"{key}: REALISTIC_DETAILS entry has no registry connector" for key in stale]
    assert not problems, "detail-parser contract coverage:\n" + "\n".join(problems)


@pytest.mark.parametrize("key", sorted(REGISTRY))
def test_realistic_payload_parses_into_sections(key):
    connector = REGISTRY[key]
    spec = REALISTIC_DETAILS[key]
    result = connector.parse_payload(spec.get("payload"), spec.get("raw_html"))

    assert result.mode == "primary", f"{key}: realistic payload fell into failover ({result.reason})"
    assert result.sections, f"{key}: realistic payload produced no sections"
    for section in result.sections:
        assert isinstance(section, JobDescriptionSection)
        assert section.key.strip()
        assert section.title.strip()
        assert section.content.strip()


def test_every_band_a_connector_reads_sits_in_the_section_the_pay_pass_reads():
    """The model pay pass reads a posting's pay section in place of its whole
    text (`pay_input_text`). A connector that isolates the band but files it
    under a key of its own hands that pass the whole description instead."""
    banded = []
    misfiled = []
    for key in sorted(REGISTRY):
        spec = REALISTIC_DETAILS[key]
        result = REGISTRY[key].parse_payload(spec.get("payload"), spec.get("raw_html"))
        if result.source_disclosed_comp is None:
            continue
        banded.append(key)
        stored = SimpleNamespace(
            description_sections=[s.as_dict() for s in result.sections],
            description_text=sections_to_text(result.sections),
        )
        if pay_input_text(stored)[1] != "pay_section":
            misfiled.append(f"{key}: sections {[s.key for s in result.sections]}")
    assert banded, "no realistic payload states a band; this contract would pass vacuously"
    assert not misfiled, "band outside the pay section:\n" + "\n".join(misfiled)


@pytest.mark.parametrize("garbage", GARBAGE_PAYLOADS)
@pytest.mark.parametrize("key", sorted(REGISTRY))
def test_garbage_payload_returns_empty_sections_not_exception(key, garbage):
    connector = REGISTRY[key]
    result = connector.parse_payload(garbage, None)
    assert result.sections == [], f"{key}: garbage payload produced sections"


# A pay range written with an en/em dash is the same disclosure as one written
# with a hyphen. `PAY_RANGE_RE` only decides whether a block counts as pay;
# `_EXPLICIT_BAND_RE` parses the bounds. When the gate is stricter than the
# parser, real bands are dropped before anyone tries to read them.
_SEPARATOR_SAMPLES = [
    pytest.param("The base range is $107,483 - $153,547 plus equity.", id="hyphen"),
    pytest.param("The base range is $107,483 – $153,547 plus equity.", id="en-dash-spaced"),
    pytest.param("The base range is $107,483 –$153,547 plus equity.", id="en-dash-tight"),
    pytest.param("The base range is $107,448–153,498 plus equity.", id="en-dash-no-symbol"),
    pytest.param("The base range is $107,483 — $153,547 plus equity.", id="em-dash"),
    pytest.param("The base range is $107,483 to $153,547 plus equity.", id="to"),
]


@pytest.mark.parametrize("text", _SEPARATOR_SAMPLES)
def test_pay_gate_and_band_parser_agree_on_range_separators(text):
    assert PAY_RANGE_RE.search(text), "gate rejected a range the parser can read"
    band = extract_grounded_band(text, text)
    assert band.disclosed, "parser found no band in a range the gate accepted"
    assert (band.base_min, band.base_max) == (107_483, 153_547) or (
        band.base_min,
        band.base_max,
    ) == (107_448, 153_498)
