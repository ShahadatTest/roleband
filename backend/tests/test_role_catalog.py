"""Pre-scope role-band inventory and safe snapshot replacement."""

import asyncio
from dataclasses import dataclass

from tracker.db.models import RoleCatalog, TrackedCompany
from tracker.enrich.enricher import Annotation, annotate
from tracker.schema import LevelBand, LevelConfidence, RawJob, RoleTrack
from tracker.scope.catalog_store import persist_company_catalog
from tracker.taxonomy.role_catalog import (
    UNCLASSIFIED_KEY,
    add_to_catalog,
    catalog_collection_error,
)


def _raw(req: str, title: str = "Software Engineer") -> RawJob:
    return RawJob(company="acme", req_id=req, title=title, url=f"https://x/{req}")


def _ann(
    band: LevelBand,
    family: str | None = "software_engineering",
    located=True,
    domains: list[str] | None = None,
):
    return Annotation(
        band=band,
        confidence=LevelConfidence.CONFIRMED,
        family=family,
        location_groups=["uk"] if located else [],
        track=RoleTrack.TECHNICAL,
        domains=domains or [],
    )


def test_catalog_tallies_joint_role_and_band_before_scope():
    tallies = {}
    add_to_catalog(tallies, _raw("1", "Junior Software Engineer"), _ann(LevelBand.ENTRY))
    add_to_catalog(tallies, _raw("2", "Staff Software Engineer"), _ann(LevelBand.STAFF))
    add_to_catalog(tallies, _raw("3"), _ann(LevelBand.SENIOR, located=False))
    add_to_catalog(tallies, _raw("4"), _ann(LevelBand.SENIOR, family=None))

    tally = tallies["software_engineering"]
    assert tally.count == 2
    assert tally.band_counts == {"entry": 1, "staff": 1}
    assert tally.band_track_counts == {
        "entry": {"technical": 1},
        "staff": {"technical": 1},
    }
    assert set(tally.titles) == {"Junior Software Engineer", "Staff Software Engineer"}


@dataclass
class _Tracked:
    role_catalog_status: str = "pending"
    role_catalog_error: str | None = None
    role_catalog_scanned_at: object | None = None


class _Session:
    def __init__(self, status="pending"):
        self.tracked = _Tracked(status)
        self.executed = []
        self.added = []

    async def get(self, model, key):
        assert model is TrackedCompany
        return self.tracked

    async def execute(self, stmt):
        self.executed.append(stmt)

    def add(self, row):
        assert isinstance(row, RoleCatalog)
        self.added.append(row)


def test_partial_snapshot_cannot_overwrite_ready_catalog():
    session = _Session("ready")
    result = asyncio.run(
        persist_company_catalog(session, "acme", {}, complete=False)
    )
    assert result == "ready"
    assert session.executed == []
    assert session.added == []


def test_persisted_catalog_keeps_joint_band_and_track_counts():
    session = _Session("pending")
    tallies = {}
    add_to_catalog(tallies, _raw("1", "Staff Software Engineer"), _ann(LevelBand.STAFF))

    result = asyncio.run(persist_company_catalog(session, "acme", tallies, complete=True))

    assert result == "ready"
    assert session.added[0].band_track_counts == {"staff": {"technical": 1}}


def test_error_preserves_rows_and_marks_state():
    session = _Session("ready")
    result = asyncio.run(
        persist_company_catalog(session, "acme", {}, complete=False, error="timeout")
    )
    assert result == "error"
    assert session.executed == []
    assert session.tracked.role_catalog_status == "error"
    assert session.tracked.role_catalog_error == "timeout"


def test_zero_result_list_drift_is_catalog_fatal():
    error = catalog_collection_error(
        errors=[], scanned=0, drift_alerts=["list parser returned no cards"]
    )

    assert error == "zero-result list drift: list parser returned no cards"


def test_hydrate_drift_after_list_results_is_not_catalog_fatal():
    error = catalog_collection_error(
        errors=[], scanned=12, drift_alerts=["description section missing"]
    )

    assert error is None


def test_catalog_tallies_domains_with_unclassified_as_first_class_bucket():
    tallies = {}
    raw_dept = RawJob(
        company="acme", req_id="d1", title="Sr. Operations Manager",
        url="https://x/d1", department="Fulfillment & Operations Management",
    )
    add_to_catalog(tallies, raw_dept, _ann(LevelBand.SENIOR, domains=["logistics_fulfillment"]))
    add_to_catalog(tallies, raw_dept, _ann(LevelBand.SENIOR, domains=["logistics_fulfillment", "ai_ml"]))
    # No domains → counted under the explicit unclassified key, never dropped:
    # the fail-open volume must stay visible.
    add_to_catalog(tallies, _raw("d2", "Software Engineer"), _ann(LevelBand.SENIOR))

    tally = tallies["software_engineering"]
    assert tally.domain_counts["logistics_fulfillment"] == 2
    assert tally.domain_counts["ai_ml"] == 1
    assert tally.domain_counts[UNCLASSIFIED_KEY] == 1
    # Evidence is the employer's verbatim category text, deduplicated + capped.
    assert tally.domain_examples["logistics_fulfillment"] == [
        "Fulfillment & Operations Management"
    ]
    assert UNCLASSIFIED_KEY not in tally.domain_examples


def test_a_real_annotation_satisfies_the_catalog_protocol():
    """`add_to_catalog` types its input as `CatalogAnnotation` so the vocabulary
    tier does not import `enrich` to name a class. Nothing type-checks this
    repo, so a Protocol that drifted from `Annotation` would fail silently at
    the one place it matters — here.

    The realistic posting is load-bearing: `add_to_catalog` returns early when
    `family` is None or `location_groups` is empty, so a vague title would make
    this pass without ever reading an attribute.
    """
    job = RawJob(
        company="google",
        req_id="req-1",
        title="Staff Software Engineer, Search",
        url="https://careers.google.com/req-1",
        locations=["Mountain View, CA, USA"],
    )
    ann = annotate(job)
    assert ann.family is not None and ann.location_groups, ann

    tallies: dict = {}
    add_to_catalog(tallies, job, ann)

    tally = tallies[ann.family]
    assert tally.count == 1
    assert tally.band_counts[ann.band.value] == 1
    assert tally.band_track_counts[ann.band.value][ann.track.value] == 1
    assert tally.titles["Staff Software Engineer, Search"] == 1
    # [] is a first-class bucket, not an omission.
    assert sum(tally.domain_counts.values()) == 1
