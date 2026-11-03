"""The level atlas: the leveling model's data as files.

Every company's ladders, rungs, printed codes, pay policy, posted pay ranges
and identity live in `tracker/levels/atlas/` as CSV tables with a Frictionless Data
Package descriptor (`datapackage.json`). The record types stay in
`model.py`; this module states each table ONCE (`TABLES`, on the shared
`tracker.platform.tables` statement), and the descriptor, the reader's
validation and the canonical writer are all derived from that statement, so
they cannot drift apart.

Why files: one source of truth that ships with the code, can be diffed
and reviewed as data, and can be updated by a person or their agent
without editing Python. The model the app runs is exactly what the
files say: `tests/test_level_atlas.py` holds the round trip (files -> model ->
files is byte-identical) and the descriptor (regenerated == committed).

Rules the files keep:
- No source name or URL in any file. Evidence is described by its kind
  (`basis`, `stated_by`), never by site.
- A row's order is meaning where the model is ordered: companies in their
  dict order, ladders in a company's order, rungs lowest first (position is
  rank).
- Lists are written `a|b|c`; an empty cell is "none" (not zero, not false).
- Notes are documentation for the person reading the file. They are not part
  of the model and nothing reads them.

Pure: reads files beside this module, no DB, no network, no other tracker tier.
`problems` checks a copy elsewhere (a data checkout) for `scripts.check_datasets`.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import date
from functools import cache
from pathlib import Path

from tracker.levels.model import (
    BONUS_RULES,
    EQUITY_RULES,
    EVIDENCE_BASES,
    PHRASE_MATCHES,
    STATED_BY,
    STATED_BY_ESTIMATED,
    VALUE_UNKNOWN,
    CompanyIdentity,
    CompanyLevels,
    Ladder,
    PayPolicy,
    Rung,
    RungTitle,
)
from tracker.platform import tables
from tracker.platform.tables import Field, TableError
from tracker.schema import LevelBand

ATLAS_DIR = Path(__file__).with_name("atlas")
DESCRIPTOR = ATLAS_DIR / "datapackage.json"
#: Semver of the table shapes: a breaking change ships a converter.
SCHEMA_VERSION = "4.0.0"
#: The data's edition. Raised when the data changes, by the person changing it.
EDITION = "2026.11.02"
#: The data's licence, as a Frictionless `licenses` entry. A name without a `path`:
#: no atlas file carries a URL (`tests/test_level_atlas.py`).
LICENSES = ({"name": "CC-BY-4.0", "title": "Creative Commons Attribution 4.0"},)

_BANDS = tuple(band.value for band in LevelBand)
_LIST = "|"


class Table(tables.Table):
    """An atlas table: a CSV file in `ATLAS_DIR`, read where that points now."""

    @property
    def path(self) -> Path:
        return ATLAS_DIR / self.file


_NOTE = Field("note", description="For the reader of the file; not part of the model.")
#: When the evidence for the row was read: a date, never the kind of evidence. Carried beside the model like `note`: nothing the app decides reads it; a
#: refresh re-checks the oldest rows first, and a row without one is refused.
_AS_OF = Field("as_of", "date", required=True, description="When the evidence for this row was read.")

COMPANIES = Table(
    "companies",
    "One row per employer the model knows, in the model's order.",
    (
        Field("slug", required=True, description="tracked_company.slug"),
        Field("parent", description="A sibling employer whose ladders this one shares (google-deepmind -> google)."),
        Field("printed_field", description="The public board field the employer prints its rung in; empty = the posting's text."),
        Field("senior_unconfirmed", "boolean",
              description="A bare 'Senior' in this employer's titles is a weak signal: the posting reads senior, never confirmed (its ladder is not spoken in titles). Empty = false."),
        _AS_OF,
        _NOTE,
    ),
    ("slug",),
)
LADDERS = Table(
    "ladders",
    "A company's ladders, in the company's order. `family` is a taxonomy family or `company` (the company-wide row).",
    (
        Field("company", required=True),
        Field("family", required=True),
        Field("guide", "boolean", required=True, description="Shown in the Walk's level guide: a reviewed ladder."),
        Field("company_wide", "boolean", required=True, description="The code grades every function; false: only `tracks`."),
        Field("tracks", description="Role tracks the code grades when not company-wide, `|`-separated."),
        Field("families", description="Other taxonomy families this ladder levels, `|`-separated."),
        Field("flat", "boolean",
              description="The employer's titles state no level beyond these rungs: a band with no rung is unstated, not skipped. Empty = false."),
        _AS_OF,
        _NOTE,
    ),
    ("company", "family"),
    ((("company",), "companies", ("slug",)),),
)
RUNGS = Table(
    "rungs",
    "Every rung, lowest first within its ladder (row order is rank). A spelling names one rung per ladder.",
    (
        Field("company", required=True),
        Field("family", required=True),
        Field("code", required=True, description="How the company names the rung in the guide."),
        Field("band", required=True, enum=_BANDS, description="The band: the company's own rung word."),
        Field("aliases", description="Every other spelling of this rung, `|`-separated."),
        Field("pay_label", description="The label pay rows key this rung by, when it is not `code`."),
        Field("people_manager", "boolean", required=True),
        Field("seed_median_usd", "integer", description="Seed median total pay, USD a year; empty = no seed."),
        Field("bonus_low", "integer", description="Annual bonus target, low, percent of base."),
        Field("bonus_high", "integer", description="Annual bonus target, high, percent of base."),
        _AS_OF,
        _NOTE,
    ),
    ("company", "family", "code"),
    ((("company", "family"), "ladders", ("company", "family")),),
)
PRINTED = Table(
    "printed",
    "Codes an employer prints on a posting or in a board field, banded where measured.",
    (
        Field("company", required=True),
        Field("code", required=True),
        Field("band", required=True, enum=_BANDS),
    ),
    ("company", "code"),
    ((("company",), "companies", ("slug",)),),
)
RUNG_TITLES = Table(
    "rung_titles",
    "Phrases a company uses for one of its rungs in its postings: a title whose words meet one reads that rung. Phrases, never regexes.",
    (
        Field("company", required=True),
        Field("family", required=True),
        Field("code", required=True),
        Field("phrase", required=True, description="Lowercase words, single-spaced, as the title says them; punctuation is ignored."),
        Field("match", required=True, enum=PHRASE_MATCHES,
              description="exact: the title's words are the phrase; prefix: they start with it; word: it appears among them as whole words."),
        Field("as_of", "date", required=True, description="When the evidence was read."),
        Field("basis", required=True, enum=EVIDENCE_BASES, description="The kind of evidence, never a site."),
        _NOTE,
    ),
    ("company", "family", "phrase"),
    ((("company", "family", "code"), "rungs", ("company", "family", "code")),),
)
FACTS = Table(
    "company_facts",
    "How a company constructs an offer, one fact per row (an absent fact is unverified, never zero).",
    (
        Field("company", required=True),
        Field("fact", required=True, enum=(
            "bonus_rule", "equity_rule", "equity_vehicle", "vesting", "grant_term", "sign_on_bridges_vesting",
            "base_cap_usd", "annual_refresh", "verified",
        )),
        Field("value", required=True, description="The fact, or `unknown`: searched for and not found."),
        Field("stated_by", enum=STATED_BY,
              description="employer: the employer states it; estimated: used where the employer does not state it. "
                          "Required on known facts; empty on `verified` and unknown values."),
        _AS_OF,
    ),
    ("company", "fact"),
)
PAY_GRADES = Table(
    "pay_grades",
    "Posted annual US base ranges a company pays at one rung.",
    (
        Field("company", required=True),
        Field("family", required=True),
        Field("base_min", "integer", required=True),
        Field("base_max", "integer", required=True),
        Field("year", "integer", required=True),
        Field("rung", required=True),
        Field("anchor", required=True, description="A title that states the rung, as the company's rules read it."),
        Field("anchors", "integer", required=True, description="Postings at this range whose title stated it."),
    ),
    ("company", "family", "base_min", "base_max", "year"),
)
PAY_BANDS = Table(
    "pay_bands",
    "Band-level posted ranges for companies with no rung table, built by `scripts.bench_level_bands pay-bands --write`.",
    (
        Field("company", required=True),
        Field("family", required=True),
        Field("base_min", "integer", required=True),
        Field("base_max", "integer", required=True),
        Field("year", "integer", required=True),
        Field("band", required=True, enum=_BANDS),
        Field("anchor", required=True),
        Field("anchors", "integer", required=True),
    ),
    ("company", "family", "base_min", "base_max", "year"),
)

_QUANTILE = "Offered annual US base (the filing's wage from) at this quantile of the cell's filings."
TITLE_PAY = Table(
    "title_pay",
    "Government pay filings per company x title x US state x year, built by `scripts.build_title_pay`. "
    "Level and family are read from the title at use time; an older year is history.",
    (
        Field("company", required=True),
        Field("title", required=True, description="As filed: lowercase, single-spaced."),
        Field("state", required=True, description="The worksite's US state or territory code."),
        Field("year", "integer", required=True, description="The year the filing was made."),
        Field("n", "integer", required=True, description="Filings in the cell."),
        Field("base_p10", "integer", required=True, description=_QUANTILE),
        Field("base_p25", "integer", required=True, description=_QUANTILE),
        Field("base_p50", "integer", required=True, description=_QUANTILE),
        Field("base_p75", "integer", required=True, description=_QUANTILE),
        Field("base_p90", "integer", required=True, description=_QUANTILE),
        Field("level_i", "integer", description="Filings at prevailing-wage level I; empty = none."),
        Field("level_ii", "integer", description="Filings at prevailing-wage level II; empty = none."),
        Field("level_iii", "integer", description="Filings at prevailing-wage level III; empty = none."),
        Field("level_iv", "integer", description="Filings at prevailing-wage level IV; empty = none."),
        Field("as_of", "date", required=True, description="The date the dataset starts for the company."),
    ),
    ("company", "title", "state", "year"),
    sources=("Derived from US Department of Labor disclosure records, which are public domain.",),
)

POSTED_PAY = Table(
    "posted_pay",
    "Stored US annual USD base ranges with original title context; shadow pay only, never range-to-level mapping.",
    (
        Field("company", required=True),
        Field("title", required=True),
        Field("department"),
        Field("team"),
        Field("raw_level", description="Employer-printed code from the stored posting."),
        Field("year", "integer", required=True),
        Field("base_min", "integer", required=True),
        Field("base_max", "integer", required=True),
        Field("n", "integer", required=True, description="Distinct postings in this cell."),
        _AS_OF,
    ),
    ("company", "title", "department", "team", "raw_level", "year", "base_min", "base_max"),
)

ESTIMATED_PAY = Table(
    "estimated_pay",
    "Collected per-rung pay estimates, used where employer base data is absent and for equity estimates.",
    (
        Field("company", required=True),
        Field("family", required=True),
        Field("rung", required=True),
        Field("base_usd", "integer", required=True),
        Field("equity_usd", "integer", description="Estimated annualised equity; blank is unknown."),
        Field("cash_bonus_usd", "integer", description="Estimated cash bonus; may include sign-on, not policy."),
    ),
    ("company", "family", "rung"),
)

IDENTITY = Table(
    "company_identity",
    "Who each company is: always ours, never a plugin's. An empty cell is not researched yet, "
    "never `no`; `scripts.atlas_completeness --gaps` lists them (section `identity`).",
    (
        Field("company", required=True),
        Field("display_name", description="The name the company goes by."),
        Field("listed", "boolean", description="Its shares trade publicly; empty = not researched (never `private`)."),
        Field("ticker", description="Its primary listing's symbol, when listed."),
        Field("exchange", description="The exchange of that listing, as the SEC names it (`NYSE`, `Nasdaq`) or the home exchange."),
        Field("cik", "integer", description="The SEC registrant number the listing was checked against; it survives a ticker change."),
        Field("grant_ticker", description="The listed symbol its equity grants track when that is not its own (a subsidiary paid in its parent's stock)."),
        Field("website", description="Its own site's domain."),
        Field("hq_city", description="Where it is headquartered, as the company names the city."),
        Field("headcount", "integer", description="How many people it employs, roughly."),
        Field("year_founded", "integer", description="The year it was founded."),
        Field("logo", description="A bundled logo asset's name; empty = the dashboard's monogram."),
        Field("brand_color", description="Its brand colour, `#rrggbb`."),
        Field("basis", enum=EVIDENCE_BASES, description="The kind of evidence for the filled cells, never a site."),
        Field("as_of", "date", description="When the filled cells were read; empty while none is."),
        _NOTE,
    ),
    ("company",),
    ((("company",), "companies", ("slug",)),),
)

LEVEL_BASE = Table(
    "level_base",
    "Estimated annual US base and stock per company, family and band, built by scripts.build_level_base. "
    "Base prefers employer filings, then posted ranges, then collected pay aggregates.",
    (
        Field("company", required=True),
        Field("family", required=True),
        Field("band", required=True, enum=_BANDS),
        Field("base_usd", "integer", required=True, description="Estimated annual US base."),
        Field("stock_usd", "integer", description="Estimated annualised equity; blank is unknown, never 0."),
    ),
    ("company", "family", "band"),
)

TABLES: tuple[Table, ...] = (
    COMPANIES, LADDERS, RUNGS, PRINTED, RUNG_TITLES, FACTS, PAY_GRADES, PAY_BANDS, TITLE_PAY, POSTED_PAY, ESTIMATED_PAY,
    IDENTITY, LEVEL_BASE,
)


# --------------------------------------------------------------------------- #
# The descriptor
# --------------------------------------------------------------------------- #


def descriptor() -> dict:
    """The Frictionless Data Package descriptor, generated from `TABLES`."""
    def field(f: Field) -> dict:
        out: dict = {"name": f.name, "type": f.type}
        if f.description:
            out["description"] = f.description
        constraints: dict = {}
        if f.required:
            constraints["required"] = True
        if f.enum:
            constraints["enum"] = list(f.enum)
        if constraints:
            out["constraints"] = constraints
        return out

    def resource(t: Table) -> dict:
        schema: dict = {"fields": [field(f) for f in t.fields], "primaryKey": list(t.primary_key)}
        if t.foreign_keys:
            schema["foreignKeys"] = [
                {"fields": list(cols), "reference": {"resource": ref, "fields": list(ref_cols)}}
                for cols, ref, ref_cols in t.foreign_keys
            ]
        out: dict = {
            "name": t.name, "path": f"{t.name}.csv", "profile": "tabular-data-resource",
            "description": t.description, "format": "csv", "encoding": "utf-8", "schema": schema,
        }
        if t.sources:
            out["sources"] = [{"title": title} for title in t.sources]
        return out

    return {
        "name": "roleband-level-atlas",
        "title": "RoleBand level atlas",
        "description": "How each company levels its people and structures pay.",
        "licenses": [dict(entry) for entry in LICENSES],
        "edition": EDITION,
        "schema_version": SCHEMA_VERSION,
        "profile": "tabular-data-package",
        "resources": [resource(t) for t in TABLES],
    }


def descriptor_text() -> str:
    return json.dumps(descriptor(), indent=2, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


#: A file breaks its table's schema, or a rule across rows; the message names
#: the file and row.
AtlasError = TableError


def _read(table: Table) -> list[dict[str, str]]:
    return tables.read(table, table.path)


def _list(value: str) -> tuple[str, ...]:
    return tuple(value.split(_LIST)) if value else ()


def _int(value: str) -> int | None:
    return int(value) if value else None


def _bool(value: str) -> bool:
    return value == "true"


def load_companies() -> dict[str, CompanyLevels]:
    """Every company's levels, as `levels.companies.COMPANIES` holds them."""
    companies = _read(COMPANIES)
    known = {row["slug"] for row in companies}
    ladders: dict[str, list[dict[str, str]]] = {}
    for row in _read(LADDERS):
        if row["company"] not in known:
            raise AtlasError(f"ladders.csv: unknown company {row['company']!r}")
        ladders.setdefault(row["company"], []).append(row)
    rungs: dict[tuple[str, str], list[Rung]] = {}
    for row in _read(RUNGS):
        key = (row["company"], row["family"])
        if not any(lad["family"] == row["family"] for lad in ladders.get(row["company"], ())):
            raise AtlasError(f"rungs.csv: no ladder {key}")
        low, high = _int(row["bonus_low"]), _int(row["bonus_high"])
        rungs.setdefault(key, []).append(Rung(
            row["code"], LevelBand(row["band"]),
            aliases=_list(row["aliases"]),
            pay_label=row["pay_label"] or None,
            people_manager=_bool(row["people_manager"]),
            seed_median_usd=_int(row["seed_median_usd"]),
            bonus_target=(low / 100, high / 100) if low is not None and high is not None else None,
        ))
    printed: dict[str, dict[str, LevelBand]] = {}
    for row in _read(PRINTED):
        if row["company"] not in known:
            raise AtlasError(f"printed.csv: unknown company {row['company']!r}")
        printed.setdefault(row["company"], {})[row["code"]] = LevelBand(row["band"])
    return {
        row["slug"]: CompanyLevels(
            row["slug"],
            tuple(
                Ladder(
                    lad["family"], tuple(rungs.get((row["slug"], lad["family"]), ())),
                    guide=_bool(lad["guide"]), company_wide=_bool(lad["company_wide"]),
                    tracks=_list(lad["tracks"]), families=_list(lad["families"]),
                    flat=_bool(lad["flat"]),
                )
                for lad in ladders.get(row["slug"], ())
            ),
            parent=row["parent"] or None,
            printed=printed.get(row["slug"], {}),
            printed_field=row["printed_field"] or None,
            senior_unconfirmed=_bool(row["senior_unconfirmed"]),
        )
        for row in companies
    }


def phrase_words(text: str) -> str:
    """A title's words as a `RungTitle` phrase is written: lowercase letters
    and digits, single-spaced, punctuation dropped."""
    return " ".join("".join(c if c.isalnum() else " " for c in text.lower()).split())


def load_rung_titles() -> tuple[RungTitle, ...]:
    """Every rung phrase. A phrase names a rung that exists (company, ladder,
    code) and is written as the title's words, so the row is what it matches."""
    rungs = {(row["company"], row["family"], row["code"]) for row in _read(RUNGS)}
    out = []
    for line, row in enumerate(_read(RUNG_TITLES), start=2):
        key = (row["company"], row["family"], row["code"])
        if key not in rungs:
            raise AtlasError(f"rung_titles.csv:{line}: no rung {key}")
        if row["phrase"] != phrase_words(row["phrase"]):
            raise AtlasError(f"rung_titles.csv:{line}: phrase {row['phrase']!r} is not written as "
                             f"lowercase words ({phrase_words(row['phrase'])!r})")
        # A filing's wage lines a title up with a pay level, not with a rung:
        # a phrase needs the employer's own titles, ranges or pages.
        if row["basis"] == "government_disclosure":
            raise AtlasError(f"rung_titles.csv:{line}: a phrase cannot rest on pay alignment alone "
                             f"(basis government_disclosure)")
        out.append(RungTitle(
            row["company"], row["family"], row["code"], row["phrase"], row["match"],
            date.fromisoformat(row["as_of"]), row["basis"],
        ))
    return tuple(out)


_POLICY_FACTS = ("bonus_rule", "equity_rule", "equity_vehicle", "vesting", "grant_term", "sign_on_bridges_vesting",
                 "base_cap_usd", "annual_refresh", "verified")
#: The values `grant_term` takes.
GRANT_TERMS = ("one_year", "vested_at_grant")
#: Rows about the entry itself, which no one states: they carry no `stated_by`.
_ENTRY_FACTS = frozenset({"verified"})
#: Facts a search can come back empty on (`unknown`); the scored sections plus the vehicle.
_SEARCHABLE_FACTS = frozenset({"bonus_rule", "equity_rule", "equity_vehicle", "vesting", "annual_refresh"})


def load_pay_policies() -> dict[str, PayPolicy]:
    """Every company's offer policy, as `levels.pay.PAY_POLICIES` holds them."""
    facts: dict[str, dict[str, str]] = {}
    estimated: dict[str, set[str]] = {}
    unknown: dict[str, set[str]] = {}
    for line, row in enumerate(_read(FACTS), start=2):
        where = f"{FACTS.path.name}:{line} stated_by"
        if row["value"] == VALUE_UNKNOWN:
            if row["fact"] not in _SEARCHABLE_FACTS:
                raise AtlasError(f"{FACTS.path.name}:{line} value: {row['fact']} cannot be unknown")
            if row["stated_by"]:
                raise AtlasError(f"{where}: nobody states an unknown fact; leave it empty")
            unknown.setdefault(row["company"], set()).add(row["fact"])
            facts.setdefault(row["company"], {})
            continue
        if row["fact"] in _ENTRY_FACTS:
            if row["stated_by"]:
                raise AtlasError(f"{where}: {row['fact']} describes the entry, not a fact; leave it empty")
        elif not row["stated_by"]:
            raise AtlasError(f"{where}: required")
        facts.setdefault(row["company"], {})[row["fact"]] = row["value"]
        if row["stated_by"] == STATED_BY_ESTIMATED:
            estimated.setdefault(row["company"], set()).add(row["fact"])
    policies: dict[str, PayPolicy] = {}
    for company, f in facts.items():
        kwargs: dict = {}
        for name, allowed in (("bonus_rule", BONUS_RULES), ("equity_rule", EQUITY_RULES)):
            if name in f:
                if f[name] not in allowed:
                    raise AtlasError(f"{FACTS.path.name}: {company} {name} {f[name]!r} not in {sorted(allowed)}")
                kwargs[name] = f[name]
        if "equity_vehicle" in f:
            kwargs["equity_vehicle"] = f["equity_vehicle"]
        if "vesting" in f:
            kwargs["vesting"] = f["vesting"]
        if "grant_term" in f:
            if f["grant_term"] not in GRANT_TERMS:
                raise AtlasError(f"{FACTS.path.name}: {company} grant_term {f['grant_term']!r} not in {list(GRANT_TERMS)}")
            kwargs["grant_term"] = f["grant_term"]
        if "sign_on_bridges_vesting" in f:
            kwargs["sign_on_bridges_vesting"] = _bool(f["sign_on_bridges_vesting"])
        if "base_cap_usd" in f:
            kwargs["base_cap_usd"] = int(f["base_cap_usd"])
        if "annual_refresh" in f:
            kwargs["annual_refresh"] = _bool(f["annual_refresh"])
        if "verified" in f:
            kwargs["verified"] = date.fromisoformat(f["verified"])
        if company in estimated:
            kwargs["estimated"] = tuple(n for n in _POLICY_FACTS if n in estimated[company])
        if company in unknown:
            kwargs["unknown"] = tuple(n for n in _POLICY_FACTS if n in unknown[company])
        policies[company] = PayPolicy(company, **kwargs)
    return policies


def load_identity() -> dict[str, CompanyIdentity]:
    """`company_identity.csv` as records, keyed by company. Empty cells read None."""
    out: dict[str, CompanyIdentity] = {}
    for row in _read(IDENTITY):
        out[row["company"]] = CompanyIdentity(
            slug=row["company"],
            display_name=row["display_name"] or None,
            listed=_bool(row["listed"]) if row["listed"] else None,
            ticker=row["ticker"] or None,
            exchange=row["exchange"] or None,
            cik=int(row["cik"]) if row["cik"] else None,
            grant_ticker=row["grant_ticker"] or None,
            website=row["website"] or None,
            hq_city=row["hq_city"] or None,
            headcount=int(row["headcount"]) if row["headcount"] else None,
            year_founded=int(row["year_founded"]) if row["year_founded"] else None,
            logo=row["logo"] or None,
            brand_color=row["brand_color"] or None,
            basis=row["basis"] or None,
        )
    return out


@cache
def load_level_base() -> dict[tuple[str, str], tuple[dict[str, str], ...]]:
    """(company, family) -> its `level_base` rows, lowest band first."""
    out: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in _read(LEVEL_BASE):
        out.setdefault((row["company"], row["family"]), []).append(row)
    return {key: tuple(sorted(rows, key=lambda r: _BANDS.index(r["band"]))) for key, rows in out.items()}


def read_rows(table: Table) -> list[dict[str, str]]:
    """A table's validated rows, for a reader that builds its own records."""
    return _read(table)


# --------------------------------------------------------------------------- #
# Writing (canonical form: fixed columns, the model's order, RFC 4180, LF)
# --------------------------------------------------------------------------- #


def _csv(table: Table, rows: Iterable[dict]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=table.columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: _cell(row.get(k)) for k in table.columns})
    return out.getvalue()


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (tuple, list)):
        return _LIST.join(str(v) for v in value)
    if isinstance(value, LevelBand):
        return value.value
    return str(value)


def company_texts(
    companies: dict[str, CompanyLevels], notes: dict | None = None, as_of: dict | None = None,
) -> dict[str, str]:
    """The four company tables as canonical CSV text. `notes` and `as_of`
    (optional) are carried as they are, each keyed per table:
    {"companies": {slug: v}, "ladders": {(slug, family): v},
    "rungs": {(slug, family, code): v}}."""
    notes = notes or {}
    as_of = as_of or {}
    company_rows, ladder_rows, rung_rows, printed_rows = [], [], [], []
    for slug, record in companies.items():
        company_rows.append({"slug": slug, "parent": record.parent, "printed_field": record.printed_field,
                             # Empty for false: the field says so, and the file stays sparse.
                             "senior_unconfirmed": record.senior_unconfirmed or None,
                             "as_of": as_of.get("companies", {}).get(slug),
                             "note": notes.get("companies", {}).get(slug)})
        for ladder in record.ladders:
            ladder_rows.append({
                "company": slug, "family": ladder.family, "guide": ladder.guide,
                "company_wide": ladder.company_wide, "tracks": ladder.tracks, "families": ladder.families,
                "flat": ladder.flat or None,
                "as_of": as_of.get("ladders", {}).get((slug, ladder.family)),
                "note": notes.get("ladders", {}).get((slug, ladder.family)),
            })
            for rung in ladder.rungs:
                low, high = rung.bonus_target or (None, None)
                rung_rows.append({
                    "company": slug, "family": ladder.family, "code": rung.code, "band": rung.band,
                    "aliases": rung.aliases, "pay_label": rung.pay_label, "people_manager": rung.people_manager,
                    "seed_median_usd": rung.seed_median_usd,
                    "bonus_low": None if low is None else round(low * 100),
                    "bonus_high": None if high is None else round(high * 100),
                    "as_of": as_of.get("rungs", {}).get((slug, ladder.family, rung.code)),
                    "note": notes.get("rungs", {}).get((slug, ladder.family, rung.code)),
                })
        for code, band in record.printed.items():
            printed_rows.append({"company": slug, "code": code, "band": band})
    return {
        "companies": _csv(COMPANIES, company_rows),
        "ladders": _csv(LADDERS, ladder_rows),
        "rungs": _csv(RUNGS, rung_rows),
        "printed": _csv(PRINTED, printed_rows),
    }


def facts_text(policies: dict[str, PayPolicy], as_of: dict | None = None) -> str:
    """The company facts as canonical CSV; `as_of` is keyed (company, fact)."""
    as_of = as_of or {}
    rows = []
    for company, p in policies.items():
        defaults = PayPolicy(company)
        for name in _POLICY_FACTS:
            if name in p.unknown:
                rows.append({"company": company, "fact": name, "value": VALUE_UNKNOWN, "stated_by": None,
                             "as_of": as_of.get((company, name))})
                continue
            value = getattr(p, name)
            if value == getattr(defaults, name):
                continue  # a default is no fact: absent means unverified
            rows.append({"company": company, "fact": name,
                         "value": value.isoformat() if isinstance(value, date) else value,
                         "stated_by": None if name in _ENTRY_FACTS else p.stated_by(name),
                         "as_of": as_of.get((company, name))})
    return _csv(FACTS, rows)


def pay_bands_text(rows: Iterable[dict]) -> str:
    """The pay-band rows `scripts.bench_level_bands pay-bands` builds, as canonical CSV."""
    return _csv(PAY_BANDS, rows)


def title_pay_text(rows: Iterable[dict]) -> str:
    """The filed-pay cells `scripts.build_title_pay` builds, as canonical CSV."""
    return _csv(TITLE_PAY, rows)


def posted_pay_text(rows: Iterable[dict]) -> str:
    """Stored posted-pay cells, as canonical CSV."""
    return _csv(POSTED_PAY, rows)


def estimated_pay_text(rows: Iterable[dict]) -> str:
    """Estimated pay, as canonical CSV."""
    return _csv(ESTIMATED_PAY, rows)


def level_base_text(rows: Iterable[dict]) -> str:
    """Our per-level base pay `scripts.build_level_base` builds, as canonical CSV."""
    return _csv(LEVEL_BASE, rows)


def _row_key(table: Table, row: dict[str, str]) -> object:
    if table is COMPANIES:
        return row["slug"]
    if table is LADDERS:
        return (row["company"], row["family"])
    if table is RUNGS:
        return (row["company"], row["family"], row["code"])
    if table is FACTS:
        return (row["company"], row["fact"])
    raise ValueError(table.name)


def carried_of(table: Table, column: str) -> dict:
    """A column the model does not hold (`note`, `as_of`), keyed as the
    writers take it; empty cells are left out."""
    if column not in table.columns:
        return {}
    return {_row_key(table, row): row[column] for row in _read(table) if row[column]}


def notes_of(table: Table) -> dict:
    """The `note` cells of a table, keyed as `company_texts` takes them."""
    return carried_of(table, "note")


def current_texts() -> dict[str, str]:
    """What the files would say if written from the model they load: the
    round trip the tests hold byte-identical to the committed files."""
    notes = {"companies": notes_of(COMPANIES), "ladders": notes_of(LADDERS), "rungs": notes_of(RUNGS)}
    as_of = {t.name: carried_of(t, "as_of") for t in (COMPANIES, LADDERS, RUNGS)}
    texts = company_texts(load_companies(), notes, as_of)
    texts["rung_titles"] = _csv(RUNG_TITLES, read_rows(RUNG_TITLES))
    texts["company_facts"] = facts_text(load_pay_policies(), carried_of(FACTS, "as_of"))
    texts["pay_grades"] = _csv(PAY_GRADES, read_rows(PAY_GRADES))
    texts["pay_bands"] = _csv(PAY_BANDS, read_rows(PAY_BANDS))
    texts["title_pay"] = _csv(TITLE_PAY, read_rows(TITLE_PAY))
    texts["posted_pay"] = _csv(POSTED_PAY, read_rows(POSTED_PAY))
    texts["estimated_pay"] = _csv(ESTIMATED_PAY, read_rows(ESTIMATED_PAY))
    texts["company_identity"] = _csv(IDENTITY, read_rows(IDENTITY))
    texts["level_base"] = _csv(LEVEL_BASE, read_rows(LEVEL_BASE))
    return texts


# --------------------------------------------------------------------------- #
# Checking a copy elsewhere
# --------------------------------------------------------------------------- #

#: Every file the atlas folder holds besides its tables.
OTHER_FILES = ("README.md", DESCRIPTOR.name)


@contextmanager
def _reading(directory: Path) -> Iterator[None]:
    global ATLAS_DIR
    before = ATLAS_DIR
    ATLAS_DIR = directory
    load_level_base.cache_clear()
    try:
        yield
    finally:
        ATLAS_DIR = before
        load_level_base.cache_clear()


def problems(directory: Path) -> list[str]:
    """Every break in the atlas copy at `directory`, one line each: a file
    the atlas does not state, each table's cells, the rules across rows the
    loaders keep, the descriptor, and the canonical form the writers produce.

    For a checker process (`scripts.check_datasets`): while it runs, the
    atlas reads `directory`."""
    stated = {t.file for t in TABLES} | set(OTHER_FILES)
    out = [f"{p.name}: not an atlas file" for p in sorted(directory.iterdir())
           if p.is_file() and p.name not in stated]
    out += [f"{name}: missing" for name in sorted(stated - {p.name for p in directory.iterdir()})]
    if out:
        return out
    with _reading(directory):
        for table in TABLES:
            out += tables.problems(table, table.path)
        if out:
            return out
        try:
            texts = current_texts()
            load_rung_titles()
            load_identity()
            load_level_base()
        except TableError as error:
            return [str(error)]
        if (directory / DESCRIPTOR.name).read_text(encoding="utf-8") != descriptor_text():
            out.append(f"{DESCRIPTOR.name}: differs from the tables' statement (written by the app's descriptor_text)")
        for name, text in texts.items():
            if (directory / f"{name}.csv").read_text(encoding="utf-8") != text:
                out.append(f"{name}.csv: not in canonical form (the app's writer would change it)")
    return out
