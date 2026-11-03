"""Profile materialization: every tracked company is a `/company` profile row.

`ensure_company_profiles` gives every tracked company a profile row, so a new
adapter's companies show on /company without any outside pay refresh. It must get-or-create per tracked company, record blueprint identity
as `"blueprint"` claims (superseded by any real source), and stay idempotent.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from tracker.blueprint import BLUEPRINT
from tracker.db.models import CompanyFact, CompanyProfile
from tracker.profiles import store
from tracker.profiles.seed import ensure_company_profiles


class _Scalars:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class _Result:
    def __init__(self, one, many):
        self._one = one
        self._many = many

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return _Scalars(self._many)


class FakeSession:
    """In-memory stand-in for the profile/fact queries the seeder issues."""

    def __init__(self, tracked):
        self.tracked = tracked
        self.profiles: dict[str, CompanyProfile] = {}
        self.facts: list[CompanyFact] = []

    async def get(self, model, key):
        assert model is CompanyProfile
        return self.profiles.get(key)

    def add(self, obj):
        if isinstance(obj, CompanyProfile):
            self.profiles[obj.slug] = obj
        elif isinstance(obj, CompanyFact):
            self.facts.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def scalars(self, stmt):
        # get_tracked_companies: all tracked_company rows.
        return _Scalars(list(self.tracked))

    async def execute(self, stmt):
        # Both fact queries bind company_slug; record_fact's latest-claim probe
        # additionally binds field + source (and limits to 1).
        params = stmt.compile().params
        slug = params.get("company_slug_1")
        field = params.get("field_1")
        source = params.get("source_1")
        if field is not None:
            matches = [
                f
                for f in self.facts
                if f.company_slug == slug and f.field == field and f.source == source
            ]
            matches.sort(key=lambda f: f.observed_at, reverse=True)
            return _Result(matches[0] if matches else None, matches)
        return _Result(None, [f for f in self.facts if f.company_slug == slug])


def _tracked(slug, display=None):
    return SimpleNamespace(slug=slug, display=display or slug.title())


def test_every_tracked_company_gets_a_profile_row():
    tracked = [_tracked(s, bp.display) for s, bp in BLUEPRINT.items()]
    tracked.append(_tracked("acme", "Acme"))  # user-added, not in blueprint
    session = FakeSession(tracked)

    changed = asyncio.run(ensure_company_profiles(session))

    assert set(session.profiles) == set(BLUEPRINT) | {"acme"}
    assert set(changed) == set(BLUEPRINT) | {"acme"}
    # Identity from our dataset (`company_identity.csv`), which
    # outranks the blueprint seed; the blueprint's own claim is still recorded.
    nvidia = session.profiles["nvidia"]
    assert nvidia.is_public is True
    assert nvidia.ticker == "NVDA"
    assert nvidia.brand_color == "#76b900"
    assert nvidia.field_meta["ticker"]["source"] == "roleband"
    assert {f.source for f in session.facts if f.company_slug == "nvidia" and f.field == "ticker"} == {
        "roleband", "blueprint"}
    # A non-blueprint company still gets a row (display only, no claims).
    acme = session.profiles["acme"]
    assert acme.display_name == "Acme"
    assert not [f for f in session.facts if f.company_slug == "acme"]


def test_seeding_is_idempotent():
    session = FakeSession([_tracked(s, bp.display) for s, bp in BLUEPRINT.items()])
    asyncio.run(ensure_company_profiles(session))
    facts_after_first = len(session.facts)

    changed = asyncio.run(ensure_company_profiles(session))

    assert changed == []
    assert len(session.facts) == facts_after_first


def test_manual_claim_outranks_blueprint_seed():
    session = FakeSession([_tracked("nvidia", "Nvidia")])
    # A human pinned the ticker before the seeder ever ran.
    session.profiles["nvidia"] = CompanyProfile(slug="nvidia", display_name="Nvidia")
    asyncio.run(store.record_fact(session, "nvidia", "ticker", "NVDA-CORRECTED", "manual"))

    asyncio.run(ensure_company_profiles(session))

    profile = session.profiles["nvidia"]
    assert profile.ticker == "NVDA-CORRECTED"
    assert profile.field_meta["ticker"]["source"] == "manual"


# --- pay policy is claimed by the core, not by an outside refresh ------------ #
# The atlas vehicle and vesting, and the inferred vehicle, are the core's own
# claims: a company no outside refresh reached still shows its vesting, and the
# facts stay in the core without any integration.


_EARLIER = datetime(2026, 7, 1, tzinfo=UTC)


def _facts(session, slug, field):
    return [(f.source, f.value["v"]) for f in session.facts if f.company_slug == slug and f.field == field]


def test_a_company_never_refreshed_still_gets_its_atlas_vesting_and_vehicle():
    session = FakeSession([_tracked("microsoft", "Microsoft"), _tracked("dropbox", "Dropbox")])
    asyncio.run(ensure_company_profiles(session))
    assert _facts(session, "microsoft", "vesting_schedule") == [("employer", "25/25/25/25")]
    assert _facts(session, "dropbox", "equity_vehicle") == [("employer", "rsu")]
    assert session.profiles["microsoft"].vesting_schedule == "25/25/25/25"


def test_the_inferred_vehicle_reads_the_resolved_listing_not_a_vendor_page():
    session = FakeSession([_tracked("acme", "Acme")])
    session.profiles["acme"] = CompanyProfile(slug="acme", display_name="Acme", is_public=True)
    session.add(CompanyFact(company_slug="acme", field="equity_vehicle", value={"v": "options"},
                            source="heuristic", observed_at=_EARLIER))
    asyncio.run(ensure_company_profiles(session))
    assert _facts(session, "acme", "equity_vehicle")[-1] == ("heuristic", "rsu")


def test_until_the_cut_no_inferred_vehicle_is_added_where_none_was_claimed():
    session = FakeSession([_tracked("acme", "Acme")])
    session.profiles["acme"] = CompanyProfile(slug="acme", display_name="Acme", is_public=True)
    asyncio.run(ensure_company_profiles(session))
    assert _facts(session, "acme", "equity_vehicle") == []


def test_our_dataset_answers_size_founding_site_and_headquarters_as_its_own():
    """Identity is ours, so our dataset carries these cells itself, and a
    profile reads them as `roleband` claims."""
    from tracker.levels.atlas import load_identity

    nvidia = load_identity()["nvidia"]
    assert nvidia.headcount and nvidia.year_founded and nvidia.website and nvidia.hq_city
    session = FakeSession([_tracked(s, bp.display) for s, bp in BLUEPRINT.items()])
    asyncio.run(ensure_company_profiles(session))
    profile = session.profiles["nvidia"]
    assert (profile.headcount, profile.year_founded, profile.website, profile.hq_city) == (
        nvidia.headcount, nvidia.year_founded, nvidia.website, nvidia.hq_city)
    for field in ("headcount", "year_founded", "website", "hq_city"):
        assert profile.field_meta[field]["source"] == "roleband", field


def test_unverified_identity_cells_say_so_and_read_as_their_kind():
    """A row whose cells are not yet verified says so in its basis and when they
    were read; sites are domains, sizes and years whole numbers."""
    from tracker.levels.atlas import load_identity

    identities = load_identity().values()
    unverified = [i for i in identities if i.basis == "unverified"]
    assert len(unverified) >= 100  # control: the seed is there
    for i in identities:
        assert i.website is None or ("://" not in i.website and not i.website.startswith("www.")), i.slug
        assert i.headcount is None or (isinstance(i.headcount, int) and i.headcount > 0), i.slug
        assert i.year_founded is None or 1800 <= i.year_founded <= 2026, i.slug


def test_a_company_the_atlas_says_is_not_listed_claims_no_ticker():
    """Claims are append-only and a source's newest wins, so a newer
    "no ticker" is what retracts one the row once held (Confluent's CFLT,
    before IBM bought it). A listed company claims its ticker; an unresearched
    one claims nothing."""
    session = FakeSession([_tracked("confluent"), _tracked("block"), _tracked("sambanova")])
    asyncio.run(ensure_company_profiles(session))
    assert _facts(session, "confluent", "ticker") == [("roleband", None)]
    assert _facts(session, "confluent", "is_public") == [("roleband", False)]
    assert _facts(session, "block", "ticker") == [("roleband", "XYZ")]
    assert _facts(session, "sambanova", "ticker") == []
