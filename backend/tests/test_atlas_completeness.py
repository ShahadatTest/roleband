"""The atlas answers every named company, or lists the gap.

`tests/fixtures/atlas_gaps.json` names, per section, the named companies the
atlas does not answer yet. Contracts:

- The committed list is exactly the gaps: a company that joins a gap (a new
  catalog company without data, a row removed) fails by name, and one that
  leaves a gap fails until the list is rewritten (`scripts.atlas_completeness
  --write`), so the list only ever shrinks with the work that fills it.
- A company the atlas knows nothing about is a gap in every section; a parent's
  ladder answers for its child (google-deepmind); a policy default
  ("unverified") is never an answer.
- `level_base` (our per-level base, in shadow) is scored with the rest: its
  answers come from `tracker.enrich.level_pay`, which reads titles with the
  posting reader, so a reader change that loses a company fails here by name.
"""

from __future__ import annotations

import json

from scripts.atlas_completeness import GAPS_FILE, SCOREBOARD, scoreboard_gaps
from tracker.company_discovery import named_companies
from tracker.levels.completeness import SECTIONS, answered, gaps
from tracker.levels.model import PayPolicy
from tracker.levels.pay import PAY_POLICIES


def test_the_committed_gap_list_is_exactly_the_gaps():
    committed = json.loads(GAPS_FILE.read_text(encoding="utf-8"))
    found = scoreboard_gaps(named_companies())
    assert sorted(committed) == sorted(SCOREBOARD)
    for section in SCOREBOARD:
        joined = sorted(set(found[section]) - set(committed[section]))
        left = sorted(set(committed[section]) - set(found[section]))
        assert not joined, f"{section}: no atlas answer for {joined}; add the data (the list only shrinks)"
        assert not left, f"{section}: {left} now answered; run scripts.atlas_completeness --write"


def test_a_company_the_atlas_does_not_know_is_a_gap_everywhere():
    found = scoreboard_gaps({"no-such-employer"})
    assert all(found[s] == ["no-such-employer"] for s in SCOREBOARD)
    assert set(SECTIONS) < set(SCOREBOARD) and set(gaps({"no-such-employer"})) == set(SECTIONS)


def test_answers_come_from_the_atlas_not_from_defaults(monkeypatch):
    # Explicit fixture: an employer gaining evidence must not break this contract.
    monkeypatch.setitem(PAY_POLICIES, "unresearched-employer", PayPolicy("unresearched-employer"))
    assert answered("ladder", "google-deepmind")  # its parent's ladder
    assert answered("vesting", "google") and not answered("vesting", "unresearched-employer")
    assert answered("bonus_rule", "netflix")  # "none" is an answer
    assert not answered("bonus_rule", "unresearched-employer")  # the default, unverified, is not
    assert answered("filed_base", "meta")  # files visas though we collect none of its postings
    assert not answered("filed_base", "gitlab")  # files none


def test_level_base_needs_a_priced_ladder_not_filings_alone():
    found = scoreboard_gaps({"google", "gitlab", "rocket-lab", "palantir", "broadcom"})
    assert "google" not in found["level_base"]
    assert "gitlab" not in found["level_base"]  # direct posted titles price several bands
    assert "rocket-lab" not in found["level_base"]  # fresh employer postings price several bands
    assert "palantir" not in found["level_base"]  # reported mid + filed entry prices its SWE ladder
    assert answered("filed_base", "broadcom")
    assert "broadcom" in found["level_base"]  # filings and unmapped aggregates are not a priced ladder


def test_the_named_set_is_the_136():
    named = named_companies()
    assert len(named) == 136
    assert {"google", "servicenow", "meta", "netflix"} <= named
