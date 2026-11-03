"""Outbox rows -> the exact body PostHog's `/batch/` endpoint receives.

One function builds both what Settings shows as "What's sent next" and what the
flush posts, so the preview cannot drift from the send. Every row is checked
against the catalogue again on the way out: a row that does not fit (written by
older code, or by hand) is left out and reported, never sent as it stands.

Every event carries the install ID as `distinct_id`, `$geoip_disable` (the
project also discards IPs), and a `uuid` derived from the install ID and the
row's key, so a retry after an ambiguous failure is de-duplicated by PostHog
rather than counted twice.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

import tracker
from tracker.db.models import UsageEvent
from tracker.usage_stats import scrub
from tracker.usage_stats.registry import CATALOGUE, COUNT_CAP, Kind, UsageEventError, validate

logger = logging.getLogger(__name__)

#: Heartbeat properties also kept on the person (install) profile.
PERSON_PROPS = (
    "app_version", "os", "arch", "install_method", "country", "ui_locale", "followed_bucket", "db_mode",
    "target_craft", "target_seniority",
)
_NAMESPACE = uuid.UUID("5b0f6c1e-2a8d-4f3b-9e71-0d4c8a6b2f19")
_FINGERPRINT = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class Batch:
    body: dict[str, object]
    #: Row ids whose events are in `body["batch"]`, in order.
    ids: list[int]
    #: Row ids left out because they do not fit the catalogue.
    unfit: list[int]


def _event(row: UsageEvent, install_id: str) -> dict[str, object]:
    spec = CATALOGUE.get(row.name)
    if spec is None or spec.kind.value != row.kind or spec.group.value != row.consent_group:
        raise UsageEventError(f"row {row.id} does not match the catalogue entry for {row.name!r}")
    props = dict(row.props or {})
    properties: dict[str, object] = {"distinct_id": install_id, "$geoip_disable": True, "$lib": "roleband-backend"}
    if spec.kind is Kind.EXCEPTION:
        shape = scrub.validate_stored(props.pop("exception", None))
        fingerprint = props.pop("fingerprint", None)
        if not (isinstance(fingerprint, str) and _FINGERPRINT.fullmatch(fingerprint)):
            raise UsageEventError(f"row {row.id} has no crash fingerprint")
        validate(row.name, props)
        properties |= props | {
            "$exception_list": scrub.exception_list(shape),
            "$exception_fingerprint": fingerprint,
            "app_version": tracker.__version__,
        }
    else:
        validate(row.name, props)
        properties |= props
    if spec.kind in (Kind.COUNT, Kind.EXCEPTION):
        properties["count"] = min(int(row.count), COUNT_CAP)
    if row.day is not None:
        properties["day"] = row.day.isoformat()
    if row.name == "daily_heartbeat":
        properties["$set"] = {key: props[key] for key in PERSON_PROPS if key in props}
    stamp = row.first_at if spec.kind is Kind.MILESTONE else row.last_at
    return {
        "event": row.name,
        "properties": properties,
        "timestamp": stamp.isoformat(),
        "uuid": str(uuid.uuid5(_NAMESPACE, f"{install_id}:{row.dedupe_key}")),
    }


def build(rows: Iterable[UsageEvent], *, install_id: str, api_key: str) -> Batch:
    events: list[dict[str, object]] = []
    ids: list[int] = []
    unfit: list[int] = []
    for row in rows:
        try:
            events.append(_event(row, install_id))
            ids.append(row.id)
        except (UsageEventError, ValueError):
            logger.warning("usage: left out outbox row %s (%s), it does not fit the catalogue", row.id, row.name)
            unfit.append(row.id)
    return Batch(body={"api_key": api_key, "batch": events}, ids=ids, unfit=unfit)
