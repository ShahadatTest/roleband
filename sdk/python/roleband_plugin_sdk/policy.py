"""The host's rules for each call, as functions both hosts call.

The SDK's fake host and the core's host answer a plugin from the same code
here, so what a plugin author's test accepts is what the real host accepts.
Each check raises `protocol.CallError`; a host turns that into the reply.

What only a real host can know is passed in: whether a company exists, the
taxonomy families, the state keys and reports the plugin already keeps.
Robots and the budget are each host's own job on top of `check_get`; the
pacing floor and the identity rule are here, so a plugin's tests are paced
and refused as the real host paces and refuses.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError

from . import protocol
from .manifest import Job, PluginManifest
from .slots import FactClaim, PayLevel, row_model

#: The core's default request delay (`scraper_min_delay_seconds`): no plugin is
#: paced faster, whatever its manifest asks.
CORE_MIN_DELAY_SECONDS = 2.0


def pacing_delay(manifest: PluginManifest, core_delay: float = CORE_MIN_DELAY_SECONDS) -> float:
    """Seconds between a plugin's requests: its own declared delay, never less than the core's."""
    return max(manifest.network.min_delay_seconds if manifest.network else 0.0, core_delay)


def check_identity(manifest: PluginManifest) -> None:
    """Only the identified client fetches: a stronger tier needs the user's
    consent at run time, which v1 cannot record."""
    if manifest.network is not None and manifest.network.identity != "identified":
        raise protocol.CallError(
            protocol.REFUSED,
            f"identity {manifest.network.identity!r} needs the user's consent, which v1 cannot record",
        )


def check_get(manifest: PluginManifest, params: protocol.HttpGet) -> str:
    """The hostname `params.url` names, if the manifest lets the plugin fetch it."""
    parts = urlsplit(params.url)
    if parts.scheme != "https":
        raise protocol.CallError(protocol.REFUSED, f"only https is fetched, not {parts.scheme!r}")
    host = (parts.hostname or "").lower()
    if parts.username is not None or parts.password is not None:
        raise protocol.CallError(protocol.REFUSED, "a URL carrying credentials is not fetched")
    if not manifest.allows_host(host):
        raise protocol.CallError(protocol.REFUSED, f"host {host!r} is not declared in [network]")
    bad = sorted(k for k in params.headers if k.lower() not in protocol.ALLOWED_REQUEST_HEADERS)
    if bad:
        raise protocol.CallError(protocol.REFUSED, f"headers {bad} are set by the host, not a plugin")
    return host


def check_new_state_key(kept: int) -> None:
    """A key the plugin does not yet keep, when it already keeps `kept`.
    Rewriting a key it keeps is never refused."""
    if kept >= protocol.MAX_STATE_KEYS:
        raise protocol.CallError(protocol.INVALID, f"a plugin keeps at most {protocol.MAX_STATE_KEYS} state keys")


def check_report(params: protocol.Report, kept: Collection[str]) -> None:
    """A report, when the plugin already shows `kept`. Updating or withdrawing
    a number it shows is never refused."""
    if params.value is not None and params.key not in kept and len(kept) >= protocol.MAX_REPORTS:
        raise protocol.CallError(protocol.INVALID, f"a plugin reports at most {protocol.MAX_REPORTS} numbers")


def check_companies(job: Job) -> None:
    if "followed_companies" not in job.needs:
        raise protocol.CallError(
            protocol.REFUSED, f"job {job.name!r} does not declare needs = ['followed_companies']"
        )


def check_publish(
    manifest: PluginManifest,
    job: Job,
    params: protocol.Publish,
    *,
    company_known: Callable[[str], bool],
    families: Collection[str] | None = None,
) -> list[BaseModel]:
    """The publish's rows, validated on the host's side. A plugin can skip the
    SDK and write to the wire directly, so nothing it sends is trusted."""
    if params.slot not in job.publishes:
        raise protocol.CallError(protocol.REFUSED, f"job {job.name!r} does not publish {params.slot!r}")
    if not company_known(params.company):
        raise protocol.CallError(protocol.REFUSED, f"{params.company!r} is not a company the core knows")
    try:
        model = row_model(params.slot)
    except ValueError as exc:
        raise protocol.CallError(protocol.REFUSED, str(exc)) from None
    rows: list[BaseModel] = []
    for i, raw in enumerate(params.rows):
        try:
            row = model.model_validate(raw)
        except ValidationError as exc:
            raise protocol.CallError(protocol.INVALID, f"row {i}: {exc.errors()[0]['msg']}") from None
        if isinstance(row, FactClaim) and row.field not in manifest.fact_fields:
            raise protocol.CallError(protocol.REFUSED, f"row {i}: field {row.field!r} is not declared")
        if isinstance(row, PayLevel) and families is not None and row.family not in families:
            raise protocol.CallError(protocol.INVALID, f"row {i}: {row.family!r} is not a taxonomy family")
        rows.append(row)
    return rows
