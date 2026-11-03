"""Hidden-company exclusion on the job-list filter, with the by-ID exemption.

Compiles the filter SQL (no DB) to pin two things: browse queries exclude hidden
companies, and explicit by-ID picks (Compare's `ids`, Favorites' `favorites_only`)
never do — a saved job whose company was later hidden must still resolve.
"""

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from tracker.db.models import Job
from tracker.db.queries.jobs import apply_job_filters, exclude_hidden, structured_conds


def _filter_sql(params: dict) -> str:
    stmt = apply_job_filters(select(Job.id), params)
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_browse_query_excludes_hidden_companies():
    sql = _filter_sql({"status": "open", "hidden": ["amazon", "netflix"]})
    assert "jobs.company NOT IN ('amazon', 'netflix')" in sql


def test_no_exclusion_when_nothing_hidden():
    sql = _filter_sql({"status": "open", "hidden": []})
    # The claim is about COMPANY visibility: no hidden set, no company clause.
    # (Dismissed-row exclusion is a different, always-on browse filter.)
    assert "jobs.company NOT IN" not in sql


def test_ids_request_bypasses_hidden_exclusion():
    # Compare fetches explicit ids; a hidden company's saved job must still return.
    conds = structured_conds({"ids": [1, 2, 3], "hidden": ["amazon"]})
    sql = " ".join(str(c.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})) for c in conds)
    assert "company NOT IN" not in sql
    assert "jobs.id IN (1, 2, 3)" in sql


def test_favorites_request_bypasses_hidden_exclusion():
    conds = structured_conds({"favorites_only": True, "hidden": ["amazon"]})
    sql = " ".join(str(c.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})) for c in conds)
    assert "company NOT IN" not in sql


def test_exclude_hidden_helper_is_noop_on_empty():
    base = select(Job.id).where(Job.status == "open")
    assert str(exclude_hidden(base, [])) == str(base)
    assert "NOT IN" in str(exclude_hidden(base, ["amazon"]).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    ))


def test_domain_filter_matches_worlds_and_unclassified():
    # A selected world filters by array overlap, like locations.
    sql = _filter_sql({"domain": ["ai_ml", "cloud_infra"]})
    assert "jobs.domains && " in sql
    assert "ai_ml" in sql and "cloud_infra" in sql
    assert "cardinality" not in sql

    # "unclassified" is a first-class option: the fail-open volume (NULL
    # pre-axis rows and honestly-empty {} rows) must stay findable.
    uncls = _filter_sql({"domain": ["unclassified"]})
    assert "jobs.domains IS NULL" in uncls
    assert "cardinality(jobs.domains) = 0" in uncls
    assert "&&" not in uncls

    # Mixed selection ORs the two shapes — a row matches either way.
    mixed = _filter_sql({"domain": ["ai_ml", "unclassified"]})
    assert "jobs.domains && " in mixed
    assert "jobs.domains IS NULL" in mixed


def test_dismissed_rows_hide_from_browse_and_stay_filterable_back():
    # Default browse excludes dismissed rows ("not for me" is sticky), and
    # a place set whose member is dismissed (the role's mark)...
    browse = _filter_sql({"status": "open"})
    assert "NOT (jobs.id IN (SELECT job_feedback.job_id" in browse
    assert "job_place_set_member_2.job_id IN (SELECT job_feedback.job_id" in browse

    # ...the Dismissed lens inverts the filter instead of stacking it...
    only = _filter_sql({"dismissed_only": True})
    assert "jobs.id IN (SELECT job_feedback.job_id" in only
    assert "NOT (jobs.id IN (SELECT job_feedback.job_id" not in only

    # ...and explicit by-ID / saved reads stay resolvable: a saved job the
    # user later dismissed must still open from Favorites and Compare.
    for params in ({"ids": [7]}, {"favorites_only": True}):
        sql = _filter_sql(params)
        assert "job_feedback" not in sql, params


def test_show_lens_filters_on_the_reader_mark():
    # "Unread" is the rows /view never stamped; "Read" the rows it did. It is
    # a request filter, so unlike the dismissed exclusion it applies to by-ID
    # and saved reads that ask for it, and absent it adds no clause at all.
    assert "jobs.viewed_at IS NULL" in _filter_sql({"viewed": "unread"})
    assert "jobs.viewed_at IS NOT NULL" in _filter_sql({"viewed": "read"})
    assert "viewed_at" not in _filter_sql({"status": "open"})
    assert "jobs.viewed_at IS NULL" in _filter_sql({"ids": [7], "viewed": "unread"})
