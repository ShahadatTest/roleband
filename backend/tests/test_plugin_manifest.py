"""A plugin manifest is its whole permission set; anything it does not declare
is refused.

Every case below starts from the template's real manifest, plants one defect,
and names the reason the refusal must give. The positive control is the
template itself: it must load through both the SDK and the core.
"""

from __future__ import annotations

import copy
import re
import tomllib
from pathlib import Path

import pytest
from roleband_plugin_sdk import SDK_RELEASES, SDK_VERSION
from roleband_plugin_sdk import manifest as sdk_manifest
from roleband_plugin_sdk.manifest import (
    IDENTITIES,
    KEY_SINCE,
    PLUGIN_ID,
    RETIRED_KEYS,
    ManifestError,
    manifest_keys,
    parse_manifest,
    spec_admits,
    validate_manifest,
)

from tracker import plugin_manifest
from tracker.profiles.sources import SOURCES
from tracker.source_review import FetchTier

TEMPLATE = Path(__file__).resolve().parents[2] / "examples" / "plugin-template"
BASE = tomllib.loads((TEMPLATE / "roleband-plugin.toml").read_text())


def _with(mutate) -> dict:
    data = copy.deepcopy(BASE)
    mutate(data)
    return data


def _problems(data: dict) -> str:
    with pytest.raises(ManifestError) as caught:
        plugin_manifest.accept(validate_manifest(data))
    return "; ".join(caught.value.problems)


def test_the_template_manifest_is_accepted_by_the_sdk_and_the_core():
    manifest = plugin_manifest.load(TEMPLATE)
    assert manifest.id == "plugin-template"
    assert manifest.slots == {"pay.levels", "company.facts"}
    assert manifest.fact_fields == {"headcount"}
    assert manifest.allows_host("data.example.com")
    assert not manifest.allows_host("evil.example.com")


def _set(path, value):
    def mutate(d):
        *head, last = path
        node = d
        for key in head:
            node = node[key]
        node[last] = value

    return mutate


def _drop(path):
    def mutate(d):
        *head, last = path
        node = d
        for key in head:
            node = node[key]
        del node[last]

    return mutate


REFUSALS = [
    ("a v2 slot", _set(("provides", 0, "slot"), "listing.source"), "reserved for v2"),
    ("the notifications slot", _set(("provides", 0, "slot"), "notifications"), "reserved for v2"),
    ("an unknown slot", _set(("provides", 0, "slot"), "pay.anything"), "unknown slot"),
    ("an unknown top-level table", _set(("tables",), {"x": 1}), "tables: Extra inputs"),
    ("an unknown plugin key", _set(("plugin", "sql"), "DROP TABLE jobs"), "plugin.sql: Extra inputs"),
    ("an id with capitals", _set(("plugin", "id"), "Acme_Pay"), "plugin.id"),
    ("an id longer than the provider column", _set(("plugin", "id"), "a" * 33), "plugin.id"),
    ("a reserved id", _set(("plugin", "id"), "manual"), "reserved by the core"),
    ("the builtin id", _set(("plugin", "id"), "builtin"), "reserved by the core"),
    # Pay-trend series stored before ours and a plugin's were kept apart:
    # a plugin with this id would read that history as its own.
    ("the pre-split series id", _set(("plugin", "id"), "mixed"), "reserved by the core"),
    ("a job publishing an undeclared slot",
     _set(("jobs", 0, "publishes"), ["pay.levels", "company.facts", "company.benefits"]),
     "which provides does not declare"),
    ("a provided slot no job publishes", _set(("jobs", 0, "publishes"), ["pay.levels"]),
     "which no job publishes"),
    ("a slot declared twice", lambda d: d["provides"].append({"slot": "pay.levels"}), "slot twice"),
    ("company.facts without fields", _drop(("provides", 1, "fields")), "must list the fields"),
    ("an unknown fact field", _set(("provides", 1, "fields"), ["headcount", "ceo_salary"]),
     "may claim only ['headcount']"),
    # A company's identity is RoleBand's own.
    ("an identity fact field", _set(("provides", 1, "fields"), ["headcount", "website"]),
     "may claim only ['headcount'], not ['website']"),
    ("fields on a pay slot", _set(("provides", 0, "fields"), ["display_name"]), "only company.facts takes fields"),
    ("a host with a scheme", _set(("network", "hosts"), ["https://data.example.com"]), "lowercase hostname"),
    ("a wildcard host", _set(("network", "hosts"), ["*.example.com"]), "lowercase hostname"),
    ("a host with a port", _set(("network", "hosts"), ["data.example.com:8443"]), "lowercase hostname"),
    ("an unknown identity", _set(("network", "identity"), "stealth"), "network.identity"),
    ("an unknown schedule", _set(("jobs", 0, "schedule"), "hourly"), "jobs.0.schedule"),
    ("a zero budget", _set(("jobs", 0, "budget_seconds"), 0), "jobs.0.budget_seconds"),
    ("an unbounded budget", _set(("jobs", 0, "budget_seconds"), 10**6), "jobs.0.budget_seconds"),
    ("a boolean budget", _set(("jobs", 0, "budget_seconds"), True), "jobs.0.budget_seconds"),
    ("an unknown need", _set(("jobs", 0, "needs"), ["all_jobs"]), "jobs.0.needs"),
    ("an sdk range without an upper bound", _set(("plugin", "sdk"), ">=1"), "needs an upper bound"),
    ("an sdk range the core does not ship", _set(("plugin", "sdk"), ">=2,<3"), "does not admit the SDK"),
    ("a malformed entry", _set(("plugin", "entry"), "roleband_plugin_template"), "plugin.entry"),
    ("a plain-http repository", _set(("plugin", "repository"), "http://github.com/x/y"), "plugin.repository"),
    ("no jobs", _set(("jobs",), []), "jobs"),
]


@pytest.mark.parametrize(("case", "mutate", "reason"), REFUSALS, ids=[c[0] for c in REFUSALS])
def test_a_manifest_that_asks_for_anything_undeclared_is_refused(case, mutate, reason):
    assert reason in _problems(_with(mutate))


def test_every_problem_is_reported_at_once():
    data = _with(lambda d: (
        _set(("network", "identity"), "stealth")(d),
        _set(("jobs", 0, "schedule"), "hourly")(d),
    ))
    problems = _problems(data)
    assert "network.identity" in problems and "jobs.0.schedule" in problems


def test_a_manifest_that_is_not_toml_is_refused_with_the_reason():
    with pytest.raises(ManifestError, match="not valid TOML"):
        parse_manifest("[plugin\nid = ")


def test_the_reserved_ids_cover_every_core_source_a_plugin_id_could_spell():
    """A new core source must not be claimable as a plugin id. Sources whose
    names the id pattern cannot spell (`sec_edgar`, dotted vendor names) cannot
    collide and need no entry."""
    spellable = {name for name in SOURCES if PLUGIN_ID.fullmatch(name)}
    assert spellable, "control: some core source fits the id pattern"
    assert spellable <= plugin_manifest.RESERVED_IDS, sorted(spellable - plugin_manifest.RESERVED_IDS)


def test_the_core_sources_are_every_core_claim_source_and_name_no_vendor():
    """The registry reads a value outside `CORE_SOURCES` only through a plugin.
    A core source missing here would vanish from every profile; a vendor's name
    here would be read with no plugin on."""
    assert set(SOURCES) <= plugin_manifest.CORE_SOURCES, sorted(set(SOURCES) - plugin_manifest.CORE_SOURCES)
    assert plugin_manifest.RESERVED_IDS <= plugin_manifest.CORE_SOURCES
    assert all(PLUGIN_ID.fullmatch(s) or "_" in s for s in plugin_manifest.CORE_SOURCES), "a dotted name is a vendor's"


def test_a_manifest_identity_is_one_of_the_core_fetch_tiers():
    """The SDK cannot import the core, so the tier names are restated there;
    this is the check that they agree."""
    assert set(IDENTITIES) == {tier.value for tier in FetchTier}


@pytest.mark.parametrize(
    ("rank", "expected"), [(20, 20), (50, 50), (80, 50), (None, plugin_manifest.FACT_RANK_CEILING)]
)
def test_a_plugin_fact_rank_never_exceeds_the_ceiling(rank, expected):
    data = _with(_set(("provides", 1, "rank"), rank) if rank else _drop(("provides", 1, "rank")))
    assert plugin_manifest.fact_rank(validate_manifest(data)) == expected


def test_a_plugin_without_company_facts_has_no_fact_rank():
    data = _with(lambda d: (d["provides"].pop(1), _set(("jobs", 0, "publishes"), ["pay.levels"])(d)))
    assert plugin_manifest.fact_rank(validate_manifest(data)) is None


@pytest.mark.parametrize(
    ("spec", "version", "admits"),
    [
        (">=1,<2", "1.0.0", True),
        (">=1,<2", "1.9.3", True),
        (">=1,<2", "2.0.0", False),
        (">=1.2,<2", "1.1.9", False),
        ("==1.0.0", "1.0.0", True),
        (">=1,<2,!=1.3", "1.3.0", False),
    ],
)
def test_sdk_ranges_compare_numerically(spec, version, admits):
    assert spec_admits(spec, version) is admits


def test_the_sdk_the_core_ships_is_a_plain_version():
    assert re.fullmatch(r"\d+\.\d+\.\d+", SDK_VERSION)


# --- a range admits only SDKs that know every key the manifest uses -----

#: Every key a manifest may use, frozen: a key added without a `KEY_SINCE`
#: entry, or one removed without a `RETIRED_KEYS` entry, fails here by name.
KEYS = frozenset({
    "plugin.id", "plugin.name", "plugin.version", "plugin.sdk", "plugin.entry", "plugin.repository",
    "plugin.licence", "plugin.attribution", "plugin.description",
    "provides.slot", "provides.fields", "provides.rank",
    "network.hosts", "network.min_delay_seconds", "network.identity",
    "jobs.name", "jobs.publishes", "jobs.schedule", "jobs.budget_seconds", "jobs.needs",
})


def test_every_manifest_key_is_frozen_and_a_later_one_names_its_release():
    assert manifest_keys() == KEYS | set(KEY_SINCE), sorted(manifest_keys() ^ (KEYS | set(KEY_SINCE)))
    assert not {f"plugin.{key}" for key in RETIRED_KEYS} & manifest_keys()


def test_the_releases_are_in_order_and_end_at_the_one_shipped():
    assert SDK_RELEASES[-1] == SDK_VERSION
    assert list(SDK_RELEASES) == sorted(SDK_RELEASES, key=lambda v: tuple(int(p) for p in v.split(".")))
    assert all(since in SDK_RELEASES[1:] for since in KEY_SINCE.values())


def test_every_key_the_first_public_sdk_reads_runs_on_every_1_x_release():
    """1.0.0 is the first SDK an author can build on: a manifest that uses
    every key, `description` included, declares the plain major range."""
    data = _with(lambda d: d["plugin"].update(sdk=">=1,<2", description="Pay ladders from data.example.com"))
    assert data["jobs"][0]["needs"] and data["provides"][1]["fields"] and data["provides"][1]["rank"]  # control
    accepted = plugin_manifest.accept(validate_manifest(data))
    assert accepted.plugin.description == "Pay ladders from data.example.com"
    assert spec_admits(accepted.plugin.sdk, "1.0.0")


def test_the_template_declares_the_range_its_readers_copy():
    assert BASE["plugin"]["sdk"] == ">=1,<2"
    project = tomllib.loads((TEMPLATE / "pyproject.toml").read_text())["project"]
    assert "roleband-plugin-sdk>=1,<2" in project["dependencies"]


def _as_if_1_1_added(monkeypatch, key: str) -> None:
    """The rule held on a stand-in: SDK 1.1.0 shipped, and it added `key`."""
    import roleband_plugin_sdk

    monkeypatch.setattr(sdk_manifest, "SDK_RELEASES", ("1.0.0", "1.1.0"))
    monkeypatch.setattr(roleband_plugin_sdk, "SDK_VERSION", "1.1.0")
    monkeypatch.setattr(sdk_manifest, "KEY_SINCE", {key: "1.1.0"})


@pytest.fixture
def needs_since_1_1(monkeypatch):
    _as_if_1_1_added(monkeypatch, "jobs.needs")


def _ranged(sdk: str) -> dict:
    return _with(_set(("plugin", "sdk"), sdk))


@pytest.mark.parametrize("sdk", [">=1,<2", ">=1.0,<2", ">0.9,<2", "<2", "==1.0.0", ">=1,<2,!=1.2.0"])
def test_a_range_that_admits_an_sdk_older_than_a_key_it_uses_is_refused(needs_since_1_1, sdk):
    problems = _problems(_ranged(sdk))
    assert "jobs.needs" in problems and "1.1.0" in problems and "1.0.0" in problems


@pytest.mark.parametrize("sdk", [">=1.1,<2", "==1.1.0", ">1.0.0,<2", ">=1.1.0,<2,!=1.2.0"])
def test_a_range_that_starts_at_or_after_the_key_is_accepted(needs_since_1_1, sdk):
    assert plugin_manifest.accept(validate_manifest(_ranged(sdk))).plugin.sdk == sdk


def test_a_key_set_explicitly_empty_still_needs_the_release_that_reads_it(needs_since_1_1):
    """An older SDK refuses an unknown key whatever its value."""
    data = _with(lambda d: (d["plugin"].update(sdk=">=1,<2"), d["jobs"][0].update(needs=[])))
    assert "jobs.needs" in _problems(data)


def test_a_manifest_that_uses_no_later_key_may_admit_1_0(needs_since_1_1):
    data = _with(lambda d: (d["plugin"].update(sdk=">=1,<2"), d["jobs"][0].pop("needs")))
    assert plugin_manifest.accept(validate_manifest(data)).plugin.sdk == ">=1,<2"


def test_a_stored_manifest_without_a_later_key_is_still_accepted_on_its_old_range(monkeypatch):
    """Install stores `model_dump`, which writes every absent optional key as
    None; that None is not a key the plugin used."""
    _as_if_1_1_added(monkeypatch, "plugin.description")
    unsaid = _with(lambda d: (d["plugin"].update(sdk=">=1,<2"), d["plugin"].pop("description")))
    stored = validate_manifest(unsaid).model_dump(mode="json")
    assert stored["plugin"]["description"] is None  # control: the None is there
    assert plugin_manifest.accept(validate_manifest(stored)).plugin.sdk == ">=1,<2"
    said = _with(lambda d: d["plugin"].update(sdk=">=1,<2"))
    assert "plugin.description" in _problems(said)  # control: the stand-in bites


def test_a_retired_key_is_refused_by_name_with_why(monkeypatch):
    """The rule held on a stand-in: no key is retired in 1.x yet."""
    monkeypatch.setattr(sdk_manifest, "RETIRED_KEYS", {"rows_to_adopt": "a plugin answers only from its own rows"})
    problems = _problems(_with(_set(("plugin", "rows_to_adopt"), ["acme"])))
    assert "rows_to_adopt is no longer accepted: a plugin answers only from its own rows" in problems
