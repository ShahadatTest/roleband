"""Usage sharing: the consent, the install ID, and what is (and was) sent.

Its own router, as `PUT /api/intelligence/egress` is its own endpoint: a consent
that changes what leaves the machine must be impossible to change as a side
effect of saving something else. docs/architecture.md.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from tracker.api.deps import SessionDep
from tracker.api.errors import ErrorCode, api_error
from tracker.api.schemas.usage import UsageConsentPayload, UsagePreview, UsageSent, UsageState
from tracker.usage_stats import view
from tracker.usage_stats.consent import ConsentError, StaleScope, set_sharing
from tracker.usage_stats.install_id import reset_install_id
from tracker.usage_stats.registry import Group
from tracker.usage_stats.tally import TALLY

router = APIRouter()


@router.get("/api/usage", response_model=UsageState)
async def get_usage_ep(session: SessionDep) -> dict:
    return await view.state(session, now=datetime.now(UTC))


@router.put("/api/usage/consent", response_model=UsageState)
async def put_usage_consent_ep(payload: UsageConsentPayload, session: SessionDep) -> dict:
    """Record the user's answer per group, with the words the screen showed.

    409 when the screen described an older scope of a group being shared (the
    dashboard reloads the state and asks again); 422 for an empty text or a
    value that is not a language tag. Nothing is written in either case."""
    now = datetime.now(UTC)
    try:
        sharing = await set_sharing(
            session,
            {Group(group): share for group, share in payload.answers.items()},
            text=payload.text,
            locale=payload.locale,
            fingerprints={Group(group): value for group, value in payload.fingerprints.items()},
            now=now,
        )
    except StaleScope as stale:
        raise api_error(
            409,
            ErrorCode.USAGE_CATALOGUE_CHANGED,
            str(stale),
            groups=[group.value for group in stale.groups],
        ) from stale
    except ConsentError as refused:
        raise api_error(422, ErrorCode.INVALID_INPUT, str(refused)) from refused
    await session.commit()
    # The API's own tally follows the answer at once, not at the next drain.
    TALLY.set_flags(sharing)
    return await view.state(session, now=now)


@router.post("/api/usage/install-id/reset", response_model=UsageState)
async def reset_usage_install_id_ep(session: SessionDep) -> dict:
    """A new install ID: nothing links what is sent after this to what came before."""
    now = datetime.now(UTC)
    await reset_install_id(session, now=now)
    await session.commit()
    return await view.state(session, now=now)


@router.get("/api/usage/preview", response_model=UsagePreview)
async def get_usage_preview_ep(session: SessionDep) -> dict:
    return await view.preview(session, now=datetime.now(UTC))


@router.get("/api/usage/sent", response_model=UsageSent)
async def get_usage_sent_ep(session: SessionDep) -> dict:
    return await view.sent(session, now=datetime.now(UTC))
