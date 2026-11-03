"""Level evidence from the raw pay store.

Contracts:

- A title's own level words are read as written ("senior staff" is one rung
  word, not "senior" + "staff"), and a plain title has none.
- Pay growth is measured from the same employer, title and state in
  consecutive vintages, chained into this year's terms; a year with too few
  matched cells gets no index, so its pay is never silently "adjusted".
- Older figures weigh less: half per year of age.
- Rungs are compared by pay only WITHIN one vintage: a 2024 Senior is never
  set against a 2026 Staff, so inflation cannot manufacture or hide an
  inversion; a posting whose level is not stated is not a rung.
"""

from __future__ import annotations

import pytest

from scripts import normalize_levels as nl


@pytest.mark.parametrize(("title", "words"), [
    ("Senior Staff Software Engineer", "senior staff"),
    ("Sr. Software Engineer II", "senior|ii"),
    ("Staff Software Engineer", "staff"),
    ("SMTS Software Development Eng.", "smts"),
    ("Member of Technical Staff", "member of technical staff"),
    ("Software Engineer 3", "3"),
    ("Associate Software Engineer", "associate"),
    ("Software Engineer", ""),
    ("Principal Engineer, IC5", "principal|ic5"),
])
def test_a_title_says_its_level_in_its_own_words(title, words):
    assert nl.level_words(title) == words


def _row(employer, title, state, vintage, pay, company="", source="dol_lca", kind="offered_base"):
    return {"source": source, "employer": employer, "title": title, "location": f"San Jose, {state}",
            "vintage": vintage, "pay_low": str(pay), "company": company, "pay_kind": kind}


def _market(cells: int, pays: dict[str, int]) -> list[dict]:
    return [_row(f"Employer {i}", "Software Engineer", "CA", v, p) for i in range(cells) for v, p in pays.items()]


def test_growth_is_measured_and_chained_into_this_years_terms():
    index = nl.growth_index(_market(250, {"2024": 100_000, "2025": 103_000, "2026": 105_060}), 2026)
    assert index["2026"]["index"] == 1.0
    assert index["2025"] == {"index": 1.02, "cells": 250, "growth_to_next": 0.02}
    assert index["2024"]["index"] == pytest.approx(1.0506, abs=1e-4)


def test_a_year_with_too_few_matched_cells_gets_no_index():
    rows = _market(250, {"2025": 103_000, "2026": 105_060}) + _market(20, {"2024": 100_000, "2025": 103_000})
    index = nl.growth_index(rows, 2026)
    assert "2024" not in index and "2025" in index


@pytest.mark.parametrize(("vintage", "w"), [("2026", 1.0), ("2025", 0.5), ("2024", 0.25), ("", 0.0)])
def test_older_pay_weighs_less(vintage, w):
    assert nl.weight(vintage, 2026) == pytest.approx(w, abs=1e-6)


def _reader(company, title):
    band = {"Senior Software Engineer": "senior", "Staff Software Engineer": "staff"}.get(title, "mid")
    basis = "none" if title == "Software Engineer" else "generic"
    return ("software_engineering", "technical", band, basis)


def _cells(rows):
    return list(nl.evidence(rows, reader=_reader).values())


def test_rungs_are_compared_only_within_one_vintage():
    """A 2024 Senior paid 200k and a 2026 Staff 190k: different years, no
    verdict. The same pair inside 2026 is an inversion."""
    rows = ([_row("X", "Senior Software Engineer", "CA", "2024", 200_000, company="acme")] * 5
            + [_row("X", "Staff Software Engineer", "CA", "2026", 190_000, company="acme")] * 5)
    assert nl.inversions(_cells(rows)) == []
    rows += [_row("X", "Senior Software Engineer", "CA", "2026", 200_000, company="acme")] * 5
    flagged = nl.inversions(_cells(rows))
    assert [(f["vintage"], f["higher_band"], f["lower_band"]) for f in flagged] == [("2026", "staff", "senior")]


def test_an_unstated_level_is_not_a_rung():
    rows = ([_row("X", "Software Engineer", "CA", "2026", 250_000, company="acme")] * 5
            + [_row("X", "Senior Software Engineer", "CA", "2026", 200_000, company="acme")] * 5)
    assert nl.inversions(_cells(rows)) == []


def test_only_base_pay_at_a_tracked_company_is_evidence():
    rows = [_row("X", "Senior Software Engineer", "CA", "2026", 200_000, company="acme"),
            _row("X", "Senior Software Engineer", "CA", "2026", 900_000, company="acme", kind="posted_total_range"),
            _row("Y", "Senior Software Engineer", "CA", "2026", 150_000)]
    cells = _cells(rows)
    assert [(c.company, c.n) for c in cells] == [("acme", 1)]


def test_only_dollar_pay_is_pooled_as_evidence():
    """The store keeps each posting's own currency; a yen band
    pooled with dollar ones would set a level's pay at fifteen million."""
    rows = [_row("X", "Senior Software Engineer", "CA", "2026", 200_000, company="acme", kind="posted_base_range"),
            {**_row("X", "Senior Software Engineer", "CA", "2026", 15_000_000, company="acme",
                    kind="posted_base_range"), "currency": "JPY"},
            {**_row("X", "Senior Software Engineer", "CA", "2026", 210_000, company="acme"), "currency": "USD"}]
    (cell,) = _cells(rows)
    assert sorted(cell.pay["2026"]) == [200_000, 210_000]


def test_adjusted_pay_needs_every_vintage_indexed():
    rows = ([_row("X", "Senior Software Engineer", "CA", "2025", 100_000, company="acme")]
            + [_row("X", "Senior Software Engineer", "CA", "2026", 104_000, company="acme")])
    cell = _cells(rows)[0]
    assert nl.adjusted_median(cell, {"2026": {"index": 1.0}, "2025": {"index": 1.04}}) == 104_000
    assert nl.adjusted_median(cell, {"2026": {"index": 1.0}}) is None


# --- managers beside the engineer band they are paid like ----------------------- #


def _cell(company, family, track, band, basis, words, pays):
    cell = nl.Cell(company, family, track, band, basis, words)
    for vintage, values in pays.items():
        cell.pay[vintage].extend(values)
    cell.titles["t"] = 1
    return cell


def _ladder(vintage="2026"):
    return [
        _cell("acme", "software_engineering", "technical", "senior", "generic", "senior", {vintage: [200_000] * 5}),
        _cell("acme", "software_engineering", "technical", "staff", "generic", "staff", {vintage: [250_000] * 5}),
        _cell("acme", "ml_ai_research", "technical", "principal", "generic", "principal", {vintage: [320_000] * 5}),
    ]


def test_a_manager_is_placed_beside_the_engineer_band_paid_alike():
    mgr = _cell("acme", "engineering_management", "management", "staff", "unmapped", "manager", {"2026": [255_000] * 4})
    rows = nl.manager_alignment([*_ladder(), mgr], 2026)
    assert [(r["aligned_band"], r["agreement"]) for r in rows] == [("staff", 1.0)]
    assert rows[0]["evidence"] == "2026: $255k n4 ~ staff $250k"


def test_too_few_points_or_one_engineer_band_is_no_verdict():
    thin = _cell("acme", "engineering_management", "management", "staff", "unmapped", "manager", {"2026": [255_000] * 2})
    assert nl.manager_alignment([*_ladder(), thin], 2026) == []
    mgr = _cell("acme", "engineering_management", "management", "staff", "unmapped", "manager", {"2026": [255_000] * 4})
    assert nl.manager_alignment([_ladder()[0], mgr], 2026) == []


def test_unstated_engineers_and_other_companies_are_not_the_ladder():
    plain = _cell("acme", "software_engineering", "technical", "mid", "none", "", {"2026": [256_000] * 9})
    other = _cell("zeta", "software_engineering", "technical", "principal", "generic", "principal", {"2026": [255_000] * 9})
    mgr = _cell("acme", "engineering_management", "management", "staff", "unmapped", "manager", {"2026": [255_000] * 4})
    assert [r["aligned_band"] for r in nl.manager_alignment([*_ladder(), plain, other, mgr], 2026)] == ["staff"]


def test_the_newer_vintage_outweighs_the_older():
    """2024 (weight 0.25) says principal on 5 points; 2026 (weight 1) says
    staff on 3: staff, with the split recorded."""
    mgr = _cell("acme", "engineering_management", "management", "staff", "unmapped", "manager",
                {"2024": [318_000] * 5, "2026": [252_000] * 3})
    rows = nl.manager_alignment([*_ladder("2024"), *_ladder("2026"), mgr], 2026)
    assert [(r["aligned_band"], r["agreement"]) for r in rows] == [("staff", round(3 / 4.25, 2))]
