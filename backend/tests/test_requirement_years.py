"""One reader of years and blocks for every requirement row.

Each case fails a plausible broken reader: one that takes the first "N years"
in a line ("5 years ago" as a requirement, the second number dropped), one that
reads every line of Microsoft's single `qualifications` section as required
("12+ years" under Preferred Qualifications shown as Required), or one that
keeps one number per posting.

`segment` reads the block headings a section prints, `years.stated_years`
is the one grammar, every row keeps every number it states, and the headline
requirement is derived from the rows. Fixtures are the shapes stored postings
print (Microsoft, Qualcomm, PayPal, Anthropic, Apple).
"""

from __future__ import annotations

import pytest

from tracker.skills.catalog import get_catalog
from tracker.skills.extract import extract_job, required_years
from tracker.skills.segment import block_heading, segment_job
from tracker.skills.years import stated_experience_field, stated_years

CAT = get_catalog()


@pytest.mark.parametrize(("text", "expected"), [
    ("Years of Experience: 5+", [5]),
    ("Years of Experience: seven", [7]),
    ("Years of Experience: 3–5", [3]),
    ("Years of Experience: at least 10", [10]),
    ("Years of Experience: 100", []),
    ("Years of Experience: 3.5", []),
    ("Years of Experience: $10", []),
    ("Years of Experience: 5+ preferred", []),
    ("Our company has Years of Experience: 20+", []),
    ("Years of Service: 10+", []),
    ("Years of Experience: 5+\nSalary: 10", []),
])
def test_standalone_experience_fields_use_numeric_grammar_without_modality(text, expected):
    assert stated_experience_field(text) == expected
    assert stated_years(text) == []


def _quals(sections: list[dict], kind: str = "experience") -> list[dict]:
    return [q for q in extract_job(CAT, "Program Manager", sections).qualifications if q["kind"] == kind]


def _years(rows: list[dict]) -> dict[str, float]:
    """{modality: headline years} for one-row-per-modality fixtures."""
    return {q["modality"]: q["value"]["years"] for q in rows}


# --- the grammar -------------------------------------------------------------- #


@pytest.mark.parametrize(("text", "years"), [
    ("5+ years of owning program strategy", [5]),  # marked: needs no "experience"
    ("3-5 years of experience in data engineering", [3]),  # a range requires its floor
    ("At least 7 years of relevant work", [7]),
    ("Minimum of 4 years in a customer-facing role", [4]),
    ("Minimum 7 years for managing system integration testing", [7]),
    ("2 years minimum working on Gen AI programs", [2]),
    ("Two years of experience with SQL", [2]),
    ("10 or more years of industry experience", [10]),
    ("10+ overall years of software engineering experience", [10]),
    ("over 10+ or more years of technical operations", [10]),
    # Four phrasings that can lose or inflate the number.
    ("Looking for 5 years of experience in platform work", [5]),  # a bare "for" is no window
    ("Five (5) years of experience in audit", [5]),  # the legal form
    ("At least two (2) years of experience with Kubernetes", [2]),
    ("Between 5 and 10 years of experience leading teams", [5]),  # a range reads its floor
    ("1 or 2 years' experience in support", [1]),
    ("Twenty-five years of experience in the field", [25]),  # not "twenty" to "five"
])
def test_a_stated_requirement_reads_its_number(text, years):
    assert stated_years(text) == years


@pytest.mark.parametrize("text", [
    "Recent experience within the last 3 years in consumer software",  # Apple: a window
    "Demonstrated capability to plan at a horizon up to 5 years and beyond.",
    "Sales plans with the objective to double in 4 years",
    "PayPal has been revolutionizing commerce for more than 25 years.",
    "We have been in business for 20 years",
    "Founded 12 years ago in a garage",
    "A 4 year degree in Computer Science",
    "Advanced degrees may be substituted (Master's = one year, Doctorate = two years)",
    "5 Years? 5 Weeks! After five years, you'll earn five weeks of vacation",
    "Base pay $120,000 per year",
])
def test_a_window_a_boast_a_degree_or_a_salary_states_no_requirement(text):
    assert stated_years(text, requirement_line=True) == []


def test_an_age_bar_on_a_requirement_line_is_not_experience():
    """"Must be 18 years or older" under Minimum Qualifications read as an
    18-year requirement and, as the largest number, became the headline."""
    assert stated_years("Must be 18 years or older to apply", requirement_line=True) == []
    assert stated_years("Candidates must be 21 years of age or older", requirement_line=True) == []
    assert stated_years("Minimum of 3 years", requirement_line=True) == [3]  # the control


def test_a_bare_number_is_a_requirement_only_on_a_requirement_line():
    # Apple's minimum list says "8 years working on ...", never "experience".
    text = "8 years working on integration technologies for SAP"
    assert stated_years(text) == []  # prose: "20 years building our brand" is a boast
    assert stated_years(text, requirement_line=True) == [8]


def test_every_number_a_line_states_is_kept_in_order():
    assert stated_years(
        "5+ years of software engineering, with at least 1 to 2 years of people management"
    ) == [5, 1]
    assert stated_years(
        "Bachelor's AND 4+ years OR Master's AND 3+ years OR Doctorate AND 1+ year"
    ) == [4, 3, 1]


# --- block headings inside a section ------------------------------------------ #

MICROSOFT = [{
    "key": "qualifications",
    "title": "Qualifications",
    "content": (
        "Required Qualifications:\n"
        "Bachelor's Degree in Computer Science AND 8+ years technical engineering experience\n"
        "Preferred Qualifications:\n"
        "Master's Degree in Computer Science AND 12+ years technical engineering experience\n"
        "Experience with Kubernetes and Azure"
    ),
}]


def test_microsoft_preferred_years_are_preferred_and_never_the_headline():
    rows = _quals(MICROSOFT)
    assert _years(rows) == {"required": 8.0, "preferred": 12.0}
    assert required_years(rows) == 8.0
    education = _quals(MICROSOFT, "education")
    assert [q["modality"] for q in education] == ["required", "preferred"]


def test_microsoft_preferred_skills_are_preferred_too():
    skills = {s["slug"]: s for s in extract_job(CAT, "Software Engineer", MICROSOFT).skills}
    assert skills["kubernetes"]["modality"] == "preferred"


@pytest.mark.parametrize(("key", "title"), [
    ("preferred", "Preferred Qualifications"),  # a title containing "qualifications"
    ("preferred_requirements", "Preferred Requirements:"),  # Netflix
])
def test_a_section_titled_preferred_is_preferred(key, title):
    rows = _quals([{"key": key, "title": title, "content": "10+ years of software engineering experience"}])
    assert _years(rows) == {"preferred": 10.0}
    assert required_years(rows) is None


def test_qualcomm_minimum_block_inside_its_preferred_section_is_required():
    rows = _quals([{
        "key": "preferred_qualifications",
        "title": "Preferred Qualifications",
        "content": (
            "Experience using a scripting language such as Perl or Python\n"
            "Minimum Qualifications:\n"
            "• Bachelor's degree in Electrical Engineering and 4+ years of Hardware Engineering experience.\n"
            "OR\n"
            "Master's degree in Electrical Engineering and 3+ years of Hardware Engineering experience."
        ),
    }])
    assert [(q["modality"], q["value"]["years"]) for q in rows] == [("required", 4.0), ("required", 3.0)]
    assert required_years(rows) == 4.0


def test_a_whole_posting_in_one_section_reads_its_blocks_and_where_they_end():
    rows = _quals([{
        "key": "job_description",
        "title": "Job description",
        "content": (
            "What You'll Do\n"
            "Lead a team that has shipped for 6 years running.\n"
            "What We're Looking For\n"
            "5+ years of experience in product management\n"
            "Nice to have\n"
            "2+ years of experience in payments\n"
            "About Us\n"
            "Our founders bring 20+ years of experience building marketplaces."
        ),
    }])
    assert _years(rows) == {"required": 5.0, "preferred": 2.0}


def test_compound_and_glued_headings_open_their_block():
    paypal = _quals([{
        "key": "minimum_qualifications",
        "title": "Minimum Qualifications:",
        "content": (
            "What You'll Do\n"
            "Build and manage relationships with developer agencies.\n"
            "What You'll Bring — Minimum Qualifications\n"
            "8-10 years of experience in developer ecosystems."
        ),
    }])
    assert _years(paypal) == {"required": 8.0}
    microsoft = _quals([{
        "key": "qualifications",
        "title": "Qualifications",
        "content": (
            "Required/minimum qualifications\n"
            "Bachelor's Degree AND 4+ years experience in program management\n"
            "Additional or preferred qualificationsMaster's Degree AND 6+ years experience in program management\n"
            "6+ years working directly with a partner ecosystem"
        ),
    }])
    assert [(q["modality"], q["value"]["years"]) for q in microsoft] == [
        ("required", 4.0), ("preferred", 6.0), ("preferred", 6.0),
    ]


@pytest.mark.parametrize("line", [
    "Requirements gathering with stakeholders",
    "Python a plus",
    "MBA preferred",
    "Experience with SQL",
    "Bachelor's degree",
])
def test_a_requirement_starting_with_a_heading_word_moves_no_block(line):
    assert block_heading(line) is None
    units = segment_job(None, [{
        "key": "preferred_qualifications", "title": "Preferred Qualifications",
        "content": f"{line}\n3+ years of experience in fintech",
    }])
    assert [u.aspect for u in units] == ["preferred", "preferred"]


def test_a_label_glued_to_its_line_names_that_line_only():
    # Anthropic's logistics fields: the education line is a stated minimum;
    # the visa line after it is not a requirement at all.
    sections = [{
        "key": "logistics",
        "title": "Logistics",
        "content": (
            "Minimum education: Bachelor's degree or an equivalent combination of education and experience\n"
            "Visa sponsorship: We do sponsor visas!"
        ),
    }]
    assert [q["modality"] for q in _quals(sections, "education")] == ["required"]
    assert _quals(sections, "eligibility") == []


# --- the rows ------------------------------------------------------------------ #


def test_a_negation_reaches_its_own_sentence_only():
    rows = _quals([{
        "key": "minimum_qualifications",
        "title": "Minimum Qualifications",
        "content": (
            "Minimum of 5 years of experience as a Technical Program Manager. "
            "Consulting experience is a plus but not required\n"
            "A degree is not required."
        ),
    }])
    assert _years(rows) == {"required": 5.0}
    assert _quals([{"key": "minimum_qualifications", "title": "Minimum Qualifications",
                    "content": "A degree is not required."}], "education") == []


def test_a_row_keeps_every_number_and_the_largest_is_its_headline():
    [row] = _quals([{
        "key": "minimum_qualifications",
        "title": "Minimum Qualifications",
        "content": "7+ years of industry experience, including 2+ years of management experience.",
    }])
    assert row["value"] == {"years": 7.0, "years_stated": [7.0, 2.0]}


def test_the_headline_is_the_largest_required_number_and_none_without_one():
    rows = _quals([{
        "key": "minimum_qualifications",
        "title": "Minimum Qualifications",
        "content": "3+ years of people management\n8+ years of software engineering experience",
    }, {
        "key": "preferred_qualifications",
        "title": "Preferred Qualifications",
        "content": "12+ years of software engineering experience",
    }])
    assert required_years(rows) == 8.0
    assert required_years([q for q in rows if q["modality"] == "preferred"]) is None
