"""One host allowance across the scheduler and the directory pass."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tracker.platform import ratelimit
from tracker.platform.ratelimit import RateLimiter, RateLimiterPool, SharedSlot, _slot_path


class FakeTime:
    def __init__(self) -> None:
        self.now = 1_000.0
        self.starts: list[tuple[str, float]] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


def _process(fake: FakeTime, shared: SharedSlot | None, delay: float = 2.0) -> RateLimiter:
    """What each process builds for scope `greenhouse`: its own limiter."""
    return RateLimiter(delay, shared=shared, clock=fake.clock, sleep=fake.sleep)


async def _interleave(fake: FakeTime, scheduler: RateLimiter, directory: RateLimiter, rounds: int = 4):
    for _ in range(rounds):
        for name, limiter in (("scheduler", scheduler), ("directory", directory)):
            await limiter.wait()
            fake.starts.append((name, fake.now))
    return [at for _, at in fake.starts]


@pytest.mark.asyncio
async def test_two_process_local_pacers_double_the_hosts_rate():
    """The control: process-local pacers each pace only their own process."""
    fake = FakeTime()
    starts = await _interleave(fake, _process(fake, None), _process(fake, None))
    gaps = [b - a for a, b in zip(starts, starts[1:], strict=False)]
    assert min(gaps) == 0.0, "two pools send back to back"


@pytest.mark.asyncio
async def test_a_shared_slot_makes_the_delay_the_combined_bound(tmp_path):
    fake = FakeTime()
    path = _slot_path(tmp_path, "greenhouse")
    starts = await _interleave(fake, _process(fake, SharedSlot(path)), _process(fake, SharedSlot(path)))
    gaps = [b - a for a, b in zip(starts, starts[1:], strict=False)]
    assert min(gaps) >= 2.0
    names = [name for name, _ in fake.starts]
    assert names[:4] == ["scheduler", "directory", "scheduler", "directory"], (
        "requests interleave: neither process waits for the other's whole pass"
    )


@pytest.mark.asyncio
async def test_different_scopes_never_wait_on_each_other(tmp_path):
    fake = FakeTime()
    greenhouse = _process(fake, SharedSlot(_slot_path(tmp_path, "greenhouse")))
    lever = _process(fake, SharedSlot(_slot_path(tmp_path, "lever")))
    await greenhouse.wait()
    await lever.wait()
    assert fake.now == 1_000.0


def test_a_stale_reservation_is_not_a_queue(tmp_path):
    slot = SharedSlot(tmp_path / "x.slot")
    (tmp_path / "x.slot").write_text(repr(1_000.0 + 10_000))
    assert slot.reserve(2.0, now=1_000.0) == 1_000.0
    (tmp_path / "x.slot").write_text("not a number")
    assert slot.reserve(2.0, now=1_000.0) == 1_000.0


def test_scope_files_are_distinct_for_scopes_that_sanitize_alike(tmp_path):
    a = _slot_path(tmp_path, "workday:acme.wd1|External")
    b = _slot_path(tmp_path, "workday:acme.wd1/External")
    assert a != b and a.parent == tmp_path


def test_pools_stay_process_local_unless_an_entrypoint_enables_sharing(tmp_path, monkeypatch):
    monkeypatch.setattr(ratelimit, "_shared_dir", None)
    assert RateLimiterPool().get("greenhouse", 1.0)._shared is None
    ratelimit.enable_shared_pacing(tmp_path / "pacing")
    try:
        assert RateLimiterPool().get("greenhouse", 1.0)._shared is not None
        assert (tmp_path / "pacing").is_dir()
    finally:
        ratelimit.enable_shared_pacing(None)


@pytest.mark.parametrize("module", [
    "tracker.workflows.scheduler", "tracker.workflows.daily", "tracker.workflows.directory_sweep",
    "tracker.workflows.discover_roles", "tracker.workflows.retry_sources",
    # Reads posting pages when someone opens a posting.
    "tracker.api.app",
])
def test_every_provider_facing_entrypoint_enables_sharing(module):
    import importlib
    import inspect

    source = inspect.getsource(importlib.import_module(module))
    assert "enable_shared_pacing(PACING_DIR)" in source, module


def test_real_processes_share_one_allowance(tmp_path):
    """flock across two OS processes, real clock: combined starts stay spaced.

    What is compared is the start each `wait()` was GRANTED (the reservation),
    not the instant its sleep happened to return. Wake-ups carry the host's
    scheduling jitter: on a loaded machine one process oversleeps its slot while
    the other wakes on time, and two correctly spaced grants read 10 ms apart.
    Measured on wake-ups, this test would fail in full-suite runs and pass alone;
    the grants are the pacer's actual promise, and a pacer that stopped sharing
    (a per-process slot, no lock) still hands both processes the same instants.
    """
    script = textwrap.dedent(f"""
        import asyncio, json
        from pathlib import Path
        from tracker.platform import ratelimit
        granted = []
        reserve = ratelimit.SharedSlot.reserve
        def recording(self, min_delay, now):
            start = reserve(self, min_delay, now)
            granted.append(start)
            return start
        ratelimit.SharedSlot.reserve = recording
        async def main():
            limiter = ratelimit.RateLimiterPool(shared_dir=Path({str(tmp_path)!r})).get("greenhouse", 0.05)
            for _ in range(6):
                await limiter.wait()
            print(json.dumps(granted))
        asyncio.run(main())
    """)
    backend = Path(__file__).resolve().parents[1]
    procs = [
        subprocess.Popen([sys.executable, "-c", script], cwd=backend, stdout=subprocess.PIPE, text=True)
        for _ in range(2)
    ]
    starts = sorted(t for p in procs for t in json.loads(p.communicate(timeout=60)[0]))
    gaps = [b - a for a, b in zip(starts, starts[1:], strict=False)]
    assert len(starts) == 12
    assert min(gaps) >= 0.045, gaps
