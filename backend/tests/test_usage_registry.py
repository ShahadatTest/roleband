"""The usage catalogue is the whole of what the backend can send.

Contracts (docs/architecture.md):

* No property can carry free text: every value is an enum, a flag, a bounded
  number or a short shaped string.
* An event or property outside the catalogue is refused, not trimmed.
* A group's fingerprint changes when its KIND of data widens (a new event, a
  new property, a new browser capability) and not when an enum gains a value.
* Scan health never names an employer: a family is reported only when many
  known employers use it.
"""

from __future__ import annotations

import collections
import re
from dataclasses import replace

import pytest

from tracker.company_catalog import CATALOG
from tracker.company_directory import directory
from tracker.config import COMPANIES
from tracker.connectors.listing import ADAPTER_REGISTRY
from tracker.usage_stats import registry
from tracker.usage_stats.registry import (
    CATALOGUE,
    FAMILY_ALIASES,
    FAMILY_KINDS,
    FAMILY_MIN_EMPLOYERS,
    SINGLE_COMPANY,
    Event,
    Flag,
    Group,
    IntIn,
    Kind,
    OneOf,
    Shaped,
    UsageEventError,
    family_of,
    fingerprint,
    followed_bucket,
    validate,
)

pytestmark = pytest.mark.usefixtures("no_escape")

CANARY = "Zyxwv Robotics Senior Staff PM"


def test_every_property_is_a_closed_type() -> None:
    for spec in CATALOGUE.values():
        for key, prop in spec.props.items():
            assert isinstance(prop, OneOf | Flag | IntIn | Shaped), (spec.name, key)
            if isinstance(prop, Shaped):
                assert prop.max_len <= 48, (spec.name, key)
                # A shaped string admits no spaces, so no sentence fits.
                assert not prop.accepts("two words"), (spec.name, key)


def test_a_canary_string_fits_no_property() -> None:
    for spec in CATALOGUE.values():
        for key, prop in spec.props.items():
            assert not prop.accepts(CANARY), (spec.name, key)


def test_undeclared_events_and_properties_are_refused() -> None:
    with pytest.raises(UsageEventError):
        validate("job_title_viewed", {})
    with pytest.raises(UsageEventError):
        validate("daily_action", {"action": "save_job", "company": "acme"})
    with pytest.raises(UsageEventError):
        validate("daily_action", {"action": "search:senior pm"})
    with pytest.raises(UsageEventError):
        validate("daily_action", {})
    with pytest.raises(UsageEventError):
        validate("daily_heartbeat", {"app_version": "0.1.0", "os": "macos"})  # required missing
    assert validate("daily_action", {"action": "save_job"}).kind is Kind.COUNT


def test_heartbeat_values_are_checked() -> None:
    good = {
        "app_version": "0.1.0",
        "os": "macos",
        "os_major": 15,
        "arch": "arm64",
        "python": "3.12",
        "install_method": "source",
        "db_mode": "embedded",
        "country": "SE",
    }
    validate("daily_heartbeat", good)
    for key, bad in (("country", "XX"), ("os_major", True), ("python", "3.12 (main, Oct 2026)"), ("arch", "M3 Max")):
        with pytest.raises(UsageEventError):
            validate("daily_heartbeat", good | {key: bad})


def _with_catalogue(monkeypatch, catalogue) -> None:
    monkeypatch.setattr(registry, "CATALOGUE", catalogue)


def test_fingerprint_widens_on_new_property_or_event_not_on_new_enum_value(monkeypatch) -> None:
    before = {group: fingerprint(group) for group in Group}

    action = CATALOGUE["daily_action"]
    more_actions = replace(action, props={"action": OneOf("action", action.props["action"].values | {"export_csv"})})
    _with_catalogue(monkeypatch, dict(CATALOGUE) | {"daily_action": more_actions})
    assert fingerprint(Group.USAGE) == before[Group.USAGE]

    new_prop = replace(action, props=dict(action.props) | {"screen": OneOf("screen", frozenset({"radar"}))})
    _with_catalogue(monkeypatch, dict(CATALOGUE) | {"daily_action": new_prop})
    assert fingerprint(Group.USAGE) != before[Group.USAGE]
    # Other groups did not widen.
    assert fingerprint(Group.CRASHES) == before[Group.CRASHES]

    new_event = Event("first_compare_used", Kind.MILESTONE, Group.USAGE)
    _with_catalogue(monkeypatch, dict(CATALOGUE) | {new_event.name: new_event})
    assert fingerprint(Group.USAGE) != before[Group.USAGE]


def test_fingerprint_widens_on_new_browser_capability(monkeypatch) -> None:
    before = fingerprint(Group.CRASHES)
    widened = dict(registry.BROWSER_SCOPE) | {Group.CRASHES: (*registry.BROWSER_SCOPE[Group.CRASHES], "network_bodies")}
    monkeypatch.setattr(registry, "BROWSER_SCOPE", widened)
    assert fingerprint(Group.CRASHES) != before


def _employers_per_adapter() -> collections.Counter[str]:
    counts: collections.Counter[str] = collections.Counter()
    seen: set[str] = set()
    for source in (COMPANIES, CATALOG):
        for slug, company in source.items():
            if slug not in seen:
                seen.add(slug)
                counts[FAMILY_ALIASES.get(company.get("adapter"), company.get("adapter"))] += 1
    for slug, company in directory().items():
        if slug not in seen:
            seen.add(slug)
            counts[FAMILY_ALIASES.get(company.adapter, company.adapter)] += 1
    return counts


def test_a_reported_family_never_names_one_employer() -> None:
    counts = _employers_per_adapter()
    for family in FAMILY_KINDS:
        assert family in ADAPTER_REGISTRY, family
        assert counts[family] >= FAMILY_MIN_EMPLOYERS, (family, counts[family])


def test_every_company_specific_adapter_reports_as_single_company() -> None:
    counts = _employers_per_adapter()
    for key in ADAPTER_REGISTRY:
        family = family_of(key)
        if counts[FAMILY_ALIASES.get(key, key)] < FAMILY_MIN_EMPLOYERS:
            assert family == SINGLE_COMPANY, key
    for key in ("amazon", "apple", "google", "microsoft", "oracle", "deel", "successfactors", None, "", "acme-careers"):
        assert family_of(key) == SINGLE_COMPANY, key
    assert family_of("smartrecruiters_api") == "smartrecruiters"


@pytest.mark.parametrize(
    ("count", "bucket"),
    [(0, "0"), (1, "1-5"), (5, "1-5"), (6, "6-20"), (20, "6-20"), (21, "21-50"), (100, "51-100"), (101, "101+")],
)
def test_followed_bucket(count: int, bucket: str) -> None:
    assert followed_bucket(count) == bucket


def test_event_names_are_identifiers() -> None:
    for name in CATALOGUE:
        assert re.fullmatch(r"\$?[a-z][a-z_]{2,40}", name), name
