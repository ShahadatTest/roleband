"""Which source answers each kind of data, and whose rows the core reads.

**One source per slot, app-wide, never mixed.** A slot is
answered either by OUR data (the core's own sources, `plugin_manifest.CORE_SOURCES`)
or by ONE plugin, never by both:

- the plugin **selected** for a slot is the first runnable plugin (enabled,
  approved as it is now, not removed) that declares it, in the
  `reference_sources` order (`{slot: [provider, ...]}`), then by id. It is
  selected from the moment it is on, before it has read anything;
- while a plugin is selected, ONLY its rows are read in that slot, and only for
  the companies it has published whole (`plugin_coverage.complete_at`). A company
  it has not read is "not covered": never answered from ours instead;
- with no plugin selected, only the core's own sources are read;
- a second plugin declaring the same slot answers nothing there.

There is no fall-through per key, cell, field or company. A row under a name
that is neither a core source nor a selected plugin's belongs to no source and
is read by nothing.

Pure where it can be: `providers_from` takes plain records, `load_providers`
reads them. The long-lived processes never import the plugin SDK; the
manifest is read as the JSON the core stored at install.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import ColumnElement, and_, false, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import PluginInstall, ReferenceState
from tracker.plugin_manifest import CORE_SOURCES, fact_rank_of
from tracker.plugins.slots import (
    COMPANY_BENEFITS,
    COMPANY_FACTS,
    ESTIMATE_SLOTS,
    PAY_LEVELS,
    PAY_OBSERVATIONS,
    SLOTS,
)
from tracker.plugins.store import complete_coverage
from tracker.profiles import sources as profile_sources
from tracker.settings_store import get_setting_dict

__all__ = [
    "COMPANY_BENEFITS",
    "COMPANY_FACTS",
    "ESTIMATE_SLOTS",
    "PAY_LEVELS",
    "PAY_OBSERVATIONS",
    "SLOTS",
    "InstallRecord",
    "Providers",
    "install_records",
    "load_providers",
    "providers_from",
    "reader_providers",
]

# The slots and what the core does with each live in `plugins/slots.py`; they
# are re-exported here, where readers already import them. `ESTIMATE_SLOTS` are
# the slots whose rows the stored estimates read; the reference record covers
# every slot, and readers take every slot from the APPLIED record.

#: The settings key holding the per-slot provider order.
REFERENCE_SOURCES_KEY = "reference_sources"

T = TypeVar("T")


@dataclass(frozen=True)
class InstallRecord:
    """What the registry needs from one `plugin_install` row."""

    plugin_id: str
    enabled: bool
    fingerprint: str
    approved_fingerprint: str | None
    removed_at: datetime | None
    manifest: Mapping[str, Any]
    #: The user's schedule for every job (None = each job's own) and whether
    #: automatic runs are held. Neither changes what the registry reads.
    schedule: str | None = None
    paused: bool = False

    @classmethod
    def of(cls, row: PluginInstall) -> InstallRecord:
        """The record of a `plugin_install` row."""
        return cls(
            plugin_id=row.plugin_id,
            enabled=row.enabled,
            fingerprint=row.fingerprint,
            approved_fingerprint=row.approved_fingerprint,
            removed_at=row.removed_at,
            manifest=row.manifest or {},
            schedule=row.schedule,
            paused=row.paused_at is not None,
        )

    @property
    def approved(self) -> bool:
        return self.approved_fingerprint is not None and self.approved_fingerprint == self.fingerprint

    @property
    def runnable(self) -> bool:
        """May the host start this plugin: enabled, approved as it is now, present."""
        return self.enabled and self.approved and self.removed_at is None

    @property
    def state(self) -> str:
        """`removed`, `needs_approval` (never approved, or its code, manifest or
        lock changed since), `enabled` or `disabled`: the one answer every
        surface (the API, the CLI, the host) gives."""
        if self.removed_at is not None:
            return "removed"
        if not self.approved:
            return "needs_approval"
        return "enabled" if self.enabled else "disabled"

    @property
    def slots(self) -> frozenset[str]:
        return frozenset(str(p.get("slot")) for p in self.manifest.get("provides", ()))


@dataclass(frozen=True)
class Providers:
    """Which source answers each slot, and the filters readers apply."""

    #: Every provider value that belongs to an installed or removed plugin.
    plugins: frozenset[str] = frozenset()
    #: slot -> (the plugin selected there,): at most one. A slot absent here is
    #: answered by our own data.
    active: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: Fact trust per selected `company.facts` plugin (capped by the core). Ranks
    #: only that plugin's own claims against each other: sources never compete.
    fact_ranks: Mapping[str, int] = field(default_factory=dict)
    #: What a person reads for a plugin's claims: the plugin's own name.
    fact_labels: Mapping[str, str] = field(default_factory=dict)
    #: Provider values the core writes itself: read while no plugin is selected.
    core: frozenset[str] = CORE_SOURCES
    #: Per runnable plugin, the attribution its manifest requires.
    attributions: Mapping[str, str] = field(default_factory=dict)
    #: slot -> plugin -> {company: when it was first read whole}: the companies a
    #: selected plugin answers for. Kept for every installed plugin, so an applied
    #: set naming a disabled one still reads.
    covered: Mapping[str, Mapping[str, Mapping[str, datetime]]] = field(default_factory=dict)

    def source_for(self, slot: str) -> str | None:
        """The plugin answering `slot` for every company, or None: our own data."""
        selected = self.active.get(slot, ())
        return selected[0] if selected else None

    def covers(self, slot: str, company: str) -> bool:
        """Whether the plugin selected for `slot` has read `company` whole. False
        when ours answers: the question is a plugin's."""
        pid = self.source_for(slot)
        return pid is not None and company in self.covered.get(slot, {}).get(pid, {})

    def answering(self, slot: str, company: str) -> dict[str, Any]:
        """Who answers `slot` for `company`, as every surface says it:
        the plugin selected for it and its name, or none (ours), and
        whether it has read the company. `covered` is always true for ours; false
        is "not covered by the plugin yet", never ours in its place."""
        plugin = self.source_for(slot)
        return {
            "plugin": plugin,
            "plugin_name": self.fact_labels.get(plugin) if plugin else None,
            "covered": plugin is None or self.covers(slot, company),
        }

    def covered_companies(self, slot: str) -> list[str]:
        """The companies the plugin selected for `slot` has read whole, as of the
        applied set; none when ours answers."""
        plugin = self.source_for(slot)
        return sorted(self.covered.get(slot, {}).get(plugin, {})) if plugin else []

    def attribution(self, slots: Iterable[str], company: str | None = None) -> str | None:
        """What a surface built from `slots` must credit: every plugin selected
        for one of them; None when only ours answer. With `company`, only a
        plugin that answers for it (has read it whole in that slot): a company
        it has not read shows none of its data, so nothing of its is credited."""
        answering = {pid for slot in slots if (pid := self.source_for(slot))
                     and (company is None or self.covers(slot, company))}
        credits = sorted({self.attributions[pid] for pid in answering if pid in self.attributions})
        return " · ".join(credits) or None

    def rank_of(self, source: str) -> int:
        """A `company.facts` source's trust as every reader ranks it."""
        return profile_sources.rank_with(self.fact_ranks, source)

    def label_of(self, source: str) -> str:
        """A `company.facts` source as a person reads it."""
        return profile_sources.label_with(self.fact_labels, source)

    def visible(self, slot: str, provider: str, company: str | None = None) -> bool:
        """Whether `provider`'s rows for `company` in `slot` are read: the
        selected plugin's for a company it has read whole, else ours, never
        both. `company=None` asks whether it answers for any company."""
        pid = self.source_for(slot)
        if pid is None:
            return provider in self.core
        if provider != pid:
            return False
        companies = self.covered.get(slot, {}).get(pid, {})
        return bool(companies) if company is None else company in companies

    def where(self, slot: str, provider_column: Any, company_column: Any) -> ColumnElement[bool]:
        """A SQL predicate on a table's provider and company columns: exactly the
        rows `visible` admits."""
        pid = self.source_for(slot)
        if pid is None:
            return provider_column.in_(sorted(self.core))
        companies = sorted(self.covered.get(slot, {}).get(pid, {}))
        return and_(provider_column == pid, company_column.in_(companies)) if companies else false()

    def record(self, slots: Iterable[str] = SLOTS) -> dict[str, Any]:
        """The JSON `reference_state` keeps for these slots' provider set: who
        answers (a selected plugin counts before it has read anything), how far
        its coverage reached, and what a reader says of it (the credit it
        requires, its name, its fact trust), so a plugin turned off is still
        named until the switch that drops it lands."""
        slots = tuple(slots)
        active = {slot: list(self.active[slot]) for slot in slots if self.active.get(slot)}
        answering = {pid for pids in active.values() for pid in pids}
        return {
            "plugins": sorted(self.plugins),
            "active": active,
            "attributions": {pid: self.attributions[pid] for pid in sorted(answering) if pid in self.attributions},
            "names": {pid: self.fact_labels[pid] for pid in sorted(answering) if pid in self.fact_labels},
            "fact_ranks": {pid: self.fact_ranks[pid] for pid in sorted(answering) if pid in self.fact_ranks},
            # How far each selected plugin's coverage reached: the companies it
            # answers for in this set are those read whole by then.
            "covered_through": {
                slot: {pid: max(self.covered[slot][pid].values()).isoformat()
                       for pid in pids if self.covered.get(slot, {}).get(pid)}
                for slot, pids in active.items()
            },
        }

    def with_applied(self, record: Mapping[str, Any] | None) -> Providers:
        """This set with EVERY slot answered as `record` says.

        One switch moment for the whole app: pay, benefits and company size change
        source together, when the re-estimate that applies the set flips
        `applied_fp`, never one slot before the others. A slot `record` does not
        name is ours. A plugin `record` names stays known as a plugin's, so a
        disabled plugin's rows keep answering until that flip, credited and
        named as the record says. A stored record's `adopted` and `families`
        keys are ignored."""
        if not record:
            return self
        active: dict[str, tuple[str, ...]] = {}
        for slot, pids in (record.get("active") or {}).items():
            if slot in SLOTS and pids:
                active[slot] = (str(pids[0]),)
        plugins = self.plugins | frozenset(str(p) for p in record.get("plugins") or ())
        attributions = {**{str(k): str(v) for k, v in (record.get("attributions") or {}).items()},
                        **self.attributions}
        labels = {**{str(k): str(v) for k, v in (record.get("names") or {}).items()}, **self.fact_labels}
        facts = active.get(COMPANY_FACTS, ())
        ranks = {pid: int(rank) for pid, rank in (record.get("fact_ranks") or {}).items() if (pid,) == facts}
        # Each answering plugin answers for the companies it had read whole when
        # the set was applied; one that had read none answers none until the next
        # flip, whatever it has read since (the stored estimates say the same).
        covered = {slot: dict(by_pid) for slot, by_pid in self.covered.items()}
        through = record.get("covered_through") or {}
        for slot, (pid,) in active.items():
            at = (through.get(slot) or {}).get(pid)
            cutoff = datetime.fromisoformat(str(at)) if at else None
            covered.setdefault(slot, {})[pid] = {
                c: t for c, t in self.covered.get(slot, {}).get(pid, {}).items() if cutoff is not None and t <= cutoff
            }
        return Providers(
            plugins=plugins,
            active=active,
            fact_ranks=ranks or {pid: r for pid, r in self.fact_ranks.items() if (pid,) == facts},
            fact_labels=labels,
            core=self.core,
            attributions=attributions,
            covered=covered,
        )

    def admit(
        self,
        slot: str,
        rows: Iterable[T],
        *,
        provider: Callable[[T], str],
        company: Callable[[T], str] = lambda r: r.company_slug,  # type: ignore[attr-defined]
    ) -> list[T]:
        """The rows `visible` admits: the one answering source's, nothing else."""
        return [r for r in rows if self.visible(slot, provider(r), company(r))]


def providers_from(
    installs: Iterable[InstallRecord],
    coverage: Mapping[str, Mapping[str, Mapping[str, datetime]]],
    order: Mapping[str, Sequence[str]] | None = None,
) -> Providers:
    """The provider set from install records and, per plugin, the companies it
    has read whole in each slot (`plugin -> slot -> {company: when}`). Pure.

    Per slot the first runnable plugin declaring it, by the order setting then
    id, is selected, whether or not it has read anything yet."""
    installs = list(installs)
    order = order or {}

    def position(slot: str, pid: str) -> tuple[int, str]:
        listed = list(order.get(slot, ()))
        return (listed.index(pid) if pid in listed else len(listed), pid)

    covered: dict[str, dict[str, dict[str, datetime]]] = {}
    for rec in installs:
        for slot, companies in coverage.get(rec.plugin_id, {}).items():
            if slot in rec.slots and companies:
                covered.setdefault(slot, {})[rec.plugin_id] = dict(companies)
    runnable = [rec for rec in installs if rec.runnable]
    active: dict[str, tuple[str, ...]] = {}
    for slot in sorted({slot for rec in runnable for slot in rec.slots}):
        candidates = sorted((rec.plugin_id for rec in runnable if slot in rec.slots),
                            key=lambda pid: position(slot, pid))  # noqa: B023 (used at once)
        active[slot] = (candidates[0],)
    ranks: dict[str, int] = {}
    labels: dict[str, str] = {}
    attributions: dict[str, str] = {}
    for rec in sorted(runnable, key=lambda r: r.plugin_id):
        plugin = rec.manifest.get("plugin", {})
        labels[rec.plugin_id] = str(plugin.get("name") or rec.plugin_id)
        if plugin.get("attribution"):
            attributions[rec.plugin_id] = str(plugin["attribution"])
        if active.get(COMPANY_FACTS) == (rec.plugin_id,):
            rank = fact_rank_of(rec.manifest.get("provides", ()))
            if rank is not None:
                ranks[rec.plugin_id] = rank
    return Providers(plugins=frozenset(rec.plugin_id for rec in installs), active=active, fact_ranks=ranks,
                     fact_labels=labels, attributions=attributions, covered=covered)


async def install_records(session: AsyncSession) -> list[InstallRecord]:
    rows = (await session.execute(select(PluginInstall))).scalars().all()
    return [InstallRecord.of(r) for r in rows]


async def load_providers(session: AsyncSession) -> Providers:
    """The current provider set. With no plugin installed this is one cheap
    read and admits only the core's own sources."""
    installs = await install_records(session)
    if not installs:
        return Providers()  # only the core's own sources
    raw = await get_setting_dict(session, REFERENCE_SOURCES_KEY) or {}
    order = {slot: [str(p) for p in v] for slot, v in raw.items() if isinstance(v, list)}
    coverage = await complete_coverage(session, [rec.plugin_id for rec in installs])
    return providers_from(installs, coverage, order)


async def reader_providers(session: AsyncSession) -> Providers:
    """The set every reader uses: pay, benefits, company size.

    The current set with every slot taken from the APPLIED reference record, so
    a list (stored estimates), a detail (read-time package) and a profile never
    mix sources while a re-estimate is moving them, and the whole app
    changes source at one moment, the flip. Before the first
    re-estimate there is no applied set and the current one answers."""
    current = await load_providers(session)
    if not current.plugins:
        # No plugin was ever installed (removed ones keep their row): no plugin
        # row exists, so the applied set could only say what the current one says.
        return current
    applied = await session.scalar(select(ReferenceState.applied_providers).where(ReferenceState.id == 1))
    return current.with_applied(applied)
