"""The network below httpx, scripted: a resolver and a connection backend
that answer from a script and record every host they were handed."""

from __future__ import annotations

import httpcore


def scripted_resolver(answers: dict[str, list[str]]):
    """A DNS resolver answering `answers`; returns it with the hosts it was asked."""
    calls: list[str] = []

    async def resolve(host: str, port: int) -> list[str]:
        calls.append(host)
        return answers[host]

    return resolve, calls


class RecordingBackend(httpcore.AsyncMockBackend):
    """One scripted response per connection; records each connect address."""

    def __init__(self, *responses: list[bytes]) -> None:
        super().__init__([])
        self._responses = list(responses)
        self.connected: list[str] = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.connected.append(host)
        return httpcore.AsyncMockStream(list(self._responses.pop(0)))
