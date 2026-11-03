"""Two descriptions whose every difference is explained, pure.

Shapes from blind-labelled pairs. Each negative names the wrong rule it fails: "any passage
with a pay word is noise", "a few changed words never matter", "the size of a
change is all that counts".
"""

from __future__ import annotations

from tracker.lineage.explained_text import MAX_OTHER_WORDS, differs_by_explained_passages

ROLE = [
    "Lead the payments platform team and own the roadmap for card issuing.",
    "Partner with risk, finance and product to launch in new markets.",
    "Grow a team of eight engineers and keep settlement reliable across regions.",
]
NEVER = lambda key: 0  # noqa: E731  (a passage the company repeats nowhere else)


def text(*extra: str, role: list[str] = ROLE) -> str:
    return "\n".join([*role, *extra])


def same(left: str, right: str, *, left_places=("London, UK",), right_places=("Berlin, Germany",),
         recurrence=NEVER) -> bool:
    return differs_by_explained_passages(None, left, left_places, None, right, right_places, recurrence)


def test_a_local_benefits_block_is_not_a_different_role():
    # Reddit, OpenTable, Appfire: one country's benefits text.
    assert same(text("Private medical insurance, 25 days holiday and a pension plan."), text())


def test_a_pay_disclosure_one_posting_has_is_not_a_different_role():
    # Slice, Builders, Roku, Planet: the pay line is on one side only.
    assert same(text("The base salary range for this role is $180,000 - $230,000."), text())


def test_pay_that_moves_with_the_place_is_explained_and_pay_that_moves_at_one_place_is_not():
    # Fails "any passage with a pay word is noise": one city, a
    # different band is a different level.
    left = text("The base salary range for this role is $163,500 - $250,000.")
    right = text("The base salary range for this role is $133,500 - $250,000.")
    assert not same(left, right, left_places=("Cupertino",), right_places=("Cupertino",))
    assert same(left, right, left_places=("Cupertino",), right_places=("Austin",))


def test_a_legal_notice_and_an_office_line_are_explained():
    assert same(text("Los Angeles County applicants: qualified applicants with arrest records will be considered."), text())
    assert same(text("This role is based in our Berlin office."), text())


def test_the_companys_own_boilerplate_is_explained_by_how_often_it_recurs():
    intro = (
        "Doit is the original mission: we believe technology should make money simple for everyone, "
        "so we build the apps that millions of people use to save, invest and send money home."
    )
    # Repeated in three or more of the company's postings: the company's, not the role's.
    assert same(text(intro), text(), recurrence=lambda key: 3)
    # In fewer, and saying nothing a class names, it is the role's own text.
    assert not same(text(intro), text(), recurrence=lambda key: 2)


def test_a_few_reworded_words_pass_and_more_do_not():
    reworded = ["Lead the payments platform team and own the roadmap for card issuing in an enterprise setting."]
    assert same(text(role=reworded + ROLE[1:]), text())
    longer = [ROLE[0] + " " + " ".join(f"duty{i}" for i in range(MAX_OTHER_WORDS + 1))]
    # Fails "a few changed words never matter": past the measured bound it is a question.
    assert not same(text(role=longer + ROLE[1:]), text())


def test_a_figure_or_a_level_word_in_the_change_is_never_explained():
    # Fails "the size of a change is all that counts": one word each.
    three = ["You bring 3+ years of people management."]
    eight = ["You bring 8+ years of people management."]
    assert not same(text(role=ROLE + three), text(role=ROLE + eight))
    team = ["Grow a team of eight senior engineers and keep settlement reliable across regions."]
    assert not same(text(role=ROLE[:2] + team), text())


def test_a_swapped_ordinary_word_passes_as_the_judges_read_it():
    # The known limit, stated: "enterprises" against "client facing environment"
    # was judged the same role, and no word rule tells it from "analysts"
    # against "engineers". Kept visible so a change to it is a decision.
    swapped = ["Grow a team of eight analysts and keep settlement reliable across regions."]
    assert same(text(role=ROLE[:2] + swapped), text())


def test_texts_asking_different_years_conflict_and_texts_asking_none_do_not():
    from tracker.lineage.explained_text import requirements_conflict

    # The headline requirement differs.
    assert requirements_conflict("7+ years of direct management", "5+ years of direct management")
    assert not requirements_conflict("7+ years of direct management", "7 years of direct management")
    assert not requirements_conflict("7+ years of direct management", "Experience leading teams")
    # A site template adds an optional bullet with a smaller figure
    # to the same role; the headline ask is the same.
    assert not requirements_conflict(
        "7+ years of direct management", "7+ years of direct management. Preferred: 2+ years of Lean"
    )
