"""Which skips are honest, and a switch that turns every other one into a failure.

A skip is invisible in a green run: a whole file of tests can skip in CI while
the run reports green, and a guard that greps one file's output protects that
file and nothing else.

This inverts the default where it matters. With `ROLEBAND_REQUIRE_INTEGRATION=1`
(set by `.github/workflows/backend.yml`) a skip is a FAILURE unless its reason
belongs to a category named below. Locally the variable is unset and nothing
changes: a laptop with no database still runs the pure suite.

Fail closed: an unknown reason is required. A new skip has to be added here, by
reason, to be allowed in CI -- which is the review this list exists to force.
"""

from __future__ import annotations

import os
import re

import pytest

ENV_FLAG = "ROLEBAND_REQUIRE_INTEGRATION"

#: Reasons that stay skips even when integration is required, each with why.
OPTIONAL_SKIPS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"embedding model not available offline"),
        "model weights are provisioned separately and never in CI (tests/test_embed.py)",
    ),
    (
        re.compile(r"[a-z0-9_-]+ serves no robots file"),
        "a parametrized case with nothing to verify for that source (tests/test_source_review.py)",
    ),
    (
        re.compile(r"[a-z0-9_-]+ genuinely covers [a-z0-9_-]+"),
        "a parametrized case whose premise does not hold for that adapter "
        "(tests/contracts/test_location_coverage.py)",
    ),
    (
        re.compile(r"caffeinate is macOS's"),
        "caffeinate is a macOS command and CI runs on Linux; the supervisor's "
        "other tests cover the launch without it (tests/test_supervisor_runner.py)",
    ),
)


def enforced() -> bool:
    return os.environ.get(ENV_FLAG) == "1"


def is_optional(reason: str) -> bool:
    """True when `reason` is a known, allowed skip. Unknown reasons are required."""
    return any(pattern.fullmatch(reason.strip()) for pattern, _why in OPTIONAL_SKIPS)


def skip_reason(longrepr: object) -> str:
    """The reason pytest recorded for a skip, without its `Skipped: ` prefix."""
    text = longrepr[2] if isinstance(longrepr, tuple) and len(longrepr) == 3 else str(longrepr)
    return str(text).removeprefix("Skipped: ").strip()


def _refuse(report, where: str) -> None:
    reason = skip_reason(report.longrepr)
    if is_optional(reason):
        return
    report.outcome = "failed"
    report.longrepr = (
        f"{where} skipped with {ENV_FLAG}=1, and this reason is not an allowed skip: "
        f"{reason!r}. Make the environment provide what the test needs, or add the "
        "reason to OPTIONAL_SKIPS in tests/skip_policy.py with why it may stay a skip."
    )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):  # noqa: ARG001 - pytest hook signature
    report = yield
    # `wasxfail` is an expected failure, not a skip anyone chose.
    if enforced() and report.skipped and not hasattr(report, "wasxfail"):
        _refuse(report, report.nodeid)
    return report


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(collector):  # noqa: ARG001 - pytest hook signature
    # A module-level `importorskip` skips the whole file at COLLECTION, where no
    # runtest report is ever made.
    report = yield
    if enforced() and report.skipped:
        _refuse(report, report.nodeid)
    return report
