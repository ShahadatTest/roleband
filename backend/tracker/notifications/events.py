"""Classify lifecycle events, run health, and sync outcomes into notifications."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from tracker.config import get_settings
from tracker.notifications import say as S
from tracker.notifications.render import (
    _money,
    company_namer,
)
from tracker.pay_period import effective_period


class JobLike(Protocol):
    company: str
    title: str
    comp_median: int | None
    total_days_open: int


@dataclass(frozen=True)
class ClassifiedNotif:
    priority: str
    category: str
    title: str = ""
    body: str | None = None
    meta: dict | None = None
    #: The posting the row opens, when it is not the event's own: a saved
    #: posting that closed while its role stays listed elsewhere opens the
    #: open one.
    job_id: int | None = None

    def __post_init__(self) -> None:
        if self.meta and "say" in self.meta:
            title, body = S.english_record(self.meta["say"])
            object.__setattr__(self, "title", title)
            object.__setattr__(self, "body", body)


def _disclosed_change(detail: dict) -> tuple[dict | None, dict | None]:
    """The posted-band change recorded by `repo.upsert_job`, or (None, None).

    Deliberately NOT `comp_median`. That column is a cohort lookup keyed on
    company+level+family, so it is a fact about a *cohort*, never about this
    job: when the lookup refreshes, every row in the cohort moves together, and
    each would ring for a move no posting made.

    `disclosed_base_*` is the band the employer actually posted, and it moves
    only when the posting itself moves. That is the only comp signal that can
    honestly ring a bell.
    """
    change = detail.get("disclosed_base") if isinstance(detail, dict) else None
    if not isinstance(change, dict):
        return None, None
    before, after = change.get("from"), change.get("to")
    return (before if isinstance(before, dict) else None, after if isinstance(after, dict) else None)


def _band_midpoint(band: dict | None) -> int | None:
    """Midpoint of a posted band, for direction only. None when unusable."""
    if not band:
        return None
    low, high = band.get("min"), band.get("max")
    values = [v for v in (low, high) if isinstance(v, (int, float))]
    return int(sum(values) / len(values)) if values else None


def _band_bounds(band: dict | None) -> frozenset[str]:
    """Which bounds this band actually discloses as numbers."""

    return frozenset(
        name for name in ("min", "max") if isinstance((band or {}).get(name), (int, float))
    )


def _comparable_midpoints(
    before: dict | None, after: dict | None
) -> tuple[int | None, int | None]:
    """Midpoints, but only when the two bands disclose the SAME bounds.

    `_band_midpoint` averages whatever is present, so a source that drops `max`
    for one scrape moves the midpoint by half the band, a false "pay cut", and
    moves it back when the field returns. On a tracked
    role that is an alternating comp_down/comp_up pair on every scrape, driven by
    a source flapping a FIELD and not by any change in pay.

    Direction needs like for like. A band disclosing different bounds than the
    one before it is a DISCLOSURE change, not a comp change, and the event falls
    through to the generic `changed` row that says so honestly. A min-only band
    compared with another min-only band is still like for like, so a source that
    only ever posts a floor keeps its real moves.
    """

    if not _band_bounds(before) or _band_bounds(before) != _band_bounds(after):
        return None, None
    if _terms(before) != _terms(after):
        return None, None
    return _band_midpoint(before), _band_midpoint(after)


def _terms(band: dict | None) -> tuple[str, str]:
    """The currency and period a band states its bounds in. A detail written
    without them is a dollar band, its period read as `effective_period` reads
    a stored band with none. A band restated in another currency or period is
    a disclosure change, never a raise or a cut."""
    b = band or {}
    currency = (b.get("currency") or "USD").upper()
    return currency, effective_period(b.get("period"), b.get("min"), b.get("max"), currency)


def _band_label(band: dict | None) -> str:
    b = band or {}
    currency, period = _terms(band)
    return _money(b.get("min"), b.get("max"), currency=currency, period=period)


def _said(title: S.Say, *body: S.Say | str) -> dict:
    """`meta.say`: the title and the body's sentences as catalog keys (`say.py`).
    A string sentence is third-party text, shown as written."""
    return {"title": title, "body": list(body) or None}


def classify_event(
    event_type: str,
    detail: dict,
    job: JobLike,
    is_tracked: bool,
    *,
    long_open_days: int | None = None,
    lineage_role: str | None = None,
    listed_elsewhere: Sequence[tuple[int, str]] = (),
    names: Mapping[str, str] | None = None,
) -> ClassifiedNotif | None:
    """Classify one lifecycle event for a TRACKED role, or return None.

    `is_tracked` is the gate (`notifications/tracked.py`): saved or pursued,
    widened across repost lineage. An untracked role produces NOTHING here:
    it reaches the user through the daily digest instead, ranked by fit and
    counted once, rather than one interrupt per posting per run. Per-role
    events are interrupts, and an interrupt about a role the user never chose
    to follow is unactionable by construction.

    Categories stay specific (`closed`, `repost`, `comp_up`, ...) rather than
    collapsing into one `saved_update` bucket: the category is what the feed
    filters on, and "a role you track closed" and "a role you track changed
    title" are not the same errand. Priority is elevated across the board:
    everything here is about work the user has actually committed to.

    `lineage_role` is the job's repost-lineage role (None|original|repost|duplicate).
    `listed_elsewhere` is, for a closing, the open postings of the same role at
    other places, as (job id, place), earliest first
    (`lineage.place_sets.still_listed_elsewhere`).
    `names` is the register's `slug -> display` (`tracked_company.display`,
    the name the user follows the company by); a slug it lacks falls back to
    `_company_label`.
    """

    if not is_tracked:
        return None

    settings = get_settings()
    long_days = long_open_days if long_open_days is not None else settings.long_open_days
    company = company_namer(names)(job.company)
    is_successor = lineage_role in ("repost", "duplicate")
    base_meta = {"company": job.company, "tracked": True, "lineage_role": lineage_role}

    if event_type == "closed" and listed_elsewhere:
        # One posting of a role listed once per place came down; the role did
        # not. Saying "closed" would send the person away from a
        # role they can still apply to, so the row opens the open posting.
        places = [place for _, place in listed_elsewhere]
        return ClassifiedNotif(
            priority="high",
            category="saved_update",
            meta={
                **base_meta,
                "listed_elsewhere": [
                    {"job_id": job_id, "place": place} for job_id, place in listed_elsewhere
                ],
                "say": _said(
                    S.say("notif-saved-elsewhere", company=company, places=len(places)),
                    S.say(
                        "notif-saved-elsewhere-body",
                        title=job.title,
                        places=", ".join(places[:3]),
                        more="yes" if len(places) > 3 else "no",
                    ),
                ),
            },
            job_id=listed_elsewhere[0][0],
        )

    if event_type == "closed":
        return ClassifiedNotif(
            priority="high",
            category="closed",
            meta={**base_meta, "say": _said(S.say("notif-closed", company=company), job.title)},
        )

    if event_type in ("opened", "reopened"):
        # A role you track was closed and re-listed under a new req_id. This is
        # the event the lineage widening in `tracked.py` exists to catch, and
        # for a pursued role it is a re-apply window, not trivia.
        if event_type == "reopened" or is_successor:
            key = "notif-listed-again" if lineage_role == "duplicate" else "notif-reposted"
            return ClassifiedNotif(
                priority="high",
                category="repost",
                meta={**base_meta, "say": _said(S.say(key, company=company), job.title)},
            )
        return ClassifiedNotif(
            priority="high",
            category="saved_update",
            meta={**base_meta, "say": _said(S.say("notif-listed", company=company), job.title)},
        )

    if event_type == "changed":
        before, after = _disclosed_change(detail)
        from_mid, to_mid = _comparable_midpoints(before, after)
        if from_mid is not None and to_mid is not None and to_mid != from_mid:
            up = to_mid > from_mid
            return ClassifiedNotif(
                priority="high" if up else "normal",
                category="comp_up" if up else "comp_down",
                meta={
                    **base_meta,
                    "disclosed_base": {"from": before, "to": after},
                    "say": _said(
                        S.say("notif-pay-raised" if up else "notif-pay-lowered", company=company),
                        S.say("notif-pay-change", title=job.title, before=_band_label(before), after=_band_label(after)),
                    ),
                },
            )
        fields = sorted(detail.keys()) if isinstance(detail, dict) else []
        if job.total_days_open >= long_days:
            return ClassifiedNotif(
                priority="normal",
                category="long_open_update",
                meta={
                    **base_meta,
                    "days_open": job.total_days_open,
                    "fields": fields,
                    "say": _said(S.say("notif-updated-long-open", company=company), job.title),
                },
            )
        return ClassifiedNotif(
            priority="low",
            category="changed",
            meta={**base_meta, "fields": fields, "say": _said(S.say("notif-changed", company=company), job.title)},
        )

    return None
