"""What a listing connector must ship beside its class: a recorded fixture
and a harness entry. The completeness gate and the contribution rehearsal
both ask this one function."""

from __future__ import annotations

from tests.contracts.conftest import HARNESSES, fixture_dir


def missing_artifacts(names) -> list[str]:
    """Which contract artifacts each named adapter still owes.

    Takes the names rather than reading `ADAPTER_REGISTRY`, so the rehearsal in
    `tests/test_contribution_rehearsal.py` can hand it an adapter that was never
    onboarded and prove the gate names it: the same reason the route-table gate
    accepts a throwaway app.
    """

    problems: list[str] = []
    for name in names:
        directory = fixture_dir(name)
        if not (directory / "page1.json").is_file():
            problems.append(f"{name}: missing tests/fixtures/listings/{name}/page1.json")
        if name not in HARNESSES:
            problems.append(
                f"{name}: no harness registered in tests/contracts/conftest.py HARNESSES"
            )
    return problems
