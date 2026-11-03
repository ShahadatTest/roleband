"""Filed pay per company x title x state x year.

Contracts:

- **One cell per company x title x state x year, no source.** An LCA and a
  PERM filing for the same title, state and year are one cell; the state may
  be a code or spelled out, the title any case.
- Only government filings make cells; our postings are skipped. A filing at a
  company that is not named, or with no US state, is counted as left out.
- The spread is the filings' own: linear-interpolated quantiles of the offered
  base, a single filing its own every quantile.
- The shipped file holds named companies only, all under one `as_of`.
"""

from __future__ import annotations

import csv

import pytest

from scripts.build_title_pay import AS_OF, named_companies
from tracker.levels import atlas
from tracker.pay_store import title_pay
from tracker.pay_store.title_pay import DROP_NO_STATE, DROP_NOT_NAMED, build, quantile, state_code

NAMED = frozenset({"servicenow", "brex"})


def _obs(company="servicenow", title="Senior Software Engineer", location="Santa Clara, CA",
         vintage="2025", pay=173000, level="III", source="dol_lca") -> dict[str, str]:
    return {"source": source, "company": company, "title": title, "location": location,
            "vintage": vintage, "pay_low": str(pay), "wage_level": level}


def _one(rows, **key):
    found = [r for r in rows if all(r[k] == v for k, v in key.items())]
    assert len(found) == 1, found
    return found[0]


def test_lca_and_perm_for_one_title_state_and_year_are_one_cell():
    rows = build([
        _obs(location="Santa Clara, CA", title="Senior Software Engineer", pay=170000),
        _obs(location="San Diego, CALIFORNIA", title="SENIOR SOFTWARE  ENGINEER", pay=180000,
             level="", source="dol_perm"),
    ], NAMED, AS_OF).rows
    assert len(rows) == 1
    cell = rows[0]
    assert (cell["company"], cell["title"], cell["state"], cell["year"]) == (
        "servicenow", "senior software engineer", "CA", 2025)
    assert cell["n"] == 2
    assert "source" not in cell


def test_each_state_and_each_year_is_its_own_cell():
    rows = build([
        _obs(location="Santa Clara, CA"), _obs(location="Kirkland, WA"),
        _obs(location="Santa Clara, CA", vintage="2024"),
    ], NAMED, AS_OF).rows
    assert sorted((r["state"], r["year"]) for r in rows) == [("CA", 2024), ("CA", 2025), ("WA", 2025)]


def test_postings_make_no_cell_and_are_not_counted_as_left_out():
    built = build([_obs(source="posting")], NAMED, AS_OF)
    assert built.rows == []
    assert sum(built.dropped.values()) == 0


def test_a_company_that_is_not_named_is_left_out_and_counted():
    built = build([_obs(company="some-startup"), _obs()], NAMED, AS_OF)
    assert [r["company"] for r in built.rows] == ["servicenow"]
    assert built.dropped[DROP_NOT_NAMED] == 1


@pytest.mark.parametrize("location, code", [
    ("Georgetown, TX", "TX"),
    ("Pittsburgh, PENNSYLVANIA", "PA"),
    ("New York, New  York", "NY"),
    ("Washington, DISTRICT OF COLUMBIA", "DC"),
    ("San Juan, PR", "PR"),
    ("Remote, N/A", ""),
    ("", ""),
])
def test_the_worksite_state(location, code):
    assert state_code(location) == code


def test_a_filing_with_no_state_is_left_out_and_counted():
    built = build([_obs(location="Remote, N/A")], NAMED, AS_OF)
    assert built.rows == []
    assert built.dropped[DROP_NO_STATE] == 1


def test_the_spread_is_the_filings_own():
    rows = build([_obs(pay=p) for p in (140000, 100000, 120000, 130000, 110000)], NAMED, AS_OF).rows
    cell = rows[0]
    assert [cell[name] for name, _ in title_pay.QUANTILES] == [104000, 110000, 120000, 130000, 136000]


def test_one_filing_is_its_own_every_quantile():
    cell = build([_obs(pay=188496)], NAMED, AS_OF).rows[0]
    assert {cell[name] for name, _ in title_pay.QUANTILES} == {188496}


def test_quantile_refuses_no_values():
    with pytest.raises(ValueError):
        quantile([], 0.5)


def test_wage_levels_are_counted_and_none_stays_empty():
    cell = build([_obs(level="III"), _obs(level="III"), _obs(level="IV"), _obs(level="", source="dol_perm")],
                 NAMED, AS_OF).rows[0]
    assert (cell["level_i"], cell["level_ii"], cell["level_iii"], cell["level_iv"]) == (None, None, 2, 1)
    assert cell["n"] == 4


def test_every_cell_carries_the_dataset_start():
    rows = build([_obs(), _obs(company="brex", vintage="2023")], NAMED, "2026-10-01").rows
    assert {r["as_of"] for r in rows} == {"2026-10-01"}


def test_the_shipped_file_holds_named_companies_dated_from_october_first():
    with atlas.TITLE_PAY.path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows, "title_pay.csv is empty: run scripts.build_title_pay"
    assert {r["company"] for r in rows} <= named_companies()
    assert {r["as_of"] for r in rows} == {AS_OF} == {"2026-10-01"}
