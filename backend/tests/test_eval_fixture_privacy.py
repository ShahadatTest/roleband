"""Privacy guard for the two frozen eval fixtures that ship with the repo.

`relevance_eval.json` and `search_retrieval_eval.json` mix two kinds of text:
employer postings captured as published (out of scope here, posting bodies
keep their published contacts) and text WE wrote: intent statements, query
texts, label reasons, notes, todos. The second kind must never carry a
person's own job search: first-person remarks, an email, a home-directory
path, a phone number, or application-status talk. A re-freeze that adds one
fails here by field path.

Every authored string is walked, not a field list, so a field added later is
covered without editing this test. Only the `postings` subtree is skipped, and
posting URLs are checked separately: a stored URL may carry what the board
itself puts there, never a tracking parameter that says how a person reached
it (the production identity rule, `search.policy.identity_url_key`, decides
which parameters are tracking).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest

from tracker.search.policy import identity_url_key

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EVAL_FIXTURES = ("relevance_eval.json", "search_retrieval_eval.json")

# Case-sensitive "I": a lower-case `i` is a roman numeral or "i.e.", never a
# speaker. "we"/"our" stay legal: the semantic-intent cohort is phrased as a
# team ("keep bad actors from misusing our product").
_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("first person", re.compile(r"\bI(?:'m|'ve|'d|'ll)?\b")),
    ("first person", re.compile(r"\b(?:my|me|mine|myself)\b", re.I)),
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("home path", re.compile(r"(?:/Users/|/home/|~/|[A-Za-z]:\\Users\\)")),
    ("phone", re.compile(r"\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")),
    (
        "job-search status",
        re.compile(
            r"\b(?:applied (?:to|for)|interview(?:ed|ing|s)?|recruiter|referr(?:al|ed)"
            r"|offer letter|got an offer|ghosted|hiring manager said)\b",
            re.I,
        ),
    ),
)


def personal_markers(text: str) -> list[str]:
    """Names of every personal-data marker found in one authored string."""
    return [name for name, pattern in _MARKERS if pattern.search(text)]


def _authored_strings(node: object, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            if path == "" and key == "postings":
                continue
            yield from _authored_strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _authored_strings(value, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, node


@pytest.fixture(scope="module", params=EVAL_FIXTURES)
def fixture(request) -> tuple[str, dict]:
    return request.param, json.loads((FIXTURES / request.param).read_text())


# --- the guard itself must be able to fail ---------------------- #


@pytest.mark.parametrize(
    ("text", "marker"),
    [
        ("I applied to this one in May", "first person"),
        ("I'm L6 today, so this is a step up", "first person"),
        ("my current comp is 410k", "first person"),
        ("matches what I want", "first person"),
        ("ask jane.doe@example.com for the referral", "email"),
        ("copied from /Users/someone/notes/search.txt", "home path"),
        ("call back on (415) 555-0134", "phone"),
        ("recruiter screen on Tuesday", "job-search status"),
        ("interviewed here in 2024, no offer", "job-search status"),
        ("got an offer, declined", "job-search status"),
    ],
)
def test_guard_catches_a_planted_personal_remark(text: str, marker: str) -> None:
    assert marker in personal_markers(text)


@pytest.mark.parametrize(
    "text",
    [
        "Applied Science Manager, Prime Video Personalization & Discovery",
        "keep bad actors from misusing our product",
        "§7.3 no-answer control: nearest dense rows must be rejected; zero semantic-only admission",
        "High School Mathematics Teacher, Grade 11",
        "5316593008",
        "microsoft rows read 1.98M-3.55M base",
        "Senior Engineering Manager II, Inference",
    ],
)
def test_guard_passes_authored_eval_wording(text: str) -> None:
    assert personal_markers(text) == []


# --- the committed fixtures ------------------------------------------------- #


def test_authored_text_carries_no_personal_marker(fixture) -> None:
    name, data = fixture
    strings = list(_authored_strings(data, ""))
    assert strings, f"{name}: no authored text found; the walk is broken"
    hits = [f"{path}: {markers} in {text[:80]!r}"
            for path, text in strings if (markers := personal_markers(text))]
    assert not hits, f"{name}:\n  " + "\n  ".join(hits)


def test_posting_urls_carry_no_tracking_parameter() -> None:
    data = json.loads((FIXTURES / "search_retrieval_eval.json").read_text())
    bad = []
    for posting in data["postings"]:
        url = posting["url"]
        parts = urlsplit(url)
        stored = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
        identity = urlsplit(identity_url_key(url) or "").query
        # The identity key drops tracking parameters and the fragment and
        # nothing else, so any difference is a tracking parameter.
        if parts.fragment or stored != identity:
            bad.append(f"{posting['key']}: {url}")
    assert not bad, "\n  ".join(["posting URLs carry tracking parameters:", *bad])
