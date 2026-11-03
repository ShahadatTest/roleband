"""Every event the backend can send, and what each property may hold.

The catalogue is the whole of what leaves from the backend: an event or a
property that is not declared here cannot be stored for sending. Values are
enums, flags and bounded numbers; the few patterned strings (a version, a
locale tag) are short and shaped, so free text has no slot to travel in.

Consent groups (`Group`) are what the user chooses. Each group's fingerprint
(`fingerprint`) is a hash of the KINDS of data it covers: its events, their
property names and value types, and the browser capabilities the dashboard may
turn on for it (`BROWSER_SCOPE`). Adding an event, a property or a capability
widens the group and changes its fingerprint, so its sharers are asked again;
a new value in an existing enum (one more action, one more country) does not.
Narrowing changes the fingerprint too, and is never a reason to ask: see
`consent.py`.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from tracker.connectors.recipes.outcome import SourceOutcome
from tracker.schema import LevelBand
from tracker.taxonomy.countries import COUNTRIES
from tracker.taxonomy.roles import all_slugs as all_family_slugs


class Group(StrEnum):
    """What the user chooses on the consent screen.

    `recordings` (masked session replay) is not a group: RoleBand does not
    record sessions. An answer stored for it is kept as written and
    read by nothing (`consent.RETIRED_GROUPS`)."""

    USAGE = "usage"
    CRASHES = "crashes"
    QUESTIONS = "questions"


class Kind(StrEnum):
    """How an event's outbox row is keyed and aged (`outbox.py`)."""

    #: Once ever, timestamped when it happened.
    MILESTONE = "milestone"
    #: One row per day and property set; the row counts occurrences.
    COUNT = "count"
    #: One row per day, replaced by the latest snapshot.
    DAILY = "daily"
    #: One row per day and crash fingerprint, counting occurrences.
    EXCEPTION = "exception"


class UsageEventError(ValueError):
    """An event or property outside the catalogue. Never stored, never sent."""


@dataclass(frozen=True)
class OneOf:
    """A value from a fixed set. `label` names the set in the fingerprint, so a
    new member is not a new kind of data."""

    label: str
    values: frozenset[str]

    def accepts(self, value: object) -> bool:
        return isinstance(value, str) and value in self.values

    def describe(self) -> str:
        return f"enum:{self.label}"


@dataclass(frozen=True)
class Flag:
    def accepts(self, value: object) -> bool:
        return isinstance(value, bool)

    def describe(self) -> str:
        return "bool"


@dataclass(frozen=True)
class IntIn:
    lo: int
    hi: int

    def accepts(self, value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and self.lo <= value <= self.hi

    def describe(self) -> str:
        return f"int:{self.lo}..{self.hi}"


@dataclass(frozen=True)
class Shaped:
    """A short string of a declared shape (a version, a locale tag)."""

    label: str
    pattern: str
    max_len: int = 32

    def accepts(self, value: object) -> bool:
        return (
            isinstance(value, str)
            and len(value) <= self.max_len
            and re.fullmatch(self.pattern, value) is not None
        )

    def describe(self) -> str:
        return f"shaped:{self.label}"


Prop = OneOf | Flag | IntIn | Shaped


@dataclass(frozen=True)
class Event:
    name: str
    kind: Kind
    group: Group
    props: Mapping[str, Prop] = field(default_factory=dict)
    required: frozenset[str] = frozenset()

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "props": {key: prop.describe() for key, prop in sorted(self.props.items())},
            "required": sorted(self.required),
        }


#: A daily count is reported exactly up to here, then as this number.
COUNT_CAP = 999

#: Actions the API counts when they succeed: one stable name per mutation route
#: (`api/usage_counter.py` maps every route to one; a test holds the two equal).
#: The browser's clicks say what was tried; these say what worked.
ACTIONS = frozenset(
    {
        "add_company",
        "agent_access_set",
        "ai_egress_set",
        "apple_intelligence_set",
        "board_search",
        "cloud_model_added",
        "cloud_model_edited",
        "cloud_model_removed",
        "cloud_model_tested",
        "company_board_set",
        "company_profile_edited",
        "company_profile_field_cleared",
        "company_schedule_changed",
        "company_selection_saved",
        "company_updated",
        "compare_set",
        "connector_previewed",
        "dismiss_job",
        "follow_all",
        "intelligence_tested",
        "intent_saved",
        "job_opened",
        "lineage_link_analyzed",
        "lineage_link_removed",
        "lineage_link_reviewed",
        "local_model_added",
        "local_model_edited",
        "local_model_removed",
        "local_model_selected",
        "local_model_tested",
        "local_models_toggled",
        "local_server_controlled",
        "locale_set",
        "matching_resumed",
        "matching_stopped",
        "matching_tier_set",
        "notification_dismissed",
        "notification_read",
        "notification_restored",
        "notification_unread",
        "notifications_marked_unread",
        "notifications_read_all",
        "pay_floor_cleared",
        "pay_floor_set",
        "place_set_reviewed",
        "plugin_approved",
        "plugin_data_removed",
        "plugin_disabled",
        "plugin_enabled",
        "plugin_paused",
        "plugin_refreshed",
        "plugin_resumed",
        "plugin_schedule_set",
        "plugin_uninstalled",
        "posting_page_opened",
        "price_key_removed",
        "price_key_saved",
        "pursuit_stage_set",
        "recipe_activated",
        "recipe_created",
        "recipe_started",
        "recipe_validated",
        "retention_set",
        "save_job",
        "schedule_plan_set",
        "scope_previewed",
        "scope_refreshed",
        "scope_rule_added",
        "scope_rule_removed",
        "settings_saved",
        "suggestion_accepted",
        "suggestion_dismissed",
        "sync_cancelled",
        "sync_started",
        "twin_link_added",
        "twin_link_analyzed",
        "twin_link_reviewed",
        "undismiss_job",
        "unsave_job",
    }
)

#: Job-site families that serve many employers, so naming one names nobody. A
#: family qualifies with at least `FAMILY_MIN_EMPLOYERS` known employers across
#: the built-ins, the catalog and the directory. Every other provider key
#: reports as `single_company`: a company's own careers site and the thin
#: families, where the family would all but name the employer.
#: `tests/test_usage_registry.py` re-measures the floor.
FAMILY_MIN_EMPLOYERS = 10
FAMILY_KINDS = frozenset({"ashby", "greenhouse", "lever", "smartrecruiters", "workable", "workday"})
SINGLE_COMPANY = "single_company"
#: Provider keys that are a family under another name.
FAMILY_ALIASES: Mapping[str, str] = {"smartrecruiters_api": "smartrecruiters"}

FOLLOWED_BUCKETS = ("0", "1-5", "6-20", "21-50", "51-100", "101+")

OUTCOMES = OneOf("source-outcome", frozenset(outcome.value for outcome in SourceOutcome))
#: A code identifier (a task type, a provider, an outcome class): never prose.
IDENTIFIER = Shaped("identifier", r"[a-z][a-z0-9_]{0,31}")
COUNTRY = OneOf("iso3166-alpha2", frozenset(country.alpha2.upper() for country in COUNTRIES))
#: The kind of role the user is looking for: the one family their answers
#: name, `several`, or `any` (`facts.target_craft`).
CRAFT = OneOf("craft", frozenset(all_family_slugs()) | {"several", "any"})
SENIORITY = OneOf("level-band", frozenset(band.value for band in LevelBand))

CATALOGUE: Mapping[str, Event] = {
    event.name: event
    for event in (
        Event(
            "daily_heartbeat",
            Kind.DAILY,
            Group.USAGE,
            props={
                "app_version": Shaped("version", r"\d{1,4}\.\d{1,4}\.\d{1,4}(?:[.+-][0-9A-Za-z.]{1,16})?"),
                "os": OneOf("os", frozenset({"macos", "linux", "windows", "other"})),
                "os_major": IntIn(0, 999),
                "arch": OneOf("arch", frozenset({"arm64", "x86_64", "other"})),
                "python": Shaped("python-version", r"3\.\d{1,2}"),
                "install_method": OneOf("install-method", frozenset({"source", "package", "container"})),
                "db_mode": OneOf("db-mode", frozenset({"embedded", "external"})),
                "followed_bucket": OneOf("followed-bucket", frozenset(FOLLOWED_BUCKETS)),
                "ai_egress": Flag(),
                "ui_locale": Shaped("bcp47", r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}", max_len=20),
                "country": COUNTRY,
                "target_craft": CRAFT,
                "target_seniority": SENIORITY,
            },
            required=frozenset({"app_version", "os", "arch", "python", "install_method", "db_mode"}),
        ),
        Event(
            "daily_action",
            Kind.COUNT,
            Group.USAGE,
            props={"action": OneOf("action", ACTIONS)},
            required=frozenset({"action"}),
        ),
        Event(
            "daily_scan_health",
            Kind.COUNT,
            Group.USAGE,
            props={
                "family": OneOf("job-site-family", FAMILY_KINDS | {SINGLE_COMPANY}),
                "outcome": OUTCOMES,
            },
            required=frozenset({"family", "outcome"}),
        ),
        Event(
            "daily_ai_task",
            Kind.COUNT,
            Group.USAGE,
            # From `ai_task_log`, which holds no prompt or output by design:
            # code identifiers, a vendor's model id (cloud only), numbers.
            props={
                "task": IDENTIFIER,
                "provider": IDENTIFIER,
                "outcome": IDENTIFIER,
                "failure": IDENTIFIER,
                "model": Shaped("vendor-model-id", r"[a-z0-9][a-z0-9.\-]{1,47}", max_len=48),
                "latency_p50_ms": IntIn(0, 3_600_000),
                "input_tokens": IntIn(0, 10**10),
                "output_tokens": IntIn(0, 10**10),
            },
            required=frozenset({"task", "provider", "outcome"}),
        ),
        Event("first_company_followed", Kind.MILESTONE, Group.USAGE),
        Event("first_job_saved", Kind.MILESTONE, Group.USAGE),
        Event(
            "first_scan_finished",
            Kind.MILESTONE,
            Group.USAGE,
            props={"outcome": OUTCOMES},
            required=frozenset({"outcome"}),
        ),
        Event(
            "$exception",
            Kind.EXCEPTION,
            Group.CRASHES,
            # The exception itself is checked by `scrub.validate_stored`; these
            # are the properties stored beside it. Dashboard crashes go from
            # the browser SDK (`BROWSER_SCOPE[CRASHES]`), not through here.
            props={"source": OneOf("crash-source", frozenset({"api", "pipeline", "scheduler"}))},
            required=frozenset({"source"}),
        ),
    )
}

#: What the dashboard may turn on for each group, read by the browser through
#: `GET /api/usage`: it enables a capability only when it is listed here AND
#: the group is shared. Part of each group's fingerprint.
BROWSER_SCOPE: Mapping[Group, tuple[str, ...]] = {
    Group.USAGE: (
        "autocapture",
        "dead_clicks",
        "early_access",
        "experiments",
        "feature_flags",
        "heatmaps",
        "pageleave",
        "pageviews",
        "person_profile",
        "rage_clicks",
        "web_vitals",
    ),
    Group.CRASHES: ("exceptions",),
    Group.QUESTIONS: ("surveys",),
}


def event(name: str) -> Event:
    spec = CATALOGUE.get(name)
    if spec is None:
        raise UsageEventError(f"usage event {name!r} is not in the catalogue")
    return spec


def validate(name: str, props: Mapping[str, object]) -> Event:
    """The event's spec when `props` fit it; raises `UsageEventError` otherwise.

    Callers that record from a request, a run or a tick wrap this: an event that
    does not fit is dropped and logged, it never fails the work around it."""
    spec = event(name)
    unknown = set(props) - set(spec.props)
    if unknown:
        raise UsageEventError(f"{name}: undeclared properties {sorted(unknown)}")
    missing = spec.required - set(props)
    if missing:
        raise UsageEventError(f"{name}: missing properties {sorted(missing)}")
    for key, value in props.items():
        if not spec.props[key].accepts(value):
            raise UsageEventError(f"{name}: {key} holds a value outside {spec.props[key].describe()}")
    return spec


def family_of(provider_key: str | None) -> str:
    """The job-site family a provider key reports as; never an employer."""
    key = FAMILY_ALIASES.get(provider_key or "", provider_key or "")
    return key if key in FAMILY_KINDS else SINGLE_COMPANY


def followed_bucket(count: int) -> str:
    if count <= 0:
        return "0"
    for bucket, top in (("1-5", 5), ("6-20", 20), ("21-50", 50), ("51-100", 100)):
        if count <= top:
            return bucket
    return "101+"


def fingerprint(group: Group) -> str:
    """sha256 of the kinds of data `group` covers (see the module docstring)."""
    scope = {
        "group": group.value,
        "events": sorted(
            (spec.describe() for spec in CATALOGUE.values() if spec.group is group),
            key=lambda described: str(described["name"]),
        ),
        "browser": sorted(BROWSER_SCOPE.get(group, ())),
    }
    return hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()


def fingerprints() -> dict[Group, str]:
    return {group: fingerprint(group) for group in Group}
