"""Every workflow runs code it names exactly, with the least it needs.

A tag such as `actions/checkout@v4` or `pgvector/pgvector:pg16` can be moved
to other code by whoever controls it, and the next run executes that code
with the workflow's token. So an action is referenced by its full commit SHA
(the version it is, in a trailing comment, for the reader and for Dependabot),
a service image by digest, and every workflow declares its `permissions`
instead of inheriting the repository default. Every job also states its
`timeout-minutes`, so a hung step fails within minutes instead of the runner's
six-hour default.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[2] / ".github" / "workflows").glob("*.yml"))
USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)(.*)$", re.M)
SHA = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
VERSION_NOTE = re.compile(r"^\s*#\s*v\d+(\.\d+){1,2}\s*$")


def _images(node) -> list[str]:
    if isinstance(node, dict):
        found = [node["image"]] if isinstance(node.get("image"), str) else []
        return found + [image for value in node.values() for image in _images(value)]
    if isinstance(node, list):
        return [image for value in node for image in _images(value)]
    return []


def _untimed_jobs(workflow: dict) -> list[str]:
    return [name for name, job in workflow.get("jobs", {}).items() if "timeout-minutes" not in job]


def test_the_scan_finds_the_workflows_and_their_actions():
    assert WORKFLOWS, "no workflows found"
    assert sum(len(USES.findall(w.read_text())) for w in WORKFLOWS) >= 10


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_commit_with_its_version_noted(workflow):
    loose = [
        f"{ref}{rest}" for ref, rest in USES.findall(workflow.read_text())
        if not ref.startswith("./") and not (SHA.match(ref) and VERSION_NOTE.match(rest))
    ]
    assert loose == [], f"{workflow.name}: reference by full SHA with '# vX.Y.Z': {loose}"


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_every_service_image_is_pinned_by_digest(workflow):
    images = _images(yaml.safe_load(workflow.read_text()))
    assert [i for i in images if "@sha256:" not in i] == []


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_every_workflow_declares_its_permissions(workflow):
    assert "permissions" in yaml.safe_load(workflow.read_text()), f"{workflow.name} inherits the default token"


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_every_job_declares_a_timeout(workflow):
    doc = yaml.safe_load(workflow.read_text())
    assert doc["jobs"], f"{workflow.name} has no jobs"
    assert _untimed_jobs(doc) == [], f"{workflow.name}: add timeout-minutes to these jobs"


def test_the_timeout_rule_reads_the_job_not_its_steps():
    """A step's timeout does not bound the job: only the job-level key counts."""
    workflow = {"jobs": {
        "timed": {"timeout-minutes": 5, "steps": []},
        "step_only": {"steps": [{"run": "x", "timeout-minutes": 5}]},
    }}
    assert _untimed_jobs(workflow) == ["step_only"]


@pytest.mark.parametrize(("ref", "rest", "pinned"), [
    ("actions/checkout@11d5960a326750d5838078e36cf38b85af677262", " # v4.4.0", True),
    ("actions/checkout@v4", "", False),
    ("actions/checkout@11d5960a326750d5838078e36cf38b85af677262", "", False),
])
def test_the_pin_rule_tells_a_pinned_reference_from_a_tag(ref, rest, pinned):
    """The negative controls for the rule above."""
    assert bool(SHA.match(ref) and VERSION_NOTE.match(rest)) is pinned
