# Field authority

Who writes a posting's level, description, places and pay, who wins, what
clears, and what the posting inventory can replay. Read it before changing a
writer of any column below. Paths are under `backend/tracker/` unless written
in full. Change a row here in the same change as its writer, clearing rule or
gate. How pay figures are computed is in [pay.md](pay.md).

## Three facts that hold for every field

| Fact | Where | Consequence |
|---|---|---|
| A posting the scan judges out of scope is not written. | `workflows/collection.py`: only kept rows reach `enrich/enricher.build_enriched` and `db/repo.upsert_job`. | A held row the scan now rejects keeps its columns, except what `repo.refresh_held_reads` carries from the scan's read: places when one classifies into a location group, and title, family, track and worlds when the board retitled the posting. Level, team, description and pay stay as they were. |
| The writer re-projects scope from stored columns. | `workflows/pipeline.py` `_RunWriter._commit` calls `scope/projection.recompute_saved_scope`; held rows the scan judged out are marked by `repo.apply_scope_state`, after `refresh_held_reads`. | Scope comes from the stored columns under the scope saved now (current places and title, the stored level), not from the scan's verdict. |
| Post-passes see touched rows only. | `workflows/run_persistence.py` collects upserted ids and held rows `refresh_held_reads` changed; `workflows/post_passes.backfill_missing_descriptions` and inventory promotion add theirs. | A held out-of-scope row the scan did not change is never re-read by a touched-id pass (text pay, embeddings, content fingerprint). |

## 1. Printed rung and level

Columns on `Job` (`db/models.py`): `raw_level`, `level_band` (not null),
`level_confidence`, `level_basis`, `family`, `track`. In memory:
`RawJob.raw_level` and the `EnrichedJob.level_*` fields (`schema.py`). The
posting inventory mirrors them.

| Question | Answer |
|---|---|
| Writers of `raw_level` | Listing adapters that print a rung (Greenhouse, Apple, Accenture, SmartRecruiters). Detail text through `connectors/detail._note_stated_level`, which never overwrites a rung the listing gave. `repo.refresh_listed_rungs`, from the inventory, as the first step of `workflows/relevel.relevel_jobs`. Persisted by `repo._apply_fields`. |
| Writers of `level_band`, `level_confidence`, `level_basis` | The scan: `enrich/enricher.annotate` calls `enrich/level_mapper.read_level`, and reads again after the detail fetch. Inventory admission (the inventory's reading). `relevel_jobs` through `repo.set_job_levels` (the `levels_backfill` post-pass, whole table, every run). `backend/scripts/backfill_level_bands.py`. |
| Who wins | Last write wins. In a run the scan writes first, then `levels_backfill` rewrites; relevel's reading stands until the next scan. Within one reading, `read_level` decides: the printed rung first, then the company's own title vocabulary, then the posted pay grade, then generic title words, with early-stage markers (intern, new grad) and rung-naming company rules placed by `read_level` itself; `none` when nothing reads. |
| Fallback | No reading gives band `mid`, confidence unconfirmed, basis `none`. Relevel reads `raw_level`, else `taxonomy/stated_level.stated_level` over the description, and only for a company where `levels/ladder.prints_rungs_in_text` holds. A NULL `level_basis` reads as `generic`. |
| Missing, failed, absent | Basis `none`: the title states no level. Basis `unmapped`: it states one RoleBand cannot place. `raw_level` NULL covers three cases nothing distinguishes: nothing printed, detail not read (inside the refresh window), or the detail read failed. |
| Stamp | None per row; relevel re-derives every row each run. The inventory records its classifier fingerprint in `app_settings` (`db/inventory_store.CLASSIFIED_WITH_KEY`). History lives in `JobObservation.payload`, and a `changed` lifecycle event records a `level_band` move. |
| Clearing | `level_band` is never NULL. `_apply_fields` overwrites `raw_level` with whatever the scan holds, `None` included. `refresh_listed_rungs` never writes NULL, and relevel never writes `raw_level`. |
| Downstream | Scope re-projection on a scan write and in relevel. A `changed` event (upsert only) feeds tracked-role notifications. Relevel re-estimates the jobs whose band moved (`workflows/relevel.py`, `reestimate.refresh_jobs`); a row admitted from the inventory starts with no estimate. Lineage re-checks a posting when its band changes (`lineage/detect.lineage_input_key`). Place sets and comp metrics are rebuilt from the corpus each run. |
| Inventory replay | The inventory captures the row in `collection.retain()` before hydrate and before the post-read level re-read. Listing-printed rungs replay (`refresh_listed_rungs`); text-stated rungs and pay-grade evidence do not. |
| Scope gate | Held out-of-scope rows keep their old level columns. `refresh_listed_rungs` covers `raw_level` only (listing-printed, open rows, inventory newer than the row). It reads a row under its own key and under each binding's alias for it (`job_source_identities`), and the newest read that prints a rung decides. `refresh_held_reads` moves `family` and `track` only with a new title, never the level. A discovery scan never updates a held open row (`run_persistence.discovery_should_persist`). |

## 2. Description

Columns: `description_html`, `description_text`, `description_sections`,
`description_fetched_at`, `content_hash`, `content_changed_at`.
`RawJob.description_complete` describes one read and is not stored.

| Question | Answer |
|---|---|
| Writers | `repo._apply_fields`, when `raw.description_complete` is true or the row is new (input from `connectors/detail.structure_job_detail` after `hydrate`). `post_passes.backfill_missing_descriptions`: open rows with no text, non-empty text only. `backend/scripts/backfill_severed_pay_sections.py`. `backend/scripts/refetch_descriptions.py`: open rows of one adapter fetched before a cutoff, non-empty text only. Inventory admission writes blank text. The fingerprint is written by `content.fingerprint_content`, over touched ids only. |
| Who wins | A complete read overwrites. An incomplete read never downgrades held text. The backfill only fills gaps. A detail read that holds the whole text but cannot isolate the pay its source prints (`connectors/detail/base.pay_unread`) is complete: its text is stored and stamped, so the posting is not fetched again every scan. It is a failover, so it states no band and clears none; the text pass reads the band. |
| Fallback | A new row accepts listing or search text. Text is built from the sections, else from the HTML. Rows still blank wait for the backfill queue. |
| Missing, failed, absent | Missing: text and `description_fetched_at` are NULL. A failed hydrate leaves a drift note and keeps the held text. A posting that serves no text records nothing in the backfill and is selected again every run. No column tells these apart. |
| Stamp | `description_fetched_at`, set only when the text is non-empty. `content_hash` is md5 of title plus text; `content_changed_at` moves when it does. |
| Clearing | Only a listing-carried source (`description_complete` defaults to true) that sends empty content writes NULL text, and it leaves the old `description_fetched_at`. |
| Downstream (on `content_changed_at`) | Embeddings, the text pay pass (`disclosed_comp.owed_ids`), the posting page queue, relevance review, the search vector, lineage through `embedded_at`. |
| Inventory replay | None. The inventory keeps no description, by design (privacy and size), so admitted rows start blank. |
| Scope gate | Held out-of-scope rows are not hydrated or written. Text read only to decide a level is discarded if the row stays out. The backfill is not scope-gated; it puts in-scope rows first. |

## 3. Places

Columns: `locations`, `location_groups`, `location_cities`, `workplace_type`,
and `source_facts.locations`. `disclosed_place_key` belongs to the pay pass.
There is no scalar country or city column.

| Question | Answer |
|---|---|
| Writers of `locations` | Listing adapters, and hydrate overrides in the adapters that read places from the posting page (Workday, Avature, SmartRecruiters, SuccessFactors). `connectors/listing/base.BaseAdapter.place_from_page`. `BaseAdapter.keep_held_places` reuses recently read page places. Persisted unconditionally by `repo._apply_fields`. `backend/scripts/backfill_google_places.py` drops a searched country the listed places already name from stored Google rows. |
| Writers of groups and cities | `repo._apply_fields`. `post_passes.reclassify_places` through `repo.set_job_places` (scope is recomputed): the whole table once after a classifier change (`enrich/inventory.classifier_fingerprint`), and the run's own rows otherwise; the domain and role passes work the same way. `backend/scripts/backfill_location_groups.py` (does not recompute scope) and `backend/scripts/backfill_location_cities.py`. |
| Who wins | This scan's `RawJob` wins outright. Within one read, the detail page beats the listing. |
| Fallback | Places read within the refresh window are reused (`known_places`) for count-only or generic rows. The listed place stays when the page names none, unless the adapter passes `clear_listed_place`. `workplace_type` defaults to unknown. |
| Missing, failed, absent | In `place_from_page` a failed read and a page that names no place take the same branch. `[]` can also mean `place_gate` refused the page read. `workplace_type` unknown means not stated or not read. |
| Stamp | None. Known-place freshness borrows `description_fetched_at`. |
| Clearing | Every write replaces `locations`, `[]` included; but a row with `[]` fails the location axis, so a held row in that state is not written and keeps its places. A rescan inside the description refresh window skips hydrate, so places a detail page supplied give way to the listing's, except at SmartRecruiters, which keeps recently read page places. |
| Downstream | `location_groups` feed `in_scope`. The text pay pass re-reads a row when its `pay_place_key` moves. Place sets are rebuilt each run. Lineage re-checks a posting when its places change. The content hash ignores places, and a place move emits no lifecycle event. |
| Inventory replay | The inventory keeps `locations` (after `place_from_page`, before hydrate), `workplace_type` and `location_groups`. Listing places and listing-time page places replay; hydrate-only places do not. Count-only rows outside the role gate stay unresolved. |
| Scope gate | A held out-of-scope row takes the listing's places when one classifies into a location group (`refresh_held_reads`, with or without the inventory), with its groups and cities, and `workplace_type` unless unknown. A listing with no place, or a count-only card ("Multiple Locations", "62 Locations"), withdraws none. A discovery scan never updates a held open row. `place_gate` blocks page place reads outside the role scope. |

## 4. Pay

Stated band: `disclosed_base_min`, `disclosed_base_max`, `disclosed_currency`,
`disclosed_pay_basis`, `disclosed_pay_period`, `disclosed_snippet`,
`disclosed_confidence`, `disclosed_bonus_pct`, `disclosed_source`
(`connector`, `text` or `page`), `disclosed_place_key`, and the stamps
`structured_at`, `structured_prompt_version`. Estimate: `jobs.comp_*` and one
`job_comp_estimate` row per source. `source_facts.compensation` holds the
page's pay tiers and retrieval state.

| Question | Answer |
|---|---|
| Writers of the stated band | Connector: `repo._apply_fields` when `raw.source_disclosed_comp` is set (detail connectors fill it through `connectors/detail/base.source_disclosed_comp_from_text`); it stamps `structured_at` and `CONNECTOR_READER_VERSION`. Text: `intelligence_runtime/disclosed_comp.extract_disclosed_comp` (each run reads its touched ids newest first, then the open rows still owed a read, in-scope then oldest first (`disclosed_comp.backlog_ids`), each up to `intelligence_max_per_run`; `workflows/backfill_disclosed_comp.py` for a full pass). Page: `workflows/posting_pages.apply_page` (background drain, and a read when a posting is opened). `disclosed_comp.correct_pay_periods` corrects stored periods from any source. |
| Writers of the estimate | `enrich/comp.EstimateSet` resolves RoleBand's estimate and, while a plugin is selected for pay, the plugin's; `enricher.build_enriched` carries both; `repo.upsert_job` writes `jobs.comp_*` (the selected source) through `_apply_fields` and every source's row through `repo.write_estimates`. `plugins/reestimate.reestimate` rewrites every job when the reference set changes. |
| Settling an unclear basis | Every writer passes its basis through `pay_disclosure.settle_band` with the job's family, title and band: an `unclear` band whose posting defines bands per kind of role becomes base (non-sales) or total (sales); otherwise one its paragraph calls a salary becomes base. The stated bonus share is read after, against the settled basis. Stored connector and page bands are settled by `disclosed_comp.settle_stored_bands` (run from `backfill_disclosed_comp`), never by the text pass. A family that changes later does not re-settle a band until its writer writes it again. |
| Who wins | Connector beats text beats page. A connector band overwrites any band; the text pass skips connector rows (`owed_ids`); a page read never replaces a text or connector band; the text pass replaces a page band when the text states one. |
| Fallback | Text with no band falls back to the page band. The text pass reads the pay section, else the full text. The estimate falls back through providers in order ([pay.md](pay.md)). |
| Missing, failed, absent | One reading for every reader, `pay_disclosure.disclosure_known`: a stored band is stated pay whoever wrote it; no band and `structured_at` NULL is "not read yet"; no band and `structured_at` set is absent. The text pass has no failed state: a row with no text is stamped processed and nothing is withdrawn. The page keeps failed apart (`RETRIEVAL_FAILED`, band kept) from absent (page band cleared). A connector that sends no band keeps the stored band, unless it scanned the posting's text in a complete read (`raw.pay_looked`) and the band is its own: then the band is cleared. The four retrieval states live only in `source_facts`. |
| Stamp | `structured_at`; `structured_prompt_version` (the parser version, or a version pinned in settings); `disclosed_source`; `disclosed_place_key`; `source_facts.compensation.observed_at`; one `ai_task_log` row per text read. The estimate carries `comp_provenance`, `comp_ref_fp` and, per source, `job_comp_estimate.ref_fp` and `estimated_at`. |
| Clearing | The text pass clears a text band (every `disclosed_*` column) when the text states no band and the page states none; it never clears a page band. A page read clears a page band on absent. A connector band is cleared by its own connector when that connector reads pay from the posting's text (`pay_from_text`) and a complete read with text finds none; a structured reader's band (Ashby, OpenAI) is never cleared. Nothing clears `structured_at` in bulk: `backfill_disclosed_comp --force` re-reads rows the text pass last read before it started (resumable with `--force-before`), and the severed-sections and `refetch_descriptions` scripts clear it on the non-connector rows they rewrite. `comp_*` is overwritten by every scan that estimates, NULL included (a resolver miss, below Senior, inventory admission); a row with a deferred estimate keeps its figures. |
| Downstream | `owed_ids` re-reads on stale text, a new parser version or a moved place. The page queue needs `structured_at`, no band and `in_scope`. Relevel reads every stored band for the pay-grade tier, which feeds level and scope. Each of the three writers records a `changed` event with a `disclosed_base` detail when it moves a stored band's bounds; a first reading is not a move, and `correct_pay_periods` records nothing, since it corrects our reading. Notifications classify the event as `comp_up` or `comp_down`, whichever writer moved the band, when both sides state the same bounds in the same currency and period. The feed reads one run's events, so a page read on open, which belongs to no run, reaches the posting's history only. A `comp_median` move is a `changed` event only under the same reference set; a reference change is one `reference_change` record. Lineage re-checks a posting when its stated pay changes. Comp metrics rebuild each run. |
| Inventory replay | None: the inventory keeps no pay. Observations keep incoming tiers (upserted rows only) and RoleBand's estimate. |
| Scope gate | The text pass reads touched ids and every open row still owed a read, in scope or not, in-scope first; a moved place is owed only through the touched ids, since the scan that moves it touches the row. Closed rows are read only when a run touches them or by the backfill command. The page drain requires `in_scope`. The resolver runs for kept rows only. |

## Replay and privacy

`posting_inventory` keeps an allowlisted row (`enrich/inventory.InventoryRow`:
listing facts, level reading, places), never descriptions, raw payloads or
pay. A repair can replay only listing-printed rungs and listing-time places;
everything else needs a fresh read. Assume no fuller rebuild.
