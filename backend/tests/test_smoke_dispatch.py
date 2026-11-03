"""What `scripts.smoke_adapters` agrees to smoke.

The script makes deliberate live requests, which is why it is gated. A dispatch
of `[args[0]] if args[0] in COMPANIES else list(COMPANIES)` would let an
argument it did not recognise widen the run from one source to every built-in:
a typo, or a catalog-only slug like `datadog`, would fire every live source
instead of failing.

No network here. `run_one` is replaced, so these assert the dispatch decision
and nothing else; the live behavior is the script's own job.
"""

from __future__ import annotations

import pytest

from scripts import smoke_adapters
from tracker.config import COMPANIES

pytestmark = pytest.mark.asyncio


@pytest.fixture
def dispatched(monkeypatch):
    """Record (company, limit) pairs instead of making requests."""
    calls: list[tuple[str, int]] = []

    async def fake_run_one(company: str, limit: int) -> None:
        calls.append((company, limit))

    monkeypatch.setattr(smoke_adapters, "run_one", fake_run_one)

    async def run(argv: list[str]) -> tuple[int, list[tuple[str, int]]]:
        monkeypatch.setattr(smoke_adapters.sys, "argv", ["smoke_adapters", *argv])
        code = await smoke_adapters.main()
        return code, calls

    return run


async def test_an_unknown_company_refuses_instead_of_smoking_everything(dispatched, capsys):
    """The defect. Widening scope on an unrecognised name is the opposite of
    what the one deliberately-narrow live command should do."""
    code, calls = await dispatched(["datadog", "3"])

    assert code == 2
    assert calls == [], "an unknown name must reach no source at all"
    assert "unknown company 'datadog'" in capsys.readouterr().err


async def test_the_refusal_names_what_it_can_smoke_and_where_else_to_look(dispatched, capsys):
    """A refusal that does not say what IS valid just gets retried blind. The
    pointer matters too: a catalog-only company has no built-in config, so the
    board check is the right tool rather than this one."""
    await dispatched(["nosuchco"])
    err = capsys.readouterr().err

    assert all(name in err for name in ("anthropic", "spotify", "google"))
    assert "check_catalog_tokens" in err


async def test_a_named_built_in_smokes_only_itself(dispatched):
    code, calls = await dispatched(["anthropic", "3"])

    assert code == 0
    assert calls == [("anthropic", 3)]


async def test_no_argument_still_smokes_every_built_in(dispatched):
    code, calls = await dispatched([])

    assert code == 0
    assert [company for company, _ in calls] == list(COMPANIES)
    assert {limit for _, limit in calls} == {5}


async def test_a_bare_number_is_a_limit_for_the_whole_roster(dispatched):
    """Preserved behavior: the first argument is a limit when it is a digit, so
    `smoke_adapters 2` still means "everything, two jobs each"."""
    code, calls = await dispatched(["2"])

    assert code == 0
    assert [company for company, _ in calls] == list(COMPANIES)
    assert {limit for _, limit in calls} == {2}
