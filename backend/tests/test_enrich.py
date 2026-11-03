"""Pure-logic tests for level mapping and classification (no network)."""

from __future__ import annotations

import pytest

from tests.factories import scope_filter
from tracker.config import default_enabled_location_groups
from tracker.enrich.classify import classify_family, location_groups_for, match_location_groups
from tracker.enrich.enricher import ScopeFilter, annotate, passes_filters
from tracker.enrich.level_mapper import map_level
from tracker.levels import default_enabled_bands
from tracker.schema import LevelBand, LevelConfidence, RawJob, RoleTrack
from tracker.taxonomy.domains import all_slugs as all_domain_slugs
from tracker.taxonomy.roles import default_enabled_slugs
from tracker.taxonomy.tracks import default_enabled_tracks

DEFAULT_ROLES = set(default_enabled_slugs())
ALL_TRACKS = frozenset(default_enabled_tracks())
ALL_LOCATIONS = frozenset(default_enabled_location_groups())
DEFAULT_SCOPE = ScopeFilter(
    enabled_bands=frozenset(default_enabled_bands()),
    enabled_roles=frozenset(DEFAULT_ROLES),
    enabled_tracks=ALL_TRACKS,
    enabled_locations=ALL_LOCATIONS,
    enabled_domains=frozenset(),
)


def _job(company: str, title: str, locations: list[str]) -> RawJob:
    return RawJob(company=company, req_id="x", title=title, url="u", locations=locations)


def test_early_stage_titles_classify_to_first_class_stages():
    # Intern and Entry are distinct first-class stages, not a "below" bucket
    #: an internship is not a first full-time role, and Junior is.
    for t in ["Software Engineering Intern", "Graduate Intern, Data", "PhD Student Researcher", "Werkstudent Data"]:
        band, conf = map_level(_job("google", t, ["Mountain View, CA, USA"]))
        assert band is LevelBand.INTERN, t
        assert conf is LevelConfidence.CONFIRMED
    for t in ["New Grad SWE", "Graduate Trainee", "Junior Data Analyst", "Associate Product Manager", "Apprentice Engineer"]:
        band, conf = map_level(_job("google", t, ["Mountain View, CA, USA"]))
        assert band is LevelBand.ENTRY, t
        assert conf is LevelConfidence.CONFIRMED
    # "Intern" is a whole word: Internal and Internet are not internships.
    for t in ["Internal Audit Manager", "Staff Software Engineer, Internet Egress"]:
        band, _ = map_level(_job("google", t, ["Mountain View, CA, USA"]))
        assert band is not LevelBand.INTERN, t


def test_unmarked_titles_are_mid_and_flagged_unconfirmed():
    # A bare title carries no seniority signal: mid-level, honestly flagged —
    # absence of signal is not confirmation.
    band, conf = map_level(_job("openai", "Software Engineer", ["San Francisco"]))
    assert band is LevelBand.MID
    assert conf is LevelConfidence.UNCONFIRMED


def test_google_uses_title_level_without_company_floor():
    band, conf = map_level(_job("google", "Product Manager", ["Mountain View, CA, USA"]))
    assert band is LevelBand.SENIOR
    assert conf is LevelConfidence.UNCONFIRMED
    junior, _ = map_level(_job("google", "Junior Software Engineer", ["London, UK"]))
    assert junior is LevelBand.ENTRY


def test_management_titles_are_confirmed_l6():
    band, conf = map_level(_job("anthropic", "Engineering Manager, Inference", ["London, UK"]))
    assert band is LevelBand.STAFF
    assert conf is LevelConfidence.CONFIRMED


def test_group_pm_is_principal():
    band, _ = map_level(_job("google", "Group Product Manager, Ads", ["London, UK"]))
    assert band is LevelBand.PRINCIPAL


def test_director_plus():
    band, _ = map_level(_job("anthropic", "Director of Product", ["San Francisco"]))
    assert band is LevelBand.DIRECTOR_PLUS


def test_ambiguous_pm_is_senior_unconfirmed():
    band, conf = map_level(_job("openai", "Product Manager, API", ["San Francisco"]))
    assert band is LevelBand.SENIOR
    assert conf is LevelConfidence.UNCONFIRMED


def test_a_senior_pm_states_its_rung_but_a_senior_team_does_not():
    assert map_level(_job("openai", "Senior Product Manager, API", ["San Francisco"])) == (
        LevelBand.SENIOR, LevelConfidence.CONFIRMED,
    )
    assert map_level(_job("openai", "Product Manager, Senior Leadership Tools", ["San Francisco"])) == (
        LevelBand.SENIOR, LevelConfidence.UNCONFIRMED,
    )


def test_mts_is_senior_unconfirmed():
    band, conf = map_level(_job("openai", "Member of Technical Staff", ["San Francisco"]))
    assert band is LevelBand.SENIOR
    assert conf is LevelConfidence.UNCONFIRMED


def _taxonomy(job):
    """The taxonomy groups a posting matches: metros, countries, regions. The
    stored list adds the gazetteer cities after them (see the test below)."""
    return location_groups_for(job.locations)


def test_location_matching():
    # Two-level: a Bay Area posting carries both the metro AND its country, metro
    # first so location_groups[0] (comp/primary axis) stays the fine metro.
    assert _taxonomy(_job("google", "x", ["Mountain View, CA, USA"])) == [
        "silicon_valley",
        "united_states",
        "north_america",
    ]
    # A European posting carries its country AND the Europe umbrella (country first).
    # London is a metro under uk (added so a coverage manifest can declare the
    # city several sources can only ask about), so it leads the chain.
    assert _taxonomy(_job("apple", "x", ["London, UK"])) == [
        "london",
        "uk",
        "europe",
    ]
    assert _taxonomy(_job("netflix", "x", ["Singapore"])) == [
        "singapore",
        "southeast_asia",
    ]
    # A disabled country group still *matches* (matching != tracked); the enabled
    # filter is applied downstream at scope-gate time.
    assert _taxonomy(_job("netflix", "x", ["Tokyo, Japan"])) == [
        "japan",
        "east_asia",
    ]


def test_location_matching_us_metros_and_country():
    # Non-Bay-Area US hubs get their metro tag + united_states, country never first.
    def groups(loc):
        return _taxonomy(_job("microsoft", "x", [loc]))

    us = ["united_states", "north_america"]
    assert groups("Seattle, Washington, USA") == ["pacific_northwest", *us]
    assert groups("Austin, Texas, USA") == ["austin", *us]
    assert groups("New York, NY, USA") == ["new_york", *us]
    assert groups("Arlington, Virginia, USA") == ["dc_metro", *us]
    # A US city with no metro group still gets the country.
    assert groups("Denver, Colorado, USA") == us
    # Country-first Workday phrasing and bare state abbrevs still read as US.
    assert groups("United States, Washington, Redmond") == ["pacific_northwest", *us]


def test_location_matching_country_disambiguation():
    # No US string leaks into `canada`, and no California string does either
    # (", CA" is California, not Canada). Guards the substring/token collisions.
    def groups(loc):
        return _taxonomy(_job("x", "x", [loc]))

    assert "canada" not in groups("San Francisco, CA, USA")
    assert "canada" not in groups("Los Angeles, CA")
    assert groups("Vancouver, British Columbia, Canada") == ["canada", "north_america"]
    # Foreign country token wins over a colliding US-state abbrev (MD here is a
    # comma-part but the ES/Spain token classifies the piece); Spain implies Europe.
    assert groups("Madrid, MD, ES") == ["spain", "europe"]
    # A non-US city containing the substring "usa" must not read as US. South
    # Korea is a real group, so this pins the US half rather than emptiness.
    assert _taxonomy(_job("x", "x", ["Busan, South Korea"])) == [
        "south_korea",
        "east_asia",
    ]
    # The one ISO name that is also a US state name. Both directions, because
    # `out |= foreign` is unconditional and would otherwise tag the country too.
    assert groups("Atlanta, Georgia, USA") == ["united_states", "north_america"]
    assert groups("Tbilisi, Georgia") == ["georgia", "middle_east"]
    # Alpha-2 codes that collide with a US state abbrev are never admitted.
    assert groups("Indianapolis, IN, USA") == ["united_states", "north_america"]
    assert groups("New Orleans, LA, USA") == ["united_states", "north_america"]


def test_location_matching_bare_city_fallbacks():
    # Bare city names with no country/state token still resolve, via the country
    # substring fallback (UK) and the metro's parent country (US).
    def groups(loc):
        return _taxonomy(_job("x", "x", [loc]))

    # Bare "London" resolves through the london metro to its country and region.
    assert groups("London") == ["london", "uk", "europe"]
    assert groups("Cupertino") == ["silicon_valley", "united_states", "north_america"]
    assert groups("Sunnyvale") == ["silicon_valley", "united_states", "north_america"]
    assert groups("Singapore") == ["singapore", "southeast_asia"]


def test_location_group_defaults_and_order():
    from tracker.config import LOCATION_GROUPS, default_enabled_location_groups

    defaults = set(default_enabled_location_groups())
    # US-wide + the US metros + the two existing countries ship enabled.
    assert "united_states" in defaults
    assert {"silicon_valley", "pacific_northwest", "new_york", "austin", "dc_metro"} <= defaults
    assert {"uk", "singapore"} <= defaults
    # The Europe umbrella + low-volume countries are defined but shipped disabled
    # (enabling Europe would track the whole continent; uk stays enabled on its own).
    for slug in ("europe", "ireland", "germany", "switzerland", "spain", "italy",
                 "canada", "japan", "china", "poland"):
        assert slug in LOCATION_GROUPS and slug not in defaults
    # European countries nest under europe; US metros under united_states.
    assert LOCATION_GROUPS["uk"]["parent"] == "europe"
    assert LOCATION_GROUPS["silicon_valley"]["parent"] == "united_states"
    assert LOCATION_GROUPS["europe"]["kind"] == "region"
    # Leaves are declared before their umbrella so location_groups[0] (comp axis)
    # stays the fine leaf, not the umbrella.
    order = list(LOCATION_GROUPS)
    assert order.index("silicon_valley") < order.index("united_states")


def test_europe_umbrella_groups_member_countries():
    # Any European country implies the Europe umbrella; non-European ones do not.
    def groups(loc):
        return _taxonomy(_job("x", "x", [loc]))

    assert groups("Munich, Germany") == ["germany", "europe"]
    assert groups("Dublin, Ireland") == ["ireland", "europe"]
    assert groups("Zürich, Switzerland") == ["switzerland", "europe"]
    # Non-European countries carry THEIR region, not Europe's.
    assert groups("Singapore") == ["singapore", "southeast_asia"]
    assert groups("Toronto, Ontario, Canada") == ["canada", "north_america"]
    # A multi-country posting carries each country and Europe once, deepest
    # first: the london metro leads, then the two same-depth countries (tied on
    # depth, so broken by declaration order, alphabetical since countries
    # are generated), then the umbrella last.
    assert _taxonomy(_job("x", "x", ["London, UK | Berlin, Germany"])) == [
        "london", "germany", "uk", "europe",
    ]


def test_stored_location_slugs_add_the_city_after_the_taxonomy():
    """What a job stores: the taxonomy groups, deepest first, then the GeoNames
    city the place names. The city never leads, so `location_groups[0]` (the
    comp axis) stays the metro or country it always was."""
    def stored(loc):
        return match_location_groups(_job("x", "x", [loc]))

    assert stored("London, UK") == ["london", "uk", "europe", "city_2643743"]
    assert stored("Stockholm, Sweden") == ["sweden", "europe", "city_2673730"]
    # A city a metro names hangs off the metro.
    assert stored("Mountain View, CA, USA")[:3] == ["silicon_valley", "united_states", "north_america"]
    assert stored("Mountain View, CA, USA")[3] == "city_5375480"
    # A bare city lands in its country.
    assert stored("Berlin") == ["germany", "europe", "city_2950159"]
    assert stored("Bangalore") == ["india", "south_asia", "city_1277333"]
    # The same name elsewhere is decided by the country the place names.
    assert stored("San Jose, Costa Rica") == ["costa_rica", "latin_america", "city_3621849"]
    assert stored("Portland, ME, USA")[-1] == "city_4975802"
    assert stored("Portland, OR")[-1] == "city_5746545"
    # No city where the place names none, or no single one.
    assert stored("Remote - US") == ["united_states", "north_america"]
    assert stored("Remote, Mexico") == ["mexico", "latin_america"]
    assert stored("Cambridge") == []


def test_role_classification():
    assert classify_family(_job("google", "Engineering Manager", [])) == "engineering_management"
    assert classify_family(_job("google", "Group Product Manager", [])) == "product_management"
    assert classify_family(_job("google", "Technical Program Manager", [])) == "technical_program_management"
    # TPM is independently selectable; general program roles stay in their existing group.
    assert classify_family(_job("google", "Program Manager", [])) == "program_management"
    # SWE classifies into its own group (tracked only if enabled in settings).
    assert classify_family(_job("google", "Staff Software Engineer", [])) == "software_engineering"
    assert classify_family(_job("openai", "Research Engineer", [])) == "ml_ai_research"
    assert classify_family(_job("openai", "Enterprise Account Executive", [])) == "sales_business_development"


@pytest.mark.parametrize(("title", "family"), [
    # A keyword starts a word: "ux " is not the end of Linux, Redux or Benelux,
    # and "soc " is not the end of "Assoc".
    ("Linux Engineer", "software_engineering"),
    ("Embedded Linux Engineer", "software_engineering"),
    ("Linux Platform Software Engineer", "software_engineering"),
    ("Senior Frontend Engineer (React/Redux)", "software_engineering"),
    ("Enterprise Account Executive, Benelux", "sales_business_development"),
    ("Modern Service Management Assoc Director", None),
    # The controls: the keyword itself still files its family.
    ("UX Engineer", "design_ux"),
    ("Senior UX Designer", "design_ux"),
    ("SoC Design Engineer", "hardware_engineering"),
    # One-word compounds keep the family their second half names.
    ("Presales Engineer", "solutions_sales_eng"),
    ("Telesales Representative", "sales_business_development"),
    ("Senior SecDevOps Engineer", "infrastructure_sre"),
    ("Senior Hydromechanical Engineer", "hardware_engineering"),
    # A controller an engineer builds is not a finance title...
    ("Memory Controller Engineer", "software_engineering"),
    ("Battery Controller Engineer", "software_engineering"),
    ("Flight Controller Software Engineer", "software_engineering"),
    ("Document Controller", None),
    # ...and a finance controller still is.
    ("Financial Controller", "finance_accounting"),
    ("Assistant Controller", "finance_accounting"),
    ("Controller", "finance_accounting"),
    ("VP, Controller", "finance_accounting"),
    ("Credit Controller", "finance_accounting"),
])
def test_a_family_keyword_names_a_word_not_part_of_one(title, family):
    assert classify_family(_job("acme", title, [])) == family


def test_applied_science_is_a_title_phrase_not_only_a_department():
    # `applied scientist` alone does not cover amazon's "Applied Science
    # Manager": the title would classify as None and only the department field
    # could rescue it, leaving the *query* parser (which has no department) with
    # no family at all. One shared table owns both surfaces, so
    # this is asserted here and in test_search_parse.
    assert classify_family(_job("amazon", "Applied Science Manager", [])) == "ml_ai_research"
    assert (
        classify_family(_job("amazon", "Applied Science Manager, Prime Video", []))
        == "ml_ai_research"
    )
    # It is a science-leadership role, so the track must stay management.
    assert annotate(_job("amazon", "Applied Science Manager", [])).track is RoleTrack.MANAGEMENT
    # Plain list precedence is untouched: a program role that merely mentions the
    # discipline is still program management.
    assert (
        classify_family(_job("amazon", "Applied Sciences Program Manager", []))
        == "program_management"
    )


@pytest.mark.parametrize(("title", "family"), [
    # The office a Chief of Staff runs is not the role, whichever discipline
    # the title names after it.
    ("Technical Advisor & Chief of Staff to the VP of Applied Science, Alexa AI",
     "business_operations_strategy"),
    ("Chief of Staff, Applied Science", "business_operations_strategy"),
    ("Technical Chief of Staff for ASIC Engineering", "business_operations_strategy"),
    # The controls: the discipline's own roles keep their families.
    ("Applied Science Manager", "ml_ai_research"),
    ("Senior Applied Science Manager, AWS Analytics Engineering", "ml_ai_research"),
    ("Applied Sciences Program Manager", "program_management"),
])
def test_a_chief_of_staff_is_filed_by_the_role_not_the_office_it_serves(title, family):
    assert classify_family(_job("amazon", title, [])) == family


@pytest.mark.parametrize(("title", "family"), [
    # After the comma, Developer Experience is the tooling team the engineer
    # is on, and the role before it decides.
    ("Senior Software Engineer, Developer Experience", "software_engineering"),
    ("Staff Engineer, Developer Experience", "software_engineering"),
    ("Staff Product Marketing Manager, Developer Experience", "marketing_communications"),
    # The controls: a developer relations role, and Developer Experience as
    # the whole title, stay where they are.
    ("Developer Advocate", "developer_relations"),
    ("Developer Relations Manager", "developer_relations"),
    ("Head of Developer Experience", "developer_relations"),
    ("Content Engineer, Developer Relations", "developer_relations"),
])
def test_developer_experience_after_the_comma_is_the_team_not_the_role(title, family):
    assert classify_family(_job("acme", title, [])) == family


def test_specialization_outranks_generic_engineering_manager():
    # A forward-deployed EM manages a forward-deployed function. Engineering
    # Management sits first in ROLE_GROUPS, so without the qualifier rule its
    # keyword would take every such title and the Solutions/Forward-Deployed
    # toggle could not exclude the role.
    fde = "Forward Deployed Engineering Manager, GenAI, Delta, Google Cloud"
    assert classify_family(_job("google", fde, ["Singapore"])) == "solutions_sales_eng"
    assert classify_family(_job("google", "Sales Engineering Manager, Cloud", [])) == "solutions_sales_eng"
    # The IC form must stay put.
    assert classify_family(_job("google", "Forward Deployed Engineer", [])) == "solutions_sales_eng"
    # The role is still people-leadership: only the family differs, not the track.
    assert annotate(_job("google", fde, ["Singapore"])).track is RoleTrack.MANAGEMENT
    # Unqualified EM titles are untouched: the rule must not scatter EM roles
    # into whichever specialization their team name happens to mention.
    for title in (
        "Engineering Manager, Search",
        "Senior Engineering Manager",
        "Director of Engineering",
        "Engineering Manager, Machine Learning Platform",
        "Technical Lead Manager, Ads",
    ):
        assert classify_family(_job("google", title, [])) == "engineering_management", title


def test_forward_deployed_manager_follows_the_solutions_toggle():
    # The user-visible contract: with Solutions/Forward-Deployed off (the
    # default) the FDE manager drops, while a plain EM at the same band and
    # location is kept. Turning the group on brings it back.
    fde = _job("google", "Forward Deployed Engineering Manager, GenAI", ["Singapore"])
    plain = _job("google", "Engineering Manager, Search", ["Singapore"])
    scope = ScopeFilter(
        enabled_bands=DEFAULT_SCOPE.enabled_bands,
        enabled_roles=frozenset(DEFAULT_ROLES),
        enabled_tracks=ALL_TRACKS,
        enabled_locations=frozenset(ALL_LOCATIONS | {"singapore"}),
        enabled_domains=frozenset(),
    )
    assert passes_filters(annotate(plain), scope) is True
    assert passes_filters(annotate(fde), scope) is False
    with_solutions = ScopeFilter(
        enabled_bands=scope.enabled_bands,
        enabled_roles=frozenset(DEFAULT_ROLES | {"solutions_sales_eng"}),
        enabled_tracks=ALL_TRACKS,
        enabled_locations=scope.enabled_locations,
        enabled_domains=frozenset(),
    )
    assert passes_filters(annotate(fde), with_solutions) is True


def test_passes_filters_requires_enabled_role_level_and_location():
    # Product manager in London, product_management is default-enabled => keep.
    j = _job("google", "Group Product Manager", ["London, UK"])
    assert passes_filters(annotate(j), DEFAULT_SCOPE) is True
    # Right role/level but Tokyo => dropped.
    j2 = _job("google", "Group Product Manager", ["Tokyo, Japan"])
    assert passes_filters(annotate(j2), DEFAULT_SCOPE) is False
    # SWE is not in the default-enabled role set => dropped...
    j3 = _job("google", "Staff Software Engineer", ["Mountain View, CA, USA"])
    assert passes_filters(annotate(j3), DEFAULT_SCOPE) is False
    # ...but kept once the user enables software_engineering.
    software_scope = ScopeFilter(
        enabled_bands=DEFAULT_SCOPE.enabled_bands,
        enabled_roles=frozenset(DEFAULT_ROLES | {"software_engineering"}),
        enabled_tracks=ALL_TRACKS,
        enabled_locations=ALL_LOCATIONS,
        enabled_domains=frozenset(),
    )
    assert passes_filters(annotate(j3), software_scope) is True


def test_early_stages_are_controlled_only_by_scope_setting():
    ann = annotate(_job("apple", "Junior Software Engineer", ["London, UK"]))
    roles = frozenset({"software_engineering"})
    assert passes_filters(
        ann,
        ScopeFilter(
            enabled_bands=frozenset(default_enabled_bands()),
            enabled_roles=roles,
            enabled_tracks=ALL_TRACKS,
            enabled_locations=ALL_LOCATIONS,
            enabled_domains=frozenset(),
        ),
    ) is False
    assert passes_filters(
        ann,
        ScopeFilter(
            enabled_bands=frozenset({"entry"}),
            enabled_roles=roles,
            enabled_tracks=ALL_TRACKS,
            enabled_locations=ALL_LOCATIONS,
            enabled_domains=frozenset(),
        ),
    ) is True


def test_a_person_starting_out_is_not_shown_internships():
    """Entry / Junior and Intern are separate rungs, so choosing Entry
    keeps a junior role and leaves an internship out; choosing Intern does the
    reverse."""
    junior = annotate(_job("apple", "Junior Software Engineer", ["London, UK"]))
    intern = annotate(_job("apple", "Software Engineering Intern", ["London, UK"]))
    roles = frozenset({"software_engineering"})

    def scope(bands: set[str]) -> ScopeFilter:
        return ScopeFilter(
            enabled_bands=frozenset(bands), enabled_roles=roles, enabled_tracks=ALL_TRACKS,
            enabled_locations=ALL_LOCATIONS, enabled_domains=frozenset(),
        )

    assert (passes_filters(junior, scope({"entry"})), passes_filters(intern, scope({"entry"}))) == (True, False)
    assert (passes_filters(junior, scope({"intern"})), passes_filters(intern, scope({"intern"}))) == (False, True)


def test_track_gate_isolates_management_from_ic():
    # A cross-domain manager (family stays technical, track is management).
    mgr = annotate(_job("google", "Director of Data Science", ["Mountain View, CA, USA"]))
    ic = annotate(_job("google", "Staff Data Scientist", ["Mountain View, CA, USA"]))
    roles = frozenset({"data_science"})
    bands = frozenset(default_enabled_bands())

    mgmt_only = scope_filter(bands=bands, roles=roles, tracks={"management"}, locations=ALL_LOCATIONS, domains=())
    ic_only = scope_filter(bands=bands, roles=roles, tracks={"technical"}, locations=ALL_LOCATIONS, domains=())
    all_tracks = scope_filter(bands=bands, roles=roles, tracks=ALL_TRACKS, locations=ALL_LOCATIONS, domains=())

    assert passes_filters(mgr, mgmt_only) is True
    assert passes_filters(mgr, ic_only) is False
    assert passes_filters(ic, ic_only) is True
    assert passes_filters(ic, mgmt_only) is False
    # All-tracks (the default) is a no-op: both the manager and the IC pass.
    assert passes_filters(mgr, all_tracks) is True
    assert passes_filters(ic, all_tracks) is True


def test_business_position_requires_explicit_family_and_track_selection():
    ann = annotate(_job("openai", "Senior Enterprise Account Executive", ["London, UK"]))
    assert ann.family == "sales_business_development"
    assert ann.track.value == "business_customer"
    assert passes_filters(
        ann,
        scope_filter(
            bands=default_enabled_bands(),
            roles={"sales_business_development"},
            tracks={"business_customer"},
            locations=ALL_LOCATIONS,
            domains=(),
        ),
    ) is True
    assert passes_filters(
        ann,
        scope_filter(
            bands=default_enabled_bands(),
            roles={"sales_business_development"},
            tracks={"technical"},
            locations=ALL_LOCATIONS,
            domains=(),
        ),
    ) is False


def test_location_axis_is_a_pure_filter_over_stored_matches():
    # Matching stores every group; the enabled set only gates scope at read time.
    ann = annotate(_job("google", "Group Product Manager", ["Singapore"]))
    assert ann.location_groups == ["singapore", "southeast_asia"]

    bands = DEFAULT_SCOPE.enabled_bands
    keep = scope_filter(bands=bands, roles=DEFAULT_ROLES, tracks=ALL_TRACKS, locations={"singapore"}, domains=())
    drop = scope_filter(
        bands=bands,
        roles=DEFAULT_ROLES,
        tracks=ALL_TRACKS,
        locations={"uk", "silicon_valley"},
        domains=(),
    )
    empty = scope_filter(bands=bands, roles=DEFAULT_ROLES, tracks=ALL_TRACKS, locations=(), domains=())

    assert passes_filters(ann, keep) is True
    assert passes_filters(ann, drop) is False
    # An empty locations axis fails everything, matching the other axes.
    assert passes_filters(ann, empty) is False


def _scope_for(ann, *, domains: frozenset[str]) -> ScopeFilter:
    """A scope the annotation passes on every axis EXCEPT possibly domains —
    isolates the 5th axis so these tests fail only for domain-gate bugs."""
    return ScopeFilter(
        enabled_bands=frozenset({ann.band.value}),
        enabled_roles=frozenset({ann.family} if ann.family else set()),
        enabled_tracks=frozenset({ann.track.value}),
        enabled_locations=frozenset(ann.location_groups[:1]),
        enabled_domains=domains,
    )


def _dept_job(company: str, title: str, department: str | None, locations: list[str]) -> RawJob:
    return RawJob(
        company=company, req_id="x", title=title, url="u",
        locations=locations, department=department,
    )


def test_domain_axis_regression_pair_and_fail_open():
    """The amazon noise case, all three legs."""
    every_world_but_retail = frozenset(all_domain_slugs()) - {"retail_commerce"}

    # 1. Retail-department director: out once retail_commerce is disabled.
    store = annotate(_dept_job(
        "amazon", "Senior Director, Store Product Management",
        "Retail & Commerce", ["Seattle, WA"],
    ))
    assert store.domains == ["retail_commerce"]
    assert passes_filters(store, _scope_for(store, domains=every_world_but_retail)) is False
    assert passes_filters(store, _scope_for(store, domains=frozenset({"retail_commerce"}))) is True

    # 2. The wanted sibling with identical surface indicators stays in —
    #    via fail-open, because no vocabulary names AGI yet. This leg pins the
    #    axis's core safety property, not classification coverage.
    agi = annotate(_dept_job(
        "amazon", "Senior Director, Product Management, AGI", None, ["Seattle, WA"],
    ))
    assert agi.domains == []
    assert passes_filters(agi, _scope_for(agi, domains=every_world_but_retail)) is True

    # 3. A title-only, runtime-added company the lexicon knows nothing about
    #    must never lose rows to a narrowed worlds axis.
    unknown = annotate(_dept_job("newco", "Senior Engineering Manager", None, ["London, UK"]))
    assert unknown.domains == []
    assert passes_filters(unknown, _scope_for(unknown, domains=frozenset({"ai_ml"}))) is True


def test_domain_axis_multi_world_posting_survives_if_any_world_is_enabled():
    ann = annotate(_dept_job(
        "google", "Machine Learning Engineering Manager, Ads Ranking", None, ["London, UK"],
    ))
    assert {"advertising", "ai_ml"} <= set(ann.domains)
    assert passes_filters(ann, _scope_for(ann, domains=frozenset({"ai_ml"}))) is True
    assert passes_filters(ann, _scope_for(ann, domains=frozenset({"advertising"}))) is True
    assert passes_filters(
        ann, _scope_for(ann, domains=frozenset({"logistics_fulfillment"}))
    ) is False


def test_domain_axis_empty_enabled_set_means_no_narrowing():
    # The deliberate inversion of the other axes: empty = pass all,
    # because empty-fails-classified plus fail-open-unknown would invert the
    # filter. The settings store never persists empty; this pins the pure gate.
    ann = annotate(_dept_job(
        "amazon", "Sr. Operations Manager", "Fulfillment & Operations Management",
        ["Seattle, WA"],
    ))
    assert ann.domains  # classified — the interesting case
    assert passes_filters(ann, _scope_for(ann, domains=frozenset())) is True


def test_rule_excluded_matches_verbatim_employer_vocabulary_only():
    from tracker.enrich.enricher import rule_excluded

    rules = frozenset({
        ("amazon", "department", "fulfillment & operations management"),
        ("google", "team", "ads"),
    })
    dept_job = RawJob(
        company="amazon", req_id="1", title="Sr. Ops Manager", url="u",
        locations=["Seattle, WA"], department="Fulfillment & Operations Management",
    )
    # Case-insensitive exact match on the employer's own field.
    assert rule_excluded(dept_job, rules) is True
    # The same value at another company means nothing.
    other_company = RawJob(
        company="microsoft", req_id="2", title="x", url="u",
        locations=[], department="Fulfillment & Operations Management",
    )
    assert rule_excluded(other_company, rules) is False
    # Exact, never substring: a rule for team "Ads" must not swallow siblings.
    superstring = RawJob(
        company="google", req_id="3", title="x", url="u", locations=[], team="Ads Integrity",
    )
    assert rule_excluded(superstring, rules) is False
    # Kind is respected: a department rule does not match the team field.
    wrong_field = RawJob(
        company="amazon", req_id="4", title="x", url="u",
        locations=[], team="Fulfillment & Operations Management",
    )
    assert rule_excluded(wrong_field, rules) is False
    # No rules -> nothing excluded; empty employer fields -> nothing to match.
    assert rule_excluded(dept_job, frozenset()) is False
    blank = RawJob(company="amazon", req_id="5", title="x", url="u", locations=[])
    assert rule_excluded(blank, rules) is False


def test_chief_officer_is_director_but_chief_engineer_is_not():
    # "Chief" can name an executive or a senior IC. A bare prefix must not
    # confirm director_plus for a chief engineer; the full title must supply
    # an executive signal.
    for title in [
        "Chief Technology Officer",
        "Chief Information Security Officer",
        "Chief Scientist",
    ]:
        band, conf = map_level(_job("amazon", title, ["Seattle, WA"]))
        assert band is LevelBand.DIRECTOR_PLUS, title
        assert conf is LevelConfidence.CONFIRMED, title
    for title in [
        "Data Center Chief Engineer",
        "Chief Engineer, Data Center Engg Ops",
        "Technical Advisor & Chief of Staff to the VP of Applied Science",
    ]:
        band, conf = map_level(_job("amazon", title, ["Seattle, WA"]))
        assert band is not LevelBand.DIRECTOR_PLUS, title
        assert conf is LevelConfidence.UNCONFIRMED, title


def test_chief_of_staff_is_not_the_staff_rung():
    # The substring trap the rule above must not walk into: dropping "chief " from
    # the director list leaves "Chief of Staff" matching the STAFF keyword, which
    # would trade one wrong confident band for another.
    band, conf = map_level(_job("google", "Chief of Staff, YouTube", ["Mountain View, CA, USA"]))
    assert band is not LevelBand.STAFF
    assert band is not LevelBand.DIRECTOR_PLUS
    assert conf is LevelConfidence.UNCONFIRMED
    # An explicit director signal in the same title still wins.
    band, _ = map_level(
        _job("google", "Director, Chief of Staff, Workspace Product", ["Mountain View, CA, USA"])
    )
    assert band is LevelBand.DIRECTOR_PLUS
