"""What a notification says, as catalog keys the dashboard renders.

A row's `title` and `body` stay the English RoleBand has always stored: the
fallback for an old row, the text feed search matches, the copy diagnostics
shows. Beside them each producer writes `meta.say`, the same words as message
keys with their parameters, which the dashboard renders from its catalog in the
reader's language (`dashboard/src/api/notificationText.ts`,
`dashboard/src/copy/en/notifications.ftl`):

    meta["say"] = {"title": Say, "body": [Say | str, ...] | None}
    Say = {"k": "<key>", "p": {name: str | int | Say | {"date": "YYYY-MM-DD"}}}

The body is its sentences in order, said one after another with a space
between, the way the stored body joins them. A plain string in the body is
third-party text shown as written (a role's title, a run's own error text).

A parameter is third-party content (a role's title, a company's name as the
person follows it), a number, a value already written in figures (a time, a
pay band), a calendar day (`{"date": iso}`, written by the reader's region), or
another `Say` for a phrase the product words itself (a count of companies, a
duration). The logic that picks the sentences stays here and in `events.py`;
the dashboard only says them.

Keys are a contract with rows already stored: each is listed with its
parameters in `tests/fixtures/notification_keys.json`, a key is never removed
or reused for another meaning, and a rewording keeps it.
`scripts/export_notification_samples` writes one sample per branch, which the
dashboard renders against the stored English
(`dashboard/src/api/notificationText.test.ts`), so the two
cannot drift apart.

Producers own descriptors and branch selection. `ClassifiedNotif` renders their
English through `catalog_gen.py`, generated from the same FTL AST as the
dashboard. Compatibility formatters call these helpers; no parallel wording.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date
from typing import Any

Say = dict[str, Any]


def say(key: str, **params: Any) -> Say:
    """One message: its key and the values it is said with."""
    return {"k": key, "p": params}


def day(value: date) -> dict[str, str]:
    """A calendar day, written by the reader's region ("28 Sep" in English)."""
    return {"date": value.isoformat()}


def companies(count: int) -> Say:
    """`_companies`: "1 company", "3 companies"."""
    return say("notif-companies", count=count)


def duration(seconds: float | None) -> Say:
    """`_fmt_duration`: "45s", "3m 12s", "1h 4m"."""
    if seconds is None:
        return say("notif-duration-unknown")
    whole = int(round(seconds))
    if whole < 60:
        return say("notif-duration-seconds", s=whole)
    minutes, secs = divmod(whole, 60)
    if minutes < 60:
        return say("notif-duration-minutes", m=minutes, s=secs)
    hours, minutes = divmod(minutes, 60)
    return say("notif-duration-hours", h=hours, m=minutes)


def sources(names: list[str]) -> Say | str:
    """`_source_summary`: names joined, then "+N more" past four."""
    if not names:
        return say("notif-sources-all")
    if len(names) <= 4:
        return ", ".join(names)
    return say("notif-sources-more", names=", ".join(names[:4]), more=len(names) - 4)


def affected(slugs: list[str], label: Callable[[str], str]) -> Say | str:
    """`_affected_summary` once its slugs are gathered: nothing at fault is said."""
    if not slugs:
        return say("notif-affected-none")
    return sources([label(slug) for slug in slugs])


def days(value: float | None) -> int:
    """`_for_days`'s count: whole days, 0 when under one (the title then says none)."""
    whole = int(value) if value is not None else 0
    return whole if whole >= 1 else 0


def keys(said: dict) -> Iterator[tuple[str, frozenset[str]]]:
    """Every message a `meta.say` uses, nested ones included, with its parameter names."""

    def walk(value: Any) -> Iterator[tuple[str, frozenset[str]]]:
        if isinstance(value, dict) and "k" in value:
            yield value["k"], frozenset(value["p"])
            for param in value["p"].values():
                yield from walk(param)

    yield from walk(said["title"])
    for sentence in said["body"] or []:
        yield from walk(sentence)


def english(value: Any) -> str:
    """Render a descriptor using compiler-generated English, including nested values."""
    from tracker.notifications.catalog_gen import MESSAGES, PARAMETERS
    if isinstance(value, dict) and "date" in value:
        parsed = date.fromisoformat(value["date"])
        # Fixed English month names: process locale must not affect persisted English.
        months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
        return f"{parsed.day} {months[parsed.month - 1]}"
    if isinstance(value, dict) and "k" in value:
        key, params = value["k"], value["p"]
        required = PARAMETERS[key]
        args = {name: english(params[name]) if isinstance(params[name], dict) else params[name] for name in required}
        return str(MESSAGES[key](args))
    return str(value)


def english_record(said: dict) -> tuple[str, str | None]:
    return english(said["title"]), " ".join(english(sentence) for sentence in said["body"] or []) or None
