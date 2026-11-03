"""SQLAlchemy models — designed for longitudinal (append-only) tracking.

The key idea: `jobs` holds current canonical state (upserted each run), while
`job_observations` is append-only (one row per job per run). Everything analytical
— days-open, repost detection, demand trends — is reconstructable from the
observation history, so we never lose signal by overwriting.
"""

from __future__ import annotations

from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from tracker.config import get_settings

_EMBED_DIM = get_settings().embedding_dim



#: The provider column the reference tables share: who published the row (a
#: plugin id, or `manual`). Unique keys lead with it, so a plugin's row and the
#: built-in one can sit side by side. Every writer names the provider.
def _provider_column():
    return mapped_column(String(32), index=True)

class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- #
# Postings: the held role, each read of it, and its estimates.
# --------------------------------------------------------------------------- #


class Job(Base):
    """Current canonical state of a posting (upserted every run)."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company: Mapped[str] = mapped_column(String(64), index=True)
    req_id: Mapped[str] = mapped_column(String(128))
    dedupe_key: Mapped[str] = mapped_column(String(256), unique=True, index=True)

    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(Text, nullable=True)
    team: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_sections: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    # When a detail fetch last produced this description. NULL = never
    # fetched, which is not the same claim as "this posting has no text": for a
    # detail-fetch source it means we chose not to spend the request.
    # `content_changed_at` cannot stand in — it moves only when the text CHANGES,
    # so a stable description would read as permanently stale and be re-fetched
    # nightly forever.
    description_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    locations: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    location_groups: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    # Every world the posting is about (taxonomy/domains.py), primary first.
    # NULL = never classified; [] = classified and honestly unknown. Both pass
    # the scope gate (fail-open).
    domains: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    # Canonical city labels derived from `locations` via tracker/taxonomy/locations.py
    # (normalize_cities). Powers the per-company offices view.
    location_cities: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    workplace_type: Mapped[str] = mapped_column(String(16), default="unknown")

    raw_level: Mapped[str | None] = mapped_column(String(128), nullable=True)
    level_band: Mapped[str] = mapped_column(String(32), index=True)
    level_confidence: Mapped[str] = mapped_column(String(16), default="confirmed")
    # stated|company|generic|none (schema.LevelBasis); NULL = not recorded.
    level_basis: Mapped[str | None] = mapped_column(String(16), nullable=True)
    family: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Cross-cutting role kind: management | product_program | technical. Classified
    # from the title (not the band); a board filter + optional scrape-scope axis.
    track: Mapped[str] = mapped_column(String(32), default="technical", index=True)

    # Compensation estimate (denormalized snapshot of best resolver result).
    comp_low: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comp_high: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comp_median: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comp_currency: Mapped[str] = mapped_column(String(8), default="USD")
    comp_provenance: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per component. `comp_low/median/high` are the TOTAL,
    # written only when the answering row measured one; the base range is its
    # own estimate, so a base-only answer never reads as a total. NULL = unknown.
    comp_base_low: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comp_base_median: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comp_base_high: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: total | base: the widest component the estimate answers. NULL = no estimate.
    comp_component: Mapped[str | None] = mapped_column(String(8), nullable=True)
    #: Who answered: a plugin id, a core-written source, or `builtin`.
    comp_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    comp_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: The reference fingerprint this estimate was computed under.
    #: A job whose value differs from `reference_state.applied_fp` is pending.
    comp_ref_fp: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Lifecycle / longitudinal fields.
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open|closed
    # User scope is orthogonal to source lifecycle. A source-open job can be
    # out of the configured role/seniority/location scope without being closed.
    in_scope: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The earliest publish or creation date the employer EVER gave for this
    # posting: min(stored, incoming `posted_at`, incoming
    # `source_facts.first_published_at`), never raised, implausible dates
    # ignored. `posted_at` is the employer's CURRENT date and moves when they
    # re-date; this is the start the headline listing age reads.
    first_posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Our first sighting of the posting: its creation here, or the inventory's
    # earlier `first_seen_at` (`db/arrival.py`).
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Whether `first_seen` dates the posting's appearance (`schema.Arrival`).
    arrival: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # First time the user opened the opportunity detail. The user's read state is
    # independent of source lifecycle and scope changes; never reset on scrape.
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # WHY this row is closed, and on whose evidence (`schema.ClosureBasis`).
    # `closed_at` stays DETECTION time — when we
    # noticed the posting was gone, not when the employer acted — so the pair
    # says "absent from a complete listing, first noticed on run R" rather than
    # the hiring conclusion neither field is entitled to make.
    #
    # Both NULL on an open row (never closed) and on a closure recorded without
    # a basis (unknown, deliberately not reconstructed — see `ClosureBasis`).
    # Both are cleared on reopen, alongside `closed_at`: a re-listed posting
    # whose basis outlived its closure would report evidence for a state it is
    # not in. The row remembers only the CURRENT
    # closure; every closure's basis is in the append-only lifecycle event.
    closure_basis: Mapped[str | None] = mapped_column(String(48), nullable=True)
    closure_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="SET NULL"), nullable=True
    )
    # Evidence toward closure by absence (`repo.count_miss`): how many
    # complete listings that speak for this open posting have not listed it
    # (0, 1 or 2) and when the first of them ran. Seeing the posting, or a
    # failed/degraded/blocked scan of its company, resets both; a closure
    # clears them.
    absent_scans: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    absent_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_days_open: Mapped[int] = mapped_column(Integer, default=0)
    repost_count: Mapped[int] = mapped_column(Integer, default=0)

    search_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)

    # Generic content-change signal (owned by `tracker/content.py`, not the skills
    # passes). `content_hash` = md5(title || description_text); `content_changed_at`
    # bumps only when that hash moves. Embeddings + disclosed-comp gate on it.
    content_hash: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Semantic embedding of (title + description). Re-embedded when a job's text
    # changes (content_changed_at > embedded_at). Powers similarity + clustering.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(_EMBED_DIM), nullable=True)
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # WHICH artifact produced `embedding`. Without it the system could
    # only say "current" or "stale", so a tier switch would clear every row and
    # a cancelled pass would start over. With it the re-embed trigger is
    # `embedded_tier IS DISTINCT FROM <active>`, which makes progress a COUNT
    # rather than a bulk UPDATE we must remember to run, makes stopping cheap
    # (only the rows already moved go back), and makes a mixed space impossible
    # by representation instead of by procedure.
    embedded_tier: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # What the SOURCE stated about this posting, versioned and allowlisted
    # (`schema.SourceJobFacts`). NULL on a row read before facts were recorded
    # and on every adapter that maps no facts — history cannot be backfilled
    # from today's board, so an absent record stays absent.
    source_facts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Disclosed pay band parsed from the posting text by the on-device AI pass.
    # Coexists with the comp_* ESTIMATE (never overwrites it): the estimate is a
    # level-seeded total-comp guess; these are what the posting literally states.
    # `structured_at IS NOT NULL` means "processed" — band columns NULL then just
    # means "posting disclosed nothing" (vs. NULL structured_at = "not yet run").
    disclosed_base_min: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    disclosed_base_max: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    disclosed_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    disclosed_pay_basis: Mapped[str | None] = mapped_column(String(8), nullable=True)  # base|total|unclear
    disclosed_pay_period: Mapped[str | None] = mapped_column(String(8), nullable=True)  # year|month|hour|unclear
    disclosed_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)  # verbatim grounding span
    disclosed_confidence: Mapped[str | None] = mapped_column(String(8), nullable=True)  # high|low
    # Target bonus the posting STATES as a share of base ("+ 25% bonus target"
    # -> 0.25). Only set when disclosed_pay_basis == "base"; a bonus share of an
    # unclear or total band would be meaningless. Lets the UI show bonus as a stated
    # figure instead of one estimated from the company baseline.
    disclosed_bonus_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Who wrote the band: `connector` (a structured field the source
    # serves), `page` (a posting page's pay field) or `text` (the text
    # pass). NULL with no band. The text pass never overwrites a connector's
    # band, so a parser fix can be re-run over stored rows without erasing it.
    disclosed_source: Mapped[str | None] = mapped_column(String(12), nullable=True)
    # Gating for the structured-extraction pass (mirrors content_changed_at / embedded_at):
    # re-run when structured_at IS NULL OR content_changed_at > structured_at OR the prompt
    # version changed. Written by this pass and by a connector band (`repo._apply_fields`
    # stamps `PAY_PARSER_VERSION`); see docs/field-authority.md.
    structured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    structured_prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # The place the text band was chosen for: `first_place` of the
    # locations the pass read, its city and metro slugs joined. A text that
    # states one band per city is read again when this moves; NULL = no key
    # recorded, so the text is read once more.
    disclosed_place_key: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Requirements gating — its own processed-version fields (each enrichment owns
    # its version), separate from the generic content_hash/content_changed_at pair.
    # Re-extract when the stored text hash, extractor version, or taxonomy version differs.
    requirements_content_hash: Mapped[str | None] = mapped_column(String(32), nullable=True)
    requirements_extractor_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    requirements_taxonomy_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    requirements_extracted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The years of experience the posting REQUIRES: the largest number on a
    # required experience row (`skills.extract.required_years`), written with
    # those rows. Stored so the Board can order by it.
    required_years: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Semantic cluster assignment (rebuilt in batch; complements `family`, never replaces).
    cluster_id: Mapped[int | None] = mapped_column(
        ForeignKey("clusters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    cluster_distance: Mapped[float | None] = mapped_column(nullable=True)

    # Repost lineage: denormalized projection of the job_lineage_link graph, so a
    # job card knows its stack without a recursive query. NULL lineage_role = a
    # standalone posting. `lineage_first_seen` mirrors the lineage's earliest
    # first_seen and is the "effective" age clock every metric reads via
    # coalesce(lineage_first_seen, first_seen). Written ONLY by the lineage pass
    # (tracker/lineage/), never by the scrape upsert.
    lineage_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_lineage.id", ondelete="SET NULL"), nullable=True
    )
    lineage_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-based, by first_seen
    lineage_role: Mapped[str | None] = mapped_column(String(12), nullable=True)  # original|repost|duplicate
    lineage_first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lineage_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lineage_detector_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # What the detector read when it last checked this posting
    # (`lineage.detect.lineage_input_key`): a change re-checks it.
    lineage_input_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # The same three for the twin pass (`lineage.twins.twin_input_key`).
    twin_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    twin_detector_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    twin_input_key: Mapped[str | None] = mapped_column(String(32), nullable=True)

    observations: Mapped[list[JobObservation]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    events: Mapped[list[JobLifecycleEvent]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "arrival IN ('new', 'already_listed', 'first_read')", name="ck_jobs_arrival"
        ),
        Index("ix_jobs_search_vector", "search_vector", postgresql_using="gin"),
        Index("ix_jobs_company_status", "company", "status"),
        Index("ix_jobs_status_in_scope", "status", "in_scope"),
        Index("ix_jobs_lineage", "lineage_id", "lineage_seq"),
        Index("ix_jobs_lineage_role", "lineage_role"),
        # Candidate prefilter for lineage detection (company + family + level_band).
        Index("ix_jobs_company_family_level", "company", "family", "level_band"),
        # Effective-age clock: every age metric reads
        # coalesce(lineage_first_seen, first_seen), so index that expression.
        Index("ix_jobs_effective_age", text("COALESCE(lineage_first_seen, first_seen)")),
        # The listed age of open roles (`queries.jobs.listed_since`): the header's
        # New count and the New view range over it on every request.
        Index(
            "ix_jobs_open_listed_since",
            text("least(first_posted_at, first_seen)"),
            postgresql_where=text("status = 'open'"),
        ),
        # ANN index for semantic similarity (pgvector cosine).
        Index(
            "ix_jobs_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # Trigram indexes power typo-tolerant fuzzy search (pg_trgm `%`/similarity).
        Index(
            "ix_jobs_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_jobs_company_trgm",
            "company",
            postgresql_using="gin",
            postgresql_ops={"company": "gin_trgm_ops"},
        ),
    )


class JobObservation(Base):
    """Append-only: one row per job per scrape run. Source of truth for history."""

    __tablename__ = "job_observations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.id", ondelete="CASCADE"), index=True)

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    title: Mapped[str] = mapped_column(Text)
    level_band: Mapped[str] = mapped_column(String(32))
    family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    locations: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    comp_median: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)  # raw snapshot for audit

    # Source provenance. Nullable, and NULL when the writer recorded no binding
    # (`repo.upsert_job` and `repo.admit_from_inventory` set neither).
    binding_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_bindings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_identity_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_source_identities.id", ondelete="SET NULL"), nullable=True
    )

    job: Mapped[Job] = relationship(back_populates="observations")


class JobCompEstimate(Base):
    """One source's pay estimate for one job, side by side with the other's.

    Our data and a plugin's never mix and never change each other's stored
    data. So every job keeps OUR estimate (`source = "roleband"`,
    computed from our data only, always) and, while a plugin is selected for
    `pay.levels`, that plugin's (`source` = its id, computed from its rows only;
    none for a company it has not read). `jobs.comp_*` is a copy of the selected
    source's row, the one every list, sort and filter reads; a switch writes each
    source's row batch by batch and copies the selected one onto every job at
    once, in the transaction that applies the switch. `sources` keeps the
    answers that source's providers gave, which the job detail shows.
    """

    __tablename__ = "job_comp_estimate"

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    comp_low: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comp_high: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comp_median: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comp_currency: Mapped[str] = mapped_column(String(8), default="USD")
    comp_provenance: Mapped[str | None] = mapped_column(Text, nullable=True)
    comp_base_low: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comp_base_median: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comp_base_high: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comp_component: Mapped[str | None] = mapped_column(String(8), nullable=True)
    comp_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    comp_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: The answer of every provider the source's resolver asked, in order.
    sources: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    #: The fingerprint of the source's inputs this estimate was computed under.
    ref_fp: Mapped[str | None] = mapped_column(String(64), nullable=True)
    estimated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --------------------------------------------------------------------------- #
# Sources: how a company is read (bindings, identities, recipes, tuning).
# --------------------------------------------------------------------------- #


class SourceBinding(Base):
    """Which connector+recipe revision currently speaks for a company.

    Rebinding is routine and UI-driven (wizard, recipe activation, rollback, ATS
    re-detection). A binding change yields a disjoint source-key set; without
    identity scoping, `close_missing` would see a complete listing that "lost"
    every job and close then reopen the entire company, destroying longitudinal
    history.

    `closure_capability` is assigned by RoleBand validation, never by recipe text:
    a source author must not be able to declare their own authority to close
    jobs. Search/category/sample sources stay `none` forever -- they can open and
    update jobs but never close by absence.
    """

    __tablename__ = "source_bindings"
    __table_args__ = (
        Index(
            "ix_source_bindings_one_active_per_company",
            "company_slug",
            unique=True,
            postgresql_where=text("status = 'stable'"),
        ),
        Index("ix_source_bindings_company_status", "company_slug", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_slug: Mapped[str] = mapped_column(
        ForeignKey("tracked_company.slug", ondelete="CASCADE"), index=True
    )
    #: `adapter` or `recipe`; `connector_id` names the adapter or the recipe slug.
    connector_kind: Mapped[str] = mapped_column(String(32))
    connector_id: Mapped[str] = mapped_column(String(128))
    #: immutable pin. Changing a recipe's default revision affects NEW bindings
    #: only; it never retargets a company already bound to a revision.
    recipe_revision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: proposed -> shadow -> reconciling -> stable (| retired). Only `stable`
    #: may close by absence.
    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)
    #: none | authoritative. New bindings start `none`.
    closure_capability: Mapped[str] = mapped_column(String(16), default="none")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def may_close(self) -> bool:
        """Closure eligibility. Both conditions, always."""
        return self.status == "stable" and self.closure_capability == "authoritative"


class JobSourceIdentity(Base):
    """Alias: `(binding, source_key) -> job`.

    Not a single `Job.binding_id`: one canonical job is observed under several
    bindings over its life, and overwriting a single FK loses the provenance
    that makes rebinding auditable. Not a rewrite of `Job.dedupe_key` either: it
    is unique-indexed and history points at it.
    """

    __tablename__ = "job_source_identities"
    __table_args__ = (
        UniqueConstraint("binding_id", "source_key", name="uq_identity_binding_source_key"),
        Index("ix_identity_job", "job_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    binding_id: Mapped[int] = mapped_column(
        ForeignKey("source_bindings.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    #: the key this binding's source uses for the job (e.g. `Job.dedupe_key`).
    source_key: Mapped[str] = mapped_column(String(256))

    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: exact_auto | reviewer_map | backfill — how this alias came to exist.
    origin: Mapped[str] = mapped_column(String(24), default="exact_auto")


class BindingReconciliationDecision(Base):
    """Append-only audit of every rebind identity decision.

    Identity changes must never masquerade as job lifecycle events: a reviewer
    retiring an unmatched job is an operator decision with a reason, not
    evidence that the source stopped listing it.
    """

    __tablename__ = "binding_reconciliation_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    binding_id: Mapped[int] = mapped_column(
        ForeignKey("source_bindings.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    source_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    #: exact_auto | map | retire | unresolved
    decision: Mapped[str] = mapped_column(String(24), index=True)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: user | system — a retire is always attributable.
    actor: Mapped[str] = mapped_column(String(16), default="system")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ConnectorRecipe(Base):
    """A declarative listing recipe's stable identity.

    Recipe *documents* are never stored as unversioned `AppSetting` blobs — they
    live in normalized, versioned rows so activation, rollback, and staleness are
    first-class. A recipe in use is never hard-deleted: it is `disabled` and its
    revisions/audit are retained.
    """

    __tablename__ = "connector_recipes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), default="job_listing")
    format_version: Mapped[int] = mapped_column(Integer, default=1)
    #: the one validated revision new/proposed bindings pin to; changing it never
    #: retargets an existing stable binding.
    default_revision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: draft | validating | active | invalid | disabled
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    #: Where the recipe came from, e.g. `{"bundled": true, "evidence": ...}` for
    #: one RoleBand ships.
    provenance: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ConnectorRecipeRevision(Base):
    """Append-only revision of a recipe document.

    An edit creates a new revision; a revision is never mutated. `checksum` pins
    the exact document bytes, and `validation` records the extractor version the
    revision was validated under — so a revision validated below the current
    `EXTRACTOR_VERSION` is detectably stale.
    """

    __tablename__ = "connector_recipe_revisions"
    __table_args__ = (
        UniqueConstraint("recipe_id", "version", name="uq_recipe_revision_version"),
        # Migration-chosen names (shorter than the ix_connector_recipe_revisions_*
        # defaults `index=True` would pick); declared so autogen sees the DB's schema.
        Index("ix_recipe_revisions_recipe_id", "recipe_id"),
        Index("ix_recipe_revisions_checksum", "checksum"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(
        ForeignKey("connector_recipes.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    document: Mapped[dict] = mapped_column(JSONB)
    checksum: Mapped[str] = mapped_column(String(64))
    #: {extractor_version, parser, adaptive_threshold?, ...} — empty until validated.
    validation: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(32), default="system")


class SourceBindingTuning(Base):
    """Per-binding learned bounds, one row per (binding, query).

    The hand-written bounds (`scraper_source_budget_seconds`, the adapters'
    `_MAX_PAGES`) are *seeds*; this row is the standing bound, because source
    durations and depths differ by orders of magnitude.

    Keyed per **query**, not per source, because one source's queries differ by
    orders of magnitude — a country-wide term needs depth its metro terms
    reach in a handful of pages, and one number for both is either wasteful or
    truncating. The reserved key `*` carries the source-level row, where the
    time budget lives (duration is a property of the source, not of one query).

    `page_samples`/`duration_samples` are retained evidence rather than a
    running p95, so a bound is re-derivable and explainable in Settings instead
    of being folklore in a module constant. Both are bounded by
    `scraper_tuning_samples`.
    """

    __tablename__ = "source_binding_tuning"
    __table_args__ = (
        UniqueConstraint("binding_id", "query_key", name="uq_source_binding_tuning_query"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    binding_id: Mapped[int] = mapped_column(
        ForeignKey("source_bindings.id", ondelete="CASCADE"), index=True
    )
    #: Adapter-supplied stable name for the query (location term, facet group,
    #: board site), or `*` for the source-level row.
    query_key: Mapped[str] = mapped_column(String(120))
    #: Recent per-run page counts; p95 over these is the ratchet floor.
    page_samples: Mapped[list] = mapped_column(JSONB, default=list)
    #: Recent per-run source durations (source-level row only).
    duration_samples: Mapped[list] = mapped_column(JSONB, default=list)
    #: The source's own last declared count for this query, when it declares one.
    declared_total_last: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The most recent run ended at OUR ceiling rather than the source's end.
    saturated: Mapped[bool] = mapped_column(Boolean, default=False)
    #: `StopReason` value -> count, so "how did this query usually end" is
    #: answerable without replaying runs.
    stop_reason_hist: Mapped[dict] = mapped_column(JSONB, default=dict)
    tuned_max_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tuned_budget_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# --------------------------------------------------------------------------- #
# Scheduling: when each source is read next, and the machine's day.
# --------------------------------------------------------------------------- #


class SyncScheduleState(Base):
    """Persistent due-work state for one active source binding.

    Scheduling belongs to the binding, not the company slug: rebinding changes
    the source identity and must start a new cadence record. Discovery is
    intentionally separate from reconciliation. A discovery probe may add or
    update jobs but never authorizes closure; `last_reconcile_at` is the
    per-binding freshness clock.
    """

    __tablename__ = "sync_schedule_state"
    __table_args__ = (
        CheckConstraint(
            "discovery_anchor_minute IS NULL OR "
            "discovery_anchor_minute BETWEEN 0 AND 1439",
            name="ck_sync_schedule_discovery_anchor_minute",
        ),
        CheckConstraint(
            "reconcile_anchor_minute IS NULL OR "
            "reconcile_anchor_minute BETWEEN 0 AND 1439",
            name="ck_sync_schedule_reconcile_anchor_minute",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    binding_id: Mapped[int] = mapped_column(
        ForeignKey("source_bindings.id", ondelete="CASCADE"), unique=True, index=True
    )
    provider_key: Mapped[str] = mapped_column(String(128), index=True)
    discovery_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    discovery_cadence_seconds: Mapped[int] = mapped_column(Integer, default=21_600)
    reconcile_cadence_seconds: Mapped[int] = mapped_column(Integer, default=86_400)
    last_discovery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_reconcile_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_discovery_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    next_reconcile_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # Nullable until the user directly arranges the clock. Once present, the
    # scheduler keeps successful future runs on this local-time phase rather
    # than drifting by however long the previous scrape took.
    discovery_anchor_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reconcile_anchor_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Manual sync is priority metadata, not a second queue. Preserve the
    # scheduler's prior deadline so cancel can remove only the manual
    # acceleration without suppressing naturally overdue work.
    manual_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    manual_previous_reconcile_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    last_new_count: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_empty_discoveries: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MachineAwakeSample(Base):
    """One moment this machine was seen properly awake.

    Written by every scheduler tick in a full wake (never a dark wake), and
    once from `pmset -g log` when there is no history of our own yet. The
    schedule learns from these when the computer is usually on, so the user is
    never asked. Samples a tick apart join into one stretch of being on.
    """

    __tablename__ = "machine_awake_samples"

    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    #: `tick` (a scheduler tick saw it) or `pmset` (read from the system log).
    source: Mapped[str] = mapped_column(String(8))


class SchedulePlanRun(Base):
    """One run of the schedule plan, or one user scan that read everyone.

    The plan reads every company on its own clock: a full read when the
    computer comes on (or the last full read is a day old), a quick check on
    each repeat. This row is that clock. `kind` is `full`, `quick`, `manual`
    (a Scan now) or `continue` (the companies a stopped full read had not
    read yet); only a run that read the whole roster moves the clock, which
    `companies` against `roster` decides.
    """

    __tablename__ = "schedule_plan_runs"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('full', 'quick', 'manual', 'continue')", name="ck_schedule_plan_runs_kind"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(8))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Companies the run set out to read, and the automatic roster it was
    #: planned against at that moment.
    companies: Mapped[int] = mapped_column(Integer)
    roster: Mapped[int] = mapped_column(Integer)
    #: `ok`, `failed`, `skipped` or `interrupted`; null while it runs. A run
    #: its process never finished is closed as `interrupted` by the next tick.
    outcome: Mapped[str | None] = mapped_column(String(12), nullable=True)


class DirectoryCheck(Base):
    """When the background scan last read one directory company, and what it found.

    One row per directory slug (`company_directory`), upserted per check. It is
    how the scan knows what is due (never checked first, then anything older
    than a day) and how the register reports progress; the postings themselves
    are never stored here. A company with roles for you is FOLLOWED instead,
    and from then on the pipeline collects it like any other.
    """

    __tablename__ = "directory_checks"

    slug: Mapped[str] = mapped_column(String(80), primary_key=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    #: A `SourceOutcome` value; stored rows may also hold `refused`.
    #: Only `ok` is a completed check; `bounded`/`truncated` stay pending.
    outcome: Mapped[str] = mapped_column(String(16))
    #: Postings the board listed, and how many of them fit what your radar looks for.
    scanned: Mapped[int] = mapped_column(Integer, default=0)
    roles_for_you: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProviderPressureState(Base):
    """Cross-run pressure/cooldown state for one provider scope.

    `RateLimiterPool` and `BreakerPool` still protect requests inside a run.
    This row prevents a fresh process from immediately re-entering a provider
    that just blocked or failed. `pressure_key` is the adapter family
    (`TrackedCompany.adapter`).
    """

    __tablename__ = "provider_pressure_state"

    pressure_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    # ready | backoff | blocked | paused | policy_denied
    state: Mapped[str] = mapped_column(String(24), default="ready", index=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consecutive_pressure_events: Mapped[int] = mapped_column(Integer, default=0)
    last_outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# --------------------------------------------------------------------------- #
# Lifecycle and relations: what happened to a posting, and the postings
# it is one role with (lineage, twins, place sets).
# --------------------------------------------------------------------------- #


class JobLifecycleEvent(Base):
    """Discrete lifecycle transitions: opened / closed / reopened / changed."""

    __tablename__ = "job_lifecycle_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(24), index=True)  # opened|closed|reopened|changed
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)  # e.g. {"field": "title", ...}
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    job: Mapped[Job] = relationship(back_populates="events")


class JobLineage(Base):
    """Materialized repost lineage — a group of postings that are the same role.

    A derived, idempotently-rebuilt projection of the ``job_lineage_link`` graph
    (union-find over effective links). `first_seen` = the earliest member's
    first_seen: the honest age clock for a role that was closed and re-posted.
    """

    __tablename__ = "job_lineage"
    __table_args__ = (
        # The DB enforces one-lineage-per-root as a named unique index (created by
        # the lineage migration), not an anonymous UniqueConstraint.
        Index("uq_job_lineage_root", "root_job_id", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company: Mapped[str] = mapped_column(String(64), index=True)
    root_job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    size: Mapped[int] = mapped_column(Integer, default=1)
    open_members: Mapped[int] = mapped_column(Integer, default=0)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class JobLineageLink(Base):
    """Source of truth for one repost/duplicate pair: evidence + two verdicts.

    ``confidence`` is the MACHINE verdict (auto|suspected); ``status`` is the HUMAN
    verdict (pending|confirmed|rejected). The two axes together are a labeled
    eval set for a model adjudicator. A reviewed verdict is immutable
    to the detector (enforced by an ON CONFLICT ... WHERE status='pending' upsert),
    so a rejected link is a durable negative label, never resurrected by a re-run.
    """

    __tablename__ = "job_lineage_link"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )  # newer posting
    prior_job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )  # older posting
    relation: Mapped[str] = mapped_column(String(12))  # repost | duplicate
    method: Mapped[str] = mapped_column(String(24))  # title+embedding | embedding | title_jaccard | manual | llm
    score: Mapped[float | None] = mapped_column(Float, nullable=True)  # cosine at detection
    title_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)  # token jaccard
    gap_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[str] = mapped_column(String(12))  # auto | suspected  (MACHINE)
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending|confirmed|rejected (HUMAN)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detector_version: Mapped[str] = mapped_column(String(32))
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("job_id", "prior_job_id", name="uq_job_lineage_link"),
        Index("ix_job_lineage_link_review", "status", "confidence", "created_at"),
    )


class JobTwinLink(Base):
    """Symmetric relationship between separate, closely related openings.

    Unlike ``JobLineageLink``, a confirmed twin never enters lineage projection:
    both jobs remain independent demand. Canonical endpoint ordering makes one
    durable row per unordered pair. Reviewed rows are detector-immutable.
    """

    __tablename__ = "job_twin_link"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_a_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    job_b_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    method: Mapped[str] = mapped_column(String(24))
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    title_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[str] = mapped_column(String(12))  # suspected | auto
    status: Mapped[str] = mapped_column(String(12), default="pending")
    detector_version: Mapped[str] = mapped_column(String(32))
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("job_a_id < job_b_id", name="ck_job_twin_link_canonical_pair"),
        UniqueConstraint("job_a_id", "job_b_id", name="uq_job_twin_link_pair"),
        Index("ix_job_twin_link_review", "status", "confidence", "created_at"),
    )


class JobPlaceSet(Base):
    """One role an employer lists once per place.

    Open postings of one company with the same normalized title and the same
    description text, each at a different place. Machine-decided by
    `lineage/place_sets.py`, never a review proposal; NOT a lineage (nothing was
    listed again) and not twins (nothing differs but the place). The natural
    key keeps a set's id stable across the whole-corpus rebuild.
    """

    __tablename__ = "job_place_set"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company: Mapped[str] = mapped_column(String(64), index=True)
    #: `normalize_title` of the members (equal by the rule).
    title: Mapped[str] = mapped_column(Text)
    #: md5 of the whitespace- and case-folded description, the identity evidence.
    text_hash: Mapped[str] = mapped_column(String(32))
    size: Mapped[int] = mapped_column(Integer)
    #: The places across the members, each once, earliest member first.
    places: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    rule_version: Mapped[str] = mapped_column(String(32))
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("company", "title", "text_hash", name="uq_job_place_set_identity"),
    )


class JobPlaceSetMember(Base):
    """A posting's membership of a place set, or a person's word that it is not one.

    `auto` rows are the rebuild's to write and delete. A `rejected` row is a
    human "Different roles" and is immutable to the rebuild: that posting joins
    no set until the person takes the verdict back (the row is deleted).
    """

    __tablename__ = "job_place_set_member"

    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    set_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_place_set.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(12))  # auto | rejected
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("status IN ('auto', 'rejected')", name="ck_job_place_set_member_status"),
    )


# --------------------------------------------------------------------------- #
# The user's own records: notifications, saves, verdicts, scope rules,
# pursuits and the profile.
# --------------------------------------------------------------------------- #


class Notification(Base):
    """Materialized user notification derived from lifecycle events and run health."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    priority: Mapped[str] = mapped_column(String(8))  # high|normal|low
    category: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="SET NULL"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(8))  # event|run
    source_id: Mapped[int] = mapped_column(BigInteger)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "category", name="uq_notification_source"),
        Index("ix_notifications_unread", "dismissed_at", "read_at", "created_at"),
    )


class Favorite(Base):
    """A saved/starred job the user wants to pursue. Global (single-user tool)."""

    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("job_id", name="uq_favorite_job"),)


class CompareSelection(Base):
    """The roles currently held side by side. Global (single-user tool).

    Durable for the same reason `favorites` is: selecting a role for comparison
    is the user's work, and it lives with the rest of user state under the
    `db/ownership.py` gate, not in the browser.

    The FK cascade is the point, not incidental bookkeeping. The dashboard's
    beacon renders a count from the ids and a roster from fetching each one, and
    it drops a fetch that fails — so an id outliving its job would make the count
    lie. Postgres deleting the row cannot rot; hand-written eviction can.

    `position` carries the insertion order the UI depends on: the beacon docks
    level with the role selected LAST, which an unordered table would lose.
    """

    __tablename__ = "compare_selection"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("job_id", name="uq_compare_selection_job"),)


# Optional structured reason on a dismissal. A vocabulary, not free text, so a
# suggestion loop can aggregate them.
FEEDBACK_REASONS = ("wrong_domain", "wrong_level", "wrong_role", "company", "other")


class JobFeedback(Base):
    """Per-job negative signal: "not for me".

    One verdict per job, upserted. Deliberately a VIEW filter, not a scope
    input: `in_scope` is a projection of the saved scope axes and gets
    recomputed wholesale on every scope save — a dismissal folded into it
    would be silently resurrected by the next recompute. Dismissed rows are
    excluded at list time and stay filterable back.
    """

    __tablename__ = "job_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, index=True
    )
    verdict: Mapped[str] = mapped_column(String(16), default="dismissed")
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class JobRelevanceReview(Base):
    """Advisory model verdict for one in-scope-but-unclassified posting.

    Which world the posting serves and whether that is relevant to the user's
    tracked worlds — with the model's rationale, shown in the UI. STRICTLY
    advisory: it never writes `jobs.domains`, never touches `in_scope`, and a
    human action is the only path from a verdict to any scope effect. One row
    per job, upserted; re-reviewed when the posting's text changes or the
    prompt version moves (mirrors the disclosed-comp staleness gate).
    """

    __tablename__ = "job_relevance_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, index=True
    )
    # NULL = the model could not place the posting in any vocabulary world.
    domain: Mapped[str | None] = mapped_column(String(64), nullable=True)
    relevance: Mapped[str] = mapped_column(String(16))  # relevant | irrelevant | uncertain
    confidence: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text)
    # The tracked-worlds set the verdict was judged against (a relevance verdict
    # is meaningless without it — scope changes after the fact must be visible).
    tracked_worlds: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "relevance IN ('relevant','irrelevant','uncertain')",
            name="ck_relevance_review_verdict",
        ),
    )


class CompanyScopeRule(Base):
    """Learned per-company exclusion in the employer's OWN vocabulary.

    "Exclude team 'Fulfillment & Operations Management' at one company" — the value
    is the verbatim department/team string, matched case-insensitively, never
    a keyword we invented. Only explicit user confirmation writes a row
    (analogous to source_binding_tuning: learned, never hand-coded). Rules
    join both gates: the ingest scope decision and the saved-scope SQL
    recompute — so they are part of what `in_scope` projects, unlike a
    dismissal.
    """

    __tablename__ = "company_scope_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company: Mapped[str] = mapped_column(String(64), index=True)
    # "team" | "department" — which employer field the value came from.
    kind: Mapped[str] = mapped_column(String(16))
    value: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("company", "kind", "value", name="uq_company_scope_rule"),
    )


class Pursuit(Base):
    """Current job-seeker progress for one opportunity."""

    __tablename__ = "pursuits"
    # UPDATE refreshes updated_at in Postgres. Fetch it during flush so the
    # synchronous public serializer never initiates implicit async IO after
    # commit (MissingGreenlet, despite the pursuit already being saved).
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, index=True
    )
    stage: Mapped[str] = mapped_column(String(24), default="saved", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action_due: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True
    )

    __table_args__ = (
        CheckConstraint(
            "stage IN ('saved','researching','networking','applied','interviewing',"
            "'offer','rejected','withdrawn')",
            name="ck_pursuit_stage",
        ),
        CheckConstraint("priority BETWEEN 1 AND 5", name="ck_pursuit_priority"),
    )


class ProfileClaim(Base):
    """One provenance-tracked fact about the candidate.

    Append-only: an edit supersedes the old row (sets `superseded_at`) and
    inserts a new one, so the profile's history survives its corrections.
    `field` names the fact kind (`identity` | `experience` | `skill`); `value`
    is the fact; `source` is where it came from. Active rows =
    `superseded_at IS NULL`. The inference pass reads the active `experience`
    rows; nothing in the app writes the table.
    """

    __tablename__ = "profile_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    field: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[dict] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(16))  # user | linkedin
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    # Where this value came from, verbatim (the subset of the imported record).
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ('user','linkedin')", name="ck_profile_claim_source"
        ),
        CheckConstraint(
            "field IN ('identity','experience','skill')",
            name="ck_profile_claim_field",
        ),
    )


class ProfileSuggestion(Base):
    """One inferred profile adjustment awaiting the user's verdict.

    Written only by `post_pass:profile_inference` (deterministic scoring over
    the user's own saves/passes/companies/intent);
    status mutations are API-only. STRICTLY a proposal: nothing is applied
    until an explicit accept, which writes through the existing settings
    stores. A resolved (accepted/dismissed) row's `dedupe_key` is never
    re-raised — a dismissed suggestion must stay dismissed, or the inbox
    becomes a nag. Pending rows whose evidence does not support them are
    deleted by the pass.
    """

    __tablename__ = "profile_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # world_on | world_off
    # `kind:world` — one live proposal per adjustment, ever.
    dedupe_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    payload: Mapped[dict] = mapped_column(JSONB)  # {"world": <slug>}
    # Evidence breakdown shown verbatim in the UI (counts, sectors, intent hit,
    # score) — a suggestion that cannot say why earns no trust.
    basis: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','accepted','dismissed')",
            name="ck_profile_suggestion_status",
        ),
        CheckConstraint(
            "kind IN ('world_on','world_off')",
            name="ck_profile_suggestion_kind",
        ),
    )


class PursuitEvent(Base):
    """Append-only audit record for human/agent pursuit changes."""

    __tablename__ = "pursuit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pursuit_id: Mapped[int] = mapped_column(
        ForeignKey("pursuits.id", ondelete="CASCADE"), index=True
    )
    actor: Mapped[str] = mapped_column(String(16))  # user | agent
    event_type: Mapped[str] = mapped_column(String(24))  # created | updated
    from_stage: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_stage: Mapped[str] = mapped_column(String(24))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


# --------------------------------------------------------------------------- #
# Market rollups: demand, skills and pay over time.
# --------------------------------------------------------------------------- #


class DemandMetric(Base):
    """Daily rollup per (company × family × location group). Powers the demand view."""

    __tablename__ = "demand_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    metric_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    company: Mapped[str] = mapped_column(String(64), index=True)
    family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location_group: Mapped[str | None] = mapped_column(String(64), nullable=True)

    open_count: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    closed_count: Mapped[int] = mapped_column(Integer, default=0)
    reposted_count: Mapped[int] = mapped_column(Integer, default=0)
    long_open_count: Mapped[int] = mapped_column(Integer, default=0)
    median_days_open: Mapped[float | None] = mapped_column(nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "metric_date", "company", "family", "location_group", name="uq_demand_slice"
        ),
    )


class SkillDemandDaily(Base):
    """Daily rollup of skill demand per (company × family × concept). Powers the
    Statistics "Trends" sub-tab (skill demand over time).

    `job_count` = distinct open jobs at that company+family with a displayable
    requirement for the concept on `metric_date` (high-confidence, non-context;
    industries excluded — a vertical is never a skill). One row-set is appended per
    pipeline run, mirroring DemandMetric.
    `family` is nullable to mirror jobs with an unclassified family.
    """

    __tablename__ = "skill_demand_daily"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    metric_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    company: Mapped[str] = mapped_column(String(64), index=True)
    family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    concept_id: Mapped[int] = mapped_column(
        ForeignKey("skill_concepts.id", ondelete="CASCADE"), index=True
    )
    job_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint(
            "metric_date", "company", "family", "concept_id", name="uq_skill_demand_slice"
        ),
    )


class CompMetric(Base):
    """Daily rollup of comp percentiles for the Statistics "Compensation" trend.

    One dated slice per grouping so each series is an *independently computed*
    percentile summary (percentiles can't be re-aggregated from stored aggregates).
    `dim` names the grouping (`overall`/`company`/`level`/`family`) and `key` holds
    the value (company slug / level band / family slug; `""` for overall). Using a
    non-null dim/key discriminator keeps the daily upsert conflict target NULL-free.
    Mirrors DemandMetric/SkillDemandDaily: one row-set appended per pipeline run.
    """

    __tablename__ = "comp_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    metric_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    dim: Mapped[str] = mapped_column(String(16), index=True)  # overall|company|level|family
    key: Mapped[str] = mapped_column(String(64), index=True)  # slug/band, "" for overall
    count: Mapped[int] = mapped_column(Integer, default=0)
    p25: Mapped[float | None] = mapped_column(nullable=True)
    p50: Mapped[float | None] = mapped_column(nullable=True)
    p75: Mapped[float | None] = mapped_column(nullable=True)
    p90: Mapped[float | None] = mapped_column(nullable=True)

    __table_args__ = (
        UniqueConstraint("metric_date", "dim", "key", name="uq_comp_slice"),
    )


class CompSnapshot(Base):
    """Daily raw comp values per (company, level_band, family) for the trend series.

    Unlike `CompMetric` (which stores pre-computed percentiles that cannot be
    re-aggregated), this keeps the underlying `comp_median` values so the trend can
    recompute exact percentiles over any *subset* of companies at read time — which
    is what lets the visibility toggle change the Statistics numbers without a
    pipeline rerun or losing history. `level_band`/`family` use `''` (not NULL) as
    the "any" sentinel to keep the upsert conflict target NULL-free, matching the
    CompMetric convention. One row-set appended per pipeline run.
    """

    __tablename__ = "comp_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    metric_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    company: Mapped[str] = mapped_column(String(64), index=True)
    level_band: Mapped[str] = mapped_column(String(32), default="")  # "" = any
    family: Mapped[str] = mapped_column(String(64), default="")  # "" = any
    comp_values: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    #: Whose estimates the values are: ours (`roleband`) or a plugin's
    #: id, never both in one row. `mixed`: values taken from whichever source
    #: answered each posting first; no reader reads it.
    source: Mapped[str] = mapped_column(String(64), server_default="mixed", index=True)

    __table_args__ = (
        UniqueConstraint(
            "metric_date", "company", "level_band", "family", "source", name="uq_comp_snapshot"
        ),
    )


class DisclosureSnapshot(Base):
    """Daily pay-transparency snapshot: who states pay, and what band they print.

    The comp_* tables above track the *imputed* total-comp estimate. This one
    tracks what employers literally publish, at two grains that must never be
    conflated:

    * **The rate** — `disclosed / checked` — is basis-independent. `checked`
      counts only roles the disclosure pass has actually read (`structured_at`
      set); a NULL band on an unread role is "unknown", never "stated nothing",
      which is the same predicate the `discloses_pay` board filter uses.
    * **The bands** — `bands` — are basis-scoped and only ever aggregated within
      one `pay_basis`. Base pay and total comp are different quantities,
      so a row's bands may only be pooled with rows carrying the same basis.

    One row per `(metric_date, company, level_band, pay_basis)`. `pay_basis` is
    `''` for roles that stated no band, so summing `roles` over every basis for a
    cell gives the open count and summing over `pay_basis != ''` gives the
    disclosed count — the two can never disagree. `level_band` uses `''` (not
    NULL) as the unclassified sentinel, matching the CompSnapshot convention.

    `bands` holds the *distinct* bands in the cell as `{low, high, reqs}` —
    an employer publishes one band and hangs many reqs off it, so the
    honest unit is the band, with `reqs` recording how many open roles sit on it.
    Storing them per company (rather than pre-aggregated percentiles) is what
    lets the trend recompute exactly over the visible-company subset.
    """

    __tablename__ = "disclosure_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    metric_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    company: Mapped[str] = mapped_column(String(64), index=True)
    level_band: Mapped[str] = mapped_column(String(32), default="")  # "" = unclassified
    pay_basis: Mapped[str] = mapped_column(String(8), default="")  # "" = no band stated
    roles: Mapped[int] = mapped_column(Integer, default=0)
    # Roles in this cell the disclosure pass has read. Equals `roles` for any
    # pay_basis != '' row (a band implies the pass ran); the '' row is where the
    # not-yet-read roles live, and the gap is what keeps the rate honest.
    checked: Mapped[int] = mapped_column(Integer, default=0)
    bands: Mapped[list[dict]] = mapped_column(JSONB, default=list)  # [{low, high, reqs}]

    __table_args__ = (
        UniqueConstraint(
            "metric_date", "company", "level_band", "pay_basis", name="uq_disclosure_snapshot"
        ),
    )


# --------------------------------------------------------------------------- #
# Settings, the followed companies, and what is derived over every posting
# (the role catalog, the posting inventory, similarity, clusters).
# --------------------------------------------------------------------------- #


class AppSetting(Base):
    """Simple key -> JSON settings store (e.g. which role groups are tracked)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, default=dict)


class TrackedCompany(Base):
    """Every company to scrape — built-in and user-added alike — is a row here.

    Built-ins are seeded from `config.COMPANIES` by `company_store.ensure_builtins`
    with `source="builtin"` (which only blocks deletion); they then obey identical
    rules to user-added companies. The pipeline's targets are the `active` +
    `enabled` rows with an adapter (`get_active_targets`). A company added by careers
    URL whose ATS we can't yet scrape is stored `status="pending"` (adapter needed)
    and skipped until an adapter exists. `enabled` gates future scans; `visible`
    gates browse/aggregate display.
    """

    __tablename__ = "tracked_company"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    display: Mapped[str] = mapped_column(String(128))
    adapter: Mapped[str | None] = mapped_column(String(32), nullable=True)
    board_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: Regional deployment for a multi-region ATS (`schema.BoardRegion`), or
    #: NULL when the family has one host. Nullable rather than defaulting to
    #: `global` because "this family has one deployment" and "this tenant is on
    #: the global host" are different records, and a multi-region board can
    #: answer an identical 404 for a wrong region and a wrong token alike — so
    #: the region has to be carried, never inferred from a failure.
    board_region: Mapped[str | None] = mapped_column(String(16), nullable=True)
    careers_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | pending
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # future scans on/off
    # Display switch: when False the company's postings are excluded from every
    # browse/aggregate read surface (not from scraping — see company_store).
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(16), default="catalog")  # catalog | url
    # A pending URL company whose careers page named a known board family that
    # did not become a board: the family, and why (`board_resolve.PendingReason`).
    detected_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pending_reason: Mapped[str | None] = mapped_column(String(24), nullable=True)
    # Pre-gate inventory state. Kept separate from `status`, which means whether
    # an adapter exists (`active|pending`).
    role_catalog_status: Mapped[str] = mapped_column(String(16), default="pending")
    role_catalog_scanned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    role_catalog_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What the last catalog scan could see. `places`: the location
    # groups a source that lists only asked-for places was queried for (NULL:
    # the whole board was listed). The catalog drops a listed posting it cannot
    # count, for one of two reasons, counted apart: `unplaced`, no
    # recognised place; `unsorted`, a place but no role family.
    role_catalog_places: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    role_catalog_unplaced: Mapped[int | None] = mapped_column(Integer, nullable=True)
    role_catalog_unsorted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The user's consent to collect a WALLED company: when it was
    # given, the dialog text they confirmed, and the register fingerprint of the
    # wall they were shown (`SourceReview.wall_fingerprint`). Any stored consent
    # unlocks collection, whatever the register later records: the user is asked
    # once. Kept on unfollow: it records a consent that was given, and it is what
    # lets Undo or a later follow put the company back without asking again.
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # The language `consent_text` is in (a BCP 47 tag): a record of an agreement
    # says which language it was made in. Never rewritten by a language switch.
    consent_locale: Mapped[str | None] = mapped_column(String(35), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RoleCatalog(Base):
    """Per (role_group × company) tally of observed postings + example titles.

    Populated by the discovery pass so the settings picker can show which roles
    exist and how each company phrases them (one company calls it 'Staff SWE').
    """

    __tablename__ = "role_catalog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role_group: Mapped[str] = mapped_column(String(64), index=True)
    company: Mapped[str] = mapped_column(String(64), index=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    band_counts: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Exact intersection used by Settings impact math. Shape:
    # {"staff": {"technical": 12, "management": 2}, ...}.
    band_track_counts: Mapped[dict] = mapped_column(JSONB, default=dict)
    # The joint over band x track x locations x domains. One entry
    # per distinct coordinate: {"band","track","locations":[...],
    # "domains":[...],"count"}. Every other count on this row is a MARGINAL and
    # cannot be intersected — `domain_counts` in particular double-counts
    # multi-label rows — so without the joint the scope screen could show the
    # location and domain axes only at full-market volume, overstating them.
    # Self-describing by slug
    # rather than interned: `persist_company_catalog` rewrites one company at a
    # time, so a shared dictionary would couple rows that are written apart.
    # The API interns for the wire.
    scope_cells: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    examples: Mapped[list] = mapped_column(JSONB, default=list)  # distinct observed titles
    # Domain-axis observability: {"logistics_fulfillment": 41,
    # "unclassified": 7, ...} so widening/narrowing worlds is an informed
    # choice. Multi-label rows count once per matched domain.
    domain_counts: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Employer-verbatim category strings per domain, capped — the evidence the
    # worlds UI shows ("Fulfillment & Operations Management"), because the
    # employer's own vocabulary is what the classifier read.
    domain_examples: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("role_group", "company", name="uq_role_company"),)


class PostingInventory(Base):
    """Every posting a sync read for a followed company, in scope or not.

    The superset of `jobs`, joined by the same `dedupe_key`: a slim row of
    listing facts (allowlisted, never a description or a person) plus the
    classification `annotate()` gave it, so a scope widening can admit a
    posting without a rescan. Current state only: `gone_at` marks a posting
    absent from an authoritative listing, and a reappearance clears it. The
    classification columns mirror `jobs` in name, type and NULL semantics so
    one scope expression reads both. Written only by `db/inventory_store.py`.
    """

    __tablename__ = "posting_inventory"
    # Stored with fillfactor 85, set by its migration (`544950844911`): SQLAlchemy
    # declares no table storage parameters, so `create_all` leaves the default.

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    company: Mapped[str] = mapped_column(String(64))
    req_id: Mapped[str] = mapped_column(String(128))
    binding_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_bindings.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(Text, nullable=True)
    team: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_level: Mapped[str | None] = mapped_column(Text, nullable=True)
    locations: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    workplace_type: Mapped[str] = mapped_column(String(16), default="unknown")
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    level_band: Mapped[str] = mapped_column(String(32))
    level_confidence: Mapped[str] = mapped_column(String(16))
    level_basis: Mapped[str | None] = mapped_column(String(16), nullable=True)
    family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    track: Mapped[str] = mapped_column(String(32))
    location_groups: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    domains: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    # sha256 over the listing facts and classification: an unchanged row is
    # not rewritten on the next scan.
    content_hash: Mapped[str] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="SET NULL"), nullable=True
    )
    gone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_posting_inventory_company_gone", "company", "gone_at"),
        Index(
            "ix_posting_inventory_live_role",
            "family",
            "level_band",
            "track",
            postgresql_where=text("gone_at IS NULL"),
        ),
        Index("ix_posting_inventory_location_groups", "location_groups", postgresql_using="gin"),
    )


class JobSimilarity(Base):
    """Precomputed nearest-neighbor jobs by embedding cosine similarity.

    Two scopes per job: `within` (same company) and `cross` (other companies), kept
    separate so near-duplicate within-company reposts never crowd out the cross-company
    matches that answer "where else is this role open?". `score` = 1 - cosine distance.
    """

    __tablename__ = "job_similarity"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    neighbor_job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(String(12))  # within|cross
    rank: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column()

    __table_args__ = (
        UniqueConstraint("job_id", "scope", "neighbor_job_id", name="uq_job_similarity"),
        Index("ix_job_similarity_lookup", "job_id", "scope", "rank"),
    )


class Cluster(Base):
    """A semantic cluster of roles (KMeans over embeddings), rebuilt in batch.

    Complements the hand-curated `family` taxonomy: one family (e.g. software_engineering)
    legitimately splits into several skill clusters (distributed-systems vs frontend vs
    ml-infra). `label` and `top_terms` are derived from members' top mean-TF-IDF skills;
    `family_hint` is the modal family among members.
    """

    __tablename__ = "clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_version: Mapped[str] = mapped_column(String(48))
    label: Mapped[str] = mapped_column(Text)
    top_terms: Mapped[list] = mapped_column(JSONB, default=list)  # [{term, display, weight}]
    family_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# --------------------------------------------------------------------------- #
# Runs: each scan and each source within it, and model task telemetry.
# --------------------------------------------------------------------------- #


class ScrapeRun(Base):
    """One row per pipeline execution — run log + drift alerts."""

    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Liveness beat: a live run bumps this every ``run_heartbeat_seconds``. A
    # ``running`` row whose heartbeat (fallback ``started_at``) has gone silent
    # past ``stale_run_heartbeat_seconds`` is a crashed/killed run, detectable in
    # minutes instead of waiting out ``stale_run_minutes``.
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # running|ok|partial|error — a *projection* of the per-source outcomes in
    # `per_source` (see connectors.recipes.outcome.run_status_for), not an
    # independent vocabulary. `partial` = at least one source returned usable
    # data and at least one did not; it counts as a successful refresh.
    status: Mapped[str] = mapped_column(String(16), default="running")
    # full|targeted — what this run *covered*, which is a different question from
    # how it went. A targeted run re-attempts a chosen subset (a retry of the
    # sources that failed), so its success says nothing about the companies it
    # never touched. Only a `full` run may advance `last_success_at`: without
    # this column a retry of a few sources returning `ok` would mark the whole
    # tree fresh and suppress the watchdog catch-up for the companies it skipped.
    scope: Mapped[str] = mapped_column(String(16), default="full", server_default="full")
    # Which checkout produced this run: "<sha>[-dirty] (<branch>)". The agents
    # execute the working tree, so a branch switch changes what runs with no
    # other trace. Nullable: a deployment need not be a git checkout, and naming
    # itself must never be able to fail a scrape.
    code_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The OS process group executing this run (`os.getpgrp()` at open).
    # `POST /api/sync/cancel` signals a process GROUP, so this is what names the
    # run a cancel stopped; the newest running run could be a scheduled run in a
    # group the cancel never touched. Nullable: NULL when none was recorded. A
    # group number is reused once its process is gone, so it identifies a run
    # only while that run is live.
    process_group: Mapped[int | None] = mapped_column(Integer, nullable=True)
    jobs_seen: Mapped[int] = mapped_column(Integer, default=0)
    jobs_new: Mapped[int] = mapped_column(Integer, default=0)
    jobs_closed: Mapped[int] = mapped_column(Integer, default=0)
    per_source: Mapped[dict] = mapped_column(JSONB, default=dict)  # counts + errors per adapter
    drift_alerts: Mapped[list] = mapped_column(JSONB, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # Covers the freshness lookup (`scope='full'` + status, newest first)
        # that runs on every `/api/status` poll.
        Index("ix_scrape_runs_scope_status", "scope", "status"),
    )


class ScrapeSourceRun(Base):
    """Normalized per-binding audit for one pipeline run.

    `ScrapeRun.per_source` is the compatibility projection. Scheduler,
    freshness, and capacity decisions read this table instead of reparsing a
    growing JSONB blob. Request counters are NULL when transport telemetry did
    not record them; unknown is never rewritten as zero.
    """

    __tablename__ = "scrape_source_runs"
    __table_args__ = (
        UniqueConstraint("run_id", "binding_id", name="uq_scrape_source_run_binding"),
        Index("ix_scrape_source_runs_binding_finished", "binding_id", "finished_at"),
        # The newest run of a binding, read once per followed company by
        # `/api/status` (latest outcome, last attempt, last listed count);
        # `scripts.bench_status_cost` measures it.
        Index("ix_scrape_source_runs_binding_started", "binding_id", "started_at"),
        Index("ix_scrape_source_runs_provider_finished", "provider_key", "finished_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="CASCADE"), index=True
    )
    binding_id: Mapped[int] = mapped_column(
        ForeignKey("source_bindings.id", ondelete="CASCADE"), index=True
    )
    company_slug: Mapped[str] = mapped_column(String(64), index=True)
    provider_key: Mapped[str] = mapped_column(String(128), index=True)
    # discovery | reconcile | repair | shadow
    scan_mode: Mapped[str] = mapped_column(String(16), index=True)
    outcome: Mapped[str] = mapped_column(String(24), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scanned: Mapped[int] = mapped_column(Integer, default=0)
    kept: Mapped[int] = mapped_column(Integer, default=0)
    jobs_new: Mapped[int] = mapped_column(Integer, default=0)
    jobs_closed: Mapped[int] = mapped_column(Integer, default=0)
    request_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes_received: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    list_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    closure_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    errors: Mapped[list] = mapped_column(JSONB, default=list)
    drift: Mapped[list] = mapped_column(JSONB, default=list)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)


class AiTaskLog(Base):
    """One redacted row per AI-provider invocation — the measurement substrate.

    One row per AI task, routed or not. Deliberately holds NO raw prompt or
    model output: only counts, timings, and outcome classes. These rows are the
    evidence for which work is worth escalating from the local model to a cloud
    model.
    """

    __tablename__ = "ai_task_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    task_type: Mapped[str] = mapped_column(String(32), index=True)  # e.g. "disclosed_comp"
    provider: Mapped[str] = mapped_column(String(24))  # the backend that answered (`provider_name`)
    availability_state: Mapped[str] = mapped_column(String(32))
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    validation_result: Mapped[str] = mapped_column(String(16))  # ok|coerced|invalid|skipped
    failure_class: Mapped[str | None] = mapped_column(String(32), nullable=True)  # timeout|sdk_error|unavailable|validation
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Which tier answered and why. NULL for any call that was not routed,
    # so "was this routed?" stays answerable.
    route_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)  # redacted extras only — no raw text

    __table_args__ = (
        Index("ix_ai_task_log_type_time", "task_type", "created_at"),
    )


# --------------------------------------------------------------------------- #
# Company facts: profiles, pay ladders, benefits, facts and prices.
# --------------------------------------------------------------------------- #


class CompanyProfile(Base):
    """Durable, per-company substrate. Curated once, reused as the baseline for
    every posting at that company (see docs/architecture.md).

    Identity + equity mechanics are resolved from claims (`company_fact`), and no
    one source is authoritative: a source's ticker or company type can lag real
    events, such as a listing. `manual` always wins over every source on refresh — that
    override rule is what makes "fill it in once" actually hold.
    """

    __tablename__ = "company_profile"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128))

    # Identity / enrichment (resolved from claims, overridable).
    #: Listed or not, resolved from our sources only; None = not known,
    #: never "private": identity we have not researched is not a no.
    is_public: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ticker: Mapped[str | None] = mapped_column(String(12), nullable=True)
    headcount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hq_city: Mapped[str | None] = mapped_column(String(64), nullable=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    year_founded: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Equity mechanics — drives the Trajectory projection.
    # equity_vehicle: rsu|options|none|cash_election  (cash_election: publicly
    # listed yet ~0% stock, so its TC is stock-price-insensitive).
    equity_vehicle: Mapped[str | None] = mapped_column(String(16), nullable=True)
    vesting_schedule: Mapped[str | None] = mapped_column(String(32), nullable=True)
    comp_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Brand identity for the profile hero; `brand_color` backs the monogram
    # fallback when the logo fails to load.
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand_color: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Per-field provenance: which fields a human has pinned. Refresh never
    # overwrites a key listed here.
    manual_fields: Mapped[list] = mapped_column(ARRAY(Text), default=list)

    # Resolved provenance cache, written by profiles/resolve.py:
    # {field: {source, source_label, observed_at, freshness, conflicts[]}}.
    # The evidence itself lives in `company_fact`; this is the fast read path.
    field_meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Company badge rolled up from field health: ok | stale | conflict | missing.
    data_health: Mapped[str] = mapped_column(String(16), default="missing")

    profile_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CompanyCompLevel(Base):
    """THE salary baseline: real base/stock/bonus composition per company level.

    Source of truth for comp composition; the ratios in `comp_split.py` are the
    fallback for companies without rows.
    Stores the company's OWN level vocabulary (`L7`, `ICT5`, `IC6`, `G10`) rather
    than assuming ours: a rung keeps the label its company prints, and our
    dataset decides which of our bands it is.

    A plugin's row stores what the plugin sent: its label and `aliases`, never a
    band. Which of our bands it is gets worked out when it is READ, from our
    atlas (`levels.words.rung_band`), so our data never rewrites a
    plugin's row. `band` / `band_source` hold a band only on a row of ours (one
    entered by hand); on a plugin row they are NULL or stale values nothing
    reads. A row no plugin published is read by nothing.
    """

    __tablename__ = "company_comp_level"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_slug: Mapped[str] = mapped_column(
        ForeignKey("company_profile.slug", ondelete="CASCADE"), index=True
    )
    family: Mapped[str] = mapped_column(String(48))  # taxonomy family
    level_label: Mapped[str] = mapped_column(String(48))  # company vocabulary
    band: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    #: Who decided `band` on a row of ours. Never read on a plugin's row.
    band_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: The rung's other names as the plugin sent them: what read-time banding
    #: falls back on when the atlas cannot place the label.
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")

    #: The figures below are in THIS currency, as the publisher stated them.
    #: Nothing converts them, so a reader compares and aggregates only within
    #: one currency. Our own rows are `OUR_PAY_CURRENCY`.
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")
    tc_median: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    base_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    stock_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bonus_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Components / TC. The reusable ratio — what a job at this band inherits.
    base_pct: Mapped[float | None] = mapped_column(nullable=True)
    stock_pct: Mapped[float | None] = mapped_column(nullable=True)
    bonus_pct: Mapped[float | None] = mapped_column(nullable=True)

    provider: Mapped[str] = _provider_column()
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)  # required attribution
    # Plugin rows: the publisher's own family name, the country the figures are
    # for (ISO 3166-1 alpha-2), and the date the publisher states them as of.
    # NULL on a row no plugin published. A plugin row with no country prices no
    # posting; a row of ours with none is for `OUR_PAY_COUNTRY`.
    vendor_family: Mapped[str | None] = mapped_column(String(48), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: Set when a clean snapshot of this provider did not carry the row.
    #: Rows are retired, never deleted; readers skip retired rows.
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # One rung per country: the same label stated for two countries is two
        # rows. No country is one value, so a rung without one stays unique.
        UniqueConstraint(
            "provider", "company_slug", "family", "level_label", "country", name="uq_company_comp_level",
            postgresql_nulls_not_distinct=True,
        ),
    )


class ExternalCompObservation(Base):
    """One raw self-reported pay submission, published by a plugin (`pay.observations`).

    A reference/validation surface, deliberately separate from `company_comp_level`
    (which is THE model baseline): mixing a self-reported source into that table
    would let it silently drive the comp estimate, which must not happen. Here we
    keep the raw per-submission grain so aggregates (median equity share per band)
    recompute at read time and future snapshots simply append — the same
    longitudinal-asset discipline as `job_observations` / `comp_snapshot`.

    Amounts are whole units of `currency`, for the market `country` names (NULL:
    unknown); a component the submission does not state is NULL, never zero.
    `source_level` is the source's OWN label (`ICT5`, `L6`); readers band it
    when they read it, so the stored `band` is NULL and unread.
    `dedup_key` is a deterministic natural key so re-importing a snapshot is
    idempotent (a source with no stable submission id still collapses exact duplicates).
    """

    __tablename__ = "external_comp_observation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = _provider_column()
    company_slug: Mapped[str] = mapped_column(String(64), index=True)
    source_level: Mapped[str] = mapped_column(String(48))
    band: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    function: Mapped[str | None] = mapped_column(String(48), nullable=True)
    location: Mapped[str | None] = mapped_column(String(64), nullable=True)
    yoe: Mapped[int | None] = mapped_column(Integer, nullable=True)
    family: Mapped[str | None] = mapped_column(String(48), nullable=True)

    total_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    base_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    equity_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bonus_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)

    snapshot_date: Mapped[datetime] = mapped_column(Date, index=True)
    dedup_key: Mapped[str] = mapped_column(String(200))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("provider", "dedup_key", name="uq_external_comp_obs"),
    )


class CompanyBenefit(Base):
    """One perk at one company, as a plugin publishes it (`company.benefits`).

    `value_usd` is the annualized monetary value where the source supplies one
    (a retirement match, a meal allowance); `value_text` carries the qualitative value
    ("20 days", "Unlimited", "24 weeks"). `detail` keeps the raw field blob so we
    can re-present benefits our own way without re-fetching. RoleBand's own
    benefits are the bundled dataset (`profiles/benefits_dataset/`), never rows here.
    """

    __tablename__ = "company_benefit"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_slug: Mapped[str] = mapped_column(
        ForeignKey("company_profile.slug", ondelete="CASCADE"), index=True
    )
    perk_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # the source's perk id
    category: Mapped[str] = mapped_column(String(48), index=True)  # the publisher's category label
    name: Mapped[str] = mapped_column(String(128))
    value_usd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)  # raw field blob
    #: ISO 3166-1 alpha-2, where the policy applies; NULL is unknown, never global.
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    provider: Mapped[str] = _provider_column()
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    #: As on `company_comp_level`: retired by a clean snapshot, never deleted.
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "provider", "company_slug", "name", "country",
            name="uq_company_benefit", postgresql_nulls_not_distinct=True,
        ),
    )


class CompanyFact(Base):
    """Append-only claim: one source's assertion about one company field.

    The substrate stores CLAIMS, not values. One source says a company is private;
    another gives a ticker. Both are recorded. `profiles/resolve.py` picks a winner by
    (source trust, recency) — manual always wins — and flags the disagreement as a
    conflict, which is what drives the manual-enrichment workflow.

    Never updated in place: a new observation is a new row, so we can always answer
    "what did we believe, when, and on whose word?". Same append-only contract as
    `job_observations`.
    """

    __tablename__ = "company_fact"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_slug: Mapped[str] = mapped_column(
        ForeignKey("company_profile.slug", ondelete="CASCADE"), index=True
    )
    field: Mapped[str] = mapped_column(String(48), index=True)  # ticker|is_public|headcount|...
    # JSONB so one table carries str/int/bool/null claims without per-type columns.
    value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(String(32), index=True)  # profiles/sources.py, or a plugin id
    confidence: Mapped[float] = mapped_column(default=1.0)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_company_fact_lookup", "company_slug", "field", "source"),
    )


class CompanyPrice(Base):
    """Latest-quote cache: one row per public company.

    A stock price is high-frequency time-series, NOT a trust-resolved identity
    claim, so it lives here rather than in `company_fact`. The `ticker` it quotes
    comes from the resolved `CompanyProfile.ticker` (which the claim system keeps
    current across an IPO); this table only caches the last quote so the dashboard
    never has to call a market feed on read.

    Upserted in place — unlike observations, there is no analytical value in
    keeping every intraday snapshot of "latest". The daily bars in
    `company_price_history` are the longitudinal record.
    """

    __tablename__ = "company_price"

    company_slug: Mapped[str] = mapped_column(
        ForeignKey("company_profile.slug", ondelete="CASCADE"), primary_key=True
    )
    ticker: Mapped[str] = mapped_column(String(12))
    price: Mapped[float] = mapped_column(Numeric(14, 4))
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    # Absolute + percent move for the quoted session (vs prior close).
    change_abs: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    as_of: Mapped[datetime] = mapped_column(Date)  # market date of the quote
    source: Mapped[str] = mapped_column(String(24), default="market")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CompanyPriceBar(Base):
    """One daily OHLC bar for one company. The price-history longitudinal record.

    Append/upsert by (company_slug, date): a re-fetch of an already-stored day
    corrects it in place rather than duplicating. Powers the profile sparkline.
    """

    __tablename__ = "company_price_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    company_slug: Mapped[str] = mapped_column(
        ForeignKey("company_profile.slug", ondelete="CASCADE"), index=True
    )
    date: Mapped[datetime] = mapped_column(Date)
    open: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    high: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    low: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    close: Mapped[float] = mapped_column(Numeric(14, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(24), default="market")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("company_slug", "date", name="uq_company_price_bar"),
    )


# --------------------------------------------------------------------------- #
# Skills — closed catalogue + evidence-grounded per-job requirements.
# The sole skill system: powers job detail, the Statistics analytics tabs, and
# cluster labels.
# --------------------------------------------------------------------------- #


class SkillConcept(Base):
    """One canonical skill concept — DB projection of catalog.yaml.

    The YAML file is the source of truth; `tracker.skills.sync` upserts this
    table to exactly one catalogue version. Stable `id`/`slug` are the identity
    every consumer (evidence, analytics, matching) keys on.
    """

    __tablename__ = "skill_concepts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display: Mapped[str] = mapped_column(String(96))
    # technology|professional_skill|industry|behavioral_competency|language
    facet: Mapped[str] = mapped_column(String(32), index=True)
    category: Mapped[str] = mapped_column(String(32))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("skill_concepts.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[str] = mapped_column(Text)
    external_refs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|deprecated
    taxonomy_version: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SkillAlias(Base):
    """Surface forms for one concept, with match mode + context guards.

    Projection of the catalogue's alias entries (same review provenance). The
    extractor compiles these from the YAML directly; this table exists for
    joins/inspection and to keep DB state equal to one catalogue version.
    """

    __tablename__ = "skill_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    concept_id: Mapped[int] = mapped_column(
        ForeignKey("skill_concepts.id", ondelete="CASCADE"), index=True
    )
    alias: Mapped[str] = mapped_column(String(96))
    match_mode: Mapped[str] = mapped_column(String(16), default="exact_ci")
    required_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    excluded_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="catalog")

    __table_args__ = (UniqueConstraint("concept_id", "alias", name="uq_skill_alias"),)


class SkillRelation(Base):
    """Reviewed non-containment relations between concepts (matching fuel).

    kind: related | equivalent_alternative | prerequisite. Containment stays in
    skill_concepts.parent_id. No writer and no reader yet (`db/ownership.py`).
    """

    __tablename__ = "skill_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_id: Mapped[int] = mapped_column(
        ForeignKey("skill_concepts.id", ondelete="CASCADE"), index=True
    )
    to_id: Mapped[int] = mapped_column(
        ForeignKey("skill_concepts.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="catalog")

    __table_args__ = (
        UniqueConstraint("from_id", "to_id", "kind", name="uq_skill_relation"),
        CheckConstraint("from_id <> to_id", name="ck_skill_relation_no_self"),
    )


class JobSkill(Base):
    """Current requirement snapshot: one row per (job, concept) with evidence.

    Derived + recomputable (a deliberate exception to observation append-only).
    Replaced atomically per job by the extractor. `importance_*` is role
    emphasis in THIS posting; independent of confidence and never a user
    match signal. Rows with band='context' are stored for audit, hidden from
    the API/analytics.
    """

    __tablename__ = "job_skills"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[int] = mapped_column(
        ForeignKey("skill_concepts.id", ondelete="CASCADE"), index=True
    )
    importance_score: Mapped[int] = mapped_column(Integer)  # 0..100, ordering only
    importance_band: Mapped[str] = mapped_column(String(12))  # core|important|supporting|context
    confidence: Mapped[str] = mapped_column(String(8))  # high|medium|low
    modality: Mapped[str] = mapped_column(String(16))  # required|preferred|used_in_role|context
    proficiency: Mapped[str] = mapped_column(String(16), default="unspecified")
    evidence_count: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str] = mapped_column(String(32))
    extractor_version: Mapped[str] = mapped_column(String(16))
    taxonomy_version: Mapped[str] = mapped_column(String(16))
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    evidence: Mapped[list[JobSkillEvidence]] = relationship(
        back_populates="job_skill", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("job_id", "concept_id", name="uq_job_skill"),)


class JobSkillEvidence(Base):
    """One grounded evidence unit behind a job_skill row.

    `quote` is an exact substring of the stored section content and
    `[start_offset, end_offset)` round-trips to it — enforced by the grounding
    validator before insert. No evidence row, no displayed skill.
    """

    __tablename__ = "job_skill_evidence"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_skill_id: Mapped[int] = mapped_column(
        ForeignKey("job_skills.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[int] = mapped_column(ForeignKey("skill_concepts.id", ondelete="CASCADE"))
    section_key: Mapped[str | None] = mapped_column(String(64), nullable=True)  # NULL => title
    section_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_index: Mapped[int] = mapped_column(Integer, default=0)
    quote: Mapped[str] = mapped_column(Text)
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    # minimum|preferred|responsibility|team|company|benefit|legal|application|other
    aspect: Mapped[str] = mapped_column(String(16))
    modality: Mapped[str] = mapped_column(String(16))
    proficiency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    years: Mapped[float | None] = mapped_column(Float, nullable=True)
    actor: Mapped[str] = mapped_column(String(12))  # candidate|role|team|company|other
    boilerplate_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    extractor: Mapped[str] = mapped_column(String(12), default="dictionary")  # dictionary|model
    confidence: Mapped[str] = mapped_column(String(8), default="high")
    score: Mapped[int] = mapped_column(Integer, default=0)  # this unit's evidence score

    job_skill: Mapped[JobSkill] = relationship(back_populates="evidence")


class JobQualification(Base):
    """Structured non-skill requirements: experience/education/credential/
    eligibility/clearance/travel/schedule. Same grounding contract as skill
    evidence; never forced into skill_concepts."""

    __tablename__ = "job_qualifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    display: Mapped[str] = mapped_column(Text)
    value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # normalized (years, degree…)
    modality: Mapped[str] = mapped_column(String(12))  # required|preferred
    confidence: Mapped[str] = mapped_column(String(8), default="high")
    section_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    section_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    quote: Mapped[str] = mapped_column(Text)
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    extractor_version: Mapped[str] = mapped_column(String(16))


class SkillCandidate(Base):
    """Discovery/review backlog for terms outside the catalogue.

    Never read by user APIs or analytics. Promotion = a reviewed catalog.yaml
    diff; this row then records verdict + the promoted concept for
    backfill-on-promotion (re-extract exactly the jobs that proposed it).
    """

    __tablename__ = "skill_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(96), unique=True)
    proposed_facet: Mapped[str | None] = mapped_column(String(32), nullable=True)
    job_count: Mapped[int] = mapped_column(Integer, default=0)
    requirement_context_count: Mapped[int] = mapped_column(Integer, default=0)
    sample_quotes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    ambiguity_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)  # model/provider/version
    verdict: Mapped[str] = mapped_column(String(16), default="open")  # open|promoted|rejected
    verdict_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    concept_id: Mapped[int | None] = mapped_column(
        ForeignKey("skill_concepts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# --------------------------------------------------------------------------- #
# Derivation state and usage events.
# --------------------------------------------------------------------------- #


class DerivationState(Base):
    """Per-pass freshness/health projection for the derivation registry.

    One row per POST_PASSES entry that has actually run, keyed by pass name.
    `run_post_passes` upserts it after each executed pass (a capped/disabled
    skip leaves the prior row untouched). `/api/status` joins the enabled pass
    table against these rows so a pass that is registered but has never run —
    or is failing — shows up as stale instead of silently producing nothing.
    Not user data; safe to rebuild by re-running.
    """

    __tablename__ = "derivation_state"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_ok_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status: Mapped[str] = mapped_column(String(16), default="ok")  # ok|error
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)


class UsageEvent(Base):
    """One usage-sharing event waiting to be sent, or sent in the last 30 days.

    The outbox of `tracker.usage_stats` (docs/architecture.md): written
    only while the user shares the event's consent group, read by the daily
    flush, which claims unsent rows (`attempted_at`), posts them to the usage
    endpoint and marks them `sent_at`. `dedupe_key` makes every write an upsert: a daily
    count is one row per day and property set that three processes increment
    together; a milestone is one row ever. Sent rows are pruned after 30 days;
    rows unsent when the user stops sharing are marked
    `withdrawn_at` and kept, never sent. Not domain data: no job, company or
    text is stored here, only catalogue values (`usage_stats.registry`).
    """

    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    #: `count:<day>:<name>:<props hash>`, `milestone:<name>`, `daily:<day>:<name>`,
    #: `exception:<day>:<fingerprint>`.
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(64))
    consent_group: Mapped[str] = mapped_column(String(16))
    props: Mapped[dict] = mapped_column(JSONB, default=dict)
    day: Mapped[date | None] = mapped_column(Date, nullable=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    first_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --------------------------------------------------------------------------- #
# Plugins and the reference data they keep current.
# --------------------------------------------------------------------------- #


class PluginInstall(Base):
    """One installed plugin: its pinned code, its manifest, and the user's approval.

    `fingerprint` is sha256 over the manifest bytes, the source tree
    (`code_sha`) and the lock file, recomputed on every install or update. The plugin may run only while
    `approved_fingerprint` equals it: any change to code, manifest or lock lapses
    the approval. `approved_text` keeps what the user was
    shown, as `record_consent` keeps a consent's wording.

    A removed plugin keeps its row (`removed_at`): its rows in the slot tables
    stay, and the registry must still know the provider is a plugin's, so they
    stay hidden instead of reading as core-written.

    `schedule` is the user's choice of how often its jobs run (manual | daily |
    weekly | monthly), NULL = each job's manifest schedule. `paused_at` holds
    every automatic run while the plugin stays on and answers: Pause, then
    Start.

    `robots_consent` is the user's choice to let the plugin read pages its sites'
    robots rules disallow: per declared host, the
    sha256 of the robots file they were shown, so a site that changes its file is
    asked about again. NULL = it follows every site's rules. `robots_seen` is the
    file the host last read per host, which says when a consent has lapsed.
    """

    __tablename__ = "plugin_install"

    plugin_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(64))
    source_dir: Mapped[str] = mapped_column(Text)
    #: sha256 over the installed source tree; the host recomputes it before every run.
    code_sha: Mapped[str] = mapped_column(String(64))
    #: The git commit installed from, when the source was a repository (informational).
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manifest_sha: Mapped[str] = mapped_column(String(64))
    lock_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: The validated manifest as installed (`PluginManifest.model_dump`).
    manifest: Mapped[dict] = mapped_column(JSONB)
    fingerprint: Mapped[str] = mapped_column(String(64))
    approved_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_text: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    schedule: Mapped[str | None] = mapped_column(String(16), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: The SDK version installed into its venv; NULL when not recorded.
    sdk_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: {host: sha256 of the robots file the user allowed it past}; NULL = it follows them.
    robots_consent: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    robots_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: {host: sha256 of the robots file the host last read}, written each run.
    robots_seen: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class PluginRun(Base):
    """One run of one plugin job, as the host recorded it.

    `outcome` is the host's verdict, never the plugin's: running | clean |
    partial | bounded | stopped | error (the SDK fake host's vocabulary, pinned
    in tests/test_plugin_sdk.py). A company published whole (`complete=True`)
    is read, and retires the rows the run did not repeat for it, at that publish
    whatever the run's end; which plugin answers is the user's choice
    (enabled and approved), never a run's outcome.
    `fingerprint` is the install fingerprint the run executed under.
    """

    __tablename__ = "plugin_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    plugin_id: Mapped[str] = mapped_column(
        ForeignKey("plugin_install.plugin_id", ondelete="CASCADE"), index=True
    )
    job: Mapped[str] = mapped_column(String(32))
    #: schedule | sync | manual | cli
    trigger: Mapped[str] = mapped_column(String(16))
    fingerprint: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16), default="running", server_default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_done: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Slots this run published at least one batch to, and per-slot counts.
    published: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    refusals: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: What the run did, in the plugin's own words (`ctx.summary`): its
    #: latest, kept whatever the run's end. Third-party text, shown as written.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The plugin ended this run with its pass unfinished (`end.more`): the
    #: next run continues it soon, and the schedule counts from the pass's start.
    continues: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('running', 'clean', 'partial', 'bounded', 'stopped', 'error')",
            name="ck_plugin_run_outcome",
        ),
        Index("ix_plugin_run_clean", "plugin_id", "outcome"),
    )


class PluginState(Base):
    """A plugin's own small key/value store (`ctx.state`), kept between runs."""

    __tablename__ = "plugin_state"

    plugin_id: Mapped[str] = mapped_column(
        ForeignKey("plugin_install.plugin_id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PluginReport(Base):
    """A number a plugin asked the user to see beside it (`ctx.report`):
    the latest value per key, with the plugin's own words for it. Kept across
    runs and updates; withdrawn by the plugin, gone with the install."""

    __tablename__ = "plugin_report"

    plugin_id: Mapped[str] = mapped_column(
        ForeignKey("plugin_install.plugin_id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger)
    label: Mapped[str] = mapped_column(String(160))
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PluginCoverage(Base):
    """When a provider last tried and last published a slot for a company.

    The freshness the API reports for a provider's data. The key is the
    provider value, not the install, so it outlives a removal the
    same way the rows do.

    `complete_at` is when the provider first published the company whole
    (`complete=True`): from then on its rows for that company in that slot are
    read, without waiting for the rest of a pass. NULL = never read
    whole, so its rows there stay unread.
    """

    __tablename__ = "plugin_coverage"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    slot: Mapped[str] = mapped_column(String(32), primary_key=True)
    company_slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    complete_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReferenceState(Base):
    """The one row saying which reference set the stored estimates match.

    `applied_fp` is what every pay reader uses, so a list and a detail never mix
    sources mid-switch. While a re-estimate runs, `target_fp` names where
    it is going and `cursor_job_id` how far it got; a different target restarts
    the cursor.
    """

    __tablename__ = "reference_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_fp: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: The ordered active providers `applied_fp` was computed from.
    applied_providers: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    target_fp: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: The ordered active providers `target_fp` was computed from.
    target_providers: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    #: The moved report so far, carried across batches and processes; it becomes
    #: the `reference_change.moved_report` when the last batch flips `applied_fp`.
    target_report: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    cursor_job_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_change_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (CheckConstraint("id = 1", name="ck_reference_state_singleton"),)


class ReferenceChange(Base):
    """One switch of the reference set: the estimates moved together, once.

    A provider toggle, a clean plugin refresh or a new atlas edition moves many
    estimates at the same moment; it is recorded as one change (with its moved
    report), never as thousands of per-job `changed` events. `comp-trends`
    serves `at` as a chart marker.
    """

    __tablename__ = "reference_change"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    from_fp: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_fp: Mapped[str] = mapped_column(String(64))
    providers: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    moved_report: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))


# --------------------------------------------------------------------------- #
# The supervisor's jobs: requests, runs and published status.
# --------------------------------------------------------------------------- #


class JobRequest(Base):
    """A durable "run this job now", from the API, a command or the supervisor itself.

    A doorbell with arguments, delivered at least once. The work it asks for lives
    in its domain queue (`SyncScheduleState.manual_requested_at` for scans, the
    plugin schedule for plugin runs), so a replayed request starts a job that finds
    nothing left to do. While queued, requests with one `coalesce_key` are one row
    (`uq_job_requests_queued`): ten clicks during a scan ring once.

    `state`: queued | claimed | done | cancelled | failed. A request is claimed in
    the transaction that opens its `job_runs` row; `job_runs.request_id` links them,
    and a request whose run was lost is queued again, up to its attempt limit.
    """

    __tablename__ = "job_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job: Mapped[str] = mapped_column(String(32))
    #: One instance of a job: the job's name, or `<job>:<argument>` for a job that
    #: runs once per argument (`plugin_run:<plugin id>`).
    key: Mapped[str] = mapped_column(String(96))
    args: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    coalesce_key: Mapped[str] = mapped_column(String(160))
    #: Who rang: sync | first_scan | scope | settings | catch_up | plugin | cli ...
    requested_by: Mapped[str] = mapped_column(String(32))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    state: Mapped[str] = mapped_column(String(16), default="queued", server_default="queued")
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "uq_job_requests_queued",
            "coalesce_key",
            unique=True,
            postgresql_where=text("state = 'queued'"),
        ),
        Index("ix_job_requests_key_state", "key", "state"),
        CheckConstraint(
            "state IN ('queued', 'claimed', 'done', 'cancelled', 'failed')",
            name="ck_job_requests_state",
        ),
    )


class JobRun(Base):
    """One process the supervisor started or adopted, as the supervisor saw it.

    `state` is the process's, never the work's: starting | running | exited |
    timed_out | cancelled | lost | spawn_failed. What the work did is `result`, the
    child's own account (`kind` ran | nothing_due | waiting | busy | refused, a
    reason, links), and the domain record it links to (`scrape_runs`,
    `plugin_run`), which stays the outcome of a collection.

    At most one live run per key (`uq_job_runs_live`), whichever process opened it:
    a second supervisor on the same database cannot start a duplicate. The process
    identity (`pid`, `proc_started_at` and the `--run <id>` marker in its argv) lets
    a restarted supervisor adopt a run it did not start: the OS recycles PIDs, so
    a PID alone proves nothing.
    """

    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job: Mapped[str] = mapped_column(String(32))
    key: Mapped[str] = mapped_column(String(96))
    #: schedule | request | change
    trigger: Mapped[str] = mapped_column(String(16))
    request_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_requests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    state: Mapped[str] = mapped_column(String(16), default="starting", server_default="starting")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pgid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proc_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    code_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    log_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Size of the log when the run started: where its output begins, until the
    #: file rotates past it.
    log_offset: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: The log has rotated since the run started: `log_offset` no longer points
    #: at its output in `log_path`.
    log_rotated: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    #: What the child last reported while running: done, total, note, pending, until.
    progress: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index(
            "uq_job_runs_live",
            "key",
            unique=True,
            postgresql_where=text("state IN ('starting', 'running')"),
        ),
        Index("ix_job_runs_key_started", "key", "started_at"),
        CheckConstraint(
            "state IN ('starting', 'running', 'exited', 'timed_out', 'cancelled', 'lost', 'spawn_failed')",
            name="ck_job_runs_state",
        ),
    )


class JobStatus(Base):
    """What each job is doing now, as the supervisor last published it.

    One row per job key, read by `/api/status`. A waiting job has no run: its row
    says why (`reason`) and since when. The row keyed `supervisor` is the
    supervisor's own heartbeat; an `updated_at` older than the reader's bound means
    nothing is dispatching, whatever the other rows say.
    """

    __tablename__ = "job_status"

    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    job: Mapped[str] = mapped_column(String(32))
    #: idle | waiting | queued | starting | running | stopping | disabled
    state: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: The live or latest run; not a foreign key, because runs are pruned.
    run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PriceFeedRequest(Base):
    """One request to the stock price provider, reserved before it is sent.

    The budget ledger. A provider's limits count every request, a failure, a
    timeout and a refusal included, so the hour, the day and the month are counted
    from these rows, never inferred from stored quotes. `key_fingerprint` is a hash
    prefix of the key that made the request, never the key itself.

    `outcome`: pending | ok | no_data | unauthorized | rate_limited | timeout |
    offline | error.
    """

    __tablename__ = "price_feed_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16))
    key_fingerprint: Mapped[str] = mapped_column(String(16))
    #: bars | retry
    purpose: Mapped[str] = mapped_column(String(16))
    symbol: Mapped[str] = mapped_column(String(16))
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
