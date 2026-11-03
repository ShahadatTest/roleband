from sqlalchemy.dialects import postgresql

from tracker.db.queries.jobs import most_updated_open_stmt


def test_most_updated_open_query_excludes_any_previously_closed_job():
    sql = str(
        most_updated_open_stmt(limit=7).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "job_lifecycle_events.event_type = 'changed'" in sql
    assert "job_lifecycle_events.event_type = 'closed'" in sql
    assert "jobs.status = 'open'" in sql
    assert "LEFT OUTER JOIN" in sql
    assert "anon_2.job_id IS NULL" in sql
    assert "count(*) >= 2" in sql
    assert "LIMIT 7" in sql
