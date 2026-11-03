"""Application settings plus the company table derived from the blueprint.

Taxonomy data lives in `tracker/taxonomy/` (roles, tracks, categories,
locations); this module keeps `Settings` and `COMPANIES`, and re-exports
the location-group surface for callers that import it from here.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypedDict

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from tracker.blueprint import BLUEPRINT
from tracker.platform.database_presets import PRESETS, DatabasePreset, PresetName, preset_for
from tracker.platform.embedded_db import DEFAULT_LOCALE
from tracker.platform.memory import total_memory_bytes
from tracker.platform.paths import PACKAGED

if TYPE_CHECKING:
    from tracker.platform.embedded_db import EmbeddedServer

# Re-exported for callers that import them from here; they live in
# tracker.taxonomy.locations.
from tracker.taxonomy.locations import (  # noqa: F401
    LOCATION_GROUPS,
    all_location_group_slugs,
    default_enabled_location_groups,
    enabled_location_groups,
)

# Extensions the schema cannot start without: `vector` backs the embedding
# column and its HNSW index, `pg_trgm` backs the two fuzzy-search indexes in
# the schema baseline. Asserted at server start so a missing one is a
# clear error rather than a half-applied migration.
REQUIRED_EXTENSIONS = ("vector", "pg_trgm")
#: `backend/.env`, read wherever a process starts: the background agents start
#: in `backend/`, a person's shell anywhere.
ENV_FILE = None if PACKAGED else Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    # Every setting reads its environment variable with the `ROLEBAND_` prefix
    # (`scraper_min_delay_seconds` is `ROLEBAND_SCRAPER_MIN_DELAY_SECONDS`), so
    # a name another tool also uses (`POSTGRES_DB`, `API_HOST`,
    # `ANTHROPIC_API_KEY`), set in an ambient shell, can never reconfigure the
    # app. A field with a `validation_alias` reads exactly that name instead.
    model_config = SettingsConfigDict(
        env_prefix="ROLEBAND_", env_file=ENV_FILE, extra="ignore", populate_by_name=True,
    )

    # Database resolution, highest precedence first:
    #   1. `database_url_override` (env ROLEBAND_DATABASE_URL) — external server,
    #      the escape hatch for CI, power users, and debugging.
    #   2. embedded Postgres (`db_embedded`), the shipped default: the app owns
    #      its own server, so a user installs and configures nothing.
    #   3. the `postgres_*` fields below — the :5433 docker container.
    database_url_override: str | None = Field(default=None, validation_alias="ROLEBAND_DATABASE_URL")
    db_embedded: bool = True
    # PGDATA for the embedded server. Defaults to a per-user application data
    # directory rather than the checkout: an install directory is replaced by
    # upgrades, and a checkout under iCloud/OneDrive puts Postgres under file
    # sync. Dev checkouts point this at the repo; worktrees share the main
    # checkout's PGDATA.
    db_pgdata: str | None = Field(default=None, validation_alias="ROLEBAND_PGDATA")
    db_locale: str | None = Field(default=None, validation_alias="ROLEBAND_DB_LOCALE")
    # The embedded server's memory preset (`platform/database_presets.py`) is
    # picked from the computer's memory at each start; this names one instead,
    # for support. The app offers no such choice.
    db_preset: PresetName | None = Field(default=None, validation_alias="ROLEBAND_DB_PRESET")

    postgres_user: str = "roleband"
    postgres_password: str = "roleband"
    postgres_db: str = "roleband"
    postgres_port: int = 5433

    # Where the always-on API serves (the supervisor starts it on this pair);
    # the health check derives its base URL from these.
    api_host: str = "127.0.0.1"
    api_port: int = 8010
    # Host names the API answers to beyond the loopback names (always trusted)
    # and `api_host` itself. Any other Host is refused 400 — the
    # DNS-rebinding defence — and an unsafe request from a page on any other
    # host is refused 403 (`tracker/api/boundary.py`). An operator serving on a
    # LAN name adds it as a JSON list: ROLEBAND_API_TRUSTED_HOSTS='["mybox.local"]'.
    api_trusted_hosts: list[str] = Field(
        default_factory=list, validation_alias="ROLEBAND_API_TRUSTED_HOSTS"
    )
    # Origins a dashboard dev server answers from, allowed cross-origin by the
    # API (Vite's default port). A dev server on another port adds its origin
    # as a JSON list: ROLEBAND_DEV_ORIGINS='["http://127.0.0.1:5174"]'.
    dev_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        validation_alias="ROLEBAND_DEV_ORIGINS",
    )
    postgres_host: str = "localhost"

    scraper_user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    )
    scraper_min_delay_seconds: float = 2.0
    scraper_max_retries: int = 4
    # The proxy the `proxy` fetch tier routes its headless browser through,
    # e.g. `http://user:pass@host:port`. Unset = the tier is not
    # available and a source that needs it is `unattempted`. Never logged:
    # it may carry credentials. Used only for a walled, consented company.
    scraper_proxy_url: SecretStr | None = None
    # Parallelize distinct ATS backends. Companies sharing one backend queue on
    # one collector stream and one `scraper_min_delay_seconds` pacer, so a lane
    # is one host at its own pace and a wider run raises no site's rate. 12
    # because a first sync over every company flattens there: wider runs finish
    # little sooner, since every width ends at the longest board's own time.
    # Background shards stay small whatever this is.
    scraper_max_concurrent_sources: int = Field(default=12, ge=1, le=24)
    # Bulkhead bounds, so a source that fails *slowly* cannot consume the whole
    # run. Two bounds, because one number cannot tell "slow but working" from
    # "hung":
    #
    #   stall  — sliding. Silence for this long is the source's own pathology and
    #            is recorded as its error. Must stay well above the worst legitimate
    #            gap between two units of work: `scraper_max_retries` attempts of
    #            backoff (capped at RetryPolicy.max_backoff=30s each) plus pacing,
    #            or a polite source obeying Retry-After is judged dead.
    #   budget — absolute ceiling. A source still producing when this expires is
    #            `bounded`: our threshold, not its fault, so it counts nothing
    #            against the source. Catches the pathological slow trickle a stall
    #            window never can.
    #
    # The budget is a backstop, not the working bound: some healthy boards
    # legitimately need most of half an hour.
    scraper_source_stall_seconds: int = Field(default=90, ge=1)
    scraper_source_budget_seconds: int = Field(default=1800, ge=1)
    # Wall-clock seconds unaccounted for by the monotonic clock before a source's
    # run counts as interrupted by host suspension rather than by the source
    # (`SuspensionMonitor`). Clean runs show gaps well under a minute, while a
    # run broken by a real suspension (sockets dead on resume) shows gaps of
    # several minutes. 60s clears ordinary scheduler jitter and NTP slew by an
    # order of magnitude and still catches a short real suspension. 0 disables
    # the detection.
    scraper_host_suspension_seconds: int = Field(default=60, ge=0)
    # Consecutive *requests* that exhaust their retries on one backend scope
    # before further sends fail fast (the unit is the request, so the
    # threshold is independent of `scraper_max_retries`: counted per attempt,
    # one exhausted request would trip it). Run-scoped — the next run always
    # re-probes. An open circuit admits one probe per cooldown (doubling on
    # failure); a detected WAF block (identical no-Retry-After status across
    # two full requests' attempts) admits none for the rest of the run.
    scraper_breaker_threshold: int = Field(default=5, ge=1)
    scraper_breaker_cooldown_seconds: float = Field(default=60.0, ge=1.0)

    # Per-binding learned bounds. The constants above are one number for
    # sources whose real durations span seconds to most of half an hour; these
    # turn each binding's own measured behavior into its bound, inside the
    # operator limits above — `scraper_source_budget_seconds` stays the hard
    # ceiling a learned budget may never exceed.
    #: Multiplier over observed p95. Room for a board to grow between runs
    #: without the bound firing; too low re-truncates on ordinary growth.
    scraper_tuning_headroom: float = Field(default=1.5, ge=1.0, le=10.0)
    #: Applied to the CURRENT bound when it fired. A bound that fired proves
    #: only that it was too low, never by how much — so the response is a
    #: doubling, not a fit to an observation the bound itself truncated.
    scraper_tuning_escalate: float = Field(default=2.0, ge=1.0, le=10.0)
    #: Maximum fraction a bound may fall in one run. The ratchet: a quiet day
    #: must not be able to re-cut a source tomorrow.
    scraper_tuning_decay: float = Field(default=0.1, ge=0.0, le=1.0)
    #: Observations kept per row to compute p95 from. Bounded so the row cannot
    #: grow without limit, long enough that one odd night cannot move the p95.
    scraper_tuning_samples: int = Field(default=20, ge=2, le=200)

    # Adaptive sync scheduler. A short launchd tick selects due bindings; it
    # does not repeat the roster. Discovery is capped + non-authoritative;
    # reconciliation is complete + closure-capable. Provider cooldown state is
    # persisted in Postgres, so a fresh process cannot erase a recent block.
    sync_scheduler_enabled: bool = True
    sync_scheduler_max_providers: int = Field(default=2, ge=1, le=5)
    #: Hard ceiling on one shard, whatever the per-provider depths add up to.
    #: A shard is meant to be a SMALL pipeline run (the scheduler's docstring),
    #: and `provider_pacing` decides the mix inside it; this is the one number
    #: that bounds the whole tick regardless of how the roster grows.
    sync_scheduler_max_bindings: int = Field(default=8, ge=1, le=40)
    #: The schedule plan: every company read on one clock, a full
    #: read when the computer comes on and a quick check on each repeat, in
    #: place of each company's own drifting timer. Off = the per-binding timers
    #: and their small shards.
    sync_schedule_plan_enabled: bool = True
    #: A planned run is a full read when the last full read of the whole roster
    #: is at least this old, so an always-on machine still gets one a day. Under
    #: 24h so a daily full read does not slide later by its own length each day.
    schedule_plan_full_after_hours: int = Field(default=20, ge=6, le=48)
    #: Off for at least this long before a tick that finds the machine awake
    #: again = the computer was turned on, and the plan's next run is full.
    schedule_plan_wake_gap_minutes: int = Field(default=120, ge=30, le=720)
    #: Seconds one background pass over every other company may run:
    #: the unit that reads the radar and the followed set again. Passes run back
    #: to back inside one process. A pass's end stops NEW board reads;
    #: a read under way always finishes.
    directory_sweep_budget_seconds: int = Field(default=540, ge=10, le=3000)
    #: Seconds one directory process keeps running passes before it exits.
    #: launchd starts the next 600s after an EXIT, not after a start, so every
    #: exit costs ten idle minutes; one pass per process would sit idle about
    #: half the time. Three hours keeps the idle share small and still picks up
    #: newly installed code the same afternoon.
    directory_sweep_run_seconds: int = Field(default=10_800, ge=10, le=86_400)
    sync_discovery_cadence_seconds: int = Field(default=21_600, ge=3600)
    sync_reconcile_cadence_seconds: int = Field(default=86_400, ge=21_600)
    #: SCHEDULING freshness: a binding whose last authoritative (closure-capable)
    #: read is older than this is owed one. Not display staleness: see
    #: `coverage_stale_after_days`, which is what a person is told.
    sync_authoritative_stale_hours: int = Field(default=30, ge=24, le=168)
    #: DISPLAY freshness: a followed company with no full scan this long is
    #: "stale" in the coverage register and its notice. Three daily reconcile
    #: cycles: one failed night, or two, is a transient the next scan usually
    #: clears.
    coverage_stale_after_days: float = Field(default=3.0, ge=1.0, le=30.0)
    #: DIRECTORY cadence: a directory company is read again this long after its
    #: last check, every outcome alike, an empty board included: daily, like the
    #: companies the user follows. Also the age past which a part-read cursor
    #: restarts.
    directory_check_due_hours: float = Field(default=24.0, ge=1.0, le=336.0)
    #: RETRY pacing: seconds between connectivity checks while a directory pass
    #: finds no job site reachable (the network is ours to blame).
    directory_offline_recheck_seconds: float = Field(default=30.0, ge=1.0, le=600.0)
    #: How often a running directory pass asks whether to stop: a manual sync
    #: waiting, or the set unfollowed. Shared by every lane.
    directory_yield_check_seconds: float = Field(default=15.0, ge=1.0, le=600.0)
    #: The least time between the two complete listings that must miss a posting
    #: before it closes. Below the 24 h reconcile cadence, so a daily
    #: scan whose start drifts a few hours still counts as the second miss.
    closure_second_miss_min_hours: float = Field(default=20.0, ge=1.0, le=72.0)
    sync_provider_backoff_seconds: int = Field(default=900, ge=60)
    sync_provider_blocked_cooldown_seconds: int = Field(default=86_400, ge=3600)
    # Connector capabilities, not company policy. Apple/Google expose
    # newest-first listings; Greenhouse/Ashby are one-request board feeds.
    # Other connectors remain reconciliation-only until their frontier/order
    # contract is proven.
    sync_discovery_adapters: frozenset[str] = frozenset(
        {"apple", "google", "greenhouse", "ashby"}
    )
    # Providers we are not permitted to collect from. Empty by default, and
    # deliberately kept: this is the only enforcement path for a denial, read by
    # the scheduler and every supported collection execution path.
    # `source_review.py` records the REASON for a denial in its own per-binding
    # register; it never enforces one.
    sync_policy_denied_providers: frozenset[str] = frozenset()

    long_open_days: int = 45
    high_comp_threshold: int = 700_000

    # Stock prices for public company profiles. No key -> the offline fixture
    # provider is used (deterministic, safe for tests and demos). Set a Tiingo key
    # to fetch live quotes + daily bars.
    tiingo_api_key: str | None = None
    # The price feed's limits, as the request ledger counts them: Tiingo's free
    # plan. A paid plan raises them here.
    price_feed_hourly_limit: int = 50
    price_feed_daily_limit: int = 1000
    price_feed_monthly_symbols: int = 500

    # Semantic embedding model (local, CPU, ONNX). Must have a pinned entry in
    # tracker/semantic/manifest.py; artifacts are app-provisioned, never a pip dep.
    embedding_model: str = "lightonai/DenseOn"
    embedding_dim: int = 768
    #: Wall-clock the pipeline's embed pass may spend before it leaves the rest
    #: of the queue to the next run. A backlog can hold more postings than one
    #: run can encode, and every pass ordered after this one waits while it
    #: works, so the pass yields instead of running the corpus down in one
    #: sitting and starving lineage, similarity, demand and pay metrics of a
    #: refresh for as long as that takes. Checked between
    #: committed chunks, and one chunk always runs: a budget too small to fit a
    #: chunk must still make progress, never stall the corpus. Bulk catch-up
    #: belongs to `tracker.semantic.backfill`, which has no run to outlive.
    embedding_budget_seconds: float = 300.0

    # Smart search (hybrid ranked lexical + semantic + fuzzy).
    search_semantic_enabled: bool = True  # include the vector half in RRF
    search_warm_model_on_startup: bool = True  # provision + preload weights at startup
    search_rrf_k: int = 60  # Reciprocal Rank Fusion constant (standard default)
    #: How long a fetched description stays fresh before a detail-fetch source is
    #: asked again. Only binds where hydration costs a request: a source that
    #: carries its text in the listing response refreshes it every scan for
    #: free. The trade is real: an edited pay band on a detail-fetch source is
    #: noticed within this window rather than within 24h, in exchange for not
    #: re-reading unchanged descriptions nightly.
    description_refresh_days: int = 14
    #: Detail requests one discovery probe may spend. New roles are rare per
    #: probe, so this never binds in normal operation; it exists so
    #: a board dumping hundreds of new rows cannot turn a 6-hourly probe into a
    #: burst. Overflow is deferred to the backfill pass and counted, never dropped.
    scraper_discovery_detail_budget: int = 25
    #: Blank open rows the backfill pass may fill per run. Bounded because it
    #: runs after every scrape; the backlog is normally a few rows, so this only
    #: matters when something has been failing for a while.
    description_backfill_per_run: int = 25
    #: Posting pages read per run for the application form and the structured
    #: pay of postings whose text states no pay. One paced request each; once
    #: the queue is drained a run reads only what is new or changed.
    posting_pages_per_run: int = 25
    #: After a posting page read fails, neither an open nor the background
    #: queue asks for that page again until this long has passed.
    #: Longer than a browsing session and a run's retries, shorter than a day,
    #: so a posting gone since the scan is not asked on every open and a
    #: transient failure is still retried the same day.
    posting_page_retry_hours: float = Field(default=6.0, gt=0)
    #: Keep every posting a sync reads in `posting_inventory`. Off:
    #: nothing is captured or written, retention removes nothing (its window
    #: is measured against touches capture makes), and nothing else changes.
    inventory_enabled: bool = True
    #: An unchanged inventory row is rewritten only when its last touch is older
    #: than this, so a steady board costs no row churn on every scan.
    inventory_touch_hours: float = 12.0
    #: Admit inventory postings a scope save widens into onto the Board at
    #: once. Off: a widening waits for each company's next sync.
    inventory_promotion_enabled: bool = True
    #: Where the scope screens' counts come from:
    #: `catalog`, the per-company tallies in `role_catalog`, or `inventory`,
    #: the postings in `posting_inventory` a save promotes. Switch only when
    #: every followed company has a complete inventory read and
    #: `scripts.bench_inventory_joint` reports no difference.
    scope_counts_source: Literal["catalog", "inventory"] = "catalog"
    #: Under the inventory source, a company with no complete read counts only
    #: the rows read within this many days: a capped read only adds rows, and
    #: without a complete read nothing marks one gone.
    scope_partial_window_days: float = 14.0
    #: Promotion admits only a posting a scan read within this many hours.
    #: A followed company's live rows are touched at least every
    #: `inventory_touch_hours` + one reconcile cadence (36 h at the defaults);
    #: a row older than this was not listed at the last scans, or its company
    #: went unscanned (unfollowed, failing), and must not reach the Board as open.
    inventory_promotion_fresh_hours: float = 48.0
    #: Remove inventory postings no scan has read for the user's chosen time
    #: (Settings > Data retention). Off: nothing is removed.
    inventory_retention_enabled: bool = True
    search_candidate_pool: int = 200  # per-source candidate depth before fusion
    #: Ceiling the pool may grow to when a query matches more than the base.
    #: A bound we impose, so the response reports when it binds rather than
    #: presenting a truncated ranking as the whole result set.
    search_candidate_pool_max: int = 2000
    # Optional LLM query understanding. Off by default, and a query is sent only
    # while AI egress is on; falls back to the local parser whenever disabled,
    # keyless, slow, or erroring — search never breaks.
    search_llm_enabled: bool = False
    anthropic_api_key: str | None = None
    search_llm_model: str = "claude-haiku-4-5"
    search_llm_timeout_seconds: float = 2.5

    # Disclosed-salary-band extraction. Deterministic — it runs in
    # the daily pipeline on every platform with nothing installed and nothing
    # configured, so there is no enablement flag for it and no host it skips on.
    # `intelligence_max_per_run` bounds one pass's transaction: the read is
    # about a millisecond a posting, so the cap rations no model, as the
    # neighbouring passes' caps do not.
    #
    # `apple_fm_enabled` gates no automatic work. It is the
    # Settings > Experimental switch that decides whether the Apple provider may
    # be constructed for the on-demand self-test.
    apple_fm_enabled: bool = False
    intelligence_extract_in_pipeline: bool = True
    intelligence_max_per_run: int = Field(default=500, ge=1)
    # The Apple self-test's generation: a per-job budget, and an input budget
    # that leaves room for the instructions, the schema and the model's output.
    intelligence_timeout_seconds: float = 30.0
    intelligence_context_tokens: int = 8192
    intelligence_input_token_budget: int = 6000
    intelligence_model_id: str = "apple-fm-on-device"

    # Relevance review (advisory): which world an in-scope-but-unclassified
    # posting serves, judged by the world-anchor classifier in the embedding
    # space (~ms/row — the cap bounds a single transaction, it does not ration a
    # model). Family narrowing targets
    # where surface indicators mislead — senior leadership titles that read
    # identically across every world. Empty tuple = review every family (the
    # setting widens, it never disables the task).
    relevance_review_in_pipeline: bool = True
    relevance_review_max_per_run: int = Field(default=500, ge=1)
    relevance_review_families: tuple[str, ...] = (
        "engineering_management",
        "product_management",
        "program_management",
        "technical_program_management",
        "business_operations_strategy",
    )

    # Tiered routing, which the model bench drives (no product task routes).
    # `intelligence_routing_enabled` only decides whether the ladder is
    # consulted; it can never by itself cause egress. `ai_egress_enabled` is
    # the ONLY switch that admits a cloud tier, defaults off, and the DB row
    # set from Settings overrides this env default exactly as the Apple FM
    # toggle does.
    intelligence_routing_enabled: bool = True
    ai_egress_enabled: bool = False

    # Usage sharing (docs/architecture.md): where events go when the user
    # shares. The project token is PostHog's public, write-only key: it can
    # send events to the project and read nothing, so it ships in the code like
    # any analytics snippet. A fork sets its own, or "" to send nothing. Neither
    # setting can turn sharing ON: that is the user's consent alone, and the
    # environment can only turn it off (`usage_stats/kill.py`; the unprefixed
    # `DO_NOT_TRACK` and `CI` it reads are the exception to the prefix rule above).
    usage_stats_project_key: str = Field(
        default="phc_C79qbYQxBdjvHcZf7Zmejxk2MbYy68b5VaFTcBaPGG4x",
        validation_alias="ROLEBAND_USAGE_STATS_KEY",
    )
    usage_stats_host: str = Field(default="https://eu.i.posthog.com", validation_alias="ROLEBAND_USAGE_STATS_HOST")

    # Repost lineage detection: link a near-identical re-listing under a new req_id
    # to the older posting instead of counting it as a brand-new job. Deterministic
    # gates + the existing embedding decide. Title/grade/raw-location/pay
    # contradictions reject; time is display context, never a verdict signal.
    # Runs on FULL scrapes only (capped scrapes skip it, same
    # rule as closure reconciliation). Thresholds are a starting hypothesis — run
    # `python -m tracker.lineage.backfill --calibrate` and tune. See tracker/lineage/.
    lineage_enabled: bool = True
    # Calibrated for the configured 768-dim embedding space from gate-passing
    # candidate percentiles, each checked on two independent half-samples; the
    # percentile each threshold sits at is named beside it. They are specific to
    # the model: values below a model's boilerplate ceiling auto-link unrelated
    # same-family pairs, so a new embedding model needs a fresh calibration.
    lineage_cos_auto: float = 0.955          # auto-link when normalized titles DIFFER (> differ p99)
    lineage_cos_title_equal: float = 0.82    # auto-link when normalized titles are identical (~ equal p5)
    lineage_cos_suspect: float = 0.915       # -> human review queue (~ differ p95)
    lineage_cos_floor: float = 0.89          # below this: reject outright (~ differ p90)
    lineage_title_jaccard_suspect: float = 0.75
    lineage_location_jaccard_min: float = 0.50
    lineage_duplicate_auto: bool = False     # prior-still-open duplicates never auto-link
    lineage_max_size: int = 6
    lineage_word_overlap_min: float = 0.6   # title-equal auto below cos_auto demotes under this word overlap
    lineage_candidates_k: int = Field(default=10, ge=1)
    lineage_max_per_run: int = Field(default=500, ge=1)

    # Twin opportunities: separate openings with strong role identity plus a
    # full-description difference. Time/location/pay are evidence, never gates.
    # The detector never confirms a twin: a person does (`lineage/twins.py`).
    twin_enabled: bool = True
    # Cheap PRE-FILTER, not the verdict: the authoritative content check is
    # `twin_text_jaccard_min` below, which runs after it. Calibrated for the
    # configured embedding space via `tracker.lineage.twin_backfill --calibrate`:
    # it sits below every pair that clears all the other gates, with headroom,
    # so it keeps every twin, skips pairs before the expensive description
    # diff, and guards the one failure mode the text gate cannot:
    # boilerplate-heavy postings whose token overlap clears 0.72 while the work
    # genuinely differs.
    twin_cos_floor: float = 0.86
    # Model-INDEPENDENT (token-set overlap on titles / descriptions): an
    # embedding swap does not move these.
    twin_title_jaccard_min: float = 0.75
    twin_text_jaccard_min: float = 0.72
    twin_max_per_run: int = Field(default=500, ge=1)

    # Place sets: one role listed once per place, decided by rule,
    # never queued for review. A description this short or shorter is too thin
    # to be identity evidence: a boilerplate stub is shared by unrelated roles.
    place_sets_enabled: bool = True
    place_set_min_text_chars: int = Field(default=500, ge=1)

    # Pipeline / supervision robustness knobs (see tracker.watchdog, pipeline).
    #: How often a long run refreshes search, embeddings, pay estimates and
    #: skills over the rows it has written, between companies
    #: (`post_passes.run_refresh_passes`). 0 refreshes after every company.
    scan_refresh_minutes: float = Field(default=15, ge=0)
    #: How long a "running" ScrapeRun may stand for a caller that reads no
    #: heartbeat. Every caller in the tree reads one, so this is a fallback:
    #: a run is orphaned by silence, not by lasting a long time.
    stale_run_minutes: int = 90
    run_heartbeat_seconds: int = 30  # a live run bumps ScrapeRun.heartbeat_at this often
    stale_run_heartbeat_seconds: int = 180  # no heartbeat within this => run is dead (6 missed beats)
    freshness_max_hours: int = 26  # last success older than this => data is stale
    backup_max_age_hours: int = 36  # newest dump older than this => backups are failing
    advisory_lock_key: int = 91237  # fixed pg_advisory_lock key guarding overlap
    # Its own key, not the scrape key: a re-embed and a scrape may safely run
    # together (the scrape's embed pass is incremental), but two embedders may
    # not — they rewrite the same vectors. Held by `semantic/backfill.run`, so
    # a hand-run backfill is visible to the API, which a PID file cannot be.
    reembed_lock_key: int = 91238
    # Derived files rebuilt on demand and keyed by what they were built from
    # (the built-in pay rows). Losing it costs a rebuild.
    cache_dir_override: str | None = Field(default=None, validation_alias="ROLEBAND_CACHE_DIR")
    # Our own dataset as a pay source, on by default: with no pay plugin on,
    # RoleBand answers pay from its own data. `ROLEBAND_BUILTIN_PAY=false`
    # turns it off.
    builtin_pay_enabled: bool = Field(default=True, validation_alias="ROLEBAND_BUILTIN_PAY")

    def cache_dir(self) -> Path:
        if self.cache_dir_override:
            return Path(self.cache_dir_override).expanduser()
        return Path.home() / ".roleband" / "cache"

    # Installed plugins: `<id>/{src,venv,data}`. Beside the
    # database for the same reasons (`embedded_pgdata`): outside the checkout,
    # no space in the path, survives reinstalling the app.
    plugins_dir_override: str | None = Field(default=None, validation_alias="ROLEBAND_PLUGINS_DIR")
    # Plugins are a preview: off, Settings says they are coming and the API
    # lists none. `ROLEBAND_PLUGINS=true` shows them. Installing from the
    # command line works either way.
    plugins_enabled: bool = Field(default=False, validation_alias="ROLEBAND_PLUGINS")

    def plugins_dir(self) -> Path:
        if self.plugins_dir_override:
            return Path(self.plugins_dir_override).expanduser()
        return Path.home() / ".roleband" / "plugins"

    def embedded_pgdata(self) -> Path:
        """Where the embedded cluster lives. See `db_pgdata` for why not the checkout.

        A dotted home directory is portable, sync-free, and survives
        reinstalling the app. The embedded-server adapter quotes paths that
        contain spaces or shell syntax.
        """
        if self.db_pgdata:
            return Path(self.db_pgdata).expanduser()
        return Path.home() / ".roleband" / "db"

    def ensure_embedded_server(self) -> EmbeddedServer:
        """Start or attach the embedded server. Idempotent; safe from any process.

        Called from the URL properties rather than an app lifespan so that all
        five entrypoints (API, scheduler, watchdog, CLI, backup) inherit it with
        no per-entrypoint wiring.
        """
        from tracker.platform.embedded_db import claim_cluster, ensure_server

        if PACKAGED:
            claim_cluster(self.embedded_pgdata(), "app")
        memory = total_memory_bytes()
        return ensure_server(
            self.embedded_pgdata(),
            database=self.postgres_db,
            locale=self.db_locale or DEFAULT_LOCALE,
            required_extensions=REQUIRED_EXTENSIONS,
            server_settings=self.database_preset(memory).server_settings(memory),
        )

    def database_preset(self, memory_bytes: int | None) -> DatabasePreset:
        """The preset `db_preset` names, else the one this memory picks."""
        return PRESETS[self.db_preset] if self.db_preset else preset_for(memory_bytes)

    def _url(self, driver: str) -> str:
        if self.database_url_override:
            # Accept a bare libpq URL and point it at the requested driver.
            url = self.database_url_override
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", f"postgresql+{driver}://", 1)
            return url
        if self.db_embedded:
            return self.ensure_embedded_server().uri(driver=driver)
        return (
            f"postgresql+{driver}://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url(self) -> str:
        return self._url("asyncpg")

    @property
    def sync_database_url(self) -> str:
        """Sync URL for Alembic migrations."""
        return self._url("psycopg2")


@lru_cache
def get_settings() -> Settings:
    return Settings()


# --------------------------------------------------------------------------- #
# Taxonomy — data-driven, extensible.
# --------------------------------------------------------------------------- #


class BuiltinCompany(TypedDict):
    """A built-in company as the blueprint declares it. Not a scan target: it
    has no board token and no consent, which a followed company's
    `company_store.ScanTarget` carries."""

    display: str
    adapter: str
    enabled: bool
    curated: bool


# The companies we track, derived from the blueprint (tracker/blueprint.py) —
# declare a company there, not here. `enabled` flips a source off without
# deleting it; `curated` puts it on the curated list a fresh install follows.
COMPANIES: dict[str, BuiltinCompany] = {
    slug: {"display": bp.display, "adapter": bp.adapter, "enabled": bp.enabled, "curated": bp.curated}
    for slug, bp in BLUEPRINT.items()
}

# NOTE: the job-role taxonomy lives in `tracker/taxonomy/roles.py` (canonical
# groups), and which groups are *tracked* is a user setting stored in the DB
# (`tracker/settings_store.py`), defaulting to each group's `default_enabled`.
