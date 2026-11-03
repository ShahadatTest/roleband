"""`meta.say`: notifications as catalog keys the dashboard renders.

The keys are a contract with rows already stored, so they are frozen in
`tests/fixtures/notification_keys.json` (key -> parameter names). The
dashboard's half of the contract renders every sample from its catalog and
must reproduce the stored English (`notificationText.test.ts`); this half keeps
the samples current and complete.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from scripts import export_notification_samples as export
from tracker.notifications import coverage, digest, events, pursuit_due, run_result, say

REGISTRY = Path(__file__).parent / "fixtures" / "notification_keys.json"
SOURCES = tuple(Path(module.__file__) for module in (events, run_result, digest, pursuit_due, coverage, say))


def _registry() -> dict[str, list[str]]:
    return json.loads(REGISTRY.read_text())


def _said() -> dict[str, set[frozenset[str]]]:
    out: dict[str, set[frozenset[str]]] = {}
    for sample in export.samples():
        for key, params in say.keys(sample["say"]):
            out.setdefault(key, set()).add(params)
    return out


def test_the_committed_samples_are_current():
    assert export.COMMITTED.read_text() == export.render(), (
        "run .venv/bin/python -m scripts.export_notification_samples"
    )


def test_every_key_a_notification_says_is_registered_with_its_parameters():
    registry = _registry()
    for key, shapes in _said().items():
        assert key in registry, f"{key} is not in notification_keys.json"
        assert shapes == {frozenset(registry[key])}, f"{key} is said with {shapes}, registered {registry[key]}"


def test_every_registered_key_has_a_sample():
    """The dashboard proves its messages only through samples: a key no sample
    says would ship a message nothing checks."""
    missing = set(_registry()) - set(_said())
    assert not missing, f"no sample says {sorted(missing)}; add a case to scripts/export_notification_samples.py"


def test_every_key_the_classifiers_name_is_registered():
    """A branch added without a sample says its key here before it reaches a row."""
    registry = set(_registry())
    named = {m for path in SOURCES for m in re.findall(r"notif-[a-z-]*", path.read_text())}
    assert named, "the scan found no keys; the pattern no longer matches how keys are written"
    for key in named:
        if key.endswith("-"):  # a family built from a value, such as notif-fit-{band}
            assert any(k.startswith(key) for k in registry), f"no registered key starts with {key}"
        else:
            assert key in registry, f"{key} is named in the classifiers but not registered"


def test_a_say_mirrors_its_english_sentence_for_sentence():
    """Negative control on the walk itself: one sample, read by hand."""
    sample = next(s for s in export.samples() if s["case"] == "problems-while-asleep")
    assert sample["body"].startswith("Finished at 2026-09-27 10:05 UTC after 2h 5m. This machine was asleep")
    title, *body = [sample["say"]["title"], *sample["say"]["body"]]
    assert title == {"k": "notif-scan-problems", "p": {}}
    assert [s["k"] for s in body] == ["notif-finished-at", "notif-asleep", "notif-problems-at", "notif-scan-summary"]
    assert body[1]["p"]["duration"] == {"k": "notif-duration-minutes", "p": {"m": 16, "s": 27}}


def test_new_english_is_derived_from_the_catalog_descriptor(monkeypatch):
    from tracker.notifications.catalog_gen import MESSAGES
    from tracker.notifications.events import ClassifiedNotif
    # A copy edit has one owner; producers carry no parallel sentences.
    monkeypatch.setitem(MESSAGES, "notif-closed", lambda a: f"Catalog says {a['company']}")
    notification = ClassifiedNotif(priority="high", category="closed", meta={
        "say": {"title": {"k":"notif-closed", "p":{"company":"Acme"}}, "body":["Third-party title"]},
    })
    assert (notification.title, notification.body) == ("Catalog says Acme", "Third-party title")
