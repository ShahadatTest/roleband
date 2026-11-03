"""Two descriptions that differ only by where the role is, pure.

Every case is a shape real postings take, and each
negative names the wrong rule it fails: "strip every number", "strip every
place-like word", "a place word anywhere excuses any change".
"""

from __future__ import annotations

from tracker.lineage.place_sets import text_classes
from tracker.lineage.place_text import differs_only_by_place

BODY = (
    "Brex is the AI-powered spend platform. As Head of Regulatory Affairs you will own "
    "our relationships with regulators, lead licensing, and build the compliance program "
    "that lets us launch new products with confidence. This role is based in {place} and "
    "reports to the Chief Legal Officer. {pay} We offer equity, benefits and a generous "
    "parental leave policy to every employee."
)
SF = ["San Francisco, California, United States", "New York, NY", "San Francisco, CA"]
NY = ["New York, New York, United States", "New York, NY", "San Francisco, CA"]


def body(place: str, pay: str = "") -> str:
    return BODY.format(place=place, pay=pay)


def test_a_place_named_in_the_text_is_not_a_different_text():
    # brex 7523 / 7522
    assert differs_only_by_place(body("San Francisco"), SF, body("New York City"), NY)


def test_the_pay_stated_for_each_place_moves_with_the_place():
    # amazon 2297 / 1833: "USA, NY, New York - 194,700.00 ..." vs "USA, CO, Denver - 177,000.00 ..."
    ny = body("New York", "USA, NY, New York - 194,700.00 - 263,400.00 USD annually.")
    denver = body("Denver", "USA, CO, Denver - 177,000.00 - 240,000.00 USD annually.")
    assert differs_only_by_place(
        ny, ["New York, New York, USA"], denver, ["Denver, Colorado, USA"]
    )


def test_a_pay_figure_that_moves_at_the_same_place_is_a_different_role():
    # Fails "strip every number": apple 454 / 438, Cupertino both, $163,500
    # against $133,500 (a different band is a different level).
    left = body("Cupertino", "The base pay range is $163,500 to $250,000.")
    right = body("Cupertino", "The base pay range is $133,500 to $250,000.")
    assert not differs_only_by_place(left, ["Cupertino"], right, ["Cupertino"])
    # amazon 4987 / 4967: identical places, the Sunnyvale figures differ. The
    # place words are EQUAL here, so nothing excuses the figures.
    places = ["Seattle, Washington, USA", "Sunnyvale, California, USA"]
    left = body("Sunnyvale", "USA, CA, Sunnyvale - 151,600.00 - 205,000.00 USD annually.")
    right = body("Sunnyvale", "USA, CA, Sunnyvale - 156,400.00 - 211,600.00 USD annually.")
    assert not differs_only_by_place(left, places, right, places)


def test_a_figure_far_from_any_place_is_not_that_places_pay():
    # Fails "a place word anywhere excuses any number": a moved requirement
    # ("3+ years" vs "8+ years") beside a place change elsewhere in the text.
    left = body("San Francisco") + " You bring 3+ years of people management."
    right = body("New York City") + " You bring 8+ years of people management."
    assert not differs_only_by_place(left, SF, right, NY)


def test_a_figure_before_the_place_it_sits_beside_is_not_that_places_pay():
    # Fails "a run holding a place may hold any figure": the place follows the
    # figure, so the figure is a requirement, not the place's pay.
    left = body("Bristol") + " You bring 3 years in London."
    right = body("Bristol") + " You bring 8 years in Paris."
    assert not differs_only_by_place(left, ["London"], right, ["Paris"])


def test_a_word_that_is_no_place_is_a_different_text():
    # pallet 9622 / 9623: one employer job, two market hires. "Korean" and
    # "Japanese" are not place words, so the texts stay two.
    left = body("Seoul") + " Fluent Korean is required."
    right = body("Tokyo") + " Fluent Japanese is required."
    assert not differs_only_by_place(left, ["Seoul, South Korea"], right, ["Tokyo, Japan"])


def test_a_work_arrangement_is_never_stripped_as_a_place():
    # Fails "strip place-like words": "Germany (Remote)" puts "remote" in a
    # label, but remote against hybrid is a difference the user must see.
    left = body("Berlin") + " This role is remote."
    right = body("Munich") + " This role is hybrid."
    assert not differs_only_by_place(left, ["Berlin (Remote)"], right, ["Munich (Hybrid)"])


def test_punctuation_and_case_are_not_a_difference_and_no_difference_is_not_a_place():
    assert differs_only_by_place(body("London"), ["London"], body("London").upper() + "!", ["London"])
    assert not differs_only_by_place("", ["London"], body("London"), ["London"])


def test_text_classes_chain_but_never_across_a_conflict_and_key_on_the_smallest_md5():
    joined = {frozenset({"b", "c"}), frozenset({"c", "d"})}
    same = lambda x, y: frozenset({x, y}) in joined  # noqa: E731
    # A chain joins: b~c and c~d are one role through c.
    assert text_classes(["d", "c", "b", "a"], same) == {"a": "a", "b": "b", "c": "b", "d": "b"}
    # Fails plain union-find: b and d ask for
    # different years, so the chain through c cannot put them together.
    conflict = lambda x, y: {x, y} == {"b", "d"}  # noqa: E731
    classes = text_classes(["d", "c", "b", "a"], same, conflict)
    assert classes["b"] != classes["d"]
    assert classes["c"] in (classes["b"], classes["d"])
    assert text_classes(["z"], lambda x, y: (_ for _ in ()).throw(AssertionError("asked"))) == {"z": "z"}
