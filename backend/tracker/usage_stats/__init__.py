"""Usage sharing: what RoleBand sends to its usage analytics service (`sender.py`) when the user shares.

Plan and decisions: docs/architecture.md. In one paragraph: nothing is
counted, stored for sending or sent until the user shares a consent group
(`consent.py`); the environment can only turn sharing off (`kill.py`); every
backend event is declared in a frozen catalogue whose properties are enums,
flags and bounded numbers, never free text (`registry.py`); events wait in the
`usage_events` outbox (`outbox.py`) and leave at most once a day in one batch
(`flush.py`, from the scheduler tick). Crashes are reduced to an exception type
and in-app frames before they are stored (`scrub.py`).

The name is not `telemetry`: that already names the local AI task log
(`intelligence_runtime/telemetry.py`) and the dashboard's top-bar stats strip.
"""
