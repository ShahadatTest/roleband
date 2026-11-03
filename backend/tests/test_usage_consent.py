"""Nothing is collected without a current, recorded consent (docs/architecture.md).

Contracts, each asserted as an absence of rows where a row would be wrong:

* Undecided, declined and stale groups record nothing; the environment can
  only turn sharing off, never on.
* A consent is recorded with the words the screen showed and their language;
  a bad answer writes nothing at all (no partial record).
* A widened group goes stale for its sharers and re-asks only that group.
* Stopping a group withdraws its unsent rows (kept, never sent) and keeps the
  install ID; Reset replaces the ID.
* Sharing a group that was not shared withdraws whatever is pending for it, so
  a row recorded across a decline never leaves after a later grant.
* A consent edit waits for a recording still open under an earlier consent
  read, the recorder's own or the tally drain's, and withdraws its rows.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.barriers import until_waiting
from tests.usage_fixtures import CONSENT_TEXT, NOW, share
from tracker.db.models import AppSetting, UsageEvent
from tracker.usage_stats import consent, outbox, registry
from tracker.usage_stats.consent import ConsentError, StaleScope, Status, get_sharing, set_sharing
from tracker.usage_stats.install_id import INSTALL_ID_KEY, get_install_id, reset_install_id
from tracker.usage_stats.recorder import record_count, record_exception
from tracker.usage_stats.registry import Event, Group, Kind, fingerprint
from tracker.usage_stats.tally import ApiTally, drain

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]

SAVE = {"action": "save_job"}


async def _rows(session) -> int:
    return (await session.execute(select(func.count()).select_from(UsageEvent))).scalar_one()


async def test_undecided_records_nothing(db_session, sharing_allowed) -> None:
    assert (await get_sharing(db_session)).status(Group.USAGE) is Status.UNDECIDED
    assert await record_count(db_session, "daily_action", SAVE, now=NOW) is False
    assert await _rows(db_session) == 0


async def test_shared_records_and_declined_does_not(db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE)
    await share(db_session, Group.CRASHES, shared=False)
    assert await record_count(db_session, "daily_action", SAVE, now=NOW) is True
    assert await record_exception(db_session, KeyError("x"), source="api", now=NOW) is False
    assert await _rows(db_session) == 1


async def test_the_environment_never_turns_sharing_on(db_session, sharing_allowed, monkeypatch) -> None:
    # Every switch off and nothing stored: still nothing recorded.
    assert await record_count(db_session, "daily_action", SAVE, now=NOW) is False
    await share(db_session, Group.USAGE)
    # A switch on beats the stored consent.
    for name in ("ROLEBAND_NO_USAGE_STATS", "DO_NOT_TRACK", "CI"):
        monkeypatch.setenv(name, "1")
        assert await record_count(db_session, "daily_action", SAVE, now=NOW) is False, name
        monkeypatch.delenv(name)
    assert await _rows(db_session) == 0


async def test_the_suite_default_records_nothing(db_session) -> None:
    """Without `sharing_allowed`, conftest's switch is on: even a shared group
    records nothing, so no other test can fill the outbox by accident."""
    await share(db_session, Group.USAGE)
    assert await record_count(db_session, "daily_action", SAVE, now=NOW) is False


async def test_consent_records_the_words_and_language(db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE, Group.QUESTIONS)
    row = await db_session.get(AppSetting, consent.SHARING_KEY)
    stored = row.value["groups"]
    assert set(stored) == {"usage", "questions"}
    assert stored["usage"]["text"] == CONSENT_TEXT
    assert stored["usage"]["locale"] == "en"
    assert stored["usage"]["fingerprint"] == fingerprint(Group.USAGE)
    assert stored["usage"]["decided_at"] == NOW.isoformat()
    sharing = await get_sharing(db_session)
    assert sharing.shared_groups() == {Group.USAGE, Group.QUESTIONS}
    assert sharing.status(Group.CRASHES) is Status.UNDECIDED


async def test_a_retired_group_is_never_shared_and_its_record_is_kept(db_session, sharing_allowed) -> None:
    """Session recordings are not a group: an install whose stored consent
    names them shares nothing for them, and its record of what it agreed to stays."""
    assert "recordings" not in {group.value for group in Group}
    old = {"shared": True, "fingerprint": "f" * 64, "decided_at": NOW.isoformat(), "text": "Session recordings: ...", "locale": "en"}
    db_session.add(AppSetting(key=consent.SHARING_KEY, value={"groups": {"recordings": old}}))
    await db_session.flush()
    sharing = await get_sharing(db_session)
    assert sharing.shared_groups() == frozenset()
    await share(db_session, Group.USAGE)
    stored = (await db_session.get(AppSetting, consent.SHARING_KEY)).value["groups"]
    assert stored["recordings"] == old
    assert (await get_sharing(db_session)).shared_groups() == {Group.USAGE}


@pytest.mark.parametrize(
    ("text", "locale"),
    [("", "en"), ("   ", "en"), ("x" * (consent.CONSENT_TEXT_MAX + 1), "en"), (CONSENT_TEXT, "english please"), (CONSENT_TEXT, "")],
)
async def test_a_bad_answer_writes_nothing(db_session, sharing_allowed, text: str, locale: str) -> None:
    with pytest.raises(ConsentError):
        await set_sharing(
            db_session,
            {Group.USAGE: True},
            text=text,
            locale=locale,
            fingerprints={Group.USAGE: fingerprint(Group.USAGE)},
            now=NOW,
        )
    assert await db_session.get(AppSetting, consent.SHARING_KEY) is None
    assert await db_session.get(AppSetting, INSTALL_ID_KEY) is None


async def test_sharing_an_older_scope_is_refused(db_session, sharing_allowed) -> None:
    with pytest.raises(StaleScope) as refused:
        await set_sharing(
            db_session,
            {Group.USAGE: True, Group.CRASHES: True},
            text=CONSENT_TEXT,
            locale="en",
            fingerprints={Group.USAGE: "an-older-fingerprint", Group.CRASHES: fingerprint(Group.CRASHES)},
            now=NOW,
        )
    assert refused.value.groups == [Group.USAGE]
    assert await db_session.get(AppSetting, consent.SHARING_KEY) is None


async def test_a_widened_group_goes_stale_and_only_that_group(db_session, sharing_allowed, monkeypatch) -> None:
    await share(db_session, Group.USAGE, Group.CRASHES)
    await share(db_session, Group.QUESTIONS, shared=False)
    widened = Event("first_compare_used", Kind.MILESTONE, Group.USAGE)
    monkeypatch.setattr(registry, "CATALOGUE", dict(registry.CATALOGUE) | {widened.name: widened})
    sharing = await get_sharing(db_session)
    assert sharing.status(Group.USAGE) is Status.STALE
    assert sharing.status(Group.CRASHES) is Status.SHARED
    # A decliner is not re-asked when the group widens.
    assert sharing.status(Group.QUESTIONS) is Status.DECLINED
    assert await record_count(db_session, "daily_action", SAVE, now=NOW) is False
    assert await record_exception(db_session, KeyError("x"), source="api", now=NOW) is True


async def test_a_narrowing_listed_in_narrowed_from_stays_shared(db_session, sharing_allowed, monkeypatch) -> None:
    await share(db_session, Group.USAGE)
    old = fingerprint(Group.USAGE)
    narrowed = {k: v for k, v in registry.CATALOGUE.items() if k != "first_job_saved"}
    monkeypatch.setattr(registry, "CATALOGUE", narrowed)
    assert (await get_sharing(db_session)).status(Group.USAGE) is Status.STALE
    monkeypatch.setattr(consent, "NARROWED_FROM", {Group.USAGE: frozenset({old})})
    assert (await get_sharing(db_session)).status(Group.USAGE) is Status.SHARED


async def test_stopping_withdraws_unsent_rows_and_keeps_the_id(db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE, Group.CRASHES)
    install_id = await get_install_id(db_session)
    assert install_id is not None
    await record_count(db_session, "daily_action", SAVE, now=NOW)
    await record_exception(db_session, KeyError("x"), source="api", now=NOW)

    later = NOW + timedelta(hours=1)
    await share(db_session, Group.USAGE, now=later, shared=False)

    rows = {row.name: row for row in (await db_session.execute(select(UsageEvent))).scalars()}
    assert rows["daily_action"].withdrawn_at == later
    assert rows["$exception"].withdrawn_at is None  # crashes are still shared
    assert await get_install_id(db_session) == install_id
    tomorrow = (NOW + timedelta(days=1)).date()
    pending = await outbox.pending(db_session, groups=[Group.USAGE, Group.CRASHES], today=tomorrow)
    assert [row.name for row in pending] == ["$exception"]

    # Sharing again does not revive what was withdrawn.
    await share(db_session, Group.USAGE, now=later)
    pending = await outbox.pending(db_session, groups=[Group.USAGE, Group.CRASHES], today=tomorrow)
    assert [row.name for row in pending] == ["$exception"]


async def test_a_row_recorded_across_a_decline_is_never_sent_after_sharing_again(db_session, sharing_allowed) -> None:
    """A recorder that read consent before a decline commits its row after the
    decline has withdrawn the group's rows. Sharing again must not send it."""
    await share(db_session, Group.USAGE)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as recorder, factory() as settings:
        before_decline = await get_sharing(recorder)
        await share(settings, Group.USAGE, shared=False, now=NOW + timedelta(seconds=1))
        await settings.commit()
        assert await record_count(recorder, "daily_action", SAVE, now=NOW, sharing=before_decline) is True
        await recorder.commit()

    granted = NOW + timedelta(seconds=2)
    await share(db_session, Group.USAGE, now=granted)
    await db_session.commit()
    after_grant = {"action": "dismiss_job"}
    assert await record_count(db_session, "daily_action", after_grant, now=granted) is True
    await db_session.commit()

    sent = await outbox.claim(
        db_session, groups=[Group.USAGE], today=(NOW + timedelta(days=1)).date(),
        now=NOW + timedelta(days=1), retry_after=timedelta(minutes=5),
    )
    assert [(row.props, row.first_at) for row in sent] == [(after_grant, granted)]
    [early] = (await db_session.scalars(select(UsageEvent).where(UsageEvent.first_at < granted))).all()
    assert early.props == SAVE
    assert early.withdrawn_at == granted


GRANTED = NOW + timedelta(seconds=2)
AFTER_GRANT = {"action": "dismiss_job"}


async def _decline_then_share_again(factory) -> None:
    async with factory() as settings:
        await share(settings, Group.USAGE, shared=False, now=NOW + timedelta(seconds=1))
        await settings.commit()
        await share(settings, Group.USAGE, now=GRANTED)
        await settings.commit()


async def _claimed_after_the_grant(db_session) -> list[dict]:
    """Record one row after the grant, then claim what would be sent."""
    assert await record_count(db_session, "daily_action", AFTER_GRANT, now=GRANTED) is True
    await db_session.commit()
    sent = await outbox.claim(
        db_session, groups=[Group.USAGE], today=(NOW + timedelta(days=1)).date(),
        now=NOW + timedelta(days=1), retry_after=timedelta(minutes=5),
    )
    return [row.props for row in sent]


async def test_a_decline_waits_for_an_open_recording_and_withdraws_it(db_session, sharing_allowed) -> None:
    """A row the recorder wrote under a consent read is still uncommitted when
    the user declines and shares again: the decline must wait for it."""
    await share(db_session, Group.USAGE)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as recorder:
        assert await record_count(recorder, "daily_action", SAVE, now=NOW) is True
        answers = asyncio.create_task(_decline_then_share_again(factory))
        try:
            await until_waiting(db_session.bind, answers)
            await recorder.commit()
            await answers
        finally:
            answers.cancel()
    assert await _claimed_after_the_grant(db_session) == [AFTER_GRANT]


async def test_a_decline_waits_for_an_open_tally_drain(db_session, sharing_allowed) -> None:
    """The drain reads consent once and records every count under that read."""
    await share(db_session, Group.USAGE)
    await db_session.commit()
    answers: list[asyncio.Task] = []

    class AnsweredMidDrain(AsyncSession):
        async def get(self, entity, ident, **kwargs):
            row = await super().get(entity, ident, **kwargs)
            if entity is AppSetting and ident == consent.SHARING_KEY and not answers:
                answers.append(asyncio.create_task(_decline_then_share_again(factory)))
                await until_waiting(db_session.bind, answers[0])
            return row

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    tally = ApiTally(usage=True)
    tally.count("save_job")
    try:
        async with async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AnsweredMidDrain)() as drainer:
            await drain(drainer, tally, now=NOW)
        await answers[0]
    finally:
        for task in answers:
            task.cancel()
    assert await _claimed_after_the_grant(db_session) == [AFTER_GRANT]


@pytest.mark.parametrize("status", [Status.UNDECIDED, Status.DECLINED, Status.SHARED])
async def test_only_a_grant_from_not_shared_withdraws_pending_rows(db_session, sharing_allowed, status) -> None:
    """A row recorded while the group was shared stays pending when the user
    answers yes again; a grant to a group that was not shared starts clean."""
    if status is not Status.UNDECIDED:
        await share(db_session, Group.USAGE, shared=status is Status.SHARED)
    await db_session.commit()
    await outbox.add_count(db_session, registry.CATALOGUE["daily_action"], SAVE, day=NOW.date(), at=NOW)
    await share(db_session, Group.USAGE, now=NOW + timedelta(seconds=1))
    [row] = (await db_session.scalars(select(UsageEvent))).all()
    assert (row.withdrawn_at is None) is (status is Status.SHARED)


async def test_declining_everything_makes_no_install_id(db_session, sharing_allowed) -> None:
    await share(db_session, *Group, shared=False)
    assert await get_install_id(db_session) is None


async def test_reset_replaces_the_install_id(db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE)
    first = await get_install_id(db_session)
    second = await reset_install_id(db_session, now=NOW)
    assert first != second
    assert await get_install_id(db_session) == second


@pytest.mark.parametrize(
    ("initial", "answers"),
    [(True, (False, False)), (None, (True, True)), (False, (True, False))],
    ids=["two-revocations", "first-answers", "grant-and-revocation"],
)
async def test_overlapping_group_answers_both_survive(db_session, sharing_allowed, initial, answers) -> None:
    if initial is not None:
        await share(db_session, Group.USAGE, shared=initial)
        await share(db_session, Group.CRASHES)
    await reset_install_id(db_session, now=NOW)
    await db_session.commit()
    first_read, second_read, second_lock, release_first = (asyncio.Event() for _ in range(4))

    class RacingSession(AsyncSession):
        async def get(self, entity, ident, **kwargs):
            row = await super().get(entity, ident, **kwargs)
            if entity is AppSetting and ident == consent.SHARING_KEY and not self.info.get("read"):
                self.info["read"] = True
                if self.info["writer"] == "first":
                    first_read.set()
                    await release_first.wait()
                else:
                    second_read.set()
            return row

        async def execute(self, statement, *args, **kwargs):
            if self.info["writer"] == "second" and "pg_advisory_xact_lock" in str(statement):
                second_lock.set()
            return await super().execute(statement, *args, **kwargs)

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=RacingSession)

    async def answer(writer, group, shared):
        async with factory(info={"writer": writer}) as session:
            await set_sharing(
                session, {group: shared}, text=f"Words for {group.value}", locale="en-US",
                fingerprints={group: fingerprint(group)}, now=NOW + timedelta(seconds=1),
            )
            await session.commit()

    tasks = [asyncio.create_task(answer("first", Group.USAGE, answers[0]))]
    signals = []
    try:
        async with asyncio.timeout(5):
            await first_read.wait()
            tasks.append(asyncio.create_task(answer("second", Group.CRASHES, answers[1])))
            signals = [asyncio.create_task(event.wait()) for event in (second_read, second_lock)]
            await asyncio.wait(signals, return_when=asyncio.FIRST_COMPLETED)
            if second_read.is_set():
                await tasks[1]
            release_first.set()
            await asyncio.gather(*tasks)
    finally:
        release_first.set()
        for task in [*tasks, *signals]:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, *signals, return_exceptions=True)

    db_session.expire_all()
    saved = await get_sharing(db_session)
    for group, shared in zip((Group.USAGE, Group.CRASHES), answers, strict=True):
        choice = saved.choices[group]
        assert choice.shared is shared
        assert choice.text == f"Words for {group.value}"
        assert choice.locale == "en-US"
        assert choice.fingerprint == fingerprint(group)
        assert choice.decided_at == NOW + timedelta(seconds=1)


async def test_a_rolled_back_revocation_keeps_consent_and_pending_events(db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE)
    await record_count(db_session, "daily_action", SAVE, now=NOW)
    await db_session.commit()
    await share(db_session, Group.USAGE, shared=False, now=NOW + timedelta(seconds=1))
    await db_session.rollback()
    assert (await get_sharing(db_session)).shared(Group.USAGE)
    [row] = (await db_session.scalars(select(UsageEvent))).all()
    assert row.withdrawn_at is None


async def test_a_cached_setting_does_not_restore_another_windows_revocation(db_session, sharing_allowed) -> None:
    await share(db_session, Group.USAGE, Group.CRASHES)
    await db_session.commit()
    cached = await db_session.get(AppSetting, consent.SHARING_KEY)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as other:
        await share(other, Group.USAGE, shared=False, now=NOW + timedelta(seconds=1))
        await other.commit()
    await share(db_session, Group.CRASHES, shared=False, now=NOW + timedelta(seconds=2))
    await db_session.commit()
    assert cached is not None
    db_session.expire_all()
    saved = await get_sharing(db_session)
    assert not saved.shared_groups()
    assert saved.choices[Group.USAGE].decided_at == NOW + timedelta(seconds=1)
