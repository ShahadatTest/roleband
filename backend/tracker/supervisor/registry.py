"""Every job the supervisor runs: what it runs, when, and what it waits for.

One entry per job, the same pattern as `POST_PASSES`; tests read the table and the
due function decides from it. A job is a command run from a directory of the
checkout. `{python}` in a command is the supervisor's own interpreter, so a child
runs on the same virtualenv as its parent.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import time
from enum import StrEnum

from tracker.platform.paths import PACKAGED


@dataclass(frozen=True)
class Every:
    """Every `seconds` from the last start; a start that falls while the job runs
    is missed, as launchd's `StartInterval` misses it."""

    seconds: int


@dataclass(frozen=True)
class Daily:
    """Once a day at `at`, local time. With `catch_up`, a day whose slot passed
    while the machine slept runs once at the first chance after it."""

    at: time
    catch_up: bool = True


@dataclass(frozen=True)
class OnRequest:
    """Only when asked."""


@dataclass(frozen=True)
class OnChange:
    """When a watched fingerprint has differed from the accepted one for
    `settle_seconds`, so a burst of edits starts one run, not one per edit."""

    settle_seconds: int = 60


@dataclass(frozen=True)
class AtDeadline:
    """When the job itself asked to run next (a provider's next free slot)."""


Schedule = Every | Daily | OnRequest | OnChange | AtDeadline


class Power(StrEnum):
    #: Runs in any power state, a maintenance wake included.
    NONE = "none"
    #: Waits out a maintenance wake (lid shut): nobody sees the result, and a read
    #: that crosses a sleep cannot close a posting.
    AWAKE = "awake"
    #: Also waits for mains power: the work is long and the battery is the user's.
    MAINS = "mains"
    #: Mains for scheduled work, awake only for work the user asked for.
    BY_TRIGGER = "by_trigger"


@dataclass(frozen=True)
class JobSpec:
    name: str
    command: tuple[str, ...]
    schedule: Schedule
    #: Working directory, relative to the checkout. Python jobs run from `backend`,
    #: where `.env` and `pytest.ini` are read.
    cwd: str = "backend"
    power: Power = Power.AWAKE
    #: Waits for a passing preflight: the job reads third-party sites or writes
    #: collected or derived domain data.
    gated: bool = False
    #: Touches the database, so it waits while the code is ahead of the schema.
    uses_database: bool = True
    #: Runs once per argument (one live run per plugin), not once per job.
    per_argument: bool = False
    #: Hard stop after this much awake time; None leaves liveness to the job's own
    #: heartbeat.
    timeout_seconds: int | None = None
    #: SIGTERM to SIGKILL, on a cancel or a timeout.
    grace_seconds: int = 30
    #: Keep the machine from idle-sleeping while it runs.
    caffeinate: bool = False
    #: Extra environment for the child; `{python}` in a value is the supervisor's
    #: interpreter.
    env: tuple[tuple[str, str], ...] = ()
    #: Reaches a third party (a careers site, a model host, the usage endpoint).
    #: A rehearsal (`run --dry-run-network`) runs these without their requests.
    network: bool = False


MINUTE = 60
HOUR = 60 * MINUTE

JOBS: tuple[JobSpec, ...] = (
    JobSpec(
        "scan",
        ("{python}", "-m", "tracker.supervisor.entries", "scan"),
        Every(10 * MINUTE),
        # The tick waits for mains itself when the user's plan asks it to.
        power=Power.AWAKE,
        gated=True,
        # A scan's liveness is its run heartbeat, which survives a sleep; a
        # wall-clock limit would end a healthy scan at the lid opening.
        timeout_seconds=None,
        caffeinate=True,
        network=True,
    ),
    JobSpec(
        "directory",
        ("{python}", "-m", "tracker.supervisor.entries", "directory"),
        Every(10 * MINUTE),
        power=Power.MAINS,
        gated=True,
        timeout_seconds=3 * HOUR + 10 * MINUTE,
        caffeinate=True,
        network=True,
    ),
    JobSpec(
        "health",
        ("{python}", "-m", "tracker.supervisor.entries", "health"),
        Every(5 * MINUTE),
        power=Power.NONE,
        # It is what notices a database that is down or behind; it must not wait
        # for one. Starting a stopped database is the supervisor's own job.
        uses_database=False,
        timeout_seconds=5 * MINUTE,
    ),
    JobSpec(
        "plugins_due",
        ("{python}", "-m", "tracker.supervisor.entries", "plugins_due"),
        Every(5 * MINUTE),
        # Only asks: each run it asks for is gated and waits for its own power.
        power=Power.AWAKE,
        timeout_seconds=5 * MINUTE,
    ),
    JobSpec(
        "usage_send",
        ("{python}", "-m", "tracker.supervisor.entries", "usage_send"),
        Every(6 * HOUR),
        # The send waits out a maintenance wake itself, and decides whether a
        # day's batch is due; a run that finds none costs one query.
        power=Power.NONE,
        timeout_seconds=5 * MINUTE,
        network=True,
    ),
    JobSpec(
        "plugin_run",
        ("{python}", "-m", "tracker.plugins.cli", "run"),
        OnRequest(),
        power=Power.BY_TRIGGER,
        gated=True,
        per_argument=True,
        timeout_seconds=6 * HOUR,
        grace_seconds=15,
        caffeinate=True,
        network=True,
    ),
    JobSpec(
        "role_discovery",
        ("{python}", "-m", "tracker.supervisor.entries", "role_discovery"),
        OnRequest(),
        gated=True,
        timeout_seconds=2 * HOUR,
        caffeinate=True,
        network=True,
    ),
    JobSpec(
        "reembed",
        ("{python}", "-m", "tracker.supervisor.entries", "reembed"),
        OnRequest(),
        power=Power.NONE,
        gated=True,
        timeout_seconds=2 * HOUR,
        network=True,
    ),
    JobSpec(
        "reestimate",
        ("{python}", "-m", "tracker.plugins.reestimate_cli", "--wait", "600"),
        OnRequest(),
        power=Power.NONE,
        gated=True,
        timeout_seconds=30 * MINUTE,
    ),
    JobSpec(
        "prices",
        ("{python}", "-m", "tracker.supervisor.entries", "prices"),
        # On a key save and "Update now" (requests), and at the time its own last
        # run named: the next ticker due, or the next slot the budget allows.
        AtDeadline(),
        # Not gated: nobody waits on a preflight for a quote, and the rows are
        # refetchable reference data.
        power=Power.AWAKE,
        timeout_seconds=15 * MINUTE,
        network=True,
    ),
    JobSpec(
        "backup",
        ("deploy/backup_db.sh",),
        Daily(time(6, 30)),
        cwd=".",
        power=Power.NONE,
        timeout_seconds=30 * MINUTE,
    ),
    JobSpec(
        "preflight",
        ("../deploy/preflight.sh",),
        OnChange(settle_seconds=60),
        power=Power.NONE,
        # Its suite builds scratch databases of its own; the schema of the live
        # one is not its concern.
        uses_database=False,
        timeout_seconds=15 * MINUTE,
        # The script's own suite limit, inside the job's: the script then says
        # why it stopped instead of being killed mid-sentence.
        env=(("ROLEBAND_PREFLIGHT_PYTHON", "{python}"), ("ROLEBAND_PREFLIGHT_TIMEOUT", str(14 * MINUTE))),
    ),
    JobSpec(
        "dashboard_build",
        ("deploy/build_dashboard.sh",),
        OnRequest(),
        cwd=".",
        power=Power.NONE,
        uses_database=False,
        timeout_seconds=10 * MINUTE,
    ),
)

if PACKAGED:
    JOBS = tuple(
        replace(job, command=("{python}", "-m", "tracker.supervisor.entries", "backup"), cwd="backend")
        if job.name == "backup" else job
        for job in JOBS if job.name not in {"preflight", "dashboard_build"}
    )

BY_NAME: dict[str, JobSpec] = {job.name: job for job in JOBS}


def job(name: str) -> JobSpec:
    try:
        return BY_NAME[name]
    except KeyError:
        raise KeyError(f"no job named {name!r}") from None
