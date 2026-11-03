"""Rehearse upgrades on populated, isolated Postgres databases.

The baseline revision is the oldest supported schema. Its existing rows,
preferences and derived vectors must survive an upgrade to head. CI always
runs the rehearsal; locally ROLEBAND_REHEARSE_UPGRADE=1 enables it. The cluster
comes from the `baseline_database` fixture (`tests/upgrade_rehearsal.py`).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests import skip_policy
from tests.upgrade_rehearsal import (
    BASELINE_REVISION,
    REHEARSAL_FLAG,
    rehearsal_enabled,
    require_own_pgdata,
    run_alembic,
)
from tracker.platform.embedded_db import run_psql

HASHED: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "jobs",
        (
            "company", "req_id", "dedupe_key", "title", "url", "status", "level_band",
            "posted_at", "first_posted_at", "disclosed_base_min", "disclosed_base_max",
            "disclosed_currency", "disclosed_source",
        ),
        "id",
    ),
    ("scrape_runs", ("status", "jobs_seen", "jobs_new", "jobs_closed"), "id"),
    ("job_observations", ("job_id", "run_id", "title", "level_band", "locations", "payload"), "id"),
    ("job_lifecycle_events", ("job_id", "event_type", "detail"), "id"),
    ("favorites", ("job_id",), "id"),
    ("pursuits", ("job_id",), "id"),
    ("pursuit_events", ("pursuit_id", "actor", "event_type", "to_stage"), "id"),
    ("job_feedback", ("job_id", "verdict"), "id"),
    ("app_settings", ("key", "value"), "key"),
    (
        "role_catalog",
        (
            "role_group", "company", "count", "band_counts", "band_track_counts", "examples",
            "scope_cells", "domain_counts", "domain_examples",
        ),
        "id",
    ),
)

_SEED = """
insert into tracked_company (slug, display) values ('probeco', 'Probe Co');
insert into scrape_runs (status, jobs_seen, jobs_new, jobs_closed, per_source, drift_alerts)
  values ('success', 3, 1, 0, '{}'::jsonb, '[]'::jsonb);
insert into jobs (company, req_id, dedupe_key, title, url, locations, location_groups,
                  workplace_type, level_band, level_confidence, comp_currency, status,
                  total_days_open, repost_count, embedding)
  values ('probeco', 'REQ-1', 'probeco:REQ-1', 'Staff Engineer', 'https://example.test/1',
          '{"Remote"}', '{"remote"}', 'remote', 'L6', 'confirmed', 'USD', 'open', 4, 0,
          '@EMBEDDING@'::vector);
insert into job_observations (job_id, run_id, title, level_band, locations, payload)
  select j.id, r.id, 'Staff Engineer', 'L6', '{"Remote"}', '{}'::jsonb
  from jobs j, scrape_runs r;
insert into job_lifecycle_events (job_id, event_type, detail)
  select id, 'opened', '{}'::jsonb from jobs;
insert into favorites (job_id) select id from jobs;
insert into pursuits (job_id) select id from jobs;
insert into pursuit_events (pursuit_id, actor, event_type, to_stage)
  select id, 'user', 'stage_changed', 'applied' from pursuits;
insert into job_feedback (job_id, verdict) select id, 'not_for_me' from jobs;
insert into app_settings (key, value) values ('probe.setting', '{"on": true}'::jsonb);
update jobs set domains = '{payments_fintech,ai_ml}',
  posted_at = '2026-06-01 00:00:00+00', first_posted_at = '2026-05-01 00:00:00+00',
  disclosed_base_min = 180000, disclosed_base_max = 240000, disclosed_currency = 'USD',
  disclosed_source = 'connector';
-- A text-pass log for the band a connector read: its source must survive the log.
insert into ai_task_log (task_type, provider, availability_state, validation_result, job_id, meta)
  select 'disclosed_comp', 'deterministic', 'available', 'ok', id, '{"disclosed": true}'::jsonb
  from jobs;
update job_observations
  set payload = '{"source_facts": {"first_published_at": "2026-05-01T00:00:00+00:00"}}'::jsonb;
insert into app_settings (key, value)
  values ('enabled_domain_groups', '{"hidden": ["advertising", "finance_accounting"]}'::jsonb);
insert into role_catalog (role_group, company, count, band_counts, band_track_counts,
                          examples, scope_cells, domain_counts, domain_examples)
  values ('software_engineering', 'probeco', 1, '{"staff": 1}', '{}', '["Staff Engineer"]',
          '[{"band": "staff", "domains": ["payments_fintech", "ai_ml"], "count": 1}]',
          '{"payments_fintech": 1, "ai_ml": 1}', '{"ai_ml": ["Applied AI"]}');
"""

#: One rewrite per seeded column the digest must notice, with the table it lands in.
_REWRITES: tuple[tuple[str, str], ...] = (
    ("jobs", "update jobs set first_posted_at = null"),
    ("jobs", "update jobs set posted_at = posted_at + interval '1 day'"),
    ("jobs", "update jobs set disclosed_base_min = disclosed_base_min + 1"),
    ("jobs", "update jobs set disclosed_base_max = disclosed_base_max + 1"),
    ("jobs", "update jobs set disclosed_currency = 'EUR'"),
    ("jobs", "update jobs set disclosed_source = 'text'"),
    ("job_observations", "update job_observations set payload = '{}'::jsonb"),
    ("role_catalog", "update role_catalog set scope_cells = '[]'::jsonb"),
    ("role_catalog", "update role_catalog set domain_counts = '{}'::jsonb"),
    ("role_catalog", "update role_catalog set domain_examples = '{}'::jsonb"),
)


def _embedding_width(dsn: str, bin_dir: Path) -> int:
    kind = run_psql(
        dsn,
        bin_dir,
        "select format_type(atttypid, atttypmod) from pg_attribute "
        "where attrelid = 'jobs'::regclass and attname = 'embedding'",
    )
    found = re.search(r"\((\d+)\)", kind)
    assert found, f"could not read the embedding width from {kind!r}"
    return int(found.group(1))


def _seed(dsn: str, bin_dir: Path) -> int:
    width = _embedding_width(dsn, bin_dir)
    vector = "[" + ",".join("0.01" for _ in range(width)) + "]"
    # `.replace`, not `.format`: the seed is full of `'{}'::jsonb` and `'{"Remote"}'`,
    # every one of which str.format reads as a replacement field.
    run_psql(dsn, bin_dir, _SEED.replace("@EMBEDDING@", vector), timeout=None)
    return width


def _digest(dsn: str, bin_dir: Path) -> dict[str, str]:
    """One md5 per table over its seeded columns, in a fixed row order."""

    digest = {}
    for table, columns, order in HASHED:
        row = ", ".join(columns)
        digest[table] = run_psql(
            dsn,
            bin_dir,
            f"select coalesce(md5(string_agg(row({row})::text, chr(10) order by {order})), 'EMPTY') "
            f"from {table}",
        )
    return digest


def test_upgrading_a_populated_database_preserves_its_rows(baseline_database):
    env, dsn, bin_dir = baseline_database
    assert _seed(dsn, bin_dir) == 768
    before = _digest(dsn, bin_dir)
    assert all(value != "EMPTY" for value in before.values())

    result = run_alembic(env, "upgrade", "head")
    assert result.returncode == 0, (result.stderr + result.stdout)[-2000:]
    assert _digest(dsn, bin_dir) == before
    assert run_psql(dsn, bin_dir, "select domains::text from jobs") == "{payments_fintech,ai_ml}"
    assert run_psql(dsn, bin_dir, "select vector_dims(embedding) from jobs") == "768"
    assert (
        run_psql(dsn, bin_dir, "select count(*) from scrape_runs where process_group is not null")
        == "0"
    )

    result = run_alembic(env, "check")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-2000:]
    assert "No new upgrade operations detected" in output, output[-2000:]


def test_the_digest_notices_a_rewrite_of_each_seeded_column(baseline_database):
    """The negative control for the rehearsal: a column the digest missed would
    let a migration rewrite it while the upgrade test stays green."""

    _, dsn, bin_dir = baseline_database
    _seed(dsn, bin_dir)
    before = _digest(dsn, bin_dir)
    for table, rewrite in _REWRITES:
        run_psql(dsn, bin_dir, rewrite)
        after = _digest(dsn, bin_dir)
        assert {name for name in after if after[name] != before[name]} == {table}, rewrite
        before = after


@pytest.mark.parametrize("revision", ["93022d021230", "unknown_revision"])
def test_a_retired_or_unknown_revision_is_refused_without_rewriting_rows(
    baseline_database, revision
):
    env, dsn, bin_dir = baseline_database
    _seed(dsn, bin_dir)
    before = _digest(dsn, bin_dir)
    run_psql(dsn, bin_dir, f"update alembic_version set version_num = '{revision}'")

    result = run_alembic(env, "upgrade", "head")
    assert result.returncode != 0
    assert "Can't locate revision" in result.stdout + result.stderr
    assert _digest(dsn, bin_dir) == before
    assert run_psql(dsn, bin_dir, "select version_num from alembic_version") == revision


@pytest.mark.parametrize("target", ["base", "-1"])
def test_downgrading_the_baseline_refuses_to_delete_data(baseline_database, target):
    env, dsn, bin_dir = baseline_database
    _seed(dsn, bin_dir)
    before = _digest(dsn, bin_dir)
    result = run_alembic(env, "downgrade", target)
    assert result.returncode != 0
    assert "baseline cannot be downgraded" in result.stderr
    assert _digest(dsn, bin_dir) == before
    assert run_psql(dsn, bin_dir, "select version_num from alembic_version") == BASELINE_REVISION


_OBSERVATION = (
    "insert into external_comp_observation (provider, company_slug, source_level, total_amount,"
    " base_amount, equity_amount, bonus_amount, currency, snapshot_date, dedup_key)"
    " values ('probe', 'probeco', 'L5', {total}, 100000, 20000, 10000, '{currency}', '2026-10-01', 'k1')"
)


@pytest.mark.parametrize(
    ("currency", "total"), [("EUR", "130000"), ("USD", "null")], ids=["euros", "unknown-total"],
)
def test_a_downgrade_past_the_market_columns_refuses_pay_it_would_mislabel(
    baseline_database, currency, total
):
    """The old columns are named `*_usd` and hold every component: a report in
    euros would read as dollars, and an unknown total has no column to be."""
    env, dsn, bin_dir = baseline_database
    result = run_alembic(env, "upgrade", "f2a8d6c3b5e1")
    assert result.returncode == 0, (result.stderr + result.stdout)[-2000:]
    run_psql(dsn, bin_dir, _OBSERVATION.format(currency=currency, total=total))
    row = "select currency, total_amount from external_comp_observation"
    before = run_psql(dsn, bin_dir, row)

    result = run_alembic(env, "downgrade", "-1")
    assert result.returncode != 0
    assert "reported pay rows are not whole USD" in result.stderr
    assert run_psql(dsn, bin_dir, row) == before
    assert run_psql(dsn, bin_dir, "select version_num from alembic_version") == "f2a8d6c3b5e1"


def test_a_downgrade_past_plan_continuations_refuses_while_one_is_stored(baseline_database):
    """The older schema's kinds cannot hold a continuation, and the row is the
    plan's record of a scan: the downgrade stops and leaves it in place."""
    env, dsn, bin_dir = baseline_database
    result = run_alembic(env, "upgrade", "d3f9b1c7e5a2")
    assert result.returncode == 0, (result.stderr + result.stdout)[-2000:]
    run_psql(dsn, bin_dir, "insert into schedule_plan_runs (kind, started_at, companies, roster)"
                           " values ('continue', now(), 3, 10)")

    result = run_alembic(env, "downgrade", "-1")

    assert result.returncode != 0
    assert "continuations" in result.stderr
    assert run_psql(dsn, bin_dir, "select count(*) from schedule_plan_runs where kind = 'continue'") == "1"
    assert run_psql(dsn, bin_dir, "select version_num from alembic_version") == "d3f9b1c7e5a2"


def test_the_rehearsal_waits_for_its_opt_in_locally_and_always_runs_in_ci(
    monkeypatch, request
):
    """Closed, the fixture skips before it builds anything. Either the local flag
    or the integration flag CI sets opens it, so CI never skips a rehearsal."""

    monkeypatch.delenv(REHEARSAL_FLAG, raising=False)
    monkeypatch.delenv(skip_policy.ENV_FLAG, raising=False)
    assert not rehearsal_enabled()
    with pytest.raises(pytest.skip.Exception, match=REHEARSAL_FLAG):
        request.getfixturevalue("baseline_database")

    for opener in (REHEARSAL_FLAG, skip_policy.ENV_FLAG):
        with monkeypatch.context() as patched:
            patched.setenv(opener, "1")
            assert rehearsal_enabled(), opener
        assert not rehearsal_enabled()


def test_a_foreign_data_directory_is_refused(tmp_path):
    """The refusal fires, and says nothing was touched.

    The probe is faked rather than pointed at a real server: a control for "this
    would have hit the live cluster" must not go near the live cluster to prove it.
    """

    with pytest.raises(AssertionError) as caught:
        require_own_pgdata(str(Path.home() / ".roleband" / "db"), tmp_path / "rehearsal")
    assert "refusing to migrate" in str(caught.value)
    assert "Nothing has been migrated or seeded" in str(caught.value)


def test_a_symlinked_temp_path_is_accepted(tmp_path):
    """The macOS case the canonical comparison exists for.

    `/tmp` is a symlink to `/private/tmp`, so the server reports a path that is
    the same directory under a different name. Rejecting it would make the guard
    fire on every local run, and a guard that always fires gets deleted.
    """

    real = (tmp_path / "real").resolve()
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    require_own_pgdata(str(real), link)  # must not raise
