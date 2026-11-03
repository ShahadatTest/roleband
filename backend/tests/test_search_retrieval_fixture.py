"""Structural guard for the frozen search-retrieval eval fixture.

Pure (no DB, no model): the scoring lives in `scripts.eval_search_retrieval`
(live-model, not pytest — repo testing policy). This locks the *shape* of the
frozen artifact so a careless re-freeze cannot silently weaken a hard gate —
e.g. promote a family/track-conflict row to `exact`/`close`, or leave a
(query, posting) pair unlabelled (which the harness would read as `irrelevant`
by default). Mirrors how route_table.json / the ratchet baseline are gated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "search_retrieval_eval.json"

CLASSES = {"exact", "close", "related", "irrelevant"}
_MUST_NOT = {
    "exact": [],
    "close": ["exact"],
    "related": ["exact", "close"],
    "irrelevant": ["exact", "close", "related"],
}


@pytest.fixture(scope="module")
def fx() -> dict:
    return json.loads(FIXTURE.read_text())


def test_postings_unique_and_complete(fx: dict) -> None:
    keys = [p["key"] for p in fx["postings"]]
    assert len(keys) == len(set(keys)), "duplicate posting keys"
    for p in fx["postings"]:
        # Real, frozen fields the harness reasons over must all be present.
        for field in ("company", "req_id", "title", "url", "department", "team", "family", "track", "level_band", "domains", "doc_text"):
            assert field in p, f"{p['key']} missing {field}"
        assert p["doc_text"].startswith(p["title"] or ""), "doc_text must be title\\ndescription"


def test_every_query_posting_pair_labelled_exactly_once(fx: dict) -> None:
    """No implicit labels: the harness defaults unlabelled pairs to irrelevant,
    so a missing pair is a silent label. Freeze must be exhaustive."""
    pkeys = {p["key"] for p in fx["postings"]}
    qkeys = {q["key"] for q in fx["queries"]}
    seen = set()
    for lab in fx["labels"]:
        pair = (lab["query"], lab["posting"])
        assert pair not in seen, f"duplicate label for {pair}"
        seen.add(pair)
        assert lab["query"] in qkeys and lab["posting"] in pkeys
    assert len(seen) == len(qkeys) * len(pkeys), "every (query, posting) pair must be labelled"


def test_class_and_must_not_derivation(fx: dict) -> None:
    for lab in fx["labels"]:
        assert lab["class"] in CLASSES
        assert lab["must_not_class"] == _MUST_NOT[lab["class"]], (
            f"{lab['query']}/{lab['posting']}: must_not_class must be derived from class"
        )


def test_hard_gates_encoded(fx: dict) -> None:
    """The labels must actually encode the headline invariants, so the
    fixture would fail a broken impl."""
    cls = {(lab["query"], lab["posting"]): lab["class"] for lab in fx["labels"]}

    # Product Manager / Program Manager on the exact Prime Video team are
    # related at most — never exact/close — against the ASM target query.
    for pm_row in ("amazon-3204869", "amazon-10427133"):
        assert cls[("pv_exact", pm_row)] == "related"
        assert cls[("pv_exact_lc", pm_row)] == "related"

    # Minimal pairs, two-directional: the IC engineers must not be
    # exact/close for "Engineering Manager"; program managers likewise for
    # "Product Manager".
    for eng in ("anthropic-5134895008", "anthropic-5211241008"):
        assert cls[("eng_manager", eng)] not in {"exact", "close"}
    for pgm in ("anthropic-5385653008", "anthropic-5207565008", "anthropic-5251699008"):
        assert cls[("product_manager", pgm)] not in {"exact", "close"}

    # No-answer control: zero relevant labels — nearest dense rows must be
    # rejected, so nothing here may be exact/close/related.
    no_answer = [lab for lab in fx["labels"] if lab["query"] == "no_answer_vet"]
    assert no_answer and all(lab["class"] == "irrelevant" for lab in no_answer)

    # Exactly one exact identity per identifier query.
    for q in ("url_amz_target", "reqid_ant_em"):
        exact = [lab for lab in fx["labels"] if lab["query"] == q and lab["class"] == "exact"]
        assert len(exact) == 1, f"{q} must have exactly one exact identity"
