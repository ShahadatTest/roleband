"""Skill catalogue: load, validate, and compile `catalog.yaml`.

The YAML file is the human-reviewed source of truth.
This module turns it into frozen dataclasses plus compiled alias matchers, and
computes `taxonomy_version` (a hash of the parsed content, so comments do not count) — the value stamped on every extraction
so a catalogue change is detectable per job.

Validation is strict and runs on load: duplicate slugs, alias collisions, unknown
facets/match modes, missing descriptions, hierarchy cycles, and invalid guard
regexes all raise `CatalogError`. A broken catalogue must fail loudly, never
degrade into partial extraction.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

CATALOG_PATH = Path(__file__).with_name("catalog.yaml")

FACETS = (
    "technology",
    "professional_skill",
    "industry",
    "behavioral_competency",
    "language",
)
MATCH_MODES = ("exact_ci", "exact_case")


class CatalogError(ValueError):
    """Catalogue failed validation — refuse to extract with it."""


@dataclass(frozen=True)
class AliasSpec:
    concept_slug: str
    alias: str
    match: str  # exact_ci | exact_case
    required_context: str | None = None
    excluded_context: str | None = None

    # Compiled patterns (set in __post_init__ via object.__setattr__).
    pattern: re.Pattern = field(init=False, repr=False, compare=False)
    required_re: re.Pattern | None = field(init=False, repr=False, compare=False)
    excluded_re: re.Pattern | None = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        flags = 0 if self.match == "exact_case" else re.IGNORECASE
        object.__setattr__(self, "pattern", re.compile(_boundary_pattern(self.alias), flags))
        object.__setattr__(
            self, "required_re", re.compile(self.required_context) if self.required_context else None
        )
        object.__setattr__(
            self, "excluded_re", re.compile(self.excluded_context) if self.excluded_context else None
        )


@dataclass(frozen=True)
class ConceptSpec:
    slug: str
    display: str
    facet: str
    category: str
    description: str
    parent: str | None = None
    aliases: tuple[AliasSpec, ...] = ()


@dataclass(frozen=True)
class Catalog:
    version: int
    taxonomy_version: str  # short content hash of catalog.yaml
    concepts: tuple[ConceptSpec, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_slug", {c.slug: c for c in self.concepts})

    def get(self, slug: str) -> ConceptSpec | None:
        return self._by_slug.get(slug)  # type: ignore[attr-defined]

    @property
    def by_slug(self) -> dict[str, ConceptSpec]:
        return self._by_slug  # type: ignore[attr-defined]

    def all_aliases(self) -> list[AliasSpec]:
        return [a for c in self.concepts for a in c.aliases]


def _boundary_pattern(alias: str) -> str:
    """Alias regex that won't fire inside a larger alphanumeric token.

    Token characters include +, #, and . connecting alphanumerics so `c++`, `c#`,
    and `.net` match as whole tokens and `go` cannot fire inside `category`.
    """
    core = re.escape(alias.strip())
    return rf"(?<![A-Za-z0-9+#]){core}(?![A-Za-z0-9+#])"


def _validate(raw: dict) -> Catalog:
    if not isinstance(raw, dict) or "concepts" not in raw:
        raise CatalogError("catalog.yaml must be a mapping with a 'concepts' list")

    version = raw.get("version")
    if not isinstance(version, int):
        raise CatalogError("catalog.yaml needs an integer 'version'")

    concepts: list[ConceptSpec] = []
    seen_slugs: set[str] = set()
    # Alias collision guard: the same (normalized alias text) may not map to two
    # concepts — one surface form must resolve deterministically.
    alias_owner: dict[str, str] = {}

    for i, c in enumerate(raw["concepts"]):
        where = f"concept #{i} ({c.get('slug', '?')})"
        for req in ("slug", "display", "facet", "category", "description"):
            if not c.get(req):
                raise CatalogError(f"{where}: missing required field '{req}'")
        slug = c["slug"]
        if slug in seen_slugs:
            raise CatalogError(f"duplicate slug '{slug}'")
        seen_slugs.add(slug)
        if c["facet"] not in FACETS:
            raise CatalogError(f"{where}: unknown facet '{c['facet']}'")

        alias_specs: list[AliasSpec] = []
        raw_aliases = c.get("aliases") or []
        if not raw_aliases:
            raise CatalogError(f"{where}: at least one alias required")
        for a in raw_aliases:
            if not a.get("alias"):
                raise CatalogError(f"{where}: alias entry missing 'alias'")
            mode = a.get("match", "exact_ci")
            if mode not in MATCH_MODES:
                raise CatalogError(f"{where}: unknown match mode '{mode}'")
            key = a["alias"].strip().lower()
            owner = alias_owner.get(key)
            if owner and owner != slug:
                raise CatalogError(f"alias '{a['alias']}' claimed by both '{owner}' and '{slug}'")
            alias_owner[key] = slug
            try:
                alias_specs.append(
                    AliasSpec(
                        concept_slug=slug,
                        alias=a["alias"],
                        match=mode,
                        required_context=a.get("required_context"),
                        excluded_context=a.get("excluded_context"),
                    )
                )
            except re.error as e:
                raise CatalogError(f"{where}: invalid regex in alias '{a['alias']}': {e}") from e

        concepts.append(
            ConceptSpec(
                slug=slug,
                display=c["display"],
                facet=c["facet"],
                category=c["category"],
                description=c["description"].strip(),
                parent=c.get("parent"),
                aliases=tuple(alias_specs),
            )
        )

    # Parent existence + cycle check.
    by_slug = {c.slug: c for c in concepts}
    for c in concepts:
        if c.parent and c.parent not in by_slug:
            raise CatalogError(f"concept '{c.slug}': unknown parent '{c.parent}'")
    for c in concepts:
        seen: set[str] = set()
        cur: ConceptSpec | None = c
        while cur and cur.parent:
            if cur.slug in seen:
                raise CatalogError(f"hierarchy cycle involving '{c.slug}'")
            seen.add(cur.slug)
            cur = by_slug.get(cur.parent)

    # The version hashes what the catalogue SAYS, not how the file is written:
    # a comment or a reflow must not send every job back for re-extraction.
    canonical = json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str)
    taxonomy_version = hashlib.md5(canonical.encode("utf-8")).hexdigest()[:12]
    return Catalog(version=version, taxonomy_version=taxonomy_version, concepts=tuple(concepts))


def load_catalog(path: Path | None = None) -> Catalog:
    """Load + validate the catalogue from disk (uncached; prefer `get_catalog`)."""
    p = path or CATALOG_PATH
    text = p.read_text(encoding="utf-8")
    return _validate(yaml.safe_load(text))


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    """Process-wide catalogue singleton for the production path."""
    return load_catalog()
