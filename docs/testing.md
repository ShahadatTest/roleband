# Testing

Which checks a change needs, what a good test looks like here, how to run each
suite, and what CI runs. Setup is in [development.md](development.md).

## Change-scoped gate

Run the checks for every surface your change touches, from the directory
shown, and report any check you skipped with its reason.

| Change | Commands |
|---|---|
| Any change | From the repository root: `python backend/scripts/check_comment_hygiene.py` and `python backend/scripts/check_project_name.py` (standard library only, seconds) |
| Docs only (`*.md`) | From `backend/`: `.venv/bin/python -m pytest tests/test_*doc*.py`; the link check runs in CI |
| Any backend change (`backend/`) | `.venv/bin/ruff check tracker tests scripts ../sdk/python ../examples`, `.venv/bin/lint-imports`, `.venv/bin/mypy`, `.venv/bin/python -m pytest`; a new module meant to be typed goes in `[tool.mypy] files` |
| Native Mac launcher | From the root: `launcher/macos/test-core.sh`, `node dashboard/scripts/export-launcher-copy.mjs --check`, and `launcher/macos/build-app.sh`, then `python3 launcher/macos/test-transport.py` with the built app's `Contents/MacOS/RoleBandLauncher` to test its HTTP client. Installer changes also run `python3 -m unittest discover -s launcher/macos/Tools -p 'test_*.py'`, and from `backend/` `.venv/bin/ruff check ../launcher/macos/Tools ../launcher/macos/test-transport.py`, and build/mount/verify the disk image with its pinned packaging tools. Source installation and release tests replace external commands, use scratch app folders, and never register launchd or contact GitHub. Update staging, transaction and helper tests use scratch app folders and stopped Postgres clusters; a release trial still needs the persistent signing identity and a previous release's real data. Run the deploy and CI workflow contracts for installer/workflow changes. Test first open, login approval and return from Settings, Escape, browser reopening and sleep/wake on a real Mac. |
| Standalone Mac bundle | Build the dashboard with `deploy/build_dashboard.sh`, install `zstd`, then use `launcher/macos/build-bundle.sh` to build a candidate without private keys. A change to the backend requirements or constraints regenerates `launcher/macos/runtime-lock.txt` with `Tools/lock_runtime.py`. Move its Swift build folder aside, make the app read-only, then run the app executable with `--check-copy` and `--check-engine` plus a new scratch directory. The probe refuses an external database, writes only its own state and verifies unchanged bundle hashes. It runs the bundled interpreter in isolation, checks native imports, starts a scratch database with vector and pg_trgm and installs the SDK wheels offline; it never starts setup or owns a source installation. Use `Tools/release.py candidate` to package it. Locally, `Tools/signing.py seal` copies the candidate into a new app signed with a scratch keychain and release public key; `Tools/release.py prepare` verifies nested signatures, release provenance, the image checksum and Ed25519 signature. A separately trusted public key is required for verification and local attachment. The release identity comes from `generate --spare-directory`, which asks for the release-key passphrase and the certificate password; `import` asks for the certificate password and `prepare` for the passphrase when used. |
| Pre-launch installation guide | Also run `node launcher/macos/Tools/test_guide.mjs` after installing the dashboard dependencies and Playwright Chromium/WebKit. It tests offline file navigation, language persistence, the no-warning branch, recovery, keyboard controls, responsive themes and the no-JavaScript fallback. Verify the Settings link with real Safari and Chrome; WebKit engine tests alone do not prove Safari's external-protocol handling. |
| API route or response model | The backend checks; `.venv/bin/python -m scripts.export_openapi`, then `npm run gen:api` and `npm run build`; commit both generated files. A route added or removed also runs `.venv/bin/python -m scripts.freeze_route_table` |
| Model or migration | `.venv/bin/alembic upgrade head`, then `.venv/bin/alembic check`, which must report "No new upgrade operations detected"; `.venv/bin/python -m scripts.freeze_schema_metadata`; the backend checks |
| Listing or detail connector | The backend checks including `tests/contracts/`; the new fixture (scrubbed with `scripts.scrub_fixtures`) and harness entry; a `SOURCE_REVIEWS` row; `.venv/bin/python -m scripts.smoke_adapters <company> 5` |
| Pipeline, persistence or post-pass | The backend checks (including `tests/test_pipeline_lifecycle.py` and `tests/test_post_passes.py`); `.venv/bin/python -m tracker.daily --max-list 150 --no-hydrate -v` |
| Dashboard component or logic (`dashboard/`) | `npm run lint`, `npm run knip`, `npm run test:unit`, `npm run build` |
| Dashboard route or UX | The dashboard checks plus `npm run test:ux`; `ROLEBAND_UX_MODE=build npm run test:ux` before pushing (on macOS, `deploy/check_local.py ux --docker-browsers`); a run of a new spec on its own |
| UI that reads a changed API | Start the API (`.venv/bin/uvicorn tracker.api.app:app --port 8010`) and `npm run dev`, load the changed route on `http://localhost:5173`, and check the browser console and network |
| A dataset file (in a `roleband-data` checkout) | From `backend/`: `.venv/bin/python -m scripts.check_datasets --root ../../roleband-data`; then `scripts.data pin --try ../../roleband-data` and the backend checks; `scripts.data pin` once the data is pushed ([development.md](development.md#7-change-a-dataset)) |
| User-facing text | `npm run copy:check`, and `npm run test:unit`, which fails while a translation is stale (see [copy.md](copy.md)) |

The native engine-host integration tests accept `ROLEBAND_HOST_TEST_RESOURCES`
pointing at an assembled app's `Contents/Resources`. They exercise its real
Python, Postgres, supervisor and API with a new scratch home and database;
network jobs run in dry-run mode. Without an assembled bundle those two tests
are explicitly skipped. The remaining host tests use scratch interpreters and
process groups and never signal an installed engine.

## What a good test is

A test is a behaviour contract, not coverage. Name the invariant in the test
name or docstring, then write the smallest test that fails when it breaks.

- **It fails for a plausible broken implementation.** Prefer fail-first: run
  the test before the fix and watch it fail. When that is not practical,
  mutation-check it: remove the guard, revert the fix or break the branch the
  test covers, and confirm the test goes red.
- **Negative paths are required where behaviour branches**: empty results, a
  failed fetch, a rollback, an unknown provider, source drift, a capped scan.
  Show a guard refusing what it must refuse. Plant data that must not leak
  with absurd values, so a leak shows in the answer.
- **Mock at the boundary, never the subject.** Replace the network, the clock,
  storage and outside services. Behaviour that needs real SQL (upserts, unique
  indexes, retractions) runs against real Postgres.
- **Test a value through the parser that produces it.** An adapter that
  parses with `ijson` sees `Decimal`, not the `float` a hand-built dict carries.
- **No snapshot-only or "current output" assertions.**
- **Assert what the user sees.** Select by role, label or text, and add an
  accessible label when the UI has none. Assert "visible and clickable" where
  the element paints, with `expectOnTop` and `pointAndClick` in
  `dashboard/tests/ux/paint.ts`: `toBeVisible()` passes for a covered element.
- **Realistic data.** Postings carry company, level, family, location, pay and
  lifecycle fields. Dashboard tests build API responses from
  `dashboard/src/test/fixtures.ts` and read UI text through `msg()` from
  `dashboard/src/test/msg.ts`.
- **No real waiting.** Inject clocks and sleeps. Failure fixtures may use
  `Retry-After: 0` and zero pacing when timing is not the contract, but keep
  the request-count assertions. A race between two database sessions waits on
  Postgres's lock queue (`until_waiting` in `backend/tests/barriers.py`), never
  on a fixed sleep: under load a sleep ends before the second session reaches
  its read, and the test passes with the lock removed.
- **Never weaken, skip or delete a test to land a change.** When the expected
  behaviour changes, change the test in the same PR and say why.
- If a check is slow or flaky in the browser, move it down-stack to Vitest or
  pytest and keep one UX test for the user path.

## Suites

| Suite | Where | Command | Covers |
|---|---|---|---|
| Backend | `backend/tests/` | `.venv/bin/python -m pytest` | Logic, API routes, persistence, adapter parsing |
| Registry contracts | `backend/tests/contracts/` | `.venv/bin/python -m pytest tests/contracts` | Every registered connector and provider |
| Backend static | `backend/pyproject.toml` | `ruff`, `lint-imports`, `mypy` (full lines in the gate below) | Lint, layer contracts, types for `[tool.mypy] files` |
| Dashboard unit | `dashboard/src/**/*.test.{ts,tsx}` | `npm run test:unit` | Vitest + Testing Library (jsdom); also typechecks `tests/ux/` |
| Dashboard UX | `dashboard/tests/ux/` | `npm run test:ux` | Playwright on desktop Chromium and iPhone 14 (WebKit) |
| Dashboard lint, build | `dashboard/` | `npm run lint`, `npm run build` | Import rules, TypeScript, bundle size |
| Dashboard dead code | `dashboard/knip.jsonc` | `npm run knip` | Unused files, packages and exports; an export only its own file uses loses `export` |

Backend commands run from `backend/`, dashboard commands from `dashboard/`.
Backend tests run in parallel: `-n auto` in `backend/pytest.ini`, sized by
`backend/conftest.py` to the machine (at least 4 workers, at most 10, leaving
cores and memory free); unattended preflight runs 4. Use
`.venv/bin/python -m pytest -n 0` for `--pdb` or readable output. Install the
Playwright browsers once with `npx playwright install chromium webkit`.

Vitest isolates each file in a VM worker with a 512 MB recycling threshold.
The native bundler integration tests use a Node process: its native callbacks
require objects from Node's own realm. DOM tests retain jsdom and the shared
cleanup setup. Both projects retain file isolation and run through the same
`npm run test:unit` command.

Plugin authors test against `FakeHost` in
`sdk/python/roleband_plugin_sdk/testing.py`; see [plugins.md](plugins.md).

### Local profiles and timings

From the repository root, `backend/.venv/bin/python deploy/check_local.py all`
runs the standard backend and dashboard gates sequentially; `all --parallel` runs
the backend lane (root checks, static checks, pytest) and the dashboard lane at the
same time. Each lane stops at its own first failure, the other runs on, and the
cluster cleanup waits for both. Choose `backend` or
`dashboard` for one surface, `unit` for dashboard unit tests plus UX typechecking,
or `ux` for a typechecked build and both browser projects. API/schema generation,
migration checks and live smoke commands in the change-scoped gate still apply
where required. The runner reports its own invocation; it does not certify the
supervisor's preflight.

The runner keeps logs, JUnit/JSON test results and a timing report in a new
temporary directory outside the checkout. `--output` selects a new directory
there. It records HEAD, tracked and untracked source content, dirty paths,
interpreter/package versions, command arguments, per-step lane, start, wall and
CPU times, and the integration mode. A step's CPU time is its own process tree's,
so it stays correct while the lanes overlap. Changed source or installed packages invalidate the result with exit 76;
a failed command stops the profile and retains its evidence. CPU time sums work
across processes and is not elapsed time. Use a frozen worktree and run one heavy
benchmark at a time when comparing settings.

`--backend-workers`, `--unit-workers` and `--ux-workers` set independent worker
budgets. Unspecified values retain each suite's default. `--ci-parity` requires
backend integration tests with `ROLEBAND_REQUIRE_INTEGRATION=1`; ordinary local
skips remain visible in the report. The backend uses a separate temporary
Postgres cluster, and cleanup stops only clusters within this run's directory.
In a worktree, invoke the script with the main checkout's interpreter.

For a focused run, use `unit`, `ux` or `backend` with repeatable `--test` file/node
selectors. A focused run is recorded as such and does not replace a full gate.

The dashboard profile builds once and serves that artifact on its own port,
with separate browser results and a dead API proxy target. Standalone Playwright
also supports `ROLEBAND_UX_MODE=dev|build|preview`: `dev` starts Vite, `build`
builds and previews, and `preview` serves an already prepared build. Built modes
forbid `.only` and run the CSP checks. `CI=1` remains a supported built-mode
shortcut with two workers; local built mode uses the local worker default.
`ROLEBAND_UX_WORKERS`, `ROLEBAND_UX_PORT` and `ROLEBAND_UX_OUTPUT_DIR` override
the standalone worker budget, port and results directory. Every mode starts its
own server with a strict port; an existing server is refused.

`--docker-browsers` (for `all`, `dashboard` or `ux`) runs the checked build and
both browser projects in Linux, in the Playwright image of the locked
`@playwright/test` version, with 12 browser workers unless `--ux-workers` says
otherwise. Lint and Vitest still run on the host. Use it on macOS for a full
browser run: there WebKit's window captures accumulate in WindowServer until it
aborts and ends the desktop session, and Linux has no WindowServer. A few specs
on the host are fine. The container
receives a tar of exactly the files the report fingerprints. Its packages are
installed once per image and lockfile, into a Docker volume named
`roleband-ux-node-modules-<hash>`; that install is the only step with a network,
so the build and the browsers cannot reach an API on the host. Containers carry
the run's label and cleanup removes any an interrupted run leaves. The mode needs
a running Docker engine and is never part of unattended execution: Docker stays
optional, and nothing the supervisor runs calls this runner.

The browser focus sweep waits for actual CSS transitions under reduced motion;
normal-motion and missing-ring controls retain the painted contract.

## The test database

Most backend tests are pure and need no database. A test that needs one takes
the `db_session` fixture from `backend/tests/conftest.py`:

- Each test process creates its own scratch database, `roleband_test_<pid>`,
  on whatever server the settings resolve to, so parallel workers never
  collide. Locally that is the embedded Postgres, which starts on first use;
  in CI it is a Postgres 16 service with pgvector, named by
  `ROLEBAND_DATABASE_URL`.
- The schema is built from the SQLAlchemy models with the `vector` and
  `pg_trgm` extensions. Before each test every table is emptied and every
  sequence its columns own is restarted: the tables holding committed rows are
  truncated, and all of them are while another session on the scratch database
  is inside a transaction. The database is dropped at session end. Tests never touch your `roleband`
  database.
- `api_client` drives the real FastAPI routes on the scratch database, a fresh
  session per request, so commit your seed rows.

Autouse guards fail a test that reaches the live database
(`tracker.db.session.get_engine`; take the `scratch_scope` fixture instead,
which points every module's `session_scope` at the scratch database), refuse a file lock in the checkout's `data/` (where the
live run locks are; give the code a data directory under `tmp_path`), refuse
DNS, answer the outage and power probes, keep usage sharing off, and give each
test its own secret key file. A test of one of those features sets its own answer. A test
driving a route that would really start a scrape or spend money also takes
`no_escape`, which refuses subprocesses, signals and outbound HTTP.
`backend/tests/test_process_tripwire.py` fails a module that can start or signal
a process unless it is named there, and a test module that can reach one without
`no_escape`.

**Skips.** With no reachable server, database tests skip locally. CI sets
`ROLEBAND_REQUIRE_INTEGRATION=1`, which turns every skip into a failure unless
its reason matches `OPTIONAL_SKIPS` in `backend/tests/skip_policy.py`. A new,
legitimate skip is added there with the reason it may stay a skip.

**Real-cluster tests.** `backend/tests/test_embedded_db.py` starts a
throwaway embedded cluster and checks the extensions, the pinned locale, the
Postgres features the code uses, and that every migration applies with
`alembic check` clean. It also starts clusters with a memory preset, without
one, and through the app's own start; `backend/tests/test_database_presets.py`
pins each memory size's preset and the line it shares with the model. `./setup.sh` installs the prebuilt `pg_trgm` they
need; in a virtualenv made without it, run
`.venv/bin/python -m scripts.install_pg_contrib` once. The populated-upgrade
rehearsal is opt-in locally and always runs in CI:
`ROLEBAND_REHEARSE_UPGRADE=1 .venv/bin/python -m pytest tests/test_upgrade_rehearsal.py`.

## UX specs never reach a real backend

The dev server proxies `/api` to the API on `:8010`, but the server Playwright
starts proxies it to the dead port `127.0.0.1:9` unless `VITE_API_TARGET` names
another target (`DEAD_API_TARGET` in `tests/ux/runProfile.ts`): WebKit can
release a request a spec parked and never answered after its test ends, and it
must not reach an API running on your machine. If you point a run at a live API,
an unmocked spec passes locally on real data and fails in CI, so every spec is
hermetic:

- Specs import `test` and `expect` from `dashboard/tests/ux/fixtures.ts`, never
  from `@playwright/test` (eslint `no-restricted-imports`, held by
  `src/test/ux-fixture-imports.test.ts`). Its automatic `apiGuard` is a
  catch-all route on the app's `/api/**` that aborts any request no mock
  claimed and throws `Unmocked API request: <method> <url>`. Service workers
  are blocked so nothing bypasses interception.
- Mock with `mockGet` or `mockApi` from the same file. They match on method, so
  a read mock never acknowledges a write.
- Route patterns are anchored to the app's origin: write `"/api/jobs?**"`,
  never `"**/api/jobs?**"`, which also matches the dev server's modules under
  `/src/api/` and stops the app booting. `src/test/ux-route-patterns.test.ts`
  names an unanchored pattern by file and line.
- `tests/ux/api-guard.spec.ts` holds the guard's decision against planted
  cases in both directions.

Every Playwright run already points the proxy at the dead port, so a new spec
that needs a backend fails on its own. From `dashboard/`, run it on a free port:

```bash
ROLEBAND_UX_PORT=5183 npm run test:ux -- tests/ux/<your-spec>.spec.ts
```

A dead port alone does not prove it, because an app that swallows a failed
request can leave a spec green; the guard's throw is what fails by name.

## Fixtures

- **Recorded listings.** `backend/tests/fixtures/listings/<adapter>/` holds
  `page1.json` (and `page2.json` where the board pages) with the raw body the
  board serves. A counted adapter's fixture rows add up to its declared total.
  The conventions are in the docstring of `backend/tests/contracts/conftest.py`.
- **Scrub before commit.** Every new capture goes through
  `.venv/bin/python -m scripts.scrub_fixtures` (from `backend/`). It reduces a
  page to what its parser reads and replaces analytics ids, CSRF tokens and
  people's names, emails and ids with placeholders. `--check` exits 1 if
  anything would change, and `backend/tests/test_scrub_fixtures.py` fails on an
  unscrubbed fixture.
- **Real shapes.** Take a fixture's shape from a capture or the source's own
  documented example; a hand-written shape only proves the shape you invented.

## Registry-backed contract suites

`backend/tests/contracts/` parametrizes over each registry: listing connectors
(`HARNESSES` in `conftest.py`, run in normal, repeated-page, broken-payload and
429-then-recover modes), detail parsers (`REALISTIC_DETAILS`), pay, price and
intelligence providers, LLM clients, and the location and completeness rules.

A new implementation ships its fixture and harness entry in the same change;
the suite fails by name without them. Never add a skip or an allowlist entry to
land a connector. The same rule holds for `backend/tests/test_company_blueprint.py`
(a built-in company's artifacts) and `backend/tests/test_source_review.py` (a
listing adapter's `SOURCE_REVIEWS` row).

## Frozen artifacts

These files change only on purpose, in the direction shown. Regenerating one to
silence a failure your change did not intend is not allowed.

| Artifact | Guard | How it moves |
|---|---|---|
| `backend/tests/fixtures/route_table.json` | `tests/test_api_route_table.py` | `scripts.freeze_route_table` for a deliberate route change, named in the PR; `modelled_count` only rises |
| `backend/tests/fixtures/schema_metadata.json` | `tests/test_schema_metadata.py` | `scripts.freeze_schema_metadata`, with the model change's migration |
| `ignore_imports` in `backend/pyproject.toml` | `tests/test_import_contracts.py` | Only shrinks |
| `dashboard/src/test/ratchet-baseline.json` | `src/test/ratchet.test.ts` | Only lowered |
| `LEGACY_EDGES` in `dashboard/eslint.config.js` | `src/test/layer-edges.test.ts` | Only shrinks |
| `dashboard/src/test/copy-check-baseline.json` | `src/test/copy-check.test.ts`, `npm run copy:check` | Only lowered (`npm run copy:check -- --freeze`) |
| `dashboard/bundle-baseline.json` | `npm run build` | `npm run bundle:record` when a change deliberately moves the startup bundle |
| `dashboard/openapi.json`, `dashboard/src/api.gen.ts` | `contract-drift` workflow | Regenerated, never edited (see the gate) |

## No live network in tests

No automated test contacts a live job board, pay source or API. Adapters run
against `httpx.MockTransport` and recorded fixtures; a test that builds a real
adapter takes `no_escape` and mocks `make_tier_client`. Live confidence comes
from smoke commands run by hand from `backend/`: one adapter with
`.venv/bin/python -m scripts.smoke_adapters <company> 5`, catalog board tokens
with `.venv/bin/python -m scripts.check_catalog_tokens`, and a capped pipeline
run (which never closes postings) with
`.venv/bin/python -m tracker.daily --max-list 150 --no-hydrate -v`.

## Benchmarks carry negative controls

Model and classifier accuracy is measured by the `backend/scripts/bench_*`
scripts and the eval fixtures in `backend/tests/fixtures/`. Every eval set
includes inputs the instrument must fail on: a measurement that cannot fail
measures nothing, and an unchecked one tends to flatter what it measures.
For example,
`.venv/bin/python -m scripts.bench_level_bands compare <snapshot> --expect <companies>`
exits 1 when a company outside `--expect` moves or a planted control is
misjudged.

## What CI runs

| Workflow | Runs on | Steps |
|---|---|---|
| `backend.yml` | Every push and PR | Dependency audit of the locked graph; the MiniLM model for the embedding golden test; Postgres 16 with pgvector; install the prebuilt `pg_trgm`; ruff; mypy; import-linter; pytest with `ROLEBAND_REQUIRE_INTEGRATION=1` |
| `dashboard.yml` | Every push and PR | Dependency audit of production packages; lint; knip; build; Vitest; Playwright on both projects against the built app, split by test across three shards |
| `contract-drift.yml` | Every push and PR | Regenerates `openapi.json` and `api.gen.ts`, fails on any diff |
| `hygiene.yml` | Every push and PR | `backend/scripts/check_project_name.py`, `backend/scripts/check_comment_hygiene.py` |
| `mac-launcher.yml` | Every push and PR, weekly, and each release; its jobs run only when needed | A Linux `changes` job picks the tiers. Native tier (macOS): copy export check, Swift tests, installer and release tests, install guide in Chromium and WebKit, source app build, transport test. Bundle tier (macOS, never on a PR): the dashboard and the standalone app with its engine, launched read-only, packaged as a candidate for local signing |
| `links.yml` | Markdown changes, and weekly | External links in every tracked `*.md` resolve (lychee; loopback skipped, a rate limit counts as alive). Only the weekly run fails; on a pull request it reports |
| `vendored-provenance.yml` | Monthly, and when vendored pins change | Vendored snapshots against upstream; a notice, never a PR blocker |

The dependency audits fail on any known advisory (in the dashboard, high or
critical in a production package) that no current entry in
`backend/audit-exceptions.toml` or `dashboard/audit-exceptions.json` accepts.
An entry names the advisory, the package, the reason and an expiry date; an
expired entry, or one that matches nothing, fails the run too. Run them locally
with `.venv/bin/python -m scripts.check_dependency_audit` from `backend/` and
`npm run audit:check` from `dashboard/`.

The secret scan is gitleaks with the repository's `.gitleaks.toml`, which excuses
known harmless lines by file and line shape, never a whole file. A release
export stops on any finding. `backend/tests/test_gitleaks_config.py` scans the
tracked tree, plants a secret beside every excused line, and checks that each
exception is still needed. It skips where `gitleaks` is not installed; the
backend workflow installs the same version the release export uses (8.30.1),
checked against its release checksum, so in CI it always runs.

Every workflow can also be started by hand (`workflow_dispatch`). The five
that judge a pull request (backend, dashboard, contract-drift, hygiene,
mac-launcher) take no `paths:` filter, so a required check never waits on a run
that was never scheduled; `backend/tests/test_ci_workflow_triggers.py` holds
that, and fails when a filtered workflow's `paths:` misses a file its steps read.

The Mac workflow filters inside itself instead. Its `changes` job lists the paths
each tier watches (`NATIVE_PATHS`, `BUNDLE_PATHS`) and
`launcher/macos/Tools/ci_changes.py` compares them with the change; a tier that
is not needed reports as skipped, which a required check accepts. A release, a
manual or weekly run, or a diff that cannot be read runs both tiers. The bundle
copies the whole engine and dashboard but watches only its own inputs, so an
engine change it does not name is built by the weekly run or the next release.
The same test holds that each tier's list covers every file its steps read. In CI Playwright forbids `.only` and never
retries: a flaky test is diagnosed, not retried.

Backend and dashboard workflows cancel superseded runs of the same pull request.
Main-branch pushes use independent run groups and do not cancel one another.

## Triaging a flaky UX failure

A red UX run is not automatically your change.

1. **Check the load.** On a busy machine timeouts look like regressions; a
   slower total run time is the tell. Compare baseline and change by
   alternating runs in the same window, not one batch after the other.
2. **Check the test port.** Playwright refuses an occupied port. Choose
   `ROLEBAND_UX_PORT` or use the local runner's automatic port instead of
   adopting a server that may belong to another checkout.
3. **Do not edit files during a local run.** Hot reload mid-run produces
   failures that look real.
4. **Check both serving modes.** CI serves a build: run
   `ROLEBAND_UX_MODE=build npm run test:ux`.
5. **Read the evidence.** Traces are kept on failure;
   `dashboard/test-results/results.json` has every result.
6. **Do not stop at the first explanation.** A mechanism that fits the symptom
   may not be the only cause.
7. **Pin the ordering down-stack.** Once you know the failing interleaving,
   drive it directly in a Vitest test. Never add retries.
