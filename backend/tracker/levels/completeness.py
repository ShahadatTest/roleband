"""Which named companies the atlas answers, section by section.

The dataset is complete when every named company answers every section: a
fact, or `unknown` with its date. Until then the gaps are listed in
`tests/fixtures/atlas_gaps.json`, which only shrinks: `tests/test_atlas_completeness`
fails when a company joins a gap (a new catalog company without data, a row
removed) and when it leaves one without the list being updated.

Sections, and what counts as an answer:
- `ladder`: a ladder of the company's own, or its parent's (google-deepmind).
- `bonus_rule`, `equity_rule`, `vesting`, `annual_refresh`: a stated fact in
  `company_facts.csv`, or `unknown` with its date (searched, nothing found). The policy default,
  "unverified", is never an answer.
- `filed_base`: filed base pay in `title_pay.csv`.
- `identity`: `company_identity.csv` says whether the company is listed.
  Identity is always ours, so every unresearched one is a gap.

Pure: reads the atlas files; the caller names the companies.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable

from tracker.levels.atlas import TITLE_PAY, load_identity
from tracker.levels.companies import COMPANIES
from tracker.levels.model import BONUS_UNVERIFIED, EQUITY_UNVERIFIED
from tracker.levels.pay import PAY_POLICIES

SECTIONS = ("ladder", "bonus_rule", "equity_rule", "vesting", "annual_refresh", "filed_base", "identity")


def _has_ladder(slug: str) -> bool:
    record = COMPANIES.get(slug)
    if record is None:
        return False
    if record.ladders:
        return True
    parent = COMPANIES.get(record.parent) if record.parent else None
    return bool(parent and parent.ladders)


def _filed() -> frozenset[str]:
    with TITLE_PAY.path.open(newline="", encoding="utf-8") as handle:
        return frozenset(row["company"] for row in csv.DictReader(handle))


def answered(section: str, slug: str, filed: frozenset[str] | None = None) -> bool:
    """Does the atlas answer `section` for this company?"""
    if section == "ladder":
        return _has_ladder(slug)
    if section == "filed_base":
        return slug in (filed if filed is not None else _filed())
    if section == "identity":
        identity = load_identity().get(slug)
        return identity is not None and identity.listed is not None
    policy = PAY_POLICIES.get(slug)
    if policy is None:
        return False
    if section in policy.unknown:
        return True  # searched, nothing found: an answer with a date
    if section == "bonus_rule":
        return policy.bonus_rule != BONUS_UNVERIFIED
    if section == "equity_rule":
        return policy.equity_rule != EQUITY_UNVERIFIED
    if section == "vesting":
        return policy.vesting is not None or policy.grant_term is not None
    if section == "annual_refresh":
        return policy.annual_refresh is not None
    raise ValueError(f"unknown section {section!r}")


def gaps(named: Iterable[str]) -> dict[str, list[str]]:
    """section -> the named companies it does not answer, sorted."""
    companies = sorted(set(named))
    filed = _filed()
    return {s: [c for c in companies if not answered(s, c, filed)] for s in SECTIONS}
