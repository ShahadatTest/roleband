"""The bench that decides the counts switch can fail."""

from collections import Counter
from datetime import UTC, datetime, timedelta

from scripts.bench_inventory_joint import judge

AT = datetime(2026, 9, 28, 6, 51, tzinfo=UTC)
CELL = ("software_engineering", "staff", "technical", ("uk",), ())
OTHER = ("software_engineering", "senior", "technical", ("uk",), ())


def test_a_difference_is_a_defect_only_when_both_sides_came_from_one_read():
    same = Counter({CELL: 3})
    assert judge("acme", same, Counter({CELL: 3}), AT, AT).state == "equal"
    planted = Counter({CELL: 3, OTHER: 1})
    assert judge("acme", same, planted, AT, AT + timedelta(seconds=5)).state == "defect"
    assert judge("acme", same, planted, AT, AT + timedelta(hours=6)).state == "expected"
    assert judge("acme", same, Counter({CELL: 2}), AT, AT).differing == 1


def test_a_company_the_switch_would_not_count_yet_is_named_for_why():
    assert judge("acme", Counter(), Counter(), AT, None).state == "no_complete_read"
    assert judge("acme", Counter(), Counter({CELL: 1}), None, AT).state == "no_catalog"
