"""Place sets: one role an employer lists once per place.

An employer may list one role as ten postings, one per city, each with the
same title and the same text. That is one role. It is not a repost lineage (nothing was listed again: the postings
run side by side) and not twins (nothing differs but the place), so neither
review queue has a right answer for it, and the lineage detector's
location gate rejects most such pairs before anyone sees them.

The rule is deterministic and asks nobody. Open postings of one company form a
place set when:

1. their `normalize_title` is equal (level words kept, so "Senior" never meets
   "Staff"; a trailing own-location suffix is stripped);
2. their description text is equal after folding whitespace and case, and is
   longer than `place_set_min_text_chars` (a stub is no identity evidence);
3. their `family` and `level_band` are equal;
4. EVERY member names a place (canonical cities when the posting has them,
   its raw strings otherwise). When every member states its OWN place (the
   board's primary location, `source_facts.locations[is_primary]`), members
   compare by that place alone: some boards print the posting's place first
   and the company's office list after it on every posting, so the lists
   coincide and only the primary tells the postings apart.

Two postings at the same place are the role listed again there. Whether that
is one opening or two is a headcount question text cannot answer, and the
person choosing where to apply does not need it answered: it is one role,
shown as a deck, each card saying what differs. The earliest posting at a
place, by the employer's own date, holds the place; each later one is
`relisted`, and still counts as a listing for the standing-posting sign. An
employer that lists all its cities on every posting and varies only the
primary one has the same places by the full lists and different ones by the
primaries. A group in which any member states no usable primary compares the
full lists.

A person outranks the rule twice over. A group containing any pair a person has
already decided (a lineage or twin verdict, either way) is left alone, and a
posting a person has called "Different roles" here joins no set until they take
it back.

Inside a set, a pending machine proposal between two members (a suspected
duplicate, a pending twin) is withdrawn, as re-detection withdraws a proposal
the current rules do not support. Human verdicts are never touched, and an
automatic lineage link (which counts toward a lineage while pending) cannot
join two members: a set's postings overlap in time, and only a closed posting
can be reposted.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.lineage.content_diff import passage_key
from tracker.lineage.content_diff import passages as passages_of
from tracker.lineage.decision_history import holds_history_sql
from tracker.lineage.explained_text import differs_by_explained_passages, requirements_conflict
from tracker.lineage.lock import LINEAGE_LOCK_KEY
from tracker.lineage.normalize import normalize_title
from tracker.lineage.place_text import differs_only_by_place
from tracker.platform.locks import advisory_xact_lock
from tracker.taxonomy.locations import normalize_cities

RULE_VERSION = "place_set/v5"

#: Why a group of same-text postings is not a place set. Stable strings: the
#: rebuild summary and the bench report them.
SKIP_NO_PLACE = "a posting names no place"
SKIP_HUMAN_VERDICT = "a person already decided a pair of these postings"
SKIP_MIXED_CLASS = "the postings read as different levels or families"

# The SQL definition of "the same text". One definition, here: Python never
# re-derives it, so the database and the rule cannot disagree about a byte.
TEXT_HASH_SQL = (
    "md5(lower(btrim(regexp_replace(description_text, '[[:space:]]+', ' ', 'g'))))"
)


@dataclass(frozen=True)
class Posting:
    """What the rule reads of one open posting."""

    id: int
    company: str
    title: str
    locations: tuple[str, ...]
    cities: tuple[str, ...]
    text_hash: str
    family: str | None
    level_band: str
    first_seen: datetime | None = None
    employer_label: str | None = None
    employer_job: str | None = None
    #: The board's primary location label for this posting, when it states one.
    primary: str | None = None
    #: The employer's earliest date for this posting (`jobs.first_posted_at`):
    #: which posting at one place came first.
    first_posted: datetime | None = None
    #: How `text_hash` was reached: "exact" (the folded text's own md5) or
    #: "place" (the key of a text class joined because the texts differ only
    #: by where the role is) or "explained" (joined because every
    #: differing passage is explained).
    text_match: str = "exact"


@dataclass(frozen=True)
class PlaceSet:
    company: str
    title: str
    text_hash: str
    member_ids: tuple[int, ...]
    places: tuple[str, ...]
    evidence: dict = field(default_factory=dict)
    #: Each member's relation to the role: `place`, the first
    #: posting at its place, or `relisted`, another posting at a place an
    #: earlier member already holds.
    relations: dict[int, str] = field(default_factory=dict)
    #: Each member's place key, what `relisted` compares.
    place_keys: dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Skipped:
    company: str
    title: str
    member_ids: tuple[int, ...]
    reason: str


def place_key(posting: Posting) -> frozenset[str]:
    """The places a posting names, compared by canonical city when it has any.

    Raw strings spell one place many ways ("New York City", "New York, NY");
    the canonical labels (`jobs.location_cities`) fold those, so a difference
    in spelling is never mistaken for a difference in place.
    """
    raw = posting.cities or posting.locations
    return frozenset(p.strip().casefold() for p in raw if p and p.strip())


#: A primary that states how, not where: a board's arrangement word.
_ARRANGEMENT_WORDS = frozenset(
    {"remote", "hybrid", "distributed", "in-office", "in office", "on-site", "onsite", "anywhere"}
)


def primary_place_key(posting: Posting) -> str | None:
    """The posting's own place, as one comparable key, or None when it states
    no usable one.

    Unusable: no primary; a primary the posting's places do not hold (a board
    arrangement word the adapter dropped: a board that records "Hybrid" as
    the primary while its places are its offices); a bare arrangement
    word. A place compares by its canonical label, so a spelling is never a
    different place ("Germany (Remote)" and "Remote - Germany" are one). A
    remote place whose label names no country keeps its whole label: bare
    "Remote" would make every such place one.
    """
    label = (posting.primary or "").strip()
    if not label or label.casefold() in _ARRANGEMENT_WORDS:
        return None
    if label.casefold() not in {p.strip().casefold() for p in posting.locations}:
        return None
    canonical = normalize_cities([label])
    if canonical and canonical[0] != "Remote":
        return canonical[0].casefold()
    return label.casefold()


def _uses_primaries(postings: Sequence[Posting]) -> bool:
    return all(primary_place_key(p) is not None for p in postings)


def _places(postings: Sequence[Posting]) -> tuple[str, ...]:
    seen: dict[str, str] = {}
    if _uses_primaries(postings):
        # One label per place: two postings at one city spelled two ways are
        # one place on the Board chip.
        for posting in postings:
            seen.setdefault(cast(str, primary_place_key(posting)), (posting.primary or "").strip())
        return tuple(seen.values())
    for posting in postings:
        for place in posting.cities or posting.locations:
            label = place.strip()
            if label and label.casefold() not in seen:
                seen[label.casefold()] = label
    return tuple(seen.values())


def _shared(values: Iterable[str | None]) -> str | None:
    values = list(values)
    if values and values[0] is not None and all(v == values[0] for v in values):
        return values[0]
    return None


def form_place_sets(
    postings: Iterable[Posting],
    *,
    decided_pairs: set[frozenset[int]] = frozenset(),  # type: ignore[assignment]
    rejected: set[int] = frozenset(),  # type: ignore[assignment]
) -> tuple[list[PlaceSet], list[Skipped]]:
    """Group open postings into place sets. Pure.

    `decided_pairs` are the pairs a person has given any lineage or twin
    verdict; `rejected` the postings a person has said are not in a set.
    """
    groups: dict[tuple, list[Posting]] = defaultdict(list)
    for posting in postings:
        if posting.id in rejected:
            continue
        title = normalize_title(posting.title, posting.locations)
        if not title:
            continue
        # The group is the set's stored identity, (company, title, text): the
        # rule and the table cannot then disagree about which postings one
        # set holds.
        groups[(posting.company, title, posting.text_hash)].append(posting)

    sets: list[PlaceSet] = []
    skipped: list[Skipped] = []
    for (company, title, text_hash), members in groups.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda p: (p.first_seen or datetime.min.replace(tzinfo=UTC), p.id))
        ids = tuple(p.id for p in members)
        # Level words separate roles (invariant 3), and so does a level or
        # family read from anything else (a printed rung, a pay grade, a
        # department): one title and text read two ways is not a question the
        # rule can answer, so it forms no set rather than one set of two roles.
        if len({(p.family, p.level_band) for p in members}) > 1:
            skipped.append(Skipped(company, title, ids, SKIP_MIXED_CLASS))
            continue
        by_primary = _uses_primaries(members)
        keys: list[frozenset[str]] = (
            [frozenset({cast(str, primary_place_key(p))}) for p in members]
            if by_primary
            else [place_key(p) for p in members]
        )
        if any(not key for key in keys):
            skipped.append(Skipped(company, title, ids, SKIP_NO_PLACE))
            continue
        id_set = set(ids)
        if any(pair <= id_set for pair in decided_pairs):
            skipped.append(Skipped(company, title, ids, SKIP_HUMAN_VERDICT))
            continue
        evidence: dict[str, object] = {
            "same_text": True,
            "text_match": next(
                (m for m in ("explained", "place") if any(p.text_match == m for p in members)), "exact"
            ),
            "place_basis": "primary" if by_primary else "places",
            "employer_label": _shared(p.employer_label for p in members),
            "employer_job": _shared(p.employer_job for p in members),
        }
        # Two postings at one place are the role listed again there: the
        # earliest by the employer's own date holds the place, every later one
        # is `relisted`. For the person choosing where to apply it is one
        # role, shown with the difference (the date) stated.
        key_of = {p.id: "|".join(sorted(k)) for p, k in zip(members, keys, strict=True)}
        relations: dict[int, str] = {}
        held: set[str] = set()
        for p in sorted(members, key=_listed_order):
            relations[p.id] = "relisted" if key_of[p.id] in held else "place"
            held.add(key_of[p.id])
        evidence["relisted"] = sum(r == "relisted" for r in relations.values())
        sets.append(
            PlaceSet(
                company=company,
                title=title,
                text_hash=text_hash,
                member_ids=ids,
                places=_places(members),
                evidence=evidence,
                relations=relations,
                place_keys=key_of,
            )
        )
    return sets, skipped


def _listed_order(p: Posting) -> tuple:
    """Which posting at one place came first: the employer's earliest date,
    else our first sighting, then the id."""
    earliest = datetime.min.replace(tzinfo=UTC)
    return (p.first_posted or p.first_seen or earliest, p.first_seen or earliest, p.id)


# --------------------------------------------------------------------------- #
# Database half.
# --------------------------------------------------------------------------- #


def text_classes(
    hashes: Iterable[str],
    same: Callable[[str, str], bool],
    conflict: Callable[[str, str], bool] | None = None,
) -> dict[str, str]:
    """Each md5 to its class key, the smallest md5 of the class. Pure.

    Two md5s share a class when `same` says so of them or of a chain between
    them, unless the merge would put together two md5s that `conflict` says
    are different openings: two texts asking 7+ and 5+ years of management
    can each match a third template, and the chain would make them one role.
    Chains stay because they are mostly right; a hard conflict anywhere across
    the two classes refuses the merge. A single
    md5 is its own class, so `same` is never asked of it."""
    ordered = sorted(set(hashes))
    members: dict[str, list[str]] = {h: [h] for h in ordered}
    parent = {h: h for h in ordered}

    def root(h: str) -> str:
        while parent[h] != h:
            h = parent[h]
        return h

    for i, left in enumerate(ordered):
        for right in ordered[i + 1:]:
            a, b = root(left), root(right)
            if a == b or not same(left, right):
                continue
            if conflict is not None and any(conflict(x, y) for x in members[a] for y in members[b]):
                continue
            keep, gone = min(a, b), max(a, b)
            parent[gone] = keep
            members[keep] += members.pop(gone)
    return {h: root(h) for h in ordered}


def _rowcount(result: Any) -> int:
    """Rows a DML statement touched (`execute` is typed as returning a bare Result)."""
    return int(cast(CursorResult, result).rowcount)


def _company_clause(alias: str, companies: set[str] | None) -> str:
    return f" AND {alias}.company = ANY(:companies)" if companies is not None else ""


_POSTINGS_SQL = f"""
    WITH t AS (
        SELECT j.id, j.company, j.title, j.locations, j.location_cities,
               j.family, j.level_band, j.first_seen, j.first_posted_at,
               j.source_facts->>'requisition_label' AS employer_label,
               j.source_facts->>'source_job_id' AS employer_job,
               (SELECT l->>'label'
                  FROM jsonb_array_elements(
                         CASE jsonb_typeof(j.source_facts->'locations')
                              WHEN 'array' THEN j.source_facts->'locations'
                              ELSE '[]'::jsonb END) l
                 WHERE (l->>'is_primary')::boolean
                 LIMIT 1) AS primary_place,
               {TEXT_HASH_SQL} AS text_hash
          FROM jobs j
         WHERE j.description_text IS NOT NULL
           AND length(j.description_text) > :min_chars
           AND {{rows}}
    )
    SELECT t.* FROM t
"""


@dataclass
class PlaceSetReads:
    """The rule's costly reads of each company, kept for one detection run so
    every candidate of a company reuses them: its open postings with their
    text hashes, its passage recurrence, the representatives' texts, and the
    answer for each pair of texts compared.

    Valid only while nothing writes what it holds (a posting's text, places,
    title, family, level or status). The lineage detector writes its own links
    and stamps only, so one pass shares one, and drops it when the pass ends.
    A person's verdicts and splits are not held: every call reads them afresh.
    """

    open_postings: dict[str, list[Posting]] = field(default_factory=dict)
    recurrence: dict[str, Counter[str]] = field(default_factory=dict)
    texts: dict[int, tuple[str | None, list[dict] | None]] = field(default_factory=dict)
    #: (representative id, representative id) to "place", "explained" or None.
    same: dict[tuple[int, int], str | None] = field(default_factory=dict)
    conflicts: dict[tuple[int, int], bool] = field(default_factory=dict)


def _posting(r: Any) -> Posting:
    return Posting(
        id=r.id,
        company=r.company,
        title=r.title or "",
        locations=tuple(r.locations or ()),
        cities=tuple(r.location_cities or ()),
        text_hash=r.text_hash,
        family=r.family,
        level_band=r.level_band,
        first_seen=r.first_seen,
        employer_label=r.employer_label,
        employer_job=r.employer_job,
        primary=r.primary_place,
        first_posted=r.first_posted_at,
    )


async def _read(session: AsyncSession, rows: str, params: dict) -> list[Posting]:
    """The postings of `rows` that have a text longer than a stub, each with
    the md5 of its folded text."""
    params = {**params, "min_chars": get_settings().place_set_min_text_chars}
    return [
        _posting(r)
        for r in (await session.execute(text(_POSTINGS_SQL.format(rows=rows)), params)).all()
    ]


def _same_way(a: Posting, b: Posting, reads: PlaceSetReads) -> str | None:
    """How two representatives' texts are one role's text, or None."""
    (a_text, a_sections), (b_text, b_sections) = (
        reads.texts.get(a.id, (None, None)),
        reads.texts.get(b.id, (None, None)),
    )
    if differs_only_by_place(a_text, a.locations, b_text, b.locations):
        return "place"
    counts = reads.recurrence.get(a.company, Counter())
    if differs_by_explained_passages(
        a_sections, a_text, a.locations, b_sections, b_text, b.locations,
        counts.__getitem__,
    ):
        return "explained"
    return None


async def _classed(
    session: AsyncSession,
    found: Iterable[Posting],
    *,
    asked: set[int] | None = None,
    reads: PlaceSetReads | None = None,
) -> list[Posting]:
    """Postings of `found` that share a normalized title with another of their
    company, each `text_hash` set to its text class; with `asked`, only the
    titles that hold an asked posting.

    A text class is the texts of one title that are one role's text: they
    differ only by where the role is (`place_text.differs_only_by_place`), or
    every passage only one side has is explained (local pay, benefits, legal
    text, a location line, the company's own boilerplate) with at most a few
    other words changed (`explained_text.differs_by_explained_passages`). Its
    key is the smallest member md5, so it is the md5 itself when the class
    holds one text, and the stored set identity `(company, title, text_hash)`
    stays one row per role. Only titles holding two texts read text, one
    posting per md5; boilerplate is counted over those companies' postings.

    A title's classes depend only on its own postings, so leaving out the
    titles no asked posting holds changes no class of the ones kept."""
    reads = reads if reads is not None else PlaceSetReads()
    by_title: dict[tuple[str, str], list[Posting]] = defaultdict(list)
    # The representative of a text is its lowest id, so the classes do not
    # depend on the order the rows were read in.
    for posting in sorted(found, key=lambda p: p.id):
        title = normalize_title(posting.title, posting.locations)
        if title:
            by_title[(posting.company, title)].append(posting)
    groups = [
        members
        for members in by_title.values()
        if len(members) > 1 and (asked is None or any(p.id in asked for p in members))
    ]

    reps: dict[tuple[int, str], Posting] = {}
    for n, members in enumerate(groups):
        if len({p.text_hash for p in members}) > 1:
            for p in members:
                reps.setdefault((n, p.text_hash), p)
    if reps:
        unread = sorted({p.id for p in reps.values()} - reads.texts.keys())
        if unread:
            rows_read = await session.execute(
                text(
                    "SELECT id, description_text, description_sections FROM jobs "
                    "WHERE id = ANY(cast(:ids AS integer[]))"
                ),
                {"ids": unread},
            )
            reads.texts.update(
                {r.id: (r.description_text, r.description_sections) for r in rows_read.all()}
            )
        uncounted = {p.company for p in reps.values()} - reads.recurrence.keys()
        if uncounted:
            counted = await _passage_recurrence(session, uncounted)
            reads.recurrence.update({c: counted.get(c, Counter()) for c in uncounted})

    out: list[Posting] = []
    for n, members in enumerate(groups):
        how: dict[frozenset[str], str] = {}

        def same(left: str, right: str, n: int = n, how: dict = how) -> bool:
            a, b = reps[(n, left)], reps[(n, right)]
            pair = (a.id, b.id)
            if pair not in reads.same:
                reads.same[pair] = _same_way(a, b, reads)
            way = reads.same[pair]
            if way is None:
                return False
            how[frozenset((left, right))] = way
            return True

        def conflict(left: str, right: str, n: int = n) -> bool:
            a, b = reps[(n, left)], reps[(n, right)]
            pair = (a.id, b.id)
            if pair not in reads.conflicts:
                reads.conflicts[pair] = requirements_conflict(
                    reads.texts.get(a.id, (None,))[0], reads.texts.get(b.id, (None,))[0]
                )
            return reads.conflicts[pair]

        classes = text_classes({p.text_hash for p in members}, same, conflict)
        sizes = Counter(classes.values())
        explained = {
            classes[h] for pair, way in how.items() if way == "explained" for h in pair
        }
        for p in members:
            key = classes[p.text_hash]
            match = "exact" if sizes[key] == 1 else "explained" if key in explained else "place"
            out.append(replace(p, text_hash=key, text_match=match))
    return out


async def _passage_recurrence(session: AsyncSession, companies: set[str]) -> dict[str, Counter[str]]:
    """For each company, how many of its postings hold each passage: what
    `explained_text` calls the company's boilerplate. Every posting
    with a text counts, open or closed: a benefits block is the company's
    whether or not the postings that carry it are still listed."""
    found: dict[str, Counter[str]] = defaultdict(Counter)
    rows = await session.execute(
        text(
            "SELECT company, description_text, description_sections FROM jobs "
            "WHERE company = ANY(:companies) AND description_text IS NOT NULL"
        ),
        {"companies": sorted(companies)},
    )
    for r in rows.all():
        found[r.company].update(
            {passage_key(p)[1] for p in passages_of(r.description_sections, r.description_text)}
        )
    return found


async def load_postings(
    session: AsyncSession, *, companies: set[str] | None = None
) -> list[Posting]:
    """Open postings that share a title with another open posting of their
    company, each with its text class (`_classed`)."""
    params: dict = {}
    if companies is not None:
        params["companies"] = sorted(companies)
    return await _classed(
        session, await _read(session, "j.status = 'open'" + _company_clause("j", companies), params)
    )


async def _open_postings(
    session: AsyncSession, companies: set[str], reads: PlaceSetReads
) -> list[Posting]:
    """The open postings of `companies`, each company read once per `reads`."""
    unread = companies - reads.open_postings.keys()
    if unread:
        for company in unread:
            reads.open_postings[company] = []
        for posting in await _read(
            session, "j.status = 'open' AND j.company = ANY(:companies)", {"companies": sorted(unread)}
        ):
            reads.open_postings[posting.company].append(posting)
    return [p for company in sorted(companies) for p in reads.open_postings[company]]


async def still_listed_elsewhere(
    session: AsyncSession,
    job_ids: Iterable[int],
    *,
    companies: set[str] | None = None,
    reads: PlaceSetReads | None = None,
) -> dict[int, list[Posting]]:
    """For each posting (closed, as a rule), the open postings it would form a
    place set with now, earliest first; postings with none are left out.

    A tracked posting's closing is read after the run's post passes, when the
    rebuild has already dropped it from its set (sets hold open postings), so
    the stored set cannot answer. The rule can: the posting with the open
    postings sharing its text, under the same verdicts. The lineage
    detector asks it too, for a pair with a closed side, once per candidate,
    and passes one `reads` for its whole pass so a company's postings, texts
    and pairs are read and compared once; `companies` bounds the read to the
    companies the ids belong to, and defaults to exactly those.
    """
    ids = sorted(set(job_ids))
    if not ids:
        return {}
    if companies is None:
        # A set never spans two companies: only the asked postings' own can
        # hold one of theirs.
        companies = set(
            (
                await session.scalars(
                    text("SELECT DISTINCT company FROM jobs WHERE id = ANY(cast(:ids AS integer[]))"),
                    {"ids": ids},
                )
            ).all()
        )
    reads = reads if reads is not None else PlaceSetReads()
    rows = {p.id: p for p in await _open_postings(session, companies, reads)}
    # The asked postings are read now whatever their status, so one that
    # closed or reopened since the open postings were read is still asked.
    rows.update(
        (p.id, p)
        for p in await _read(
            session,
            "j.id = ANY(cast(:ids AS integer[])) AND j.company = ANY(:companies)",
            {"ids": ids, "companies": sorted(companies)},
        )
    )
    loaded = await _classed(session, rows.values(), asked=set(ids), reads=reads)
    wanted = {
        (p.company, normalize_title(p.title, p.locations), p.text_hash) for p in loaded if p.id in ids
    }
    postings = [
        p for p in loaded if (p.company, normalize_title(p.title, p.locations), p.text_hash) in wanted
    ]
    candidates = [p.id for p in postings]
    sets, _ = form_place_sets(
        postings,
        decided_pairs=await _decided_pairs(session, candidates),
        rejected=await _rejected_ids(session, candidates),
    )
    by_id = {p.id: p for p in postings}
    found: dict[int, list[Posting]] = {}
    for place_set in sets:
        for job_id in set(place_set.member_ids) & set(ids):
            # Two closed postings in one group are not each other's elsewhere.
            others = [m for m in place_set.member_ids if m not in ids]
            if others:
                found[job_id] = [by_id[m] for m in others]
    return found


async def _decided_pairs(session: AsyncSession, ids: list[int]) -> set[frozenset[int]]:
    if not ids:
        return set()
    rows = (
        await session.execute(
            text(
                """
                SELECT job_id AS a, prior_job_id AS b FROM job_lineage_link
                 WHERE status IN ('confirmed', 'rejected')
                   AND job_id = ANY(cast(:ids AS integer[])) AND prior_job_id = ANY(cast(:ids AS integer[]))
                UNION
                SELECT job_a_id, job_b_id FROM job_twin_link
                 WHERE status IN ('confirmed', 'rejected')
                   AND job_a_id = ANY(cast(:ids AS integer[])) AND job_b_id = ANY(cast(:ids AS integer[]))
                """
            ),
            {"ids": ids},
        )
    ).all()
    return {frozenset((r.a, r.b)) for r in rows}


async def _rejected_ids(session: AsyncSession, ids: list[int]) -> set[int]:
    if not ids:
        return set()
    return set(
        (
            await session.scalars(
                text(
                    "SELECT job_id FROM job_place_set_member "
                    "WHERE status = 'rejected' AND job_id = ANY(cast(:ids AS integer[]))"
                ),
                {"ids": ids},
            )
        ).all()
    )


async def rebuild_place_sets(
    session: AsyncSession, *, companies: set[str] | None = None, commit: bool = True
) -> dict:
    """Recompute every place set (or one company's) from the stored postings.

    Idempotent. Writes only `auto` memberships, never a person's `rejected`
    one, and withdraws pending machine proposals between members of one set.

    Takes `LINEAGE_LOCK_KEY` before it reads a decision: the
    rejections and decided pairs it groups by, and the relationship rows it
    withdraws, are what the verdict commands and the place-set review write
    under the same lock, so a decision is either read here or made after this
    commits; never committed between the read and the write it would change.
    One lock taken first by every writer is also one lock order: the twin
    verdict's twin-then-lineage row order cannot meet this pass's
    lineage-then-twin deletes.
    """
    await advisory_xact_lock(session, LINEAGE_LOCK_KEY)
    postings = await load_postings(session, companies=companies)
    ids = [p.id for p in postings]
    sets, skipped = form_place_sets(
        postings,
        decided_pairs=await _decided_pairs(session, ids),
        rejected=await _rejected_ids(session, ids),
    )

    member_rows: list[dict] = []
    for place_set in sets:
        # An unchanged set is not rewritten, so `updated_at` moves only when
        # the set does; the upsert then returns nothing and the second branch
        # reads the standing row's id.
        set_id = (
            await session.execute(
                text(
                    """
                    WITH written AS (
                        INSERT INTO job_place_set
                            (company, title, text_hash, size, places, rule_version, evidence)
                        VALUES (:company, :title, :text_hash, :size, :places, :rv,
                                cast(:evidence AS jsonb))
                        ON CONFLICT (company, title, text_hash) DO UPDATE
                           SET size = EXCLUDED.size,
                               places = EXCLUDED.places,
                               rule_version = EXCLUDED.rule_version,
                               evidence = EXCLUDED.evidence,
                               updated_at = now()
                         WHERE (job_place_set.size, job_place_set.places,
                                job_place_set.rule_version, job_place_set.evidence)
                               IS DISTINCT FROM
                               (EXCLUDED.size, EXCLUDED.places,
                                EXCLUDED.rule_version, EXCLUDED.evidence)
                        RETURNING id
                    )
                    SELECT id FROM written
                    UNION ALL
                    SELECT id FROM job_place_set
                     WHERE company = :company AND title = :title AND text_hash = :text_hash
                       AND NOT EXISTS (SELECT 1 FROM written)
                    """
                ),
                {
                    "company": place_set.company,
                    "title": place_set.title,
                    "text_hash": place_set.text_hash,
                    "size": len(place_set.member_ids),
                    "places": list(place_set.places),
                    "rv": RULE_VERSION,
                    "evidence": json.dumps(place_set.evidence),
                },
            )
        ).scalar_one()
        member_rows.extend(
            {
                "job_id": job_id,
                "set_id": set_id,
                "evidence": json.dumps(
                    {
                        "rule": RULE_VERSION,
                        "relation": place_set.relations.get(job_id, "place"),
                        "place_key": place_set.place_keys.get(job_id),
                    }
                ),
            }
            for job_id in place_set.member_ids
        )
    kept_members = [row["job_id"] for row in member_rows]
    if member_rows:
        # A person's `rejected` row is never overwritten: the WHERE makes the
        # upsert a no-op on it (it cannot be a candidate anyway), as it does
        # on a membership that is already what the rule says.
        await session.execute(
            text(
                """
                INSERT INTO job_place_set_member (job_id, set_id, status, evidence)
                VALUES (:job_id, :set_id, 'auto', cast(:evidence AS jsonb))
                ON CONFLICT (job_id) DO UPDATE
                   SET set_id = EXCLUDED.set_id, evidence = EXCLUDED.evidence
                 WHERE job_place_set_member.status = 'auto'
                   AND (job_place_set_member.set_id, job_place_set_member.evidence)
                       IS DISTINCT FROM (EXCLUDED.set_id, EXCLUDED.evidence)
                """
            ),
            member_rows,
        )

    scope = (
        " AND set_id IN (SELECT id FROM job_place_set WHERE company = ANY(:companies))"
        if companies is not None
        else ""
    )
    params: dict = {"kept": kept_members}
    if companies is not None:
        params["companies"] = sorted(companies)
    dropped = _rowcount(
        await session.execute(
            text(
                "DELETE FROM job_place_set_member WHERE status = 'auto' "
                f"AND NOT (job_id = ANY(cast(:kept AS integer[]))){scope}"
            ),
            params,
        )
    )
    emptied = _rowcount(
        await session.execute(
            text(
                "DELETE FROM job_place_set s WHERE NOT EXISTS ("
                "SELECT 1 FROM job_place_set_member m WHERE m.set_id = s.id AND m.status = 'auto')"
                + (" AND s.company = ANY(:companies)" if companies is not None else "")
            ),
            {"companies": sorted(companies)} if companies is not None else {},
        )
    )
    withdrawn_lineage = _rowcount(
        await session.execute(
            text(
                f"""
                DELETE FROM job_lineage_link l
                 USING job_place_set_member a, job_place_set_member b
                 WHERE l.status = 'pending' AND l.confidence = 'suspected'
                   AND NOT {holds_history_sql("l.evidence")}
                   AND a.job_id = l.job_id AND b.job_id = l.prior_job_id
                   AND a.status = 'auto' AND b.status = 'auto' AND a.set_id = b.set_id
                """
            )
        )
    )
    withdrawn_twins = _rowcount(
        await session.execute(
            text(
                f"""
                DELETE FROM job_twin_link t
                 USING job_place_set_member a, job_place_set_member b
                 WHERE t.status = 'pending'
                   AND NOT {holds_history_sql("t.evidence")}
                   AND a.job_id = t.job_a_id AND b.job_id = t.job_b_id
                   AND a.status = 'auto' AND b.status = 'auto' AND a.set_id = b.set_id
                """
            )
        )
    )
    if commit:
        await session.commit()

    by_reason: dict[str, int] = defaultdict(int)
    for skip in skipped:
        by_reason[skip.reason] += 1
    return {
        "sets": len(sets),
        "members": len(kept_members),
        "memberships_dropped": dropped,
        "sets_dropped": emptied,
        "skipped": dict(by_reason),
        "withdrawn_lineage": withdrawn_lineage,
        "withdrawn_twins": withdrawn_twins,
    }


# --------------------------------------------------------------------------- #
# Reads and the person's override.
# --------------------------------------------------------------------------- #


async def place_set_of(session: AsyncSession, job_id: int) -> dict:
    """The posting's set and its other members, or `None` with whether a
    person split it out (`rejected`)."""
    row = (
        await session.execute(
            text(
                "SELECT set_id, status, reviewed_at FROM job_place_set_member WHERE job_id = :id"
            ),
            {"id": job_id},
        )
    ).first()
    if row is None or row.status != "auto" or row.set_id is None:
        return {
            "job_id": job_id,
            "set": None,
            "rejected": row is not None and row.status == "rejected",
            "rejected_at": row.reviewed_at if row is not None and row.status == "rejected" else None,
        }
    place_set = (
        await session.execute(
            text(
                "SELECT id, company, title, size, places, rule_version, evidence "
                "FROM job_place_set WHERE id = :id"
            ),
            {"id": row.set_id},
        )
    ).one()
    member_rows = (
        await session.execute(
            text(
                "SELECT m.job_id, coalesce(m.evidence->>'relation', 'place') AS relation, "
                "m.evidence->>'place_key' AS place_key "
                "FROM job_place_set_member m JOIN jobs j ON j.id = m.job_id "
                "WHERE m.set_id = :sid AND m.status = 'auto' ORDER BY j.first_seen, j.id"
            ),
            {"sid": row.set_id},
        )
    ).all()
    member_ids = [r.job_id for r in member_rows]
    return {
        "job_id": job_id,
        "set": {
            "id": place_set.id,
            "size": place_set.size,
            "places": list(place_set.places or []),
            "rule_version": place_set.rule_version,
            "employer_label": (place_set.evidence or {}).get("employer_label"),
            "member_ids": member_ids,
            # `place` or `relisted` per member; a row from an older rule
            # version carries none and holds its place.
            "relations": {r.job_id: r.relation for r in member_rows},
            "place_keys": {r.job_id: r.place_key for r in member_rows},
        },
        "rejected": False,
        "rejected_at": None,
    }


class NotAMember(LookupError):
    """The verdict names a posting that is not in the state it needs."""


async def review_place_set_member(
    session: AsyncSession, job_id: int, decision: Literal["different", "pending"]
) -> dict:
    """A person's word on one posting: `different` splits it out of its set,
    `pending` takes that back. The company's sets are rebuilt in the same
    transaction, so the answer is the state the person will see. Under
    `LINEAGE_LOCK_KEY` from before its read, like every writer of
    a relationship decision."""
    await advisory_xact_lock(session, LINEAGE_LOCK_KEY)
    row = (
        await session.execute(
            text(
                "SELECT m.set_id, m.status, j.company FROM job_place_set_member m "
                "JOIN jobs j ON j.id = m.job_id WHERE m.job_id = :id"
            ),
            {"id": job_id},
        )
    ).first()
    if decision == "different":
        if row is None or row.status != "auto":
            raise NotAMember("this posting is not listed with other places")
        await session.execute(
            text(
                """
                UPDATE job_place_set_member
                   SET status = 'rejected', reviewed_at = now(),
                       evidence = evidence || cast(:evidence AS jsonb)
                 WHERE job_id = :id
                """
            ),
            {
                "id": job_id,
                "evidence": json.dumps({"review_outcome": "different", "set_id": row.set_id}),
            },
        )
    else:
        if row is None or row.status != "rejected":
            raise NotAMember("no verdict to take back on this posting")
        await session.execute(
            text("DELETE FROM job_place_set_member WHERE job_id = :id AND status = 'rejected'"),
            {"id": job_id},
        )
    await rebuild_place_sets(session, companies={row.company}, commit=False)
    await session.commit()
    return await place_set_of(session, job_id)
