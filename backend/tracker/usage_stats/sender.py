"""One POST of one batch to PostHog's `/batch/` endpoint. Never raises.

`sent` for a 2xx; `retry` for a 429, a 5xx or no answer at all (the rows stay
claimed and are tried again after `flush.RETRY_AFTER`); `rejected` for any
other 4xx, which retrying would only repeat. PostHog answers 200 even to an
event it later drops, so `sent` means "accepted for ingestion", nothing more.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

import httpx

import tracker
from tracker.platform.http import make_client

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0
USER_AGENT = f"RoleBand/{tracker.__version__} usage"

Outcome = Literal["sent", "retry", "rejected"]


@dataclass(frozen=True)
class SendResult:
    outcome: Outcome
    status: int | None


def batch_url(host: str) -> str:
    """`https://<host>/batch/`; anything but https is refused (ValueError)."""
    parts = urlsplit(host.strip())
    if parts.scheme != "https" or not parts.netloc:
        raise ValueError(f"usage sharing sends only over https, not to {host!r}")
    return f"https://{parts.netloc}/batch/"


async def post_batch(body: dict, *, host: str, client: httpx.AsyncClient | None = None) -> SendResult:
    url = batch_url(host)
    own = client is None
    http = client or make_client(timeout=TIMEOUT_SECONDS)
    try:
        response = await http.post(url, json=body, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError as error:
        logger.info("usage: send failed, will retry (%s)", type(error).__name__)
        return SendResult("retry", None)
    finally:
        if own:
            await http.aclose()
    status = response.status_code
    if 200 <= status < 300:
        return SendResult("sent", status)
    if status == 429 or status >= 500:
        return SendResult("retry", status)
    logger.warning("usage: PostHog refused a batch with %s; those events are not retried", status)
    return SendResult("rejected", status)
