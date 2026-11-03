"""Whether OUR network is up: the one probe both scans ask.

A read that fails when no job site at all accepts a connection is our outage,
not the board's: the directory scan records nothing for it and waits, and the
collector records the source as cut by our host (`suspended`), so neither a
board's check nor a binding's health pays for a dropped connection.

The probe opens a TCP connection to five large job-site hosts and closes it; it
sends no request. Five independent companies' hosts refusing us at once while
our own network works is not a case worth a second probe, with one exception
the callers carry: a network that filters job sites answers like no network at
all, so the probe only ever explains a read that already failed. It never stops
a scan from starting.
"""

from __future__ import annotations

import asyncio

#: Independent job-site hosts: reaching any one means our network is up.
PROBE_HOSTS = (
    "boards-api.greenhouse.io", "api.ashbyhq.com", "apply.workable.com",
    "api.lever.co", "careers.smartrecruiters.com",
)


async def _reach(host: str, timeout: float) -> bool:
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, 443), timeout)
    except (OSError, TimeoutError):
        return False
    writer.close()
    return True


async def network_up(timeout: float = 5.0) -> bool:
    """Whether any probe host accepts a connection; answers at the first that does."""
    probes = [asyncio.ensure_future(_reach(host, timeout)) for host in PROBE_HOSTS]
    try:
        for reached in asyncio.as_completed(probes):
            if await reached:
                return True
        return False
    finally:
        for probe in probes:
            probe.cancel()
        await asyncio.gather(*probes, return_exceptions=True)
