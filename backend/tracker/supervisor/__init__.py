"""One supervised process for all of RoleBand's background work.

`python -m tracker.supervisor` runs every job in `registry.JOBS` as a child process,
starts each when `due.decide` says so, records each run through `tracker.db.job_store`,
and keeps the API running beside them.
"""
