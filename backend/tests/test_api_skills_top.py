"""The Skills-tab leaderboard reads job_skills and never surfaces an industry
as a skill."""

from __future__ import annotations

from sqlalchemy.dialects import postgresql

from tracker.db.queries.skills import top_skills_stmt


def _sql(**kwargs) -> str:
    return str(
        top_skills_stmt([], **kwargs).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_reads_job_skills_and_their_concepts():
    sql = _sql()
    assert "job_skills" in sql
    assert "skill_concepts" in sql


def test_industries_are_excluded_from_the_skill_leaderboard():
    sql = _sql()
    assert "skill_concepts.facet != 'industry'" in sql


def test_only_displayable_rows_count():
    sql = _sql()
    assert "job_skills.confidence = 'high'" in sql
    assert "job_skills.importance_band != 'context'" in sql
    assert "skill_concepts.status = 'active'" in sql
    assert "jobs.status = 'open'" in sql


def test_filters_and_limit_apply():
    sql = _sql(company=["apple"], family=["software_engineering"], limit=7)
    assert "jobs.company IN ('apple')" in sql
    assert "jobs.family IN ('software_engineering')" in sql
    assert "LIMIT 7" in sql
