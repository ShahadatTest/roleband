"""What the user chose to share, per consent group, and the words they saw.

One `app_settings` row (`usage_sharing`): for each group the user has answered,
whether they share it, the group's fingerprint when they answered, when, the
exact text the screen showed and the language it was in. The pattern is the
walled-company consent (`company_store.record_consent`): record what
was agreed to, not just a flag.

A group's status:

* `undecided` - never answered; the dashboard asks.
* `shared` - shared, and the group still covers what it covered then.
* `stale` - shared, but the group has since been WIDENED (new events, new
  properties, new browser capabilities: `registry.fingerprint`). Nothing of the
  group is collected or sent until the user answers again.
* `declined` - not shared. A widened group does not re-ask a decliner.

Narrowing a group (a feature sunset) also changes its fingerprint, and must not
re-ask anyone: the change that narrows a group adds the group's old fingerprint
to `NARROWED_FROM`, and a sharer whose stored fingerprint is listed there still
counts as shared.

The environment can only turn sharing off (`kill.py`); nothing here reads it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import AppSetting
from tracker.platform.locks import advisory_xact_lock, advisory_xact_lock_shared
from tracker.usage_stats import outbox
from tracker.usage_stats.install_id import ensure_install_id
from tracker.usage_stats.registry import Group, fingerprint

SHARING_KEY = "usage_sharing"
SHARING_LOCK_KEY = 91249
CONSENT_TEXT_MAX = 4000
#: BCP 47, as `company_store` checks it: `en`, `pt-BR`, `zh-Hant-TW`.
_LOCALE_TAG = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}")

#: Fingerprints a narrowing replaced, per group: a sharer who agreed to the
#: wider scope has agreed to the narrower one. Each sunset that changes a
#: group's fingerprint adds the old value here in the same change.
NARROWED_FROM: Mapping[Group, frozenset[str]] = {}

#: Groups the screen does not offer that a stored answer may still name. A
#: stored answer for one is the record of what a user agreed to, so a write
#: keeps it as it is; nothing reads it, and nothing of it is collected.
RETIRED_GROUPS: frozenset[str] = frozenset({"recordings"})


class Status(StrEnum):
    UNDECIDED = "undecided"
    SHARED = "shared"
    STALE = "stale"
    DECLINED = "declined"


class ConsentError(ValueError):
    """A consent the store refuses; nothing was written."""


class StaleScope(ConsentError):
    """The screen the user answered described an older scope of these groups."""

    def __init__(self, groups: list[Group]) -> None:
        super().__init__("the consent screen showed an older scope for " + ", ".join(g.value for g in groups))
        self.groups = groups


@dataclass(frozen=True)
class Choice:
    shared: bool
    fingerprint: str
    decided_at: datetime
    text: str
    locale: str


@dataclass(frozen=True)
class Sharing:
    choices: Mapping[Group, Choice]

    def status(self, group: Group) -> Status:
        choice = self.choices.get(group)
        if choice is None:
            return Status.UNDECIDED
        if not choice.shared:
            return Status.DECLINED
        current = fingerprint(group)
        if choice.fingerprint == current or choice.fingerprint in NARROWED_FROM.get(group, frozenset()):
            return Status.SHARED
        return Status.STALE

    def shared(self, group: Group) -> bool:
        return self.status(group) is Status.SHARED

    def shared_groups(self) -> frozenset[Group]:
        return frozenset(group for group in Group if self.shared(group))

    def decided_at(self, group: Group) -> datetime | None:
        choice = self.choices.get(group)
        return choice.decided_at if choice is not None else None


NOTHING_SHARED = Sharing(choices={})


def _parse_choice(raw: object) -> Choice | None:
    if not isinstance(raw, dict):
        return None
    shared, print_, decided, text, locale = (
        raw.get("shared"),
        raw.get("fingerprint"),
        raw.get("decided_at"),
        raw.get("text"),
        raw.get("locale"),
    )
    if not (isinstance(shared, bool) and isinstance(print_, str) and isinstance(decided, str)):
        return None
    try:
        decided_at = datetime.fromisoformat(decided)
    except ValueError:
        return None
    return Choice(
        shared=shared,
        fingerprint=print_,
        decided_at=decided_at,
        text=text if isinstance(text, str) else "",
        locale=locale if isinstance(locale, str) else "en",
    )


async def _stored_groups(session: AsyncSession) -> dict[str, object]:
    row = await session.get(AppSetting, SHARING_KEY, populate_existing=True)
    if row is None or not isinstance(row.value, dict):
        return {}
    raw_groups = row.value.get("groups")
    return raw_groups if isinstance(raw_groups, dict) else {}


async def get_sharing(session: AsyncSession) -> Sharing:
    """The stored choices; an unreadable entry reads as undecided."""
    raw_groups = await _stored_groups(session)
    if not raw_groups:
        return NOTHING_SHARED
    choices: dict[Group, Choice] = {}
    for group in Group:
        choice = _parse_choice(raw_groups.get(group.value))
        if choice is not None:
            choices[group] = choice
    return Sharing(choices=choices)


async def get_sharing_to_record(session: AsyncSession) -> Sharing:
    """`get_sharing` for a writer of the outbox. Holds the sharing lock in
    shared mode until the transaction ends, so a consent edit waits for every
    row written under this read and withdraws it if the edit stops its group."""
    await advisory_xact_lock_shared(session, SHARING_LOCK_KEY)
    return await get_sharing(session)


async def set_sharing(
    session: AsyncSession,
    answers: Mapping[Group, bool],
    *,
    text: str,
    locale: str,
    fingerprints: Mapping[Group, str],
    now: datetime,
) -> Sharing:
    """Record the user's answer for each group in `answers`.

    Everything is checked before anything is written. A group being shared
    must carry the fingerprint the screen was built from, equal to the current
    one: otherwise the user agreed to a scope that is not the one in force
    (`StaleScope`). Groups not in `answers` keep their earlier answer. A group
    that goes from shared to not shared has its unsent rows withdrawn. So does
    a group that goes from not shared to shared: nothing pending for it was
    consented to, yet a row recorded under a consent read taken outside the
    sharing lock can commit after the decline's withdrawal, and the outbox
    sends a pending row of a shared group whatever its age."""
    if not answers:
        raise ConsentError("no consent group answered")
    clean_text = text.strip()
    if not clean_text:
        raise ConsentError("the consent text is empty")
    if len(clean_text) > CONSENT_TEXT_MAX:
        raise ConsentError(f"the consent text is longer than {CONSENT_TEXT_MAX} characters")
    if not _LOCALE_TAG.fullmatch(locale or ""):
        raise ConsentError(f"{locale!r} is not a language tag")
    stale = [g for g, share in answers.items() if share and fingerprints.get(g) != fingerprint(g)]
    if stale:
        raise StaleScope(sorted(stale, key=lambda g: g.value))

    await advisory_xact_lock(session, SHARING_LOCK_KEY)
    before = await get_sharing(session)
    was_shared = {g for g in answers if before.status(g) in (Status.SHARED, Status.STALE)}
    stopped = [g for g, share in answers.items() if not share and g in was_shared]
    started = [g for g, share in answers.items() if share and g not in was_shared]
    if stopped or started:
        await outbox.withdraw(session, [*stopped, *started], now=now)
    if any(answers.values()):
        await ensure_install_id(session, now=now)

    retired = {key: raw for key, raw in (await _stored_groups(session)).items() if key in RETIRED_GROUPS}
    merged: dict[Group, Choice] = dict(before.choices)
    for group, share in answers.items():
        merged[group] = Choice(
            shared=share,
            fingerprint=fingerprint(group),
            decided_at=now,
            text=clean_text,
            locale=locale,
        )
    value = {
        "groups": retired | {
            group.value: {
                "shared": choice.shared,
                "fingerprint": choice.fingerprint,
                "decided_at": choice.decided_at.isoformat(),
                "text": choice.text,
                "locale": choice.locale,
            }
            for group, choice in merged.items()
        }
    }
    stmt = insert(AppSetting).values(key=SHARING_KEY, value=value)
    stmt = stmt.on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": value})
    await session.execute(stmt)
    return Sharing(choices=merged)
