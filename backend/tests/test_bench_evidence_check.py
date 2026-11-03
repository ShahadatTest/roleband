"""An evidence method must agree with the levels companies state.

A method like placing a manager title group at the engineer band it is paid
like can disagree with the groups whose own titles state their band, and
lower director titles, so it may inform a reviewer, never place a posting. `evidence-check` makes the
score a gate every batch runs: 94%+ of at least 10 anchored groups, and no
director title lowered.
"""

from __future__ import annotations

import csv

import pytest

from scripts.bench_level_bands import EVIDENCE_BAR, cmd_evidence_check, evidence_agreement

#: Title groups whose titles state their band: (company, family, title, the band they state).
STATED = [
    ("acme", "software_engineering", "Senior Software Engineer", "senior"),
    ("acme", "software_engineering", "Staff Software Engineer", "staff"),
    ("acme", "software_engineering", "Principal Software Engineer", "principal"),
    ("acme", "engineering_management", "Director, Engineering", "director_plus"),
    ("google", "engineering_management", "Senior Software Engineering Manager, Search", "principal"),
    ("google", "engineering_management", "Software Engineering Manager II, Ads", "staff"),
    ("amazon", "software_engineering", "Sr. Software Development Engineer", "senior"),
    ("acme", "data_science", "Senior Data Scientist", "senior"),
    ("acme", "data_science", "Staff Data Scientist", "staff"),
    ("acme", "data_science", "Principal Data Scientist", "principal"),
    ("acme", "data_science", "Director, Data Science", "director_plus"),
    ("acme", "product_management", "Staff Product Manager", "staff"),
]


def _rows(proposal) -> list[dict]:
    return [{"company": c, "family": f, "titles": t, "aligned_band": proposal(band)} for c, f, t, band in STATED]


def test_a_method_that_recovers_every_stated_level_passes():
    report = evidence_agreement(_rows(lambda band: band), "aligned_band")
    assert (report.anchored, report.agree, report.passes) == (12, 12, True)


def test_a_method_that_puts_everyone_at_one_band_fails():
    report = evidence_agreement(_rows(lambda band: "senior"), "aligned_band")
    assert report.share < EVIDENCE_BAR and not report.passes
    assert report.directors_lowered == 2


def test_lowering_a_director_fails_even_above_the_bar():
    rows = _rows(lambda band: band) * 2  # 24 correct groups
    rows.append({"company": "acme", "family": "data_science", "titles": "Director, Data Science",
                 "aligned_band": "principal"})
    report = evidence_agreement(rows, "aligned_band")
    assert report.share >= EVIDENCE_BAR
    assert report.directors_lowered == 1 and not report.passes


def test_too_few_anchored_groups_cannot_claim_the_bar():
    report = evidence_agreement(_rows(lambda band: band)[:5], "aligned_band")
    assert report.share == 1.0 and not report.passes


def test_a_group_whose_titles_state_nothing_is_never_scored():
    # "Engineering Manager" names a role, not a band: the method is the only
    # claim there, so it is counted apart and cannot help or hurt the score.
    rows = _rows(lambda band: band) + [
        {"company": "acme", "family": "engineering_management", "titles": "Engineering Manager, Platform",
         "aligned_band": "principal"},
    ]
    report = evidence_agreement(rows, "aligned_band")
    assert (report.anchored, report.unanchored, report.agree) == (12, 1, 12)


def test_several_titles_in_a_group_are_read_and_the_stated_band_scores():
    rows = [{"company": "acme", "family": "software_engineering",
             "titles": "Staff Software Engineer ; Staff Software Engineer, Payments ; Software Engineer",
             "aligned_band": "staff"}]
    report = evidence_agreement(rows, "aligned_band")
    assert (report.anchored, report.agree) == (1, 1)


@pytest.mark.parametrize(("proposal", "code"), [(lambda band: band, 0), (lambda band: "senior", 1)])
def test_the_command_exits_one_when_the_evidence_fails(tmp_path, proposal, code):
    path = tmp_path / "groups.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["company", "family", "titles", "aligned_band"])
        writer.writeheader()
        writer.writerows(_rows(proposal))
    assert cmd_evidence_check(str(path), "aligned_band") == code
