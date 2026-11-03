"""What `pmset` answers on a Mac, for tests of the power gate.

The answers are a real Mac's where it can show them: a full wake on mains.
The battery line is `pmset -g batt` unplugged; the dark wake line is Apple's
capability model for one (the CPU and network, no graphics), which a shut Mac
has not yet been sampled in.
"""

from __future__ import annotations

from tracker.platform import power

FULL_WAKE = "Current System Capabilities are: CPU Graphics Audio Network \nCurrent Power State: 4\n"
DARK_WAKE = "Current System Capabilities are: CPU Network \nCurrent Power State: 4\n"
ON_MAINS = (
    "Now drawing from 'AC Power'\n"
    " -InternalBattery-0 (id=24248419)\t100%; charged; 0:00 remaining present: true\n"
)
ON_BATTERY = (
    "Now drawing from 'Battery Power'\n"
    " -InternalBattery-0 (id=24248419)\t87%; discharging; 6:12 remaining present: true\n"
)
#: A desktop Mac: mains, and no battery to list.
DESKTOP = "Now drawing from 'AC Power'\n"


def machine(monkeypatch, *, systemstate: str | None = FULL_WAKE, batt: str | None = ON_MAINS) -> None:
    """What `pmset` answers for the rest of the test."""
    answers = {"systemstate": systemstate, "batt": batt}
    monkeypatch.setattr(power, "_pmset", lambda _flag, what: answers[what])
