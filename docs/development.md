# Developing RoleBand

The contributor's entry point: how the system is laid out, where a change of
each kind goes, and what to run to know it worked. Written for someone with a
fresh clone and no prior context.

This doc is a map, not a second copy of the system. Every fact has one document
that owns it, and another doc repeats it only in a line that links the owner;
before you change something, read the one that owns it:

| You are changing | Owner |
|---|---|
| Installing or running RoleBand | [README](../README.md) |
| Adding a company or an adapter, extending an API field, changing a screen | the [recipes](#6-four-recipes) below |
| A dataset file (the level atlas, the benefits dataset) | [Change a dataset](#7-change-a-dataset) below, and the data card beside the files |
| Data safety, and how comments are written | [AGENTS.md](../AGENTS.md) |
| Tests, and the gate to run before a change is done | [testing.md](testing.md) |
| Backend behaviour, data, the pipeline, the API, dashboard structure | [architecture.md](architecture.md) |
| The Mac app: packaged engine, process host, signing, updates | [architecture.md](architecture.md#the-mac-app) |
| A listing source or how a site is fetched | [sources.md](sources.md) |
| Pay, or who writes a posting's level, text, places or pay | [pay.md](pay.md), [field-authority.md](field-authority.md) |
| A screen, a control or a style | [ui.md](ui.md) |
| User-facing text, API errors, notifications | [copy.md](copy.md) |
| A plugin or the plugin SDK | [plugins.md](plugins.md) |
| The MCP server | [mcp.md](mcp.md) |
| Anything that sends data off the machine | [SECURITY.md](../SECURITY.md), [usage-data.md](usage-data.md) |
| Bundled third-party code or data | [third-party.md](third-party.md) |
| The pull request itself | [CONTRIBUTING.md](../CONTRIBUTING.md) |

---

## 1. Get it running

Install and start RoleBand as in the README's [Quickstart](../README.md#quickstart);
prefer the synthetic seed over a real scrape while you work on the app itself.
For development, also know:

- Run backend commands with the clone's own environment, `backend/.venv/bin/...`;
  a bare `python`, `pip` or `pytest` may not resolve to it.
- A setting is the environment variable `ROLEBAND_` plus its name in
  `backend/tracker/config.py`, from the shell or `backend/.env`
  (`backend/.env.example` lists the common ones). A name without the prefix is
  ignored.
- `backend/requirements-optional.txt` is installed in a separate pass that is
  never fatal: on macOS `apple-fm-sdk` is built from source and needs a full
  Xcode, so a machine with only the Command Line Tools skips it with a warning.
  Nothing required depends on it.
- The embedded Postgres keeps its data in `~/.roleband/db`, one cluster per user
  account, so `alembic upgrade head` from any clone migrates that same data.
  `ROLEBAND_DB_LOCALE` points your own cluster at another locale, but the test
  suite builds its throwaway clusters at `en_US.UTF-8`.
- **Isolate your data.** `setup.sh` runs `alembic upgrade head` against whatever
  the configuration resolves, which is `~/.roleband/db` by default. If you
  already run RoleBand on this machine and want a throwaway clone to keep its
  hands off your real data, set `ROLEBAND_PGDATA` to a directory of its own (and
  `ROLEBAND_DATABASE_URL=""`) for every command in that clone.
- **Background work runs under the supervisor** ([architecture](architecture.md#background-work)).
  `.venv/bin/python -m tracker.supervisor plan` prints what every job would do
  now and why; `run --dry-run-network` supervises with every job that reaches a
  third party running without its requests, for a rehearsal on a scratch
  database. Never point a supervisor from a development clone at a database an
  installed one uses: the second waits on the first's lock, but its jobs would
  run your unfinished code if it ever took over.
- **A dirty tree holds collection until it passes its own suite**
  (`deploy/preflight.sh`, run by the supervisor once the tree has been still for
  a minute). `ROLEBAND_SKIP_PREFLIGHT=1`, read when the supervisor starts,
  skips the check; it is for maintainers only.
- **Landing on an installed checkout** needs no restart: the supervisor reads
  HEAD every minute. A landing with a migration or a dependency change waits
  until `./setup.sh` has run; one that changed `dashboard/` is rebuilt aside and
  swapped in. `python -m tracker.supervisor stop --jobs` stops every running job
  and starts nothing until `maintenance off`; a live restore needs
  `maintenance on` first.

## 2. The shape of it

```
   scrape                    enrich                      serve
   ------                    ------                      -----
 connectors/  --jobs-->  workflows/pipeline  -->  db/  -->  api/routers/  -->  dashboard/
 (listing                 collect, persist,       jobs +                        (React,
  adapters: one           post-passes             observations                   lazy routes)
  per ATS or per                                  + derived            ^
  company board)                                        |              |
                                                        +--  mcp/  ----+
                                                          (the agent transport,
                                                           independent of api/)
```

Two rules hold this together, and both are enforced rather than described:

- **Layers run strictly downward.** `.venv/bin/lint-imports` checks the
  contracts declared in `backend/pyproject.toml`: interface (L6)
  above workflows (L5) above services (L4) above implementations (L3) above
  vocabulary (L1) above primitives (L0). An implementation never imports a
  sibling implementation, nothing imports a concrete adapter module, and `api/`
  and `mcp/` never import each other.
- **History is append-only.** `jobs` holds current canonical state, upserted
  every run; `job_observations` appends one row per job per run. Everything
  analytical is reconstructable from that history, so it is never overwritten.
  The tables that declare `lifecycle="append_only"` in `db/ownership.py` are
  held to it: a test fails on an update, delete or upsert reaching one.

## 3. Code map

Domain -> where you enter it -> who owns its data -> what to run.

The "data owner" column is not prose: it is the `writers` and `readers` of
`backend/tracker/db/ownership.py`, which an AST scan holds to the code. If you
need the writer of a table, read that file first.

| Domain | Public entrypoint | Data owner | Test command (from `backend/` unless noted) |
|---|---|---|---|
| Collecting postings | `tracker/connectors/listing/*.py` (reached only through `ADAPTER_REGISTRY`) | `db/repo.py` -> `jobs`, `job_observations` | `.venv/bin/python -m pytest tests/contracts/test_listing_connectors.py` |
| One scrape run | `tracker/workflows/pipeline.py:run_pipeline` | `workflows/run_persistence.py` -> `scrape_runs` | `.venv/bin/python -m pytest tests/test_pipeline_lifecycle.py` |
| Derived data | `tracker/workflows/post_passes.py:POST_PASSES` | each pass; claimed `post_pass:<name>` in `db/ownership.py` | `.venv/bin/python -m pytest tests/test_post_passes.py` |
| Scheduling / sync | `tracker/workflows/scheduler.py`; read side `workflows/schedule_status.py` | `scheduler.py` -> `sync_schedule_state`, `provider_pressure_state` | `.venv/bin/python -m pytest tests/test_sync_scheduler.py tests/test_schedule_status.py` |
| Background work | `tracker/supervisor/` (`registry.py:JOBS`), requests from `api/job_requests.py` and `api/scan_requests.py` | `db/job_store.py` -> `job_requests`, `job_runs`, `job_status` | `.venv/bin/python -m pytest tests/test_supervisor_due.py tests/test_supervisor_dispatch.py tests/test_job_store.py` |
| HTTP API | `tracker/api/app.py` (composition root) -> `api/routers/*.py` | the routers write only the tables in `ROUTER_WRITERS` (`tests/test_table_writers.py`); the rest go through a store | `.venv/bin/python -m pytest tests/test_api_route_table.py` |
| Agent transport | `tracker/mcp/server.py` ([mcp.md](mcp.md)) | shares the query owners in `db/queries/`; imports nothing from `api/` | `.venv/bin/python -m pytest tests/test_mcp_tools.py` |
| Comp estimation | `tracker/comp_providers/` ([pay.md](pay.md)) | `analytics/comp_trends.py` -> `comp_snapshot` | `.venv/bin/python -m pytest tests/contracts/test_comp_providers.py` |
| Offline level evaluation | `scripts.bench_level_identification`, `scripts.refresh_level_signatures`, `scripts.bench_level_context`; `analytics/level_evaluation.py`, `analytics/signature_refresh.py`, `analytics/level_context.py` | Private immutable files; no canonical level writes | `.venv/bin/python -m pytest tests/test_level_evaluation.py tests/test_bench_level_identification.py tests/test_signature_refresh.py tests/test_level_context.py` |
| Skills + taxonomy | `tracker/skills/`, `tracker/taxonomy/roles.py` | `skills/extract.py` -> `job_skills` and the other tables `db/ownership.py` gives it | `.venv/bin/python -m pytest tests/test_skills_extract.py` |
| Matching / embeddings | `tracker/semantic/`, `tracker/intelligence/` | `semantic/backfill.py` -> `jobs.embedding` | `.venv/bin/python -m pytest tests/test_intelligence_backends.py` |
| Company roster | `tracker/company_store.py`, `tracker/blueprint.py` | `company_store.py` -> `tracked_company`, `source_bindings` | `.venv/bin/python -m pytest tests/test_company_blueprint.py` |
| Companies to add | `tracker/company_discovery.py` (by sector), `tracker/company_catalog.py` (boards ready to enable), `tracker/company_directory.py` (every other live board) | `company_store.py` when a user follows one | `.venv/bin/python -m pytest tests/test_company_catalog.py tests/test_company_directory.py` |
| A pasted careers URL | `tracker/ats_detect.py` (from the URL), `tracker/board_resolve.py` (from the page), `tracker/board_relocate.py` (a board that moved) | `company_store.py` -> `tracked_company`, `source_bindings` | `.venv/bin/python -m pytest tests/test_ats_detect.py tests/test_board_resolve.py tests/test_board_relocate.py` |
| Plugins | `tracker/plugins/` ([plugins.md](plugins.md)) | `plugins/writer.py` and the plugin store | `.venv/bin/python -m pytest tests/test_plugin_manifest.py` |
| Dashboard screens | `dashboard/src/features/<name>/` | the typed client in `dashboard/src/api/` | `npm run test:unit` in `dashboard/` |
| Dashboard routes | `dashboard/src/routes/`, `src/navigation.ts` | none | `npm run test:ux` in `dashboard/` |

## 4. One real walkthrough: a posting becomes a row on the Board

1. **The scheduler decides there is work.** `workflows/scheduler.py` picks the
   bindings whose cadence is due and whose provider is not paused or
   policy-denied, then runs one pipeline pass.
2. **The pipeline collects.** `workflows/collection.py` calls each source's
   adapter through `ADAPTER_REGISTRY`. Every source is bulkheaded in time as
   well as in exceptions: a `SourceClock` carries both a stall bound (silence is
   the source's fault) and an absolute budget (a source still producing when it
   expires was cut by us, and that never counts against its health).
3. **The adapter yields `RawJob`s.** Provider-neutral dataclasses from
   `tracker/schema.py`; no ATS shapes escape `connectors/`.
4. **Persistence upserts and appends.** `db/repo.py` upserts `jobs` and appends
   `job_observations`, then `workflows/run_persistence.py` writes the run and
   its per-source outcomes. A run that was capped or bounded by our own limits
   cannot reconcile closures: an operator's cap is never evidence about a
   source.
5. **Post-passes derive.** The entries in `POST_PASSES` run in order:
   description backfill; domain, role, level and place reclassification;
   inventory promotion and retention; search vectors and content fingerprints;
   skills and requirements; embeddings; stated pay and pay periods; the pay
   reference; posting pages; relevance review; profile inference; place sets,
   lineage, twins, clusters and similarity; demand, skill-demand, comp and
   disclosure metrics; prices; and bound tuning. Each owns its tables and each
   is claimed in `db/ownership.py`, so a new derived table cannot ship as a CLI
   nobody wired in.
6. **The API serves it.** `GET /api/jobs` reaches `db/queries/jobs.py`, the one
   owner of "which postings are visible": companies off the Board (hidden, or
   not followed: `company_store.off_board_company_slugs`) and dismissals are
   applied there, so HTTP and the agent transport cannot disagree.
7. **The dashboard renders it.** `features/opportunities/` calls the typed
   client in `src/api/`, whose wire types are aliases of the generated
   `src/api.gen.ts`. Change a response shape in Python and regenerate; never
   hand-write a wire type.

## 5. What to run

Run the change-scoped gate in [testing.md](testing.md#change-scoped-gate).

A script documents its own options: `.venv/bin/python -m scripts.<name> --help`
prints its module docstring. A doc names a script and what it is for; the usage
stays in the script, next to the code it describes.

When a screen shown in the README changes visibly, regenerate its screenshots:
`npm run screenshots` in `dashboard/` builds the app, seeds the synthetic dataset into a
throwaway database (never the one `ROLEBAND_PGDATA` normally names), and writes
the role page pictures, `docs/images/job-detail*.webp`. The Radar and ranking pictures
are captures of a real install, retaken by hand. Every image there must be referenced
by Markdown and stay under 300 KB (`backend/tests/test_docs_closed_set.py`); history
keeps every replaced copy, so regenerate only when the picture changes.

## 6. Four recipes

Each names the minimum files, the seam you extend (never a second one), a
realistic fixture, the negative case, and what to run. If a step feels like it
needs a new registry, it does not: the seam already exists.

### 6.1 Add a tracked company

**Seam:** one `CompanyBlueprint` entry. There are no per-company literals
anywhere else, and a test enforces that.

1. Add a row to `BLUEPRINT` in `tracker/blueprint.py`: slug, display, an
   `adapter` that resolves in `ADAPTER_REGISTRY`, `is_public` (with `ticker`
   if and only if public), `brand_color`, and `curated` (whether a fresh
   install follows it; maintainers decide this per company).
2. Run `.venv/bin/python -m pytest tests/test_company_blueprint.py`. It runs
   every check in the `ARTIFACT_CHECKS` list of `tracker/blueprint.py` for every
   company and **names each artifact you still owe**: level bands, title
   profile, pay reference, offer policy, stage ladder, price fixture, dashboard
   branding. Fill them where it points.
3. If the company is on a multi-tenant board (Greenhouse, Lever, Ashby), its
   board token is a guess until something checks it. Run
   `.venv/bin/python -m scripts.check_catalog_tokens` before you commit.
   To find a token rather than guess one, `scripts.discover_board_tokens` lists
   the boards Common Crawl has seen whose name is a planned company's.

**Fixture:** the checks read real artifacts; there is nothing to fake.

**Negative case:** delete one artifact you just added and re-run: the test must
name it. A blueprint row whose `adapter` does not resolve fails at
`adapter_registered`.

**Why the token check matters:** a dead board answers 404, so the run fails
loudly. A wrong token is worse: a live board belonging to another company
answers 200 with a complete listing and passes every run-quality gate,
collecting their postings under your slug. Only Greenhouse states its tenant's
name, so Ashby and Lever come back `unstated`, never `confirmed`.

**Run:** `.venv/bin/python -m pytest tests/test_company_blueprint.py`, then the
full backend gate.

### 6.2 Implement a listing adapter

**Seam:** `ADAPTER_REGISTRY` in `tracker/connectors/listing/__init__.py`. The
registry is the only entry: nothing imports a concrete adapter, and a contract
forbids it.

**Start from the worked example.** `backend/tests/example_adapter.py` is this
recipe as runnable code: the shortest adapter that still pages through
`paged_listing`, stops on the source's own signal, and records each row it
cannot use instead of losing the page. Copy it and work through the four steps
below.

**Steps 2-4 are for onboarding a real source.** `ADAPTER_REGISTRY` is production
discovery, and the `SOURCE_REVIEWS` row wants a robots.txt sha256 and the
deciding directive for the route you actually request: evidence a synthetic
source cannot honestly supply. A test-only adapter therefore stays in `tests/`,
registered nowhere, exactly as the example does.

1. Write the adapter in `tracker/connectors/listing/<name>.py`, subclassing the
   base in `tracker/connectors/listing/base.py` and yielding `RawJob`s from
   `tracker/schema.py`. No ATS-shaped type may escape the module.
   - **Fetching.** Fetch through `self.context.fetch(FetchRequest(...))`, or
     `self.context.stream` for a body too large to buffer, and declare the
     transport abilities your code uses in `required_capabilities`. Building
     the context checks them against the transport, so a need it cannot meet
     raises `CapabilityError` before the first request. `self.get` and
     `self.post` serve only the adapters that already call them.
   - **Class markers.** Declare `posted_date` on the class itself, or
     `tests/contracts/test_posted_date_kind.py` fails by name. Declare
     `listing_scope`, `detail`, `text_from_posting` or `declares_total` only
     where the source differs from the base defaults;
     `tests/contracts/test_capability_markers.py` and
     `tests/contracts/test_listing_completeness.py` hold each one to the code.
   - **Unusable rows.** A row with no id goes to `self.drift.drop_record`, which
     counts it as lost. A row with an id that cannot become a posting goes to
     `self.observe_unusable`, which keeps that posting open. A row skipped with
     neither call leaves the listing complete, and closure can then close a
     live posting ([architecture.md](architecture.md#completeness-and-closure)).
   - **Types.** `tracker/connectors/listing/` is inside the typed set, so
     `.venv/bin/mypy` checks your adapter, locally and in CI.
2. Register it in `ADAPTER_REGISTRY`, and declare its board root as a
   `BoardProbe` on the class in the same change. The token checker reads the
   registry and never restates a board URL, or it would verify a route the
   adapter stopped fetching.
3. Add a `SOURCE_REVIEWS` row in `tracker/source_review.py` **in the same
   change**: how we reach the source, the routes, the robots verdict for the
   route we actually request (with the file's sha256 and the deciding
   directive), and the `User-Agent` we send. The register records; it never
   permits: only `source_policy` refuses a request, and a test asserts nothing
   else imports it. Never record an approval: a review weighs terms of service
   and is a maintainer's decision, not a measurement. Then regenerate
   `docs/sources.md` with `.venv/bin/python -m scripts.gen_sources_doc`;
   `tests/test_sources_doc.py` fails while it is stale.
4. Add a fixtures directory under `tests/fixtures/listings/<name>/`, a
   harness entry in `HARNESSES` (`tests/contracts/conftest.py`), and a
   `METADATA_FIELDS` row in `tests/contracts/test_listing_connectors.py` naming
   which of `department` and `team` your fixtures fill. The contract suite
   names an adapter that has no row.

**Fixture:** real captured payloads, not synthesised ones, reduced and scrubbed
with `.venv/bin/python -m scripts.scrub_fixtures` before you commit. The
contract suite replays them in every `MODE_*` of `tests/contracts/conftest.py`,
including a page that repeats forever and a mangled payload.

**Negative case:** the contract suite fails by adapter name for a missing
fixture or harness; `backend/tests/test_contribution_rehearsal.py` proves that
by handing the gate an adapter that was never onboarded, and fails if the
example skips an unusable row without recording it. Remove your
`SOURCE_REVIEWS` row and `tests/test_source_review.py` fails by name too.

**The example can never run for real**, and its location is what guarantees it:
`tracker/` never imports `tests/`, so a teaching artifact cannot be discovered,
scheduled or pointed at a board. Registering it in `ADAPTER_REGISTRY` fails two
tests immediately.

**Run:** `.venv/bin/python -m pytest tests/contracts/ tests/test_source_review.py tests/test_sources_doc.py`,
then one live smoke: `.venv/bin/python -m scripts.smoke_adapters <company> 5`.

### 6.3 Extend an API field

**Seam:** the Pydantic response model. The dashboard's type is generated from
it, so the model is the only place the shape is written.

1. Add the field to the response model in
   `tracker/api/schemas/<domain>.py`, and populate it in
   `tracker/api/routers/<domain>.py`. `api/schemas/` is inside the typed set, so
   `.venv/bin/mypy` checks it.
2. Regenerate both committed artifacts:
   `.venv/bin/python -m scripts.export_openapi` from `backend/`, then
   `npm run gen:api` from `dashboard/`. CI diffs both and fails on any drift.
3. The dashboard's wire type is an alias of the generated one in
   `dashboard/src/api/<domain>.ts`. **Never restate a generated shape by hand**:
   `dashboard/src/test/api-contract.types.ts` fails `tsc` when a modelled
   route's client type stops being the generated one.
4. A new route also needs `tests/fixtures/route_table.json` regenerated
   (`.venv/bin/python -m scripts.freeze_route_table`) and a Pydantic
   `response_model`; a route answering JSON without one fails by name.
5. A new user-visible string field declares its text class; see
   [copy.md](copy.md).

**Fixture:** if the route has a fixture in `dashboard/src/test/fixtures.ts`,
extend it there. Not every route has one; the rule is to extend the existing
fixture or factory, never inline a second copy beside one.

**Contract tests may freeze a whole body.** Some backend contract tests compare
a route's full response or its key set, so a new field fails them until their
expected rows carry it too. The backend gate catches this; expect it.

**Negative case:** rename your new field in Python without regenerating. The
contract-drift check fails; so does `tsc`.

**Watch out:** a Pydantic docstring is a wire artifact: it publishes into
`openapi.json` as the schema description. Use a comment when you do not mean to
ship the text.

**Run:** the [gate](testing.md#change-scoped-gate) for an API shape change.

### 6.4 Change a dashboard interaction

**Seam:** the feature directory. `dashboard/src/features/<name>/` owns its
screen, its styles and its tests; `src/ui/` holds the shared primitives.

1. Read [ui.md](ui.md) before adding anything clickable. The set of controls is
   closed and a ratchet enforces it; a hand-rolled button is a named exception
   or a defect, never a default.
2. Read [copy.md](copy.md) before writing any user-facing string. Messages live
   in `dashboard/src/copy/en/*.ftl` and are called as generated functions;
   `npm run copy:check` validates them.
3. Put the change in the feature directory. Component state stays local;
   shared state is in `dashboard/src/context/` ([architecture.md](architecture.md#dashboard)).
4. Write the test where the behaviour is: a component test beside the component
   for logic, a spec in `dashboard/tests/ux/` for route-level behaviour.

**Fixture:** `dashboard/src/test/fixtures.ts` for data; user-visible selectors
(role, label) for queries. If the UI has no accessible label, add one rather
than writing a brittle selector.

**Negative case:** a UX spec must not reach a real backend; see
[testing.md](testing.md#ux-specs-never-reach-a-real-backend).

**The app shell is gated by name.** `npm run build` fails when the startup
chunk carries code only a lazy screen uses (it names the module and export:
move it to a module the shell does not import), and when its raw size moves
past the slack of the number recorded in `dashboard/bundle-baseline.json`
(`npm run bundle:record` records a deliberate change; the per-module delta it
prints is the explanation). Anything `src/shell/` imports statically is shell
bytes even when it lives under `features/`. The shell calls the API through
`dashboard/src/api/shell.ts` only.

**Run:** the [gate](testing.md#change-scoped-gate) for a dashboard route or UX change.

## 7. Change a dataset

The level atlas and the benefits dataset are edited in `roleband/roleband-data`
(`atlas/`, `benefits/`), cloned beside this repository. This repository carries a
pinned, read-only copy of one data commit at `backend/tracker/levels/atlas/` and
`backend/tracker/profiles/benefits_dataset/`, named with every file's sha256 and
size in `backend/tracker/datasets.lock.json`, so a clone sets up offline and every
install of one version reads the same data. The rules the files keep stay here:
the table statements, the loaders, the companies they name, and
`scripts.check_datasets`, which the data repository's CI runs against this
repository's `main`.

From `backend/`, with the data checkout at `../../roleband-data`:

1. Edit the data in the checkout, by hand or with a build script's `--out`
   (`scripts.build_level_base --out ../../roleband-data`). A build script refuses
   to write the pinned copy.
2. `.venv/bin/python -m scripts.data pin --try ../../roleband-data` copies the working
   files here, so the backend checks run against the change; change code and tests
   as it needs.
3. Commit and push the data. `scripts.check_datasets --root ../../roleband-data`
   runs the same check its CI does.
4. `.venv/bin/python -m scripts.data pin ../../roleband-data` pins the pushed commit;
   commit the pin with the code and test changes in one commit. `pin` refuses a
   checkout with uncommitted changes, a commit on no remote branch, or data that
   fails `scripts.check_datasets`.

`tests/test_dataset_lock.py` fails on a copy that differs from its lock and on a
trial pin, so a trial never lands. Never edit the pinned copy by hand.
`tests/test_datasets.py` holds each rule `scripts.check_datasets` claims: the data
passes and a broken copy fails.
