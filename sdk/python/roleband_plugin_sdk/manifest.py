"""`roleband-plugin.toml`: what a plugin declares, validated.

The manifest is the plugin's whole permission set: the slots it may write,
the hosts it may reach, the jobs the host may start and what each may see.
Approving a plugin approves this file, so nothing outside it is accepted:
an unknown key, a v2 slot, a slot provided but never published, or a job
publishing a slot it never declared are all errors, reported together.

This module is pure. Whether the core accepts the manifest (reserved ids,
the SDK version the core ships) is the core's own check on top of this one.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from .slots import COMPANY_FACTS, FACT_FIELDS, V1_SLOTS, V2_RESERVED_SLOTS
from .version import SDK_RELEASES

MANIFEST_FILENAME = "roleband-plugin.toml"

#: Manifest keys added after SDK 1.0.0, with the release that added them. An
#: older SDK refuses a key it does not know (every section forbids extras), so
#: a manifest using one must not admit that SDK in its `sdk` range. A new key
#: is added here in the same change (`tests/test_plugin_manifest.py`).
KEY_SINCE: Mapping[str, str] = {}

#: Retired keys a manifest may not name, with why. Refused by name rather than
#: as an unknown key, so the author reads the reason.
RETIRED_KEYS: Mapping[str, str] = {}

#: A plugin id is the provider value its rows carry (`String(32)` in the core).
PLUGIN_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")

#: The identities a plugin may ask the host to fetch with. These are the core's
#: fetch tiers, weakest first; anything above `identified` needs the user's
#: consent at run time, which the manifest cannot grant itself.
IDENTITIES = ("identified", "browser_identity", "tls_fingerprint", "headless", "proxy")

#: When a job runs on its own. `manual` jobs run only when a user starts them.
SCHEDULES = ("weekly", "manual")

#: What a job may ask the host for beyond its own data.
NEEDS = ("followed_companies",)

MAX_BUDGET_SECONDS = 4 * 3600

_HOSTNAME = re.compile(r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")
_SPEC_PART = re.compile(r"^(>=|<=|==|!=|>|<)\s*(\d+(?:\.\d+){0,2})$")


class ManifestError(ValueError):
    """The manifest cannot be accepted. `problems` lists every reason."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("; ".join(problems))


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _version_tuple(text: str) -> tuple[int, int, int]:
    parts = [int(p) for p in text.split(".")][:3]
    parts += [0] * (3 - len(parts))
    return parts[0], parts[1], parts[2]


def parse_spec(spec: str) -> list[tuple[str, tuple[int, int, int]]]:
    """`">=1,<2"` as comparisons. Only plain comparators on dotted numbers are
    accepted, and the spec must bound the major version from above: a plugin
    written for SDK 1 is not known to work on SDK 2."""
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    if not parts:
        raise ValueError("sdk spec is empty")
    out = []
    for part in parts:
        m = _SPEC_PART.match(part)
        if not m:
            raise ValueError(f"sdk spec part {part!r} is not a plain comparison like '>=1' or '<2'")
        out.append((m.group(1), _version_tuple(m.group(2))))
    if not any(op in ("<", "<=", "==") for op, _ in out):
        raise ValueError(f"sdk spec {spec!r} needs an upper bound, such as '<2'")
    return out


def spec_admits(spec: str, version: str) -> bool:
    """Whether `version` satisfies every comparison in `spec`."""
    v = _version_tuple(version.split("-")[0].split("+")[0])
    tests = {
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
        ">": lambda a, b: a > b,
        "<": lambda a, b: a < b,
    }
    return all(tests[op](v, bound) for op, bound in parse_spec(spec))


Text = Annotated[StrictStr, Field(min_length=1, max_length=200)]


class PluginSection(_Section):
    id: Annotated[StrictStr, Field(pattern=PLUGIN_ID.pattern)]
    name: Annotated[StrictStr, Field(min_length=1, max_length=80)]
    version: Annotated[StrictStr, Field(pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")]
    sdk: StrictStr
    entry: Annotated[StrictStr, Field(pattern=r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*$")]
    repository: Annotated[StrictStr, Field(pattern=r"^https://[^\s/]+/\S+$", max_length=300)]
    licence: Annotated[StrictStr, Field(min_length=1, max_length=64)]
    attribution: Text
    #: What the plugin does, in its own words: Settings shows it under the name,
    #: as written.
    description: Text | None = None

    @model_validator(mode="before")
    @classmethod
    def _retired(cls, data: Any) -> Any:
        if isinstance(data, Mapping):
            named = [key for key in RETIRED_KEYS if key in data]
            if named:
                raise ValueError("; ".join(f"{key} is no longer accepted: {RETIRED_KEYS[key]}" for key in named))
        return data

    @field_validator("sdk")
    @classmethod
    def _sdk_spec(cls, v: str) -> str:
        parse_spec(v)
        return v



class Provides(_Section):
    slot: StrictStr
    #: `company.facts` only: the fields this plugin claims, from `FACT_FIELDS`.
    fields: tuple[StrictStr, ...] | None = None
    #: `company.facts` only: how far the core trusts these claims. The core caps it.
    rank: Annotated[StrictInt, Field(ge=1, le=100)] | None = None

    @model_validator(mode="after")
    def _slot_rules(self) -> Provides:
        if self.slot in V2_RESERVED_SLOTS:
            raise ValueError(f"slot {self.slot!r} is reserved for v2 and refused in v1")
        if self.slot not in V1_SLOTS:
            raise ValueError(f"unknown slot {self.slot!r}; v1 slots are {sorted(V1_SLOTS)}")
        if self.slot == COMPANY_FACTS:
            if not self.fields:
                raise ValueError("company.facts must list the fields it claims")
            unknown = sorted(set(self.fields) - set(FACT_FIELDS))
            if unknown:
                raise ValueError(
                    f"company.facts may claim only {list(FACT_FIELDS)}, not {unknown}: a company's identity "
                    "is RoleBand's own")
            if len(set(self.fields)) != len(self.fields):
                raise ValueError("company.facts lists a field twice")
        else:
            if self.fields is not None:
                raise ValueError(f"only company.facts takes fields, not {self.slot!r}")
            if self.rank is not None:
                raise ValueError(f"only company.facts takes a rank, not {self.slot!r}")
        return self


class Network(_Section):
    hosts: tuple[StrictStr, ...] = Field(min_length=1, max_length=16)
    min_delay_seconds: Annotated[float, Field(ge=0, le=600)]
    identity: Literal["identified", "browser_identity", "tls_fingerprint", "headless", "proxy"]

    @field_validator("hosts")
    @classmethod
    def _plain_hosts(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for host in v:
            if not _HOSTNAME.match(host):
                raise ValueError(
                    f"host {host!r} must be a lowercase hostname: no scheme, port, path or wildcard"
                )
        if len(set(v)) != len(v):
            raise ValueError("hosts lists a host twice")
        return v


class Job(_Section):
    name: Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")]
    publishes: tuple[StrictStr, ...] = Field(min_length=1)
    schedule: Literal["weekly", "manual"]
    budget_seconds: Annotated[StrictInt, Field(ge=1, le=MAX_BUDGET_SECONDS)]
    needs: tuple[Literal["followed_companies"], ...] = ()


class PluginManifest(_Section):
    plugin: PluginSection
    provides: tuple[Provides, ...] = Field(min_length=1)
    network: Network | None = None
    jobs: tuple[Job, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> PluginManifest:
        problems = []
        slots = [p.slot for p in self.provides]
        if len(set(slots)) != len(slots):
            problems.append("provides declares a slot twice")
        names = [j.name for j in self.jobs]
        if len(set(names)) != len(names):
            problems.append("jobs declares a job name twice")
        published: set[str] = set()
        for job in self.jobs:
            undeclared = sorted(set(job.publishes) - set(slots))
            if undeclared:
                problems.append(f"job {job.name!r} publishes {undeclared}, which provides does not declare")
            published |= set(job.publishes)
        unused = sorted(set(slots) - published)
        if unused:
            problems.append(f"provides declares {unused}, which no job publishes")
        problems += _keys_newer_than_range(self)
        if problems:
            raise ValueError("; ".join(problems))
        return self

    @property
    def id(self) -> str:
        return self.plugin.id

    @property
    def slots(self) -> frozenset[str]:
        return frozenset(p.slot for p in self.provides)

    @property
    def fact_fields(self) -> frozenset[str]:
        for p in self.provides:
            if p.slot == COMPANY_FACTS:
                return frozenset(p.fields or ())
        return frozenset()

    def job(self, name: str) -> Job:
        for job in self.jobs:
            if job.name == name:
                return job
        raise KeyError(f"the manifest declares no job {name!r}")

    def allows_host(self, host: str) -> bool:
        return self.network is not None and host.lower() in self.network.hosts


def _section_keys(section: BaseModel, prefix: str) -> set[str]:
    """The dotted keys a section (or a list of them) was written with. A key
    whose value is None was not written: TOML has no null, and a stored
    manifest (`model_dump`) carries every absent optional key as None."""
    used = set()
    for name in section.model_fields_set:
        value = getattr(section, name)
        if value is None:
            continue
        items = value if isinstance(value, tuple) else (value,)
        nested = [v for v in items if isinstance(v, _Section)]
        if nested:
            for v in nested:
                used |= _section_keys(v, f"{name}.")
        else:
            used.add(f"{prefix}{name}")
    return used


def manifest_keys() -> set[str]:
    """Every dotted key a manifest may use (`plugin.sdk`, `jobs.name`)."""
    sections: dict[str, type[_Section]] = {"plugin": PluginSection, "provides": Provides, "network": Network,
                                           "jobs": Job}
    assert set(sections) == set(PluginManifest.model_fields), "a manifest table is missing here"
    return {f"{name}.{key}" for name, section in sections.items() for key in section.model_fields}


def _keys_newer_than_range(manifest: PluginManifest) -> list[str]:
    """A key the `sdk` range lets an older release read, which that release refuses."""
    problems = []
    used = _section_keys(manifest, "")
    for key in sorted(used & set(KEY_SINCE)):
        since = _version_tuple(KEY_SINCE[key])
        older = [r for r in SDK_RELEASES if _version_tuple(r) < since and spec_admits(manifest.plugin.sdk, r)]
        if older:
            major, minor, _ = since
            problems.append(
                f"plugin.sdk: {manifest.plugin.sdk!r} admits SDK {', '.join(older)}, which does not know {key} "
                f"(added in {KEY_SINCE[key]}); raise the lower bound to '>={major}.{minor}'"
            )
    return problems


def _problems(exc: ValidationError) -> list[str]:
    out = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err["loc"]) or "manifest"
        msg = err["msg"].removeprefix("Value error, ")
        out.append(f"{where}: {msg}")
    return out


def validate_manifest(data: Mapping[str, Any]) -> PluginManifest:
    """A parsed manifest table, validated. Raises `ManifestError`."""
    try:
        return PluginManifest.model_validate(dict(data))
    except ValidationError as exc:
        raise ManifestError(_problems(exc)) from None


def parse_manifest(text: str | bytes) -> PluginManifest:
    """Manifest TOML text, parsed and validated. Raises `ManifestError`."""
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError([f"manifest: not valid TOML: {exc}"]) from None
    return validate_manifest(data)


def load_manifest(path: str | Path) -> PluginManifest:
    """The manifest at `path`, or in the directory `path`."""
    p = Path(path)
    if p.is_dir():
        p = p / MANIFEST_FILENAME
    return parse_manifest(p.read_bytes())
