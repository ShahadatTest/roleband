"""The walk's "which roles" rows against the track classifier.

Two directions, both over `classify_track` itself rather than a snapshot of the
joint:

- every (track, family) the classifier can file is named by a row of that
  track, so "Only these" with every row ticked is "Any", and no tail is
  dropped without a word;
- every (track, family) a row names is one the classifier files, so no row can
  never match.

"Can file" is read off probe titles that walk each branch of the classifier
for each family: a plain title, the leadership words, the "Manager" forms it
reads both ways, the senior-IC words and "Chief". Each direction has a planted
control, so a check that stopped constraining anything fails here.
"""

from __future__ import annotations

import json
from dataclasses import replace

from scripts.export_role_questions import COMMITTED, render
from tracker.enrich.track import classify_track
from tracker.schema import RoleTrack
from tracker.taxonomy import role_rows
from tracker.taxonomy.role_rows import ROLE_QUESTIONS, RoleQuestion, RoleRow
from tracker.taxonomy.roles import all_slugs

#: One title shape per classifier branch; `{x}` is the family's work.
_SHAPES = (
    "{x}",
    "Senior {x}",
    "{x} Manager",
    "Senior Manager, {x}",
    "Manager of {x}",
    "{x} Team Manager",
    "Director of {x}",
    "Head of {x}",
    "VP, {x}",
    "Chief {x} Officer",
    "Principal {x} Architect",
    "Distinguished {x}",
    "{x} Fellow",
)
#: What each family's titles name; "Tax" and "Account" are the IC heads the
#: classifier reads as work, not leadership.
_WORK = {
    "engineering_management": "Engineering",
    "product_management": "Product",
    "technical_program_management": "Technical Program",
    "program_management": "Program",
    "ml_ai_research": "Machine Learning",
    "data_science": "Data Science",
    "data_engineering": "Data Engineering",
    "security_engineering": "Security Engineering",
    "infrastructure_sre": "Site Reliability",
    "hardware_engineering": "Hardware Engineering",
    "software_engineering": "Software Engineering",
    "design_ux": "Product Design",
    "developer_relations": "Developer Relations",
    "solutions_sales_eng": "Solutions Engineering",
    "technical_writing": "Technical Writing",
    "it_support": "IT Support",
    "operations_facilities": "Data Center Operations",
    "sales_business_development": "Account",
    "customer_success": "Customer Success",
    "marketing_communications": "Product Marketing",
    "business_operations_strategy": "Business Operations",
    "finance_accounting": "Tax",
    "people_recruiting": "Recruiting",
    "legal_policy": "Legal",
}


def _filed() -> set[tuple[str, str]]:
    """Every (track, family) the classifier files over the probe titles."""
    return {
        (classify_track(shape.format(x=_WORK[family]), family).value, family)
        for family in all_slugs()
        for shape in _SHAPES
    }


def _named(table: dict[str, RoleQuestion]) -> set[tuple[str, str]]:
    return {(track, family) for track, question in table.items() for row in question.rows for family in row.families}


def test_every_family_has_probe_titles():
    assert set(_WORK) == set(all_slugs())


def test_every_track_has_a_question_and_rows_name_real_families_once():
    assert set(ROLE_QUESTIONS) == {track.value for track in RoleTrack}
    families = set(all_slugs())
    for track, question in ROLE_QUESTIONS.items():
        named = [family for row in question.rows for family in row.families]
        assert set(named) <= families, track
        assert len(named) == len(set(named)), f"{track} books a family in two rows"
        assert len({row.key for row in question.rows}) == len(question.rows), track
        for row in question.rows:
            assert (row.craft in question.crafts) if question.crafts else row.craft is None, row.key


def test_everything_the_classifier_files_is_named_by_a_row():
    """Under "Only these", a (track, family) no row names is dropped with no
    row to say so, such as a business family filed hands-on ("SAP Supply
    Chain Architect")."""
    assert _filed() - _named(ROLE_QUESTIONS) == set()


def test_every_row_can_match():
    """A row naming a family the classifier never files under its track can
    never match, such as "Product & program managers" under Leading a team."""
    assert _named(ROLE_QUESTIONS) - _filed() == set()


def test_both_directions_catch_a_planted_table():
    management = ROLE_QUESTIONS[RoleTrack.MANAGEMENT.value]
    dead_row = replace(management, rows=(*management.rows, RoleRow("pm", "Product managers", ("product_management",), "")))
    planted = {**ROLE_QUESTIONS, RoleTrack.MANAGEMENT.value: dead_row}
    assert _named(planted) - _filed() == {(RoleTrack.MANAGEMENT.value, "product_management")}

    customers = ROLE_QUESTIONS[RoleTrack.BUSINESS_CUSTOMER.value]
    missing = replace(customers, rows=tuple(row for row in customers.rows if row.key != "finance"))
    dropped = {**ROLE_QUESTIONS, RoleTrack.BUSINESS_CUSTOMER.value: missing}
    assert _filed() - _named(dropped) == {(RoleTrack.BUSINESS_CUSTOMER.value, "finance_accounting")}


def test_named_pairs_is_the_table():
    assert role_rows.named_pairs() == _named(ROLE_QUESTIONS)


def test_the_dashboard_reads_this_table():
    """`roleQuestions.gen.json` is committed; regenerate with
    `python -m scripts.export_role_questions`."""
    assert COMMITTED.read_text() == render()
    assert json.loads(render())["technical"]["crafts"][0] == "Engineering & hardware"
