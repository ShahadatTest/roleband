"""`taxonomy.comp_families`: pay rows are keyed by our taxonomy, and the borrow
order is the core's own.

A family the order does not name still borrows, after every named one, so a new
role group never silently drops out of borrowing.
"""

from __future__ import annotations

import re

from tracker.taxonomy.comp_families import BORROW_ORDER, REFERENCE_FAMILY, borrow_rank
from tracker.taxonomy.roles import ROLE_GROUPS


def test_the_reference_family_is_a_role_group_and_borrows_first():
    assert REFERENCE_FAMILY in {g.slug for g in ROLE_GROUPS}
    assert BORROW_ORDER[0] == REFERENCE_FAMILY
    assert min(BORROW_ORDER + ("aaa_unlisted",), key=borrow_rank) == REFERENCE_FAMILY


def test_the_borrow_order_names_only_role_groups_and_each_once():
    """A name outside our taxonomy is another vocabulary leaking back in."""
    groups = {g.slug for g in ROLE_GROUPS}
    assert len(BORROW_ORDER) == len(set(BORROW_ORDER))
    assert set(BORROW_ORDER) <= groups, sorted(set(BORROW_ORDER) - groups)
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*", f) for f in BORROW_ORDER)


def test_an_unlisted_family_borrows_after_every_listed_one_by_name():
    listed_last = borrow_rank(BORROW_ORDER[-1])
    assert borrow_rank("aaa_new_group") > listed_last
    assert borrow_rank("aaa_new_group") < borrow_rank("zzz_new_group")
    assert sorted(["zzz_new_group", "data_science", REFERENCE_FAMILY], key=borrow_rank) == [
        REFERENCE_FAMILY, "data_science", "zzz_new_group",
    ]
