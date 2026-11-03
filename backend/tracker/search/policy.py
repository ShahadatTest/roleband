"""Pure search policy: identity, role-shape conflict, admission, classification.

Search result membership must mean *evidence of a match*. Ranking orders admitted
rows; ranking never manufactures membership. This module owns every decision that
can be made without a database or a model — the deterministic half —
so the SQL layer (`search/retrieval.py`) and the router stay orchestration.

Three claims, deliberately different:

- `exact`   — identifier equality, or conservative normalized title equality.
- `close`   — same role shape and compatible mission.
- `related` — useful adjacency, but role shape or mission differs.

The load-bearing rule is that **one material word cannot be erased by
similarity**. `Applied Science Manager` != `Product Manager`;
`Engineering Manager` != `Engineer`; `Product Manager` != `Program Manager`.
Cosine ranks every embedded row and never says "no", so a semantic score may
support a class but may never establish one and may never clear a conflict.

No second taxonomy: family/track/domain/title vocabulary is imported from
`taxonomy/*` and `enrich/track.py`. Nothing here reads `tracker.api`.

Thresholds are UNCALIBRATED. The frozen retrieval eval, split-fit and verified on
the held-out half (`scripts/calibrate_search_thresholds.py`), owns the numbers;
`SEARCH_POLICY_VERSION` says so until it does. The defaults below separate the
frozen fixture's labelled `close`/`related` boundary: that is fitting, not
calibration, and it is why every threshold the eval has not measured is `None`
and fails **closed**: an unmeasured gate can only withhold `close`, never grant it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from tracker.enrich.track import classify_track
from tracker.platform.util import normalize_text
from tracker.schema import LevelBand
from tracker.search.parse import LEVEL_SYNONYMS, ParsedQuery, parse_query
from tracker.taxonomy.domains import match_domains
from tracker.taxonomy.roles import classify_role
from tracker.taxonomy.title_parse import names_a_role, org_path, title_head

# Model + eval identity of the constants below. The last segment becomes the
# eval version once thresholds are fit on one fixture half and held on the other;
# until then it must read `uncalibrated` so nothing downstream can mistake a
# fitted default for a measured floor.
SEARCH_POLICY_VERSION = "search/v2/lightonai-DenseOn-768/uncalibrated"


class MatchClass(str, Enum):
    """Qualitative claim about an admitted row. Never a score."""

    EXACT = "exact"
    CLOSE = "close"
    RELATED = "related"


QueryKind = Literal["identifier", "exact_title", "exploratory"]


class CandidateSource(str, Enum):
    """Why a row is a candidate. Mirrors the router's `matched_via` vocabulary."""

    EXACT = "exact"
    KEYWORD = "keyword"
    FUZZY = "fuzzy"
    SEMANTIC = "semantic"


#: Sources that are *counter-evidence-bearing*: the user's own words appear in
#: the row. A hard conflict demotes such a row to `related` rather than removing
#: it, because deleting a lexical hit hides a row the user literally asked for.
#: Semantic support carries no such claim.
TEXTUAL_SOURCES = frozenset({CandidateSource.KEYWORD.value, CandidateSource.FUZZY.value})


class ConflictKind(str, Enum):
    """A material difference. Any one of these blocks `close`."""

    FAMILY = "family"
    TRACK = "track"
    EXPLICIT_LEVEL = "explicit_level"
    DOMAIN = "domain"
    ORG_PATH = "org_path"


@dataclass(frozen=True)
class SearchThresholds:
    """Policy constants, tied to embedding model + artifact tier. No Settings UI.

    `None` means *not measured yet* and is read as fail-closed everywhere: a
    supporting-score gate of `None` simply does not fire, so the row falls to
    `related`.
    """

    #: Explicit pg_trgm floor for the fuzzy source. Binds the match set in SQL so
    #: the session `pg_trgm.similarity_threshold` GUC stops deciding it; `%`
    #: stays alongside as the index probe.
    trgm_min: float = 0.30

    #: Role-head agreement required for `close`, as the overlap coefficient over
    #: head tokens with level words removed (level is its own axis and is neutral
    #: when the query is silent).
    #:
    #: An overlap coefficient, not Jaccard. Queries are terse and stored heads are verbose, so Jaccard
    #: punishes a query for being short: `Program Manager` inside `Commercial
    #: Operations Program Manager` scores 0.50 by Jaccard and 1.00 by overlap,
    #: and the fixture labels it `close`. Same argument as `org_overlap`.
    #: Discrimination is preserved where it matters — `Product Manager` vs
    #: `Program Manager` is 0.50 either way, and `Engineering Manager` vs
    #: `Engineer` shares no token at all.
    head_overlap_close_min: float = 0.6

    #: Cosine that can carry `close` on its own, for a query that names no role
    #: in words the corpus uses ("keep bad actors from misusing our product").
    #: Neither token overlap nor trigram can reach those. No value separates
    #: the classes on the shipped representation; a number here only becomes
    #: meaningful with a new representation. NOT PLUMBED: the
    #: router never passes `semantic_similarity` into `CandidateEvidence`, so
    #: setting this alone changes nothing — wiring the score through is part of
    #: any calibration change.
    semantic_close_min: float | None = None

    #: Title trigram similarity that can clear the head gate on its own. Token
    #: overlap collapses on typos by construction ("enginering" shares no token
    #: with "engineering"), so a misspelled query reaches `close` only through a
    #: measured trigram score. No value separates the classes on the frozen
    #: fixture. NOT PLUMBED: the router never passes
    #: `title_similarity` into `CandidateEvidence`, so setting this alone
    #: changes nothing — wiring the trgm CTE's score through is part of any
    #: calibration change.
    trgm_close_min: float | None = None

    #: Mission agreement between two informative org paths, as the overlap
    #: coefficient |A n B| / min(|A|, |B|). A count rule ("share >= 1 token") was
    #: too weak on the frozen fixture: `Agent Runtime Platform` vs `Agent
    #: Prompts & Evals` share "agent", and `Streaming Platform` vs `Agent Runtime
    #: Platform` share "platform" — one generic word each, both scoring 0.33,
    #: both labelled a different mission. The Prime Video close pair scores 0.5.
    org_overlap_close_min: float = 0.5


DEFAULT_THRESHOLDS = SearchThresholds()


# --------------------------------------------------------------------------- #
# Conservative exact-title key
# --------------------------------------------------------------------------- #

# Trailing damage sources leave on a title. Deliberately narrow: `+` and `#` are
# never stripped, so `C++` and `C#` survive, and `/` is kept because `AI/ML` ends
# a title in the corpus.
_TRAILING_DAMAGE = " \t ,;:|"


def fold_query(text: str) -> str:
    """The typed query, Unicode compatibility forms folded (NFKC): full-width
    letters, mathematical bold or sans, ligatures, to the letters the stored
    text and its indexes hold. Applied once where a query enters a search
    (Best match, the Board's lexical filter, the agent's phrase), before the
    identity probes and every textual source, so the trigram prefilter, the
    lexical and the fuzzy sources all see what `exact_title_key` compares
    ("ｓｅｎｉｏｒ ｐｒｏｄｕｃｔ ｍａｎａｇｅｒ" would otherwise score 0.000
    and find nothing). Case and spacing are left alone: the sources own those."""
    return unicodedata.normalize("NFKC", text)


def exact_title_key(title: str | None) -> str:
    """Normalized title key whose equality is an *identity* claim.

    Allowed, because each is provably cosmetic: Unicode canonical composition,
    exotic-space folding, lower-casing, whitespace collapse, surrounding-
    whitespace and trailing-separator trim, dash codepoint folding — all
    delegated to `platform.util.normalize_text`, the ONE symmetric normalizer
    every text comparison in the product shares. Only the trailing-separator
    strip is search-specific.

    Forbidden, because each can delete a load-bearing word: stemming, token
    sorting, stop-word deletion, synonym expansion, level-token deletion, broad
    punctuation deletion. `lineage.normalize.title_key` is NOT reused — it
    deliberately removes level tokens, which makes a different claim
    (match-grade equality), and `Senior X` is not `Principal X`.

    Interior separator damage (`Manager , Team`) is deliberately NOT repaired:
    it is not on the allowed list, and a missed exact degrades to `close`, the
    safe direction.
    """
    return normalize_text(title).strip(_TRAILING_DAMAGE).strip()


# --------------------------------------------------------------------------- #
# Identifier probes
# --------------------------------------------------------------------------- #

# Generic tracking parameters only. No provider-specific URL parser and no
# wildcard beyond `utm_*`: `gh_jid` IS the greenhouse job id, so a broad prefix
# rule would delete identity rather than noise.
_TRACKING_PARAMS = frozenset(
    {
        "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "igshid", "ttclid",
        "gh_src", "lever-source", "lever-origin", "trk", "trackingid",
        "ref", "referrer", "source", "src", "campaign",
    }
)

_URLISH = re.compile(r"^(?:https?://|www\.)", re.I)
# A bare identifier: one whitespace-free token carrying at least one digit. The
# equality itself happens in SQL; this only decides whether to *try* it.
_REQ_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]{2,63}$")


def identity_url_key(raw: str | None) -> str | None:
    """Canonical URL for identity comparison, or None when the text is not a URL.

    Removes the fragment and known tracking parameters; lower-cases scheme and
    host; drops a default port and one trailing slash. The path keeps its case —
    paths are case-sensitive and a stored URL is compared byte-for-byte after
    this same treatment.
    """
    text = (raw or "").strip()
    if not text or not _URLISH.match(text):
        return None
    if text.lower().startswith("www."):
        text = f"https://{text}"
    try:
        # urlsplit itself is lazy: `.port` (and `.hostname` for some inputs) is
        # where a malformed netloc actually raises — "http://a.com:abc/x" parses
        # fine and then blows up here. Everything that can raise stays inside
        # this block, because a garbage paste must read as "not a URL", never as
        # a 500 on the search endpoint.
        parts = urlsplit(text)
        hostname = parts.hostname
        port = parts.port
    except ValueError:
        return None
    if not parts.netloc:
        return None

    host = hostname or ""
    if host.startswith("www."):
        host = host[4:]
    if port and port not in (80, 443):
        host = f"{host}:{port}"

    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")]
    # Sorted: query-parameter order is not part of a URL's identity, and a pasted
    # link routinely reorders what the stored one recorded.
    query = urlencode(sorted(kept))

    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), host, path, query, ""))


def req_id_probe(raw: str | None) -> str | None:
    """The query read as a complete requisition id, or None.

    Conservative: a single token with a digit in it. Partial ids are never
    probed: identifier equality must never fuzzy-match a different req, and the
    SQL side compares for equality, not prefix.
    """
    text = (raw or "").strip()
    if not text or any(ch.isspace() for ch in text):
        return None
    if not _REQ_ID.match(text) or not any(ch.isdigit() for ch in text):
        return None
    return text


@dataclass(frozen=True)
class IdentityProbe:
    """What an identity lookup should try, derived purely from the query text.

    The lookup itself runs under **explicit request filters only**: a parsed
    filter is advisory and may be wrong, and it must never hide an exact
    title/URL/req match.
    """

    url_key: str | None
    req_id: str | None
    title_key: str

    def is_identifier(self) -> bool:
        return self.url_key is not None or self.req_id is not None


def identity_probe(raw: str) -> IdentityProbe:
    """Identity candidates for a raw query string."""
    return IdentityProbe(
        url_key=identity_url_key(raw),
        req_id=req_id_probe(raw),
        title_key=exact_title_key(raw),
    )


def resolve_query_kind(*, has_identifier_match: bool, has_exact_title_match: bool) -> QueryKind:
    """Query kind from *resolved evidence*: identifier, exact title, exploratory.

    Both inputs are answers from the database under explicit filters, not
    guesses about the text: a query that merely *looks* like a req id but
    matches no row is exploratory, so a typo cannot strand the user on an empty
    identifier page.
    """
    if has_identifier_match:
        return "identifier"
    if has_exact_title_match:
        return "exact_title"
    return "exploratory"


# --------------------------------------------------------------------------- #
# Title signature
# --------------------------------------------------------------------------- #

# Grammar, not vocabulary: connectives carry no role information and would
# otherwise inflate every head/org overlap.
_CONNECTIVES = frozenset({"a", "an", "and", "at", "for", "in", "of", "on", "the", "to", "with"})

# Level words, taken from the canonical query-parser table so the two surfaces
# cannot drift. Removed before head comparison because level is its own axis:
# `Senior Engineering Manager` and `Engineering Manager` are the same role shape,
# and a query that names no level is neutral about it.
_LEVEL_TOKENS = frozenset(
    tok for phrase, _ in LEVEL_SYNONYMS for tok in re.split(r"[\s\-]+", phrase) if tok
) | {"i", "ii", "iii", "iv"}

_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#]*")


def _tokens(text: str, *, drop: frozenset[str] = frozenset()) -> frozenset[str]:
    """Informative lowercase tokens, minus connectives and anything in `drop`."""
    found = _TOKEN.findall((text or "").casefold())
    return frozenset(t for t in found if t not in _CONNECTIVES and t not in drop)


def _company_tokens(company: str | None) -> frozenset[str]:
    """Tokens of a company name — carried by every one of its org paths.

    Stripped from org tokens for the same reason `domains.source_category`
    ignores a company naming itself: `Amazon Robotics` and `Amazon Fulfillment`
    share only the word that says nothing, and company is already its own
    explicit filter axis.
    """
    return _tokens((company or "").replace("-", " "))


def explicit_level(band: str | None) -> str | None:
    """A level band only when the source actually stated one.

    `mid` is the corpus sentinel for *no seniority marker in the title*
    (`schema.LevelBand`), so reading it as an explicit level would turn every
    unmarked posting into a level conflict with every `Senior` query.
    """
    if band is None or band == LevelBand.MID.value:
        return None
    return band


@dataclass(frozen=True)
class TitleSignature:
    """Role shape + mission, as read from one title (query side or row side)."""

    family: str | None = None
    track: str | None = None
    explicit_level: str | None = None
    domains: frozenset[str] = frozenset()
    head: str = ""
    head_tokens: frozenset[str] = frozenset()
    org: str = ""
    org_tokens: frozenset[str] = frozenset()
    names_a_role: bool = False

    @property
    def org_is_informative(self) -> bool:
        """An empty org path is neutral, never a mission conflict."""
        return bool(self.org_tokens)


def query_signature(raw: str, parsed: ParsedQuery | None = None) -> TitleSignature:
    """Signature of the user's query.

    Reads the query as a title: `[role head], [org path]`. Family prefers the
    query parser's answer (the router has already computed it) and falls back to
    classifying the head alone, because the org path is not evidence about the
    role. Track is claimed only when the query actually names a role — otherwise
    "Prime Video" would assert a track it never mentioned.
    """
    # Only the family and the level are read below, so no company is needed.
    parsed = parsed if parsed is not None else parse_query(raw, companies={})
    head = title_head(raw)
    org = org_path(raw)

    family = parsed.family[0] if parsed.family else classify_role(head)
    track = classify_track(head, family).value if family else None
    level = explicit_level(parsed.level_band[0]) if parsed.level_band else None

    company_tokens = _company_tokens(" ".join(parsed.company))
    return TitleSignature(
        family=family,
        track=track,
        explicit_level=level,
        # Matched SEPARATELY and unioned, never on a concatenation: joining the
        # org path to the raw query invents phrases across the seam:
        # "Streaming Platform" + "Engineering Manager, Streaming Platform"
        # contains "Platform Engineering", which would tag a streaming query
        # `cloud_infra` and clear a domain conflict that should fire.
        domains=frozenset(match_domains(org)) | frozenset(match_domains(raw)),
        head=head,
        head_tokens=_tokens(head, drop=_LEVEL_TOKENS),
        org=org,
        org_tokens=_tokens(org, drop=company_tokens),
        # A role CLAIM, not a family: `classify_role` has no family for
        # "Staff Engineer" or "Analyst", yet those queries plainly name a role
        # and must be able to reach `close` on head agreement (the close gate's
        # route 1 reads this). The role-noun check keeps mission fragments
        # ("Prime Video") and the no-answer controls out.
        names_a_role=family is not None or names_a_role(head),
    )


def posting_signature(
    *,
    title: str,
    family: str | None,
    track: str | None,
    level_band: str | None,
    domains: list[str] | tuple[str, ...] | None = None,
    company: str | None = None,
) -> TitleSignature:
    """Signature of a stored row, from its persisted classification.

    The row's own `family`/`track`/`domains` are used as stored — they are the
    product's classification of record, produced by the ingestion pipeline over
    more evidence than a title (department/team fields included). Only the head
    and org path are re-derived, because those are positional facts about this
    string.
    """
    head = title_head(title)
    org = org_path(title)
    return TitleSignature(
        family=family,
        track=track,
        explicit_level=explicit_level(level_band),
        domains=frozenset(domains or ()),
        head=head,
        head_tokens=_tokens(head, drop=_LEVEL_TOKENS),
        org=org,
        org_tokens=_tokens(org, drop=_company_tokens(company)),
        names_a_role=family is not None,
    )


def material_conflicts(
    query: TitleSignature,
    candidate: TitleSignature,
    thresholds: SearchThresholds = DEFAULT_THRESHOLDS,
) -> tuple[ConflictKind, ...]:
    """Every material difference between two signatures, in declared order.

    Missing evidence is neutral throughout: a side that does not know its
    family, track, level, or org path contributes no conflict. Only a *stated
    and different* value is a conflict — that is what keeps an unclassified row
    from being silently guessed into a mismatch.
    """
    found: list[ConflictKind] = []

    if query.family and candidate.family and query.family != candidate.family:
        found.append(ConflictKind.FAMILY)
    if query.track and candidate.track and query.track != candidate.track:
        found.append(ConflictKind.TRACK)
    if (
        query.explicit_level
        and candidate.explicit_level
        and query.explicit_level != candidate.explicit_level
    ):
        found.append(ConflictKind.EXPLICIT_LEVEL)
    if query.domains and candidate.domains and not (query.domains & candidate.domains):
        found.append(ConflictKind.DOMAIN)
    if (
        query.org_is_informative
        and candidate.org_is_informative
        and org_overlap(query, candidate) < thresholds.org_overlap_close_min
    ):
        found.append(ConflictKind.ORG_PATH)

    return tuple(found)


def org_overlap(query: TitleSignature, candidate: TitleSignature) -> float:
    """Overlap coefficient over org-path tokens. 0.0 when either side is empty.

    Coefficient rather than Jaccard: org paths differ wildly in length, and a
    two-word mission fully contained in a six-word one is still the same
    mission. Jaccard would punish that for being terse.
    """
    if not query.org_tokens or not candidate.org_tokens:
        return 0.0
    shared = len(query.org_tokens & candidate.org_tokens)
    return shared / min(len(query.org_tokens), len(candidate.org_tokens))


def head_overlap(query: TitleSignature, candidate: TitleSignature) -> float:
    """Overlap coefficient over level-stripped head tokens.

    0.0 when either head is empty. See `SearchThresholds.head_overlap_close_min`
    for why this is a coefficient and not a Jaccard.
    """
    if not query.head_tokens or not candidate.head_tokens:
        return 0.0
    shared = len(query.head_tokens & candidate.head_tokens)
    return shared / min(len(query.head_tokens), len(candidate.head_tokens))


# --------------------------------------------------------------------------- #
# Admission + classification
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CandidateEvidence:
    """Everything known about one candidate row at decision time.

    Scores are *supporting* only. `semantic_similarity` never proves exact and
    never clears a conflict.
    """

    signature: TitleSignature
    sources: frozenset[str] = frozenset()
    title_similarity: float | None = None
    semantic_similarity: float | None = None

    @property
    def has_textual_support(self) -> bool:
        return bool(self.sources & TEXTUAL_SOURCES)


@dataclass(frozen=True)
class Decision:
    """Outcome for one candidate: admitted with a class, or rejected."""

    admitted: bool
    match_class: MatchClass | None
    conflicts: tuple[ConflictKind, ...] = ()
    reason: str = ""


def close_gates_pass(
    query: TitleSignature,
    evidence: CandidateEvidence,
    thresholds: SearchThresholds = DEFAULT_THRESHOLDS,
) -> bool:
    """Whether role-shape agreement is strong enough for `close`.

    Four routes, because each fails on inputs the others handle. Never called
    before conflicts are cleared: a supporting score cannot override a hard
    conflict.

    1. Head-token overlap: the ordinary case, and the only one that needs no
       calibration.
    2. Taxonomy agreement: query and candidate agree on a KNOWN family AND a
       known track. This is what lets an abbreviation work — `TPM` shares no
       token with `Technical Program Manager`, but the taxonomy already resolved
       it to the same family, and that is stronger role-shape evidence than a
       string overlap. It cannot fire for a query that names no role, so the
       no-answer controls are unaffected.
    3. Trigram: misspellings, where token overlap collapses by construction.
    4. Cosine: paraphrases that name the role in words the corpus never uses.

    Routes 3 and 4 are uncalibrated (`None`) and simply do not fire until the
    frozen eval measures them.
    """
    # Route 1 requires the query to actually NAME a role. A coefficient always
    # scores 1.0 for a single-token query that appears anywhere in the head, so
    # a bare mission fragment ("personalization") would otherwise read as close
    # to `Lead Personalization Product Manager` — a role it never mentioned.
    if query.names_a_role and head_overlap(query, evidence.signature) >= thresholds.head_overlap_close_min:
        return True
    # Route 2 is deliberately narrow: ONE token, so there is nothing to overlap
    # with and the taxonomy is the only evidence there is. Widening it to any
    # query would make every ml_ai_research manager close to every other:
    # `Applied Science Manager` vs `Research Manager, Interpretability`
    # share family and track and are still different jobs.
    if (
        len(query.head_tokens) == 1
        and query.family is not None
        and query.family == evidence.signature.family
        and query.track is not None
        and query.track == evidence.signature.track
    ):
        return True
    if (
        thresholds.trgm_close_min is not None
        and evidence.title_similarity is not None
        and evidence.title_similarity >= thresholds.trgm_close_min
    ):
        return True
    return (
        thresholds.semantic_close_min is not None
        and evidence.semantic_similarity is not None
        and evidence.semantic_similarity >= thresholds.semantic_close_min
    )


def classify_candidate(
    query: TitleSignature,
    evidence: CandidateEvidence,
    thresholds: SearchThresholds = DEFAULT_THRESHOLDS,
) -> Decision:
    """Admit and classify one candidate. The decision tree, in order.

    Not a weighted label: every branch names the evidence that decided it, so a
    surprising class is traceable to a field rather than to a score.
    """
    if CandidateSource.EXACT.value in evidence.sources:
        return Decision(True, MatchClass.EXACT, (), "identifier or exact title key equal")

    conflicts = material_conflicts(query, evidence.signature, thresholds)

    if conflicts:
        named = "/".join(c.value for c in conflicts)
        if evidence.has_textual_support:
            # The user's own words are in this row. Demote, never delete — a
            # Product Manager on the exact team the query named is a real answer
            # to "what else is on this team", just not a close one.
            return Decision(True, MatchClass.RELATED, conflicts, f"material conflict: {named}")
        return Decision(False, None, conflicts, f"semantic-only + material conflict: {named}")

    if close_gates_pass(query, evidence, thresholds):
        return Decision(True, MatchClass.CLOSE, (), "no material conflict; head agrees")
    return Decision(True, MatchClass.RELATED, (), "no material conflict; head differs")
