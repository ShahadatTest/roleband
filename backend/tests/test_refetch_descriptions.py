"""The description re-read: which rows it selects, what it saves, how it resumes.

Real commits on the scratch database, so the per-batch contract is measured:
a run that dies keeps the batches it saved, and a rerun picks up only the rows
still fetched before the cutoff. The network is a fake adapter that serves
Google-shaped markup, so the real detail connector parses it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from scripts import refetch_descriptions
from tracker.db.models import Job

pytestmark = pytest.mark.asyncio
OLD = datetime(2026, 10, 13, tzinfo=UTC)
CUTOFF = datetime(2026, 10, 18, 17, 0, tzinfo=UTC)
GLUED = "About the job\nYou guide the way.With expertise, you lead."
FRESH_HTML = "<div><h3>About the job</h3><p>You guide the way.</p><p>With expertise, you lead.</p></div>"


class Killed(BaseException):
    """The process dying, which no per-row guard catches."""


class FakeAdapter:
    def __init__(self, served: dict[str, str | None], calls: list[str], kill_on: int | None = None):
        self.served, self.calls, self.kill_on = served, calls, kill_on
        self.drift = SimpleNamespace(note=lambda *a, **k: None)
        self.collection_consent = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def payload_from_posting(self, raw):
        return None

    async def hydrate(self, raw):
        self.calls.append(raw.req_id)
        if self.kill_on is not None and len(self.calls) == self.kill_on:
            raise Killed
        raw.description_html = self.served.get(raw.req_id, FRESH_HTML)


def _job(n: int, *, company: str = "google", status: str = "open", fetched: datetime = OLD,
         in_scope: bool = True, disclosed_source: str | None = "connector") -> Job:
    return Job(
        company=company, req_id=f"r{n}", dedupe_key=f"{company}:r{n}", title="Engineering Manager",
        url=f"https://example.com/jobs/{n}", status=status, in_scope=in_scope, level_band="senior",
        level_confidence="confirmed", level_basis="stated", family="engineering_management",
        track="management", locations=["United States"], location_groups=["us"], domains=[],
        comp_currency="USD", first_seen=OLD, last_seen=OLD,
        description_text=GLUED, description_html="<p>old</p>",
        description_sections=[{"key": "about_the_job", "title": "About the job",
                               "content": "You guide the way.With expertise, you lead."}],
        description_fetched_at=fetched, disclosed_source=disclosed_source, structured_at=OLD,
    )


@pytest.fixture
def scoped(db_session, scratch_scope, monkeypatch):
    """The script on the scratch database, reading three companies' targets."""
    targets = {
        "google": {"adapter": "google", "consent": "yes"},
        "google-deepmind": {"adapter": "google", "consent": "yes"},
        "acme": {"adapter": "greenhouse"},
    }

    async def get_active_targets(session):
        return targets

    monkeypatch.setattr(refetch_descriptions, "get_active_targets", get_active_targets)
    monkeypatch.setattr(
        refetch_descriptions, "collection_access",
        lambda key, company, consent: SimpleNamespace(denied=consent is None),
    )
    return SimpleNamespace(session=db_session, targets=targets, monkeypatch=monkeypatch)


def _serve(scoped, served: dict[str, str | None] | None = None, kill_on: int | None = None) -> list[str]:
    calls: list[str] = []
    adapter = FakeAdapter(served or {}, calls, kill_on)
    scoped.monkeypatch.setattr(refetch_descriptions, "build_adapter", lambda *a, **k: adapter)
    return calls


async def _rows(scoped) -> dict[str, Job]:
    scoped.session.expire_all()
    rows = (await scoped.session.scalars(select(Job).order_by(Job.id))).all()
    return {row.req_id: row for row in rows}


async def _run(**kw):
    return await refetch_descriptions.run(adapter_key="google", before=CUTOFF, **kw)


async def test_selects_open_rows_of_the_adapter_fetched_before_the_cutoff(scoped):
    scoped.session.add_all([
        _job(1),
        _job(2, company="google-deepmind"),
        _job(3, status="closed"),
        _job(4, fetched=CUTOFF + timedelta(hours=1)),
        _job(5, company="acme"),
    ])
    await scoped.session.commit()
    calls = _serve(scoped)

    result = await _run(apply=False)

    assert result["stats"]["pending"] == 2
    assert calls == []
    assert (await _rows(scoped))["r1"].description_text == GLUED


async def test_apply_saves_the_new_parse_and_leaves_unselected_rows_alone(scoped, tmp_path):
    scoped.session.add_all([
        _job(1),
        _job(2, disclosed_source="text"),
        _job(3, status="closed"),
    ])
    await scoped.session.commit()
    calls = _serve(scoped)
    backup = tmp_path / "old.jsonl"

    result = await _run(apply=True, backup=str(backup))

    rows = await _rows(scoped)
    assert result["stats"]["saved"] == 2
    assert sorted(calls) == ["r1", "r2"]
    for key in ("r1", "r2"):
        assert rows[key].description_sections == [
            {"key": "about_the_job", "title": "About the job",
             "content": "You guide the way.\nWith expertise, you lead."},
        ]
        assert "way.With" not in rows[key].description_text
        assert rows[key].description_fetched_at > CUTOFF
    # A connector band stays read; a text-pass row is queued for a re-read.
    assert rows["r1"].structured_at == OLD
    assert rows["r2"].structured_at is None
    assert rows["r3"].description_text == GLUED
    saved = [json.loads(line) for line in backup.read_text().splitlines()]
    assert [entry["id"] for entry in saved] == [rows["r1"].id, rows["r2"].id]
    assert all(entry["description_text"] == GLUED for entry in saved)


async def test_a_killed_run_keeps_its_batches_and_a_rerun_finishes_the_rest(scoped):
    scoped.session.add_all([_job(1), _job(2), _job(3)])
    await scoped.session.commit()

    _serve(scoped, kill_on=2)
    with pytest.raises(Killed):
        await _run(apply=True, batch=1)
    rows = await _rows(scoped)
    assert rows["r1"].description_fetched_at > CUTOFF
    assert rows["r2"].description_text == GLUED

    calls = _serve(scoped)
    result = await _run(apply=True, batch=1)

    assert calls == ["r2", "r3"], "the rerun re-reads only what the dead run did not save"
    assert result["stats"]["saved"] == 2
    assert all(row.description_fetched_at > CUTOFF for row in (await _rows(scoped)).values())


async def test_a_source_that_serves_no_text_leaves_the_row_selected(scoped):
    scoped.session.add_all([_job(1)])
    await scoped.session.commit()
    _serve(scoped, served={"r1": None})

    result = await _run(apply=True)

    row = (await _rows(scoped))["r1"]
    assert result["stats"]["no_text"] == 1
    assert row.description_text == GLUED
    assert row.description_fetched_at == OLD
    assert (await _run(apply=False))["stats"]["pending"] == 1


async def test_a_company_without_consent_is_reported_and_never_fetched(scoped):
    scoped.targets["google-deepmind"] = {"adapter": "google", "consent": None}
    scoped.session.add_all([_job(1, company="google-deepmind")])
    await scoped.session.commit()
    calls = _serve(scoped)

    result = await _run(apply=True)

    assert result["denied"] == ["google-deepmind"]
    assert result["stats"]["pending"] == 0
    assert calls == []


async def test_rows_on_the_board_are_read_first(scoped):
    scoped.session.add_all([_job(1, in_scope=False), _job(2)])
    await scoped.session.commit()
    calls = _serve(scoped)

    await _run(apply=True, batch=1)

    assert calls == ["r2", "r1"]


async def test_text_matches_reads_only_rows_whose_stored_text_matches(scoped):
    seamed, clean = _job(1), _job(2)
    seamed.description_text = "About the job\nThrough collective effort.Individual pay is determined by skills."
    clean.description_text = "About the job\nThrough collective effort.\n\nIndividual pay is determined by skills."
    scoped.session.add_all([seamed, clean])
    await scoped.session.commit()
    calls = _serve(scoped)
    seam = "[.!?]Individual pay is determined"

    assert (await _run(apply=False, text_matches=seam))["stats"]["pending"] == 1
    await _run(apply=True, text_matches=seam)

    assert calls == ["r1"]
    rows = await _rows(scoped)
    assert rows["r1"].description_fetched_at > CUTOFF
    assert rows["r2"].description_fetched_at == OLD
    assert (await _run(apply=False, text_matches=seam))["stats"]["pending"] == 0
