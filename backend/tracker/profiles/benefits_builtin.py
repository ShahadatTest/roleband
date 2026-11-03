"""Benefits from our own dataset, or from the one plugin answering them.

Our source for `company.benefits` is the benefits dataset (`benefits_dataset/`),
read here from its two files, in memory and read-only: no seed, no
`company_benefit` row, no network. `observations.jsonl` is the dataset itself,
one evidence record per line, edited in place when the data changes;
`taxonomy.json` names the types and categories. The runtime never writes either.

**One source answers, never both.** While a plugin is selected for `company.benefits` the profile shows
its rows only (`plugin_benefits`), and a company it has not read shows none of
ours in their place. With no plugin selected it shows the dataset only
(`dataset_benefits`). Turning a plugin off brings the dataset back unchanged:
nothing here reads one source to shape the other.
- a plugin row whose name no taxonomy alias maps is kept under its own name, in
  `other`, never dropped (the dataset's own rule is to fail on an unseen label;
  a reader shows what it cannot classify instead);
- a benefit with no evidence record is unknown and not listed at all: unknown
  is not "not offered", and a profile says what is known.

Per-perk values are kept per row and never summed into a total.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from tracker.comp_providers.base import BUILTIN
from tracker.platform import tables
from tracker.platform.tables import Field, Table

DATASET = Path(__file__).resolve().parent / "benefits_dataset"
#: The group for a provider row no alias maps.
OTHER = "other"

#: Where a record was found, by the kind of record it is.
_CONTEXTS = {"employer": ("job_specific", "captured_posting", "company_page"), "dataset": ("company_unknown_scope",)}

#: `observations.jsonl`, stated once: the data card's Columns section in code.
#: `scripts.check_datasets` holds every file to it; the reader below trusts it.
OBSERVATIONS = Table(
    "observations",
    "One evidence record per line: one company, one benefit type, one observation.",
    (
        Field("company", required=True, description="A company slug the app names."),
        Field("benefit_type", required=True, description="A benefit type id from taxonomy.json."),
        Field("observation_id", required=True, description="The record's stable id."),
        Field("kind", required=True, enum=("employer", "dataset")),
        Field("assertion", required=True, enum=("listed",)),
        Field("context", required=True, enum=(*_CONTEXTS["employer"], *_CONTEXTS["dataset"])),
        Field("terms", description="employer: the whole line; dataset: reference text, never shown."),
        Field("display_excerpt", description="The wording the profile shows."),
        Field("has_terms", "boolean", required=True),
        Field("estimated_annual_value_usd", "integer", description="Null is unknown; 0 is an explicit zero."),
        Field("scope", "object", required=True, description="country, region, employee_group, role_family, level."),
        Field("review_status", required=True, enum=("unreviewed", "reviewed", "disputed")),
        Field("supporting_capture_count", "integer", description="employer records only."),
    ),
    ("observation_id",),
    format="jsonl",
)
#: Every file the dataset folder holds.
FILES = (OBSERVATIONS.file, "taxonomy.json", "README.md")
_SCOPE = {"country", "region", "employee_group", "role_family", "level"}


@dataclass(frozen=True)
class Taxonomy:
    categories: tuple[str, ...]
    #: benefit type -> its one primary category
    category_of: Mapping[str, str]
    #: normalized label -> benefit type (explicit aliases only)
    alias: Mapping[str, str]


def _norm(label: str) -> str:
    return " ".join(label.split()).casefold()


@cache
def taxonomy() -> Taxonomy:
    raw = json.loads((DATASET / "taxonomy.json").read_text())
    alias: dict[str, str] = {}
    for t in raw["benefit_types"]:
        for name in (t["label"], *t.get("aliases", ())):
            alias[_norm(name)] = t["id"]
    return Taxonomy(
        categories=tuple(c["id"] for c in raw["categories"]),
        category_of={t["id"]: t["category"] for t in raw["benefit_types"]},
        alias=alias,
    )


def classify(name: str) -> str | None:
    """The benefit type a provider's label names, by explicit alias; None if none."""
    return taxonomy().alias.get(_norm(name))


@cache
def _cells() -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    """company -> its cells `{company, benefit_type, observations}`, one per
    benefit type with evidence. Cells and the observations in each keep the
    file's first-seen order: the profile's tie-breaks follow it."""
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    with (DATASET / "observations.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            key = (record.pop("company"), record.pop("benefit_type"))
            cell = cells.setdefault(key, {"company": key[0], "benefit_type": key[1], "observations": []})
            cell["observations"].append(record)
    out: dict[str, list[Mapping[str, Any]]] = {}
    for (company, _), cell in cells.items():
        out.setdefault(company, []).append(cell)
    return {company: tuple(listed) for company, listed in out.items()}


def builtin_cells(company: str) -> tuple[Mapping[str, Any], ...]:
    return _cells().get(company, ())


def _said(text: str | None) -> str:
    """The key two wordings share when they say the same thing: case, spacing
    and closing punctuation aside. (The dataset already strips list markers.)"""
    return " ".join((text or "").split()).casefold().rstrip(" .;:,!")


def _builtin_item(benefit_type: str, obs: Mapping[str, Any]) -> dict[str, Any]:
    # An employer mention's `terms` is the whole line it was found in, which can
    # open on something else entirely ("The base salary range for this position
    # ..." before the benefits it lists); `display_excerpt` is the sentence that
    # names the benefit. The row shows that sentence and keeps the full
    # statement as its description, so the wording it came from is never lost:
    # a preview never replaces the original qualifications.
    # A dataset record shows its own words or none: its `terms` carry the
    # structured fields and the estimate as reference text, never as wording.
    employer = obs.get("kind") == "employer"
    shown = (obs.get("display_excerpt") or "").strip() or None
    full = (obs.get("terms") or "").strip() or None if employer else None
    return {
        "name": None,
        "benefit_type": benefit_type,
        "value_usd": obs.get("estimated_annual_value_usd"),
        "value_text": shown,
        "description": full if full != shown else None,
        "source": BUILTIN,
        "provider": BUILTIN,
        "builtin": True,
        "kind": "employer" if employer else "dataset",
        "country": (obs.get("scope") or {}).get("country"),
        "reviewed": obs.get("review_status") == "reviewed",
        "mentions": int(obs.get("supporting_capture_count") or 0) if employer else 0,
        "wordings": [],
    }


def _row_item(row: Any, benefit_type: str | None) -> dict[str, Any]:
    return {
        "name": row.name,
        "benefit_type": benefit_type,
        "value_usd": row.value_usd,
        "value_text": row.value_text,
        "description": row.description,
        "source": row.provider,  # the row stores no source apart from its provider
        "provider": row.provider,
        "builtin": False,
        "kind": "provider",
        "country": row.country,
        "reviewed": False,
        "mentions": 0,
        "wordings": [],
    }


def _one_benefit(records: list[dict[str, Any]]) -> dict[str, Any]:
    """One benefit from every record of it: one row per benefit, whichever
    source answers. The row leads with its best wording:
    a reviewed one first, then the fullest. Every other distinct wording stays
    on the row, so nothing a record said is dropped; a record that says only
    the name adds its mentions and nothing else."""
    worded = [r for r in records if r["value_text"]]
    ranked = sorted(worded, key=lambda r: (not r["reviewed"], -len(r["value_text"])))
    lead = dict(ranked[0] if ranked else records[0])
    seen = {_said(lead["value_text"])} if lead["value_text"] else set()
    wordings = []
    for r in ranked[1:]:
        if (key := _said(r["value_text"])) not in seen:
            seen.add(key)
            wordings.append({"text": r["value_text"], "kind": r["kind"], "country": r["country"]})
    lead["wordings"] = wordings
    lead["mentions"] = sum(r["mentions"] for r in records)
    if lead["value_usd"] is None:
        lead["value_usd"] = next((r["value_usd"] for r in records if r["value_usd"] is not None), None)
    if not lead["value_text"] and lead["mentions"]:
        lead["kind"] = "employer"  # named in its postings, in no words of its own
    lead["reviewed"] = lead["reviewed"] if lead["value_text"] else any(r["reviewed"] for r in records)
    return lead


def _grouped(by_type: Mapping[str, list[dict[str, Any]]], unmapped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`[{category, items}]` in the taxonomy's category order, one item per
    benefit, `other` last (its labels map to no benefit, so each stays its own)."""
    tax = taxonomy()
    groups: dict[str, list[dict[str, Any]]] = {}
    for kind in sorted(by_type, key=lambda k: (tax.categories.index(tax.category_of[k]), k)):
        groups.setdefault(tax.category_of[kind], []).append(_one_benefit(by_type[kind]))
    out = [{"category": category, "items": items} for category, items in groups.items()]
    if unmapped:
        out.append({"category": OTHER, "items": unmapped})
    return out


#: A sentence naming this many benefits is a list of them, not any one's terms.
#: Two is still terms ("1x salary up to $200,000 in Life and Accidental Death
#: insurance" is each one's): it stays under both.
SHARED_AT = 3


def _shared(company: str) -> dict[str, list[str]]:
    """Employer sentences that name several benefits ("Medical, Dental, and
    Vision Coverage"), keyed by what they say, with the benefits they name.
    Such a sentence is said once on the profile, not under each benefit."""
    names: dict[str, set[str]] = {}
    for cell in builtin_cells(company):
        for obs in cell["observations"]:
            if obs.get("kind") == "employer" and obs.get("assertion") == "listed":
                names.setdefault(_said(obs.get("display_excerpt")), set()).add(cell["benefit_type"])
    return {key: sorted(kinds) for key, kinds in names.items() if len(kinds) >= SHARED_AT}


def dataset_benefits(company: str) -> list[dict[str, Any]]:
    """The profile's benefit groups from our dataset alone: one item per listed
    cell. A wording that only restates the benefit's name, or that several
    benefits share (`dataset_benefit_notes`), counts toward the item's mentions
    and is not repeated as its words."""
    shared = _shared(company)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for cell in builtin_cells(company):
        kind = cell["benefit_type"]
        for obs in cell["observations"]:
            if obs.get("assertion") != "listed":
                continue
            item = _builtin_item(kind, obs)
            text = item["value_text"]
            if text and (_said(text) in shared or classify(text) == kind):
                item["value_text"] = item["description"] = None
            by_type.setdefault(kind, []).append(item)
    return _grouped(by_type, [])


def dataset_benefit_notes(company: str) -> list[dict[str, Any]]:
    """The sentences several benefits share, each once, most mentioned first:
    `{text, mentions, benefit_types}`. A posting that says "Medical, Dental,
    and Vision Coverage" is one observation under each benefit it names, so a
    note's mentions are the most any one of those benefits counts, not their sum."""
    shared = _shared(company)
    text: dict[str, str] = {}
    per_cell: dict[tuple[str, str], int] = {}
    for cell in builtin_cells(company):
        for obs in cell["observations"]:
            key = _said(obs.get("display_excerpt"))
            if obs.get("kind") != "employer" or obs.get("assertion") != "listed" or key not in shared:
                continue
            text.setdefault(key, obs["display_excerpt"])
            at = (key, cell["benefit_type"])
            per_cell[at] = per_cell.get(at, 0) + int(obs.get("supporting_capture_count") or 0)
    notes = [{"text": text[key], "benefit_types": kinds,
              "mentions": max(n for (k, _), n in per_cell.items() if k == key)}
             for key, kinds in shared.items()]
    return sorted(notes, key=lambda n: (-n["mentions"], n["text"]))


def plugin_benefits(rows: Iterable[Any]) -> list[dict[str, Any]]:
    """The profile's benefit groups from the selected plugin's `company_benefit`
    rows alone, classified by the taxonomy's explicit aliases."""
    by_type: dict[str, list[dict[str, Any]]] = {}
    unmapped: list[dict[str, Any]] = []
    for row in rows:
        kind = classify(row.name)
        if kind is None:
            unmapped.append(_row_item(row, None))
        else:
            by_type.setdefault(kind, []).append(_row_item(row, kind))
    return _grouped(by_type, unmapped)


# --------------------------------------------------------------------------- #
# Checking the dataset
# --------------------------------------------------------------------------- #


def _taxonomy_problems(raw: Any) -> list[str]:
    """`taxonomy.json`: unique ids, each type in a known category, and no label
    or alias that names two types (`classify` would keep only one)."""
    where = "taxonomy.json"
    categories = [c.get("id") for c in raw.get("categories", ())]
    out = [f"{where}: category {c!r} is listed twice" for c in sorted({c for c in categories if categories.count(c) > 1})]
    seen: dict[str, str] = {}
    for t in raw.get("benefit_types", ()):
        kind = t.get("id")
        if t.get("category") not in categories:
            out.append(f"{where}: benefit type {kind!r} has category {t.get('category')!r}, not a listed one")
        for name in {_norm(n) for n in (t.get("label") or "", *t.get("aliases", ())) if n}:
            if seen.get(name, kind) != kind:
                out.append(f"{where}: {name!r} names both {seen[name]!r} and {kind!r}")
            seen.setdefault(name, kind)
    ids = [t.get("id") for t in raw.get("benefit_types", ())]
    out += [f"{where}: benefit type {k!r} is listed twice" for k in sorted({k for k in ids if ids.count(k) > 1})]
    return out


def _record_problems(line: int, r: dict[str, Any], companies: set[str], types: set[str]) -> list[str]:
    """The rules one record keeps across its fields and against the app."""
    out = []

    def say(problem: str) -> None:
        out.append(f"{OBSERVATIONS.file}:{line}: {problem}")

    if r.get("company") and r["company"] not in companies:
        say(f"company {r['company']!r} is not a named company")
    if r.get("benefit_type") and r["benefit_type"] not in types:
        say(f"benefit_type {r['benefit_type']!r} is not in taxonomy.json")
    kind = r.get("kind")
    context = r.get("context")
    if kind in _CONTEXTS and context and any(context in c for c in _CONTEXTS.values()) and context not in _CONTEXTS[kind]:
        say(f"context {context!r} does not fit a {kind} record")
    if "estimated_annual_value_usd" not in r:
        say("estimated_annual_value_usd: required, null when unknown")
    scope = r.get("scope")
    if isinstance(scope, dict):
        if missing := sorted(_SCOPE - set(scope)):
            say(f"scope needs {missing}")
        if (kind == "employer") != ("scope_title" in scope):
            say("scope.scope_title is kept on employer records only")
    if (kind == "employer") != ("supporting_capture_count" in r):
        say("supporting_capture_count is kept on employer records only")
    return out


def problems(directory: Path, companies: set[str]) -> list[str]:
    """Every break in the dataset copy at `directory`: a file it does not
    hold, the taxonomy, each record's cells, and each record against the
    taxonomy and `companies` (the slugs the app names)."""
    present = {p.name for p in directory.iterdir() if p.is_file()}
    out = [f"{name}: not a benefits dataset file" for name in sorted(present - set(FILES))]
    out += [f"{name}: missing" for name in sorted(set(FILES) - present)]
    if out:
        return out
    try:
        raw = json.loads((directory / "taxonomy.json").read_text(encoding="utf-8"))
    except ValueError as error:
        return [f"taxonomy.json: not JSON ({error})"]
    out += _taxonomy_problems(raw)
    types = {t.get("id") for t in raw.get("benefit_types", ())}
    path = directory / OBSERVATIONS.file
    out += tables.problems(OBSERVATIONS, path)
    with path.open(encoding="utf-8") as handle:
        for line, text in enumerate(handle, start=1):
            try:
                record = json.loads(text)
            except ValueError:
                continue  # named above
            if isinstance(record, dict):
                out += _record_problems(line, record, companies, types)
    return out
