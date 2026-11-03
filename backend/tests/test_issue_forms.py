"""Every issue form under `.github/ISSUE_TEMPLATE/` is one GitHub will show.

GitHub drops an invalid form from the "New issue" chooser without an error, so a
broken form is noticed only by a reporter who cannot find it. `form_errors`
checks the rules of GitHub's issue-form schema that a hand edit breaks most
often; the negative controls below prove each rule fires.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
TEMPLATES = REPO / ".github" / "ISSUE_TEMPLATE"
FORMS = sorted(TEMPLATES.glob("*.yml"))
FORMS = [p for p in FORMS if p.name != "config.yml"]

ELEMENT_TYPES = {"markdown", "textarea", "input", "dropdown", "checkboxes"}
ID = re.compile(r"^[A-Za-z0-9_-]+$")


def form_errors(form: object) -> list[str]:
    if not isinstance(form, dict):
        return ["the form is not a mapping"]
    errors = [f"missing `{key}`" for key in ("name", "description", "body") if not form.get(key)]
    body = form.get("body") or []
    ids: set[str] = set()
    labels: set[str] = set()
    for n, element in enumerate(body):
        kind = element.get("type")
        attrs = element.get("attributes") or {}
        if kind not in ELEMENT_TYPES:
            errors.append(f"element {n}: unknown type {kind!r}")
            continue
        if kind == "markdown":
            if not attrs.get("value"):
                errors.append(f"element {n}: markdown without a value")
            continue
        label = attrs.get("label")
        if not label:
            errors.append(f"element {n}: no label")
        elif label in labels:
            errors.append(f"element {n}: label {label!r} repeats")
        labels.add(label)
        element_id = element.get("id")
        if element_id is not None:
            if not ID.match(str(element_id)):
                errors.append(f"element {n}: id {element_id!r} has characters GitHub refuses")
            elif element_id in ids:
                errors.append(f"element {n}: id {element_id!r} repeats")
            ids.add(element_id)
        if kind == "dropdown":
            options = attrs.get("options") or []
            if not options or len(set(options)) != len(options):
                errors.append(f"element {n}: dropdown options empty or repeated")
        if kind == "checkboxes":
            boxes = attrs.get("options") or []
            if not boxes or not all(isinstance(b, dict) and b.get("label") for b in boxes):
                errors.append(f"element {n}: checkbox without a label")
    if body and all(e.get("type") == "markdown" for e in body):
        errors.append("only markdown: a form needs at least one field")
    return errors


def test_the_issue_forms_exist():
    assert {p.name for p in FORMS} >= {"bug.yml", "company.yml", "improvement.yml"}


@pytest.mark.parametrize("path", FORMS, ids=lambda p: p.name)
def test_issue_form_is_valid(path: Path):
    assert form_errors(yaml.safe_load(path.read_text())) == []


@pytest.mark.parametrize("path", FORMS, ids=lambda p: p.name)
def test_issue_form_lands_in_triage(path: Path):
    assert "triage" in yaml.safe_load(path.read_text()).get("labels", [])


def test_an_issue_that_fits_no_form_has_somewhere_to_go():
    """A question or a docs problem fits none of the forms: with blank issues
    off, it needs a contact link (Discussions, a support page) instead."""
    config = yaml.safe_load((TEMPLATES / "config.yml").read_text())
    assert config.get("blank_issues_enabled", True) is True or config.get("contact_links")


GOOD = {
    "name": "n",
    "description": "d",
    "body": [{"type": "textarea", "id": "a", "attributes": {"label": "A"}}],
}


@pytest.mark.parametrize(
    "broken",
    [
        {**GOOD, "name": ""},
        {**GOOD, "body": [{"type": "text", "attributes": {"label": "A"}}]},
        {**GOOD, "body": [{"type": "input", "id": "a b", "attributes": {"label": "A"}}]},
        {**GOOD, "body": GOOD["body"] * 2},
        {**GOOD, "body": [{"type": "input", "attributes": {}}]},
        {**GOOD, "body": [{"type": "dropdown", "attributes": {"label": "A", "options": ["x", "x"]}}]},
        {**GOOD, "body": [{"type": "checkboxes", "attributes": {"label": "A", "options": [{"required": True}]}}]},
        {**GOOD, "body": [{"type": "markdown", "attributes": {"value": "only text"}}]},
    ],
    ids=["no-name", "unknown-type", "bad-id", "repeated-id", "no-label", "repeated-option",
         "unlabelled-checkbox", "markdown-only"],
)
def test_validator_rejects_a_broken_form(broken: dict):
    assert form_errors(GOOD) == []
    assert form_errors(broken) != []
