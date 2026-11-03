"""Server-side diff between adjacent lineage members: only real changes surface."""

from __future__ import annotations

from types import SimpleNamespace

from tracker.lineage.diff import build_member_diff


def member(**over):
    base = dict(
        title="Staff Software Engineer",
        level_band="staff",
        locations=["Mountain View, CA"],
        comp_median=500_000,
        comp_currency="USD",
        disclosed_base_min=None,
        disclosed_base_max=None,
        disclosed_currency=None,
        disclosed_pay_basis=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_no_change_returns_empty():
    assert build_member_diff(member(), member()) == {}


def test_title_change():
    d = build_member_diff(member(), member(title="Staff Software Engineer, Inference"))
    assert d["title"] == {"from": "Staff Software Engineer", "to": "Staff Software Engineer, Inference"}


def test_disclosed_band_move():
    prev = member(disclosed_base_min=240_000, disclosed_base_max=334_000, disclosed_currency="USD")
    cur = member(disclosed_base_min=255_000, disclosed_base_max=350_000, disclosed_currency="USD")
    d = build_member_diff(prev, cur)
    assert d["disclosed_band"]["from"] == [240_000, 334_000]
    assert d["disclosed_band"]["to"] == [255_000, 350_000]
    assert d["disclosed_band"]["currency"] == "USD"


def test_newly_disclosed_band_from_null():
    cur = member(disclosed_base_min=200_000, disclosed_base_max=300_000)
    d = build_member_diff(member(), cur)
    assert d["disclosed_band"] == {"from": None, "to": [200_000, 300_000], "currency": None}


def test_pay_basis_change():
    d = build_member_diff(member(disclosed_pay_basis="total"), member(disclosed_pay_basis="base"))
    assert d["pay_basis"] == {"from": "total", "to": "base"}


def test_location_add_and_remove():
    prev = member(locations=["Mountain View, CA"])
    cur = member(locations=["Mountain View, CA", "London, UK"])
    d = build_member_diff(prev, cur)
    assert d["locations"] == {"added": ["London, UK"], "removed": []}

    d2 = build_member_diff(cur, prev)
    assert d2["locations"] == {"added": [], "removed": ["London, UK"]}


def test_level_band_change():
    d = build_member_diff(member(level_band="staff"), member(level_band="principal"))
    assert d["level_band"] == {"from": "staff", "to": "principal"}


def test_estimate_change_names_its_currency():
    prev = member(comp_median=90_000, comp_currency="GBP")
    cur = member(comp_median=110_000, comp_currency="GBP")
    assert build_member_diff(prev, cur)["comp_median"] == {"from": 90_000, "to": 110_000, "currency": "GBP"}
