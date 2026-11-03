"""One posting, as every job surface sends it.

Five routers answer with the same posting shape. A read that more than one
surface builds from is not a route helper, so the serializer lives here rather
than in one router.

It stays under `tracker.api` because a wire shape is transport: the keys, the
`detail` split and the reader-state arguments are what `api/schemas/jobs.py`
declares, and nothing below the API layer should know them.
"""

from __future__ import annotations

from datetime import UTC, datetime

from tracker.analytics.posting_reality import PostingFacts, is_new_listing, listing_age
from tracker.analytics.posting_reality import classify as classify_posting
from tracker.db.models import Job, JobLineage
from tracker.db.queries.jobs import PlaceSetCounts
from tracker.pay_disclosure import ROW_PAY_PERIODS, band_stated, disclosure_known
from tracker.pay_period import effective_period
from tracker.workflows.posting_pages import band_from_page


def posted_base(job: Job) -> dict | None:
    """The posting's own base range as a list row writes it, or None. A total or
    an unclear basis is not a base; a period its size rules out, or an unclear
    one, has no unit to write (`pay_period.effective_period`, as the detail reads it)."""
    low, high, currency = job.disclosed_base_min, job.disclosed_base_max, job.disclosed_currency
    if job.disclosed_pay_basis != "base" or currency is None or not band_stated(low, high):
        return None
    period = effective_period(job.disclosed_pay_period, low, high, currency)
    if period not in ROW_PAY_PERIODS:
        return None
    return {"min": low, "max": high, "currency": currency, "period": period}


def application_form_view(source_facts: dict | None) -> dict | None:
    """The detail route's `application_form`, from the stored counts.
    None until a posting page read answered: a form we never read, or failed to
    read, is not a form that asks nothing."""
    form = (source_facts or {}).get("application_form") or {}
    if form.get("state") != "present":
        return None
    return {
        "required": int(form.get("required") or 0),
        "written": int(form.get("written") or 0),
        "choices": int(form.get("choices") or 0),
        "asks_expected_pay": bool(form.get("asks_expected_pay")),
        "read_at": form.get("observed_at"),
    }


def serialize_job(
    job: Job,
    *,
    detail: bool = False,
    favorite_ids: set[int] | None = None,
    dismissed_ids: set[int] | None = None,
    lineage_meta: dict[int, JobLineage] | None = None,
    twin_counts: dict[int, int] | None = None,
    place_counts: dict[int, PlaceSetCounts] | None = None,
    role_starts: dict[int, datetime] | None = None,
    reopened_ids: set[int] | None = None,
    unfollowed: set[str] | None = None,
) -> dict:
    now = datetime.now(UTC)
    counts = place_counts.get(job.id) if place_counts is not None else None
    first_seen = job.first_seen
    days_open = (now - first_seen).days if first_seen else None
    # Effective age across the lineage (the honest clock for a reposted role).
    effective_first_seen = job.lineage_first_seen or job.first_seen
    lineage_days_open = (now - effective_first_seen).days if effective_first_seen else None
    # How long the posting has been listed, by the earliest date either side
    # states for THIS posting: the age a person reads,
    # and whose date it starts from. `days_open` stays our own sighting clock,
    # which is what the statistics measure. A closed posting stops counting
    # when it closed.
    listed_since, listed_days, listed_basis = (
        listing_age(
            job.first_posted_at, first_seen,
            status=job.status, closed_at=job.closed_at, now=now,
        )
        if first_seen
        else (None, None, None)
    )
    lineage_size = None
    if job.lineage_id is not None and lineage_meta is not None:
        lin = lineage_meta.get(job.lineage_id)
        lineage_size = lin.size if lin is not None else None
    data = {
        "id": job.id,
        "is_favorite": job.id in favorite_ids if favorite_ids is not None else False,
        "is_dismissed": job.id in dismissed_ids if dismissed_ids is not None else False,
        # A row at a company the user stopped following: reachable as Saved or
        # by id, and not checked any more. False unless told.
        "company_unfollowed": job.company in unfollowed if unfollowed is not None else False,
        "company": job.company,
        "req_id": job.req_id,
        "title": job.title,
        "url": job.url,
        "department": job.department,
        "team": job.team,
        "locations": job.locations,
        "location_groups": job.location_groups,
        # None (pre-axis) serializes as [] — clients only need "which worlds",
        # and the NULL-vs-empty distinction is backfill bookkeeping, not UI.
        "domains": job.domains or [],
        "workplace_type": job.workplace_type,
        "level_band": job.level_band,
        "level_confidence": job.level_confidence,
        "level_basis": job.level_basis,
        "family": job.family,
        "track": job.track,
        "comp_low": job.comp_low,
        "comp_high": job.comp_high,
        "comp_median": job.comp_median,
        "comp_currency": job.comp_currency,
        "comp_provenance": job.comp_provenance,
        "comp_base_low": job.comp_base_low,
        "comp_base_median": job.comp_base_median,
        "comp_base_high": job.comp_base_high,
        "comp_component": job.comp_component,
        "comp_provider": job.comp_provider,
        "comp_as_of": job.comp_as_of,
        "status": job.status,
        "in_scope": job.in_scope,
        "posted_at": job.posted_at,
        "first_seen": job.first_seen,
        "last_seen": job.last_seen,
        "viewed_at": job.viewed_at,
        "closed_at": job.closed_at,
        "days_open": days_open,
        "repost_count": job.repost_count,
        # Repost lineage (the "stack deck"). lineage_role NULL = standalone job.
        "lineage_id": job.lineage_id,
        "lineage_seq": job.lineage_seq,
        "lineage_role": job.lineage_role,
        "lineage_size": lineage_size,
        "lineage_days_open": lineage_days_open,
        "listed_since": listed_since,
        "listed_days": listed_days,
        "listed_basis": listed_basis,
        "new_listing": bool(first_seen) and is_new_listing(
            job.first_posted_at, first_seen, arrival=job.arrival, status=job.status,
            lineage_role=job.lineage_role, now=now,
        ),
        "twin_count": twin_counts.get(job.id, 0) if twin_counts is not None else 0,
        # How many places the role is listed in when its employer lists it
        # once per place; null for a posting in no place set, or
        # when the response did not look.
        "place_count": counts.places if counts is not None else None,
        # How many postings the role's set holds: a role listed again at one
        # place has one place and several postings.
        "place_set_size": counts.postings if counts is not None else None,
        # Cheap boolean for the list badge + the `discloses_pay` filter. The full
        # `disclosed_comp` object stays detail-only — list payloads are kept thin.
        "discloses_pay": band_stated(job.disclosed_base_min, job.disclosed_base_max),
        "posted_base": posted_base(job),
    }
    # The standing-posting sign on a list row: the verdict Job
    # detail serves, from the same stored facts, read off the page context
    # (`row_context`) so a page costs the same round trips at any size. Sent
    # only when the context carries them; null for a closed posting.
    if role_starts is not None and reopened_ids is not None and first_seen:
        data["posting_reality"] = classify_posting(
            PostingFacts(
                status=job.status,
                posted_at=job.posted_at,
                first_posted_at=job.first_posted_at,
                first_seen=first_seen,
                role_since=role_starts.get(job.lineage_id) if job.lineage_id is not None else None,
                lineage_size=lineage_size,
                repost_count=job.repost_count or 0,
                listed_here=counts.here if counts is not None else 0,
                reopened=job.id in reopened_ids,
            ),
            now,
        )
    if detail:
        data["description_text"] = job.description_text
        data["description_html"] = job.description_html
        data["description_sections"] = job.description_sections or []
        # Disclosed pay band (coexists with the comp_* estimate). None = no
        # band stored and the text not read yet; an object with
        # disclosed=false = the text was read and stated no band. A stored
        # band shows whoever wrote it (`disclosure_known`).
        if not disclosure_known(job.structured_at, job.disclosed_base_min, job.disclosed_base_max):
            data["disclosed_comp"] = None
        else:
            has_band = band_stated(job.disclosed_base_min, job.disclosed_base_max)
            data["disclosed_comp"] = {
                "disclosed": has_band,
                "base_min": job.disclosed_base_min,
                "base_max": job.disclosed_base_max,
                "currency": job.disclosed_currency,
                "pay_basis": job.disclosed_pay_basis,
                # Checked against the amount's size: a stored
                # "$600,000 / hr" or "€104 / yr" is served as `unclear`, and
                # the package then refuses to split or label it.
                "pay_period": (
                    effective_period(
                        job.disclosed_pay_period,
                        job.disclosed_base_min,
                        job.disclosed_base_max,
                        job.disclosed_currency,
                    )
                    if has_band
                    else job.disclosed_pay_period
                ),
                "snippet": job.disclosed_snippet,
                # The band was read from the posting page's pay field:
                # numbers, not a sentence, so there is no snippet to quote.
                "from_pay_field": band_from_page(job),
                "confidence": job.disclosed_confidence,
                "bonus_pct": job.disclosed_bonus_pct,
                "checked_at": job.structured_at,
            }
    return data

