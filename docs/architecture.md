# Architecture

RoleBand is a job-seeker's opportunity radar that runs on your own computer. It
reads the careers boards of the companies you follow, classifies every posting
(role, level, location, pay) and keeps every observation, so it can tell you what
is new, what closed and how hiring moves. A React dashboard shows the best
openings, and a local MCP server lets an AI agent you run ask the same questions.

This document explains how the pieces fit, the rules that hold them together and
the tests that enforce them. Setup and daily commands are in
[development.md](development.md); the testing contract is in
[testing.md](testing.md).

## System overview

Everything runs locally against one database.

| Process | Entry point | What it does |
|---|---|---|
| Embedded Postgres | `backend/tracker/platform/embedded_db.py` | Postgres 16 with pgvector from a pinned Python wheel, started on first use with a [memory preset](#embedded-database-settings) picked from the computer's memory; setup installs a matching [prebuilt pg_trgm](third-party.md#installed-then-shipped-or-run). Data lives in `~/.roleband/db`; `ROLEBAND_PGDATA` moves it, `ROLEBAND_DATABASE_URL` uses an external server. |
| Pipeline | `backend/tracker/workflows/pipeline.py` (`python -m tracker.daily`) | One collection run: read boards, enrich, persist, run the post-passes. |
| Supervisor | `backend/tracker/supervisor/` (`python -m tracker.supervisor run`) | The one background process: it serves the API as its child and runs every background job (scans, the directory read, plugins, prices, backups, health, the preflight). See [Background work](#background-work). |
| Scan tick | `backend/tracker/workflows/scheduler.py` | The supervisor's `scan` job: a short tick that runs what is due, a full read when the computer wakes or the last one is old, the rest of a full read something stopped, a quick discovery check on a repeat while it is on (`backend/tracker/workflows/schedule_plan.py`). |
| API | `backend/tracker/api/app.py` | FastAPI on `127.0.0.1:8010`: dashboard reads, the user's own writes, requests for background work, and the built dashboard from `dashboard/dist`. It starts no process: what it asks for, the supervisor runs. |
| Dashboard | `dashboard/src/` | React 19, TypeScript, Vite. In development Vite serves `:5173` and proxies `/api` to `:8010`. |
| MCP server | `backend/tracker/mcp/server.py` | Local STDIO server for external agents, reads and pursuit writes gated separately. See [mcp.md](mcp.md). |
| Health | `backend/tracker/workflows/watchdog.py` | The supervisor's `health` job: database reachability, stuck runs, stale data (asks for a scan), a stale backup, desktop alerts. |

On macOS, `deploy/install.sh` installs one per-user background item,
`com.roleband`, which runs the supervisor (`deploy/roleband`). Elsewhere the
supervisor runs in the foreground under whatever service manager you use.

The installed macOS checkout publishes launcher discovery at
`~/.roleband/launcher/installation.json`. The installer and each supervisor
startup refresh it only when the user's installed `com.roleband` plist names
that checkout. Its identity uses the resolved checkout path and its API origin
uses the configured bind address and port. Other checkouts leave it alone;
uninstall removes only the matching registration. This file discovers an
engine; it grants no permission to start or stop one. The file is written
atomically, readable by its user only, and holds a product code, a format
version, a fingerprint of the resolved checkout path, the version and the HTTP
origin. A wildcard bind address publishes its loopback counterpart; any other
non-loopback address publishes nothing. A changed port or version keeps the
fingerprint; a moved checkout changes it. A missing, malformed or unrelated file
survives uninstall. A discovery failure never stops the engine. Publishing or
removing the file needs no database and starts no scan or other work, and the
file does not prove that the API answers or that the background item runs.

The native Mac launcher uses AppKit for its menu-bar item and SwiftUI for the
panel and first-open setup. At launch it selects placement guidance, attachment
to a verified existing engine, a database-ownership block, or ownership of the
packaged engine. Attached mode verifies `/api/status.launcher` before opening
the browser and leaves the engine running on Quit. An explicit source-engine
Start request requires the registered checkout, installed plist and loaded
per-user job to match and the job to be confirmed stopped. An HTTP timeout alone
never permits Start.

Owned mode uses the [packaged process host](#packaged-process-host).
Its schema-free identity health and first-open database/model preparation follow
[First-open preparation](#first-open-preparation). Quit stops
only owned processes. Closing setup continues preparation, with no automatic
browser opening or login registration. Native text is exported from the shared
Fluent catalog. The backend's status presentation distinguishes actual work,
queued work, holds, attention, coverage and the last finished scan; pending rows
never prove execution. Beside it, `/api/status.launcher.scan` carries the scan
picture: while a run executes, its heartbeat progress (percent, the companies
read longest, roles pending and recorded); always, the last finished run's
companies, new roles, postings and whether the person stopped it, and the next
scheduled scan when scheduling is on. An engine without the field, or with a
malformed one, leaves the panel on its status card. The panel has Scan, Settings
and About tabs, with the update banner above them on every tab.

The canonical release version is `dashboard/package.json`; the backend's
`tracker.__version__`, FastAPI metadata and native app build read that value.
For a packaged engine the build writes that value to immutable release metadata;
runtime paths, supervision and resource layout are in
[Packaged engine](#packaged-engine).
The lockfile and matching changelog heading are checked against it. The local
`GET /api/release-notes` returns the installed version's exact changelog section
with the engine identity, never an unreleased draft or a different version's
notes. Native What's new renders those notes as text. The first verified
connection establishes a baseline per installation; newer installed releases
remain unread until their notes are displayed. This local flow contacts no
external update service.

Native update checks use the public GitHub releases API only after an explicit
choice. Automatic checks stay off until enabled. An explicit manual check
authorizes one request independently of that setting; it neither changes an
existing choice nor enables automatic checks. A default-off or declined choice
prevents all passive requests. The native update interaction and
content rules are in [ui.md](ui.md#native-launcher-updates).
Daily checks are throttled across restarts, including failed attempts; server
rate limits also delay manual checks. Requests carry no credentials, refuse
redirects and bound the response size and duration. Only stable semantic
versions and release pages in the official repository are accepted. A failed
check preserves the last validated offer. Release files attach after the release
is published, so a release is offered only once its image, checksum, metadata
and signature are all uploaded; until then a check finds nothing new. The release
listing is not signed, so a check also reads the release's signed checksum and
metadata and offers it only when they verify with the installed app's keys. A
release that fails is treated as no release and is never announced; a check that
cannot read them fails. A verified offer is not replaced by an older listing. Offered notes have their own preview
and never acknowledge an installed version. Update in the panel downloads the
release, verifies and stages it, then quits the app and hands the replacement to
the helper. A lost connection pauses the download until the network returns; a
server that times out eight times in a row without sending more ends it as a
failure. Update is the only press: a running scan stops, and the roles it found stay.
The next open reports the result. Launcher preferences retain the
English consent text, language and time of the choice.
The native core stages the signed image and a helper replaces the app and
database as one recoverable transaction, as [Mac app updates](#mac-app-updates)
describes.
Release checks only find an offer; these operations run only after the person
presses Update. Desktop update notices use the local UserNotifications API, with
permission requested when the person turns on notices with automatic checks in
About. Setup can enable
checks without asking for notification permission. Delivery is deduplicated by release
version and rechecks the automatic choice and current offer before posting.
An offline demo feed and faster interval require a preview bundle with an
explicit registration; normal source installation and release packaging reject
bundles containing that feed configuration.

The optional source installer builds and verifies the native app before copying
it into the user's Applications folder. A running launcher, a foreign bundle or
a symbolic-link target prevents replacement; a failed publication restores the
previous app. It registers no login item. Engine installation offers it after
registering the background service and keeps engine success independent of the
optional app. Native build metadata records the source revision and dirty state.
First-open guidance lives outside the app, in the disk image's Start here guide
([ui.md](ui.md#launcher-installation-guide)), because macOS can block a
downloaded app before its own setup runs.
Release packaging accepts only a clean matching stable version and source,
Apple silicon executable, macOS 14 deployment target and ad-hoc signature. It
verifies the mounted image and publishes its checksum and source manifest
together. CI builds with read permission only and attaches nothing.

```text
careers boards
   | connectors/listing (RawJob) + connectors/detail (description sections)
   v
enrich (level, family, location, pay) -> scope filter
   v
persist: jobs (current) + job_observations (append-only) + lifecycle events
   v
post-passes: embeddings, skills, lineage, place sets, demand, pay metrics, ...
   v
Postgres -> api/routers -> dashboard/src/api -> screens
         -> mcp/server  -> your agent
```

One writer collects at a time: the pipeline holds a file lock (`data/daily.lock`)
and a Postgres advisory lock, so a scheduled run, a manual sync and a retry never
overlap.

## The Mac app

### Packaged engine

`backend/packaged.py`, the entry point for the app's supervisor and for external
MCP clients, sets `ROLEBAND_PACKAGED=1` before importing the engine and disables
bytecode writes, which child processes inherit. Source entry points keep their
defaults, and packaged settings load no `.env`. `Contents/Resources` holds
`engine` (code, Alembic files, constraints and `release.json`, whose version
running processes read instead of git), `dashboard` (the built site and its
CSP), the changelog and `plugin-wheels` (the SDK and robots-matcher wheels that
plugin environments install, so nothing writes into the app). The app runs from
a read-only tree; the build supplies this layout and validates the version and
wheels.

All writable state lives in `~/.roleband` (database, plugins, logs, locks,
pacing, models, backups, supervisor files), so moving or replacing the app moves
none of it. Database and secret-key overrides exist for isolated tests. Packaged
supervision has no git activation, source preflight or dashboard build; schema
compatibility still gates database jobs. Its backup job uses the runtime's
Python and matching Postgres client tools, verifies the whole archive before
publishing it, keeps 14 daily archives and every monthly one, and refuses an
empty replacement while earlier archives exist. Startup only checks that
`pg_trgm` is available.

The app and a source installation share `~/.roleband/db`, so a cluster names its
maker: before creating one, packaged mode writes `db.owner.json` containing
`{"owner": "app"}` beside it, and a source installation writes none. Packaged
mode, and the app before it starts anything, refuse a cluster without that
record, including one a source uninstall left behind. Packaged mode never
migrates, takes over or stops a source installation.

### Packaged process host

`LauncherCore.EngineHost` runs the engine in owned mode. It checks source
discovery and app placement again before spawning, and a private file lock lets
one app own the engine. It reads health through the schema-free identity client
with the identity and loopback port its caller gives, exposes lifecycle state,
and creates no schema, provisions no model and never targets a source
installation.

The interpreter starts isolated, in a new process group, with only packaged
mode, the data directory, embedded Postgres and the fixed loopback address and
port in its environment; ambient Python paths, database URLs and source settings
cannot reconfigure it. Before spawning, the host publishes a private recovery
record holding a random marker that every engine child inherits, even one in its
own session, so the next host finds them after the supervisor or the app dies.

Health is read every three seconds. Startup gets a minute, renewed by each valid
preparation response; an engine that has answered restarts after three failed
reads. Restart delays double from one second, at most three automatic restarts
run in ten minutes, healthy reads do not refill that budget, and after it only
an explicit start or restart runs the engine.

Shutdown signals the supervisor, API and job groups and kills what still runs
after ten seconds. Every signal checks that the PID is the current user's and
its kernel start time; a recovered group must also carry the marker. Postgres
stops after its clients: the host confirms the data directory's server belongs
to a RoleBand app bundle and its PID file matches the server's start time and
directory, sends SIGINT, then SIGKILL after ten seconds. An app server left by a
previous launch stops before a new engine starts. Source-install servers never
receive these signals.

`Installation.owned` builds the owned identity from the bundle alone: the
instance is the first 24 hex characters of the SHA-256 of the POSIX-resolved
Resources path bytes, as the Python engine computes it; the version is
`RoleBandVersion`; the origin is `http://127.0.0.1:8010`, with a port override
for isolated runs. A source-only shell or incomplete bundle metadata has no
owned identity. It reads no source registration and writes no discovery state.

### First-open preparation

Before any database job, the packaged entry point claims only new or app-owned
storage and refuses source registrations and foreign clusters. While a child
process creates or migrates the database, backing up an existing versioned
schema first, a short-lived loopback responder serves `/api/launcher-health`; it
closes its socket before the supervisor's API takes the port. A failure keeps
the diagnostics and the responder until Retry or Quit.

Preparation facts (database, service and model state, artifact bytes, tier, and
a waiting or failure reason) live in an account-owned JSON file under the data
folder, outside Postgres, written atomically under a private file lock. Missing
or invalid facts read as waiting. The file is observational and can be
recreated; the database and partial model files hold the finished work. The
responder and the API publish the same identity and preparation contract without
opening a database session, and progress reads never hash model files.

An engine with the right identity is not yet a usable dashboard, so the host
checks identity apart from readiness. A database or service failure waits for
Retry; unreachable health, a wrong identity or dead children get the host's
bounded recovery. The model keeps its persisted RAM-based tier; its downloads
resume with Range validation, restart when a server ignores Range and retry in
the background, while the API answers with lexical search. Quit stops the owned
process tree and its database; the next launch repeats initialization safely and
resumes downloads.

### Release signing and keys

`launcher/macos/build-bundle.sh` installs a checksum-pinned CPython and, by
hash, one macOS 14 wheel per package from `runtime-lock.txt`, which agrees with
the backend constraints, so the build machine cannot change what ships; every
binary loads on macOS 14. The dashboard must carry the tree stamp of
`deploy/build_dashboard.sh` for the commit built, because git ignores built
files. A build signs ad hoc: macOS can run it, but it has no publisher identity
and no update key, so it is a candidate that cannot be attached. CI builds
candidates with no release keys and no write token.

`launcher/macos/Tools/signing.py seal` runs on the maintainer's Mac, where the
private keys stay. It re-signs a candidate with the release certificate, clears
group-write, other-write, setuid and setgid modes, and stamps the signed
Info.plist with `RoleBandUpdatePublicKey`, `RoleBandUpdateSpareKey`,
`RoleBandUpdateRequirement` and `RoleBandUpdateFeed` set to `roleband/roleband`.
`launcher/macos/release-identity.json` records the certificate's SHA-256 and
both public keys; seal, `release.py prepare` and `release.py attach` refuse any
other, because macOS ties a person's approvals to the certificate and apps trust
only their own keys. `signing.py record` writes it once, replaces it only when
asked (keeping a recorded rule) and refuses a production identity without a
spare.

No single folder can sign a release. `generate` writes the spare's private half
to a separate folder and encrypts both release keys and the certificate's p12
with secrets typed at use and never stored beside them; `record` refuses a
production identity whose folder holds the spare's private half, a stored
password or an unencrypted key. Importing the certificate uses a scratch
keychain with a random password.

A lost or leaked release key is replaced by an update signed with the spare,
which becomes the current key with a new spare beside it. The requirement names
the release certificate, or a wider `update_requirement` from the identity, so
an ordinary update cannot change the certificate and losing it ends updates. A
new signer, such as an Apple Developer ID, arrives in one release signed with
the current certificate whose rule accepts both. The app reads offers and
downloads only from its stamped feed, never from a setting, and refuses an
update naming another feed; `prepare` and `attach` accept only that feed.

Release files are the image, its checksum, source metadata and an Ed25519
signature over the checksum and metadata bytes together. `prepare
--before-you-update` adds one paragraph of at most 400 characters and makes the
metadata format 3, format 2 plus `before_you_update`; a release without a notice
stays format 2, which older apps accept, and an app accepts format 3 only with a
valid notice. `prepare` requires the sealed app to carry and meet the recorded
rule and refuses any file group or others may write, setuid or setgid files, and
anything but regular files, folders and links, because code signatures do not
cover modes; installed apps refuse the same in an update. Pre-releases get the
same checks; drafts and moved tags take no assets. Attachment runs locally after
signing; CI publishes nothing. A published release is never withdrawn, because
installed apps keep a verified newer offer: a newer release fixes a bad one.

Each build records its image size. Growth over 15 percent from the last released
image needs a note in `launcher/macos/bundle-size.json`, null or one short
sentence, which apps show as optional text. Attaching to the production feed
records the new baseline and clears the note; commit it before the next release.

### Update downloads

`LauncherCore.VerifiedArtifact` authenticates the exact checksum and metadata
bytes with CryptoKit before reading any field, with keys from the installed
release bundle only; source companions, previews and key-free candidates supply
no trust. It checks version, file name, architecture, format, key pin and source
commit, and hashes the image as a regular file, links unfollowed, bounded by the
signed length. A valid manifest is not enough: extraction and code-signing
checks still come before replacement.

`UpdateDownloader` takes no caller-supplied key, writes to a private
account-owned cache under a file lock, and authenticates the image's name,
length and digest from bounded downloads of the signed files before requesting
it. Redirects are capped and never leave HTTPS. A transport failure keeps the
bytes and retries after a cancellable delay; a Range answer must match the saved
offset and signed total, and a server ignoring Range restarts the file. A wrong
offset alone is a download failure. Free space must cover the rest of the
download plus the caller's backup and staging reserve. Failed verification
discards the partial image; a cached image is verified again before reuse.
Starting a download deletes other release folders unless another process holds
their lock, following no links. The downloader never stops an engine, mounts an
image or replaces an app or database.

### Mac app updates

- `UpdateImageStager` (`launcher/macos/Sources/LauncherCore/UpdateBundle.swift`)
  rechecks the signed image digest, mounts it read-only without opening Finder,
  and validates the candidate before and after copying it to a private staging
  folder.
- Both app signatures verify. The candidate meets the installed app's signing
  rule (`RoleBandUpdateRequirement`, stamped at sealing), or the same leaf
  certificate when the installed app has no rule, and also the rule it carries
  itself, or every later update would be refused.
- The candidate's release key is the installed app's current or spare key, and
  its version and source commit match the authenticated release.
- No candidate file is writable by group or others or carries setuid or setgid,
  and the bundle holds only regular files, folders and links, because the copy
  keeps modes the code signature does not cover.
- The executable is arm64, engine release metadata matches the app version, and
  runtime paths stay inside the bundle. Candidates, previews, dirty sources and
  source companions never qualify.
- A candidate that fails is a failed check, and its download is discarded.
  Cleanup detaches that exact mount; a forced detach touches only that mount.
- The app writes a private plan into the update's folder (paths, both versions
  and source commits, its release keys, signing rule, leaf certificate and
  process identity). It then starts its own executable as the helper in a new
  session, with a fixed environment that never carries the engine's owner
  marker.
- The helper holds a per-update lease for its life. It waits up to two minutes
  for the planning process (PID and start time) to exit, and touches nothing if
  it does not. It validates every bundle against the plan's identity, so trust
  never moves with the app being replaced.
- The helper stops an app it opened with SIGTERM, then SIGKILL after 30 seconds,
  and reclaims an engine left behind through the engine's own record and marker.
  It never discovers or kills other processes, and it launches through Launch
  Services. A failure before the journal exists leaves the app and database
  untouched, and the helper reopens the app.
- `UpdateTransaction` refuses source registrations, foreign or unmarked
  databases, symlinks and anything but an upgrade. A per-home installation lock
  excludes other replacements, and a pending journal is recovered before another
  update starts.
- It takes the engine's ownership lock, requires a stopped cluster, copies the
  database outside the app, verifies the whole tree's contents and permissions,
  and publishes that backup before changing the app. The fingerprint normalizes
  macOS path aliases and refuses symlinks and special files. Encryption keys,
  model files and other home state stay out of the copy.
- A private, versioned journal (app versions, transaction identity, backup
  fingerprint, progress) is atomically replaced and synced before each
  replacement step. A loaded journal's paths must match the configuration.
  Renames keep the previous app beside its original location. The ownership lock
  is released before the new app launches.
- Launch and health share a two-minute monotonic deadline. Each report that the
  engine is still preparing its database moves the deadline two minutes on, up
  to the engine's 30-minute preparation limit plus two minutes, so a large
  upgrade can finish and a hung one still rolls back.
- Only a health read showing the installed app's identity, the new version and a
  ready database and service commits the update.
- A launch failure or an unhealthy version starts recovery, whether or not the
  request is cancelled. Recovery stops owned work, retakes the ownership lock
  and verifies the backup before moving the failed database aside. It restores
  the database before it restores and launches the previous app.
- A damaged backup or a newly found foreign owner blocks recovery rather than
  overwrite current data. The journal and the filesystem let a new transaction
  repeat an interrupted recovery.
- An installation never starts an old engine on a migrated database before
  recovery completes. Before an owned app starts its engine, it reads the update
  folders. A live lease means a helper is at work, so the app quits, unless it
  is the version the helper opened. An unfinished journal with no helper makes
  it start a recovery helper and quit.
- The recovery helper runs from the previous app beside the stage when that app
  passes a strict signature check and meets the running app's signing rule, and
  otherwise from the running app.
- A recovery helper that cannot finish leaves a mark beside the journal,
  releases its lease and opens the app. That open, and every later one, starts
  nothing and shows that the update stopped, with the helper's log and a way to
  retry recovery. An unreadable journal, or an unfinished one written for
  another app location, shows the same window without the retry.
- Failed databases stay beside the journal. App bundles are dropped when the
  transaction finishes: they can be downloaded again, and logs stay in the home
  folder.
- The two newest verified managed backups are kept. Older managed copies retire
  only while that pair is intact. Unknown archives and backups of failed
  transactions are kept. A cleanup failure keeps extra backups and never undoes
  a healthy update.
- The journal covers process interruption, not storage loss, and does not
  replace independent backups.

## Background work

One process, the supervisor (`backend/tracker/supervisor/`), runs everything
outside the API's request path. It holds advisory lock 91247 on its database for
life, so a second supervisor (another checkout, a worktree) waits instead of
dispatching twice.

- **Jobs** are rows of `JOBS` (`registry.py`): what runs, on which schedule
  (every N seconds from the last start, daily with catch-up, on request, when a
  fingerprint settles, at a deadline the job named), in which power state, and
  whether it waits for the preflight. `due.py` decides from the registry, the
  last runs, the queued requests and the world (power, gate, schema,
  dependencies), as a pure function.
- **Each job is a child in its own session**, started through the trampoline
  (`child.py`), which records the exit code beside the run. A supervisor that
  restarts adopts what is still running; nothing is killed to restart it.
- **Requests are a durable doorbell**: the API writes a `job_requests` row in the
  same transaction as its own change and NOTIFYs; the supervisor listens and
  polls every 30 s regardless. The domain queue stays the truth about what to
  do, so a replayed request does no duplicate work.
- **Every run is recorded** in `job_runs` (process state, exit code, the job's
  structured result, links to `scrape_runs` and the like), and every job's state
  and reason in `job_status`, which `/api/status.jobs` serves.
- **The preflight gate** holds the jobs that read third-party sites or write
  collected or derived data while a dirty tree has not passed its own suite
  (`deploy/preflight.sh`). Prices, backups, health and the API never wait for it.
- **Activation** (`activation.py`) follows HEAD, never dirty content: after a
  landing it holds database jobs while the schema or the installed dependencies
  are behind (`setup.sh` finishes them), rebuilds a stale dashboard aside and
  swaps it in (`deploy/build_dashboard.sh`), then restarts itself and the API on
  the new code.
- **Maintenance** (`python -m tracker.supervisor maintenance on|off`) stops or
  drains the running jobs, stops the API and lets go of the database; a live
  restore (`deploy/restore_db.sh`) refuses to swap while a supervisor holds 91247.
- **Logs** are `data/logs/<job>.log`, `api.log` and `supervisor.log`, plus
  `data/alerts.log` and the embedded Postgres server's `log`, each cut at 10 MB
  with one rotated copy. A run whose log has rotated since it started says so
  (`job_runs.log_rotated`). `deploy/backup_db.sh` reports by exit code alone; the
  health job raises the backup alert from the failed run.
- **Liveness.** The supervisor is a single point of failure, so it stays thin (no
  models, no web server of its own): the service manager restarts it, a stall
  thread ends it when a task stops beating, and `/api/status.jobs` reports
  `supervisor_stale` while its heartbeat is old. Without a running supervisor
  nothing the API asks for happens.

## Backend layers

`backend/tracker/` is one package in strict layers; imports go downward only.

| Layer | Modules | Notes |
|---|---|---|
| L6 interface | `api`, `mcp` | Independent front doors onto the same services. `api/app.py` only composes. |
| L5 workflows | `workflows`, `daily`, `scheduler`, `watchdog`, `discover_roles`, `agents`, `supervisor` | Runs, scheduling, supervision. |
| L4 services | The L4 row of the layers contract in `backend/pyproject.toml` is the list: `db`, the services (`enrich`, `skills`, `lineage`, `semantic`, `search`, `scope`, `profiles`, `analytics`, `notifications`, `intelligence_runtime`, `plugins`, ...) and the stores (`settings_store`, `pay_store`, `company_store`, ...) | Same-layer imports allowed; `db` is the shared store. `intelligence` sits just above L3 and composes the model backends. |
| L3 implementations | `connectors`, `comp_providers`, `prices`, `cloud_llm`, `local_llm` | Never import each other. Their contracts and registries live inside them. |
| L1 vocabulary | `schema.py`, `config.py`, `taxonomy`, `levels`, `blueprint.py`, `company_catalog.py`, `source_policy.py`, `source_review.py`, `provider_pacing.py`, `pay_*`, `plugin_manifest.py` | Domain types and settings. |
| L0 primitives | `platform`, `vendored.py` | HTTP, rate limits, paging, locks, clocks, paths. Imports no other tracker module. Robots evaluation is `roleband_robots`, its own distribution, because the plugin SDK's fake host answers with the same code and the API may not load the SDK. |

Import-linter contracts in `backend/pyproject.toml` enforce this:

1. **Layers**, strictly downward. `ignore_imports` holds one permanent entry
   (`tracker.blueprint -> tracker.connectors`: the artifact checks reach upward at
   test time) and only shrinks.
2. **Concrete adapters are private**: everything outside `connectors` reaches a
   listing adapter through `ADAPTER_REGISTRY` and `ConnectorBundle`
   (`backend/tracker/connectors/__init__.py`), never by importing its module.
   The contract binds every package above the L3 row (the rows below are held
   by the layers); `backend/tests/test_import_contract_registry.py` derives
   both sides, the registry's adapters and those packages, so neither drifts.
3. **Listing and detail connectors are independent.**
4. **API and MCP are independent transports.**

`backend/tests/test_import_contracts.py` fails a top-level module no layer row
in `pyproject.toml` names, freezes the allowlist, and plants a violation against each contract to
prove it still fires. If a contract trips, move the code or edit the layer row,
never the allowlist. mypy checks the module set under `[tool.mypy]`, which only
grows (`backend/tests/test_typing_pilot.py`).

## Data model and persistence

The models in `backend/tracker/db/models.py` are the schema source of truth;
`backend/alembic/versions/` holds a frozen schema baseline and subsequent
migrations.

- **Current state.** `jobs` holds one row per posting, upserted in place:
  `status`, `in_scope`, enrichment, description sections, embedding.
- **History.** `job_observations` is append-only: every run that sees a posting
  adds a row, nothing updates or deletes one. `job_lifecycle_events` records
  opened, closed, reopened and changed. Data safety rules are in
  [AGENTS.md](../AGENTS.md#data-safety).
- **Arrival.** `jobs.arrival` (`backend/tracker/db/arrival.py`) says whether a
  role's first sighting dates its posting. It is set once, when a writer creates
  the role (`persist_rows`, `admit_from_inventory`). The first sighting is the
  earlier of the role's creation and the inventory's `first_seen_at`, and
  `first_seen` holds it; the creation time stays in the role's `opened` or
  `added` event. The company is known at that sighting when a complete or empty
  read finished before it inside the retention window (no window when retention
  is Never), or, for a company never read in full, after two partial reads that
  kept rows. The role is `first_read` when the company was not known,
  `already_listed` when it was admitted from the inventory or the inventory saw
  it first, and `new` otherwise. The classification reads `first_seen` as the
  creation, so it runs once per role: on rows a writer just created, or on rows
  still NULL. A NULL arrival counts as a sighting until it is filled.
  `backend/tracker/workflows/arrival_backfill.py` fills NULL rows while the app
  prepares the database, in batches that commit, then rebuilds the lineage
  projection; a source install drains its launchers and runs
  `scripts.backfill_arrival`. A downgrade drops `arrival` and keeps `first_seen`.
- **New.** A role is new when it is open, original or standalone, and listed in
  the last 2 days by the best evidence, `least(first_posted_at, first_seen)`; a
  first read counts only when the employer's own date is that recent. One rule
  holds this (`posting_reality.is_new_listing`, in SQL
  `queries.jobs.new_listing_clause`), and every reader of new goes through it:
  the header count, the New view, `JobRow.new_listing`, the Hiring tile, the
  demand pass and the digest. Arrival is stored rather than derived on read
  because the header count runs on every request, served by the partial index
  `ix_jobs_open_listed_since`. Pace and Overview count openings by `first_seen`
  in their window: a first read goes to the first-scan bucket, a repost or
  duplicate to reposted.
- **Runs.** `scrape_runs` holds a heartbeat, totals, `per_source` (each company's
  counts, errors and outcome) and `drift_alerts`, the audit surface for adapter
  failures and drift. `per_source` is written once, when the run ends; a run
  still going, stopped or orphaned reads the sources it committed from
  `scrape_source_runs`. A run whose process ended first is closed as a stopped
  one is, by the next scheduler tick that holds the run lock: its status is the
  projection of what it committed, capped at `partial`, and it claims no full
  refresh. Keep both intact when changing an adapter or the pipeline.
- **Bindings.** `source_bindings` ties a company to its source and carries
  `closure_capability`, which RoleBand's validation assigns; a source definition
  never declares its own authority to close jobs.
- **Saved keys.** A key saved in Settings is stored as `sealed:v1:<Fernet token>`
  (`tracker/platform/secrets.py`). The Fernet key is `~/.roleband/secret.key`,
  mode 0600, created on the first save and never inside `data/`, so no dump or
  backup holds it. Only the stores read those rows (`profiles/prices.py`,
  `intelligence_runtime/cloud_profiles.py`, `intelligence_runtime/local_profiles.py`):
  each seals on save and opens on read. A value without the prefix reads as
  itself, and `scripts.seal_secrets --apply` seals it in place. A sealed value
  this machine cannot open reads as no key, so the user is asked again; it is
  never sent to a provider as ciphertext.

### Embedded database settings

- Every start of the embedded cluster outside Windows passes one of three memory
  presets on the server's command line
  (`backend/tracker/platform/database_presets.py`), picked from installed memory:
  Small below 16 GB or when memory cannot be read, Standard from 16 GB, Large
  from 32 GB. The 16 GB line is the embedding model's
  (`backend/tracker/platform/memory.py`), so a small computer gets the small
  model and the Small preset together.
- The preset is picked again at every start and never saved, so a change takes
  effect when the cluster next starts; an app update restarts it. The person
  never chooses it; `ROLEBAND_DB_PRESET` names one for support.
  `SHOW roleband.preset` and `SHOW roleband.memory_bytes` report the running
  server's preset and the memory that picked it.
- Nothing is written into the cluster's files, so a restored backup never
  carries one computer's settings to another. A start without a preset runs
  Postgres's defaults. A process that attaches to a running server leaves its
  settings alone. An outside server (`ROLEBAND_DATABASE_URL`) keeps its own
  settings. Windows starts through the wheel's own start with stock settings.
- `posting_inventory` keeps 15% of each page free (`fillfactor` 85), so marking a
  role seen again updates the row in place and leaves its indexes alone. The
  free space arrives as scans rewrite pages, at that much more disk, never
  through a locking `VACUUM FULL`.

### Changing a company's source

`db/reconciliation.py` owns reviewed source changes and their append-only
`binding_reconciliation_decisions` audit. A shadow read is a full, robots-allowed
listing through the recipe engine that writes no jobs, observations, inventory or
lifecycle events; the audit keeps its whole output and the open canonical
postings. Closed postings with exact identity evidence are candidates too, so a
returning posting reopens its record. Only a mutually unique exact provider ID or
canonical URL links automatically; URLs compare scheme, path and query exactly
and ignore only host case and fragments. Conflicting ID and URL evidence stays
unresolved, title and location are only review evidence, and links are one to
one. Retiring an old identity keeps its posting and observations and removes it
from the new binding's closure scope; it claims nothing about the employer, and
changing its availability is a separate decision. A running collection blocks
saving or activating a change. A changed canonical listing or binding, a
conflicting canonical key, an unvalidated revision or a shadow older than 24
hours blocks activation; cancelling allows a fresh shadow. Activation and
rollback hold the pipeline's database lock. Job IDs and keys never change;
persistence and scope promotion resolve the reviewed aliases. Rollback restores
the prior company configuration and keeps every audit record, alias and
observation. No switch, retirement or rollback closes a job, and a new binding's
first complete reconcile validates it only after that run's closure is decided.

`POST /api/companies/{company}/recipe-rebind` takes a `recipe` slug and shadows
its activated revision. The response and
`GET /api/companies/{company}/recipe-rebind/{binding_id}` include the complete
comparison, decisions and unresolved IDs and keys. The existing adapter keeps
collecting until activation.

Under that binding URL, `POST /decisions` takes `decision` (`map`, `new`, or
`retire`), the applicable `job_id` and/or `source_key`, and a `reason`.
`POST /activate` requires every posting resolved and the pinned revision
validated. `POST /rollback`, with a `reason`, cancels a pending proposal or
restores its prior binding. Both directions withhold closure authority for
the first run. These operations are available through the API; recipe binding
without a comparison still refuses an adapter-collected company.

### Table ownership

**Table ownership.** Every table is claimed once in
`backend/tracker/db/ownership.py` as `TableOwnership(claim, lifecycle, writers,
readers)`. Claims: `core` (the run, bootstrapping, notifications),
`post_pass:<name>`, `user`, `manual:<route>`, `seed`, `infra`, `planned:<note>`.
`lifecycle` says how rows age (`append_only`, `canonical`, `derived`, `authored`,
`reference`, `operational`, `unpopulated`); `writers` is exhaustive.
`backend/tests/test_table_ownership.py` fails an unclaimed table;
`backend/tests/test_table_writers.py` fails an undeclared writer or an update to
an `append_only` table. A new derived table is a `post_pass:` claim plus a
`POST_PASSES` entry in the same change. An API handler writes through a store its
router calls; the router/table pairs that still write directly are frozen in
`ROUTER_WRITERS` (`backend/tests/test_table_writers.py`), which only shrinks.

**Migrations.** A model change ships its migration. After `alembic upgrade head`,
`alembic check` must report no new operations. The schema metadata file that
moves with it is listed under [frozen artifacts](testing.md#frozen-artifacts).

The baseline is `c5e1a9d3f7b2`, a revision with no parent. It declares its own
tables, indexes, constraints and extensions. It never imports the application
models, because what it creates would then change with them, and it seeds no
user preferences. A fresh database creates its schema directly; a database
already at that revision needs no stamping or data rewrite. New revisions
descend from it. The baseline cannot be downgraded: recovery restores a backup
(see **Restore** below). A database at an earlier revision is not supported by
this tree: restore a backup taken at or after the baseline, or start a fresh
database. An unknown revision is an error. Never stamp an older schema to pass
for the baseline. `backend/tests/test_upgrade_rehearsal.py` holds this boundary.

**Restore.** `deploy/restore_db.sh` never writes into the live database. Every
mode restores the dump in one transaction into a new, empty database, so
`pg_restore` runs without `--clean`, and verifies a schema revision, postings and
observations there. `--check` and `--into` stop at that copy. A restore that
names no target then swaps: it closes the live database to connections, renames
it `<live>_before_<timestamp>` and gives the verified copy the live name, and it
puts the first rename back if the second fails. The displaced database stays
until you drop it, because a wrong dump is recoverable only while it exists. A
dump older than the live schema applies, and a passed drill means the dump will
apply: `backend/tests/test_restore_drill.py` holds both paths to the same
statements up to the swap. The script's header, printed by `-h`, is the
operator's guide.

## The collection pipeline

### Connectors

- **Listing adapters** (`backend/tracker/connectors/listing/`) read one source
  family (Greenhouse, Ashby, Lever, Workday, Eightfold, SmartRecruiters, ...) or one
  company's own site and yield `RawJob`s (`backend/tracker/schema.py`). Shared
  mechanics (paging, location queries, tenant maps, `close_listing`,
  `BoardProbe`) are in `backend/tracker/connectors/listing/base.py`.
- **Detail parsers** (`backend/tracker/connectors/detail/`) turn a source payload
  into ordered description sections, plus pay the source states in structure.
- **Recipes** (`backend/tracker/connectors/recipes/`) are declarative listing
  definitions compiled to an immutable plan and run deterministically. HTML is
  parsed with selectolax's Lexbor engine. Recipe validation records its engine
  and extractor fingerprint; a different fingerprint withholds closure until
  the pinned revision is validated again.
- Connectors import the SDK (`backend/tracker/connectors/sdk/`);
  `connectors/runtime/` (transports, fetch tiers) is private; retry and the
  breaker's accounting live in `platform/http.py`.

Each listing adapter ships fixtures in `backend/tests/fixtures/listings/greenhouse/` and its siblings (one directory per adapter);
`backend/tests/contracts/` runs every registered adapter over them and fails by
name when they are missing. Scrub new captures with
`python -m scripts.scrub_fixtures`. Tests never fetch a live source; use
`python -m scripts.smoke_adapters <company> 5` for live confidence.

Per-provider pacing (minimum delay, boards in flight, shared or per-tenant host)
is one table, `backend/tracker/provider_pacing.py`, read by adapters and
scheduler alike.

### One run

The docstring of `backend/tracker/workflows/pipeline.py` is the transaction map;
change a commit boundary there first. In short: take the advisory lock and commit
the `running` marker; commit built-ins, bindings and profiles; `collection.py`
fetches with no session while one writer (`run_persistence.py`) commits rows as
they arrive and each company as its scan ends (scope flags, closure, catalog,
per-source record); `post_passes.py` runs each pass with its own commit; the
terminal status is recorded, or the failure after a rollback. A failing company
is recorded in `per_source` and never stops the others.

### Outcomes

`backend/tracker/connectors/recipes/outcome.py` is the only outcome vocabulary:

| `SourceOutcome` | Meaning |
|---|---|
| `ok` | No errors, listing complete. |
| `capped` | An operator item cap (`--max-list`) is set, fired or not. |
| `bounded` | Our time ceiling cut a source still producing. |
| `truncated` | Our page ceiling cut a listing still serving. |
| `suspended` | The computer slept or lost its network mid-scan. |
| `lossy` | Under 1% of records unreadable; the rest served. |
| `empty` | The board answered in full and lists nothing. |
| `degraded` | Usable data, but errors, an incomplete listing or a stall. |
| `failed` | Nothing usable. |
| `blocked` | The source refuses us outright. |

`scrape_runs.status` is its projection (`run_status_for`): `ok` when every source
is `ok`, `capped` or `empty`; `error` when none produced usable data; else
`partial`, still a successful refresh. Never add a second taxonomy or test
`status == "error"` when you mean "less than clean".

### Completeness and closure

- **Two gates.** Run quality (an uncapped, complete, reconciling scan) decides
  whether a listing is evidence; the binding's closure scope decides which
  postings it speaks for.
- **Two misses.** A posting closes on its second complete miss, at least
  `closure_second_miss_min_hours` (20 h) after the first. Any sighting resets
  it, and a `degraded`, `failed` or `blocked` scan of the company resets every
  count (`RESETS_ABSENCE`).
- **Our bounds are never evidence.** `capped`, `bounded`, `truncated` and
  `suspended` neither count nor reset a miss and never grant authority. Discovery
  scans (`ScanMode.DISCOVERY`) never close.
- **Incomplete is not broken.** A lost page is `invalidate_listing`; a lost row is
  `drop_record` (under 1%, `lossy`); a row that names its id but cannot be built is
  `observe_present`, which keeps it open. All three suppress closure as needed and
  live on the drift sink (`backend/tracker/platform/drift.py`).
- **Counted listings end on `close_listing`.** `listing_complete` defaults to
  true, so silence keeps authority. Fewer unique ids than the declared total is
  never complete, and a `declares_total` board that stops declaring one has
  changed shape. A board that serves an empty page before its count shrank while
  it was read: the adapter stops there and leaves the shortfall to
  `close_listing`, so a few rows on a large board read `lossy`, never `degraded`. A total at the search window is the window: refine with
  `platform.paging.expand_saturated`, only on facets verified to fail closed.
- **Scope is not closure.** Leaving scope flips `jobs.in_scope`; it never closes,
  reopens or reposts a posting.

### Time bounds and tuning

Each source gets a `SourceClock` (`backend/tracker/platform/clock.py`).
`scraper_source_stall_seconds` slides on progress, and silence counts against the
source; `scraper_source_budget_seconds` is a fixed ceiling, and hitting it means
we stopped a working source (`bounded`). Pass the clock into the transports and
ask `bound_fired()`; never use `asyncio.wait_for`, which discards the pages read.
A run has no time limit: it lasts until every company is read or has a reason it
was not, however slow the network (`backend/tracker/workflows/collection.py`).
The schedule decides when scans start, never how much they read. A source that
ignores its clock hits a backstop, and one that then will not close is left behind
so its lane goes on. Never-read companies go first, in the plan's roster
(`scheduler.planned_roster`) and inside each lane (`collector_lanes`). A full read
something stopped is continued, not started over: while the newest full read began
within `daily_full_after`, a tick reads the companies with no full read since it
began (`schedule_plan.continuation_start`, `read_since`) as a `continue` plan run.
A run whose process ended is closed as `interrupted` and continued at the next
tick. A `continue` run that finished or failed is tried again only after
`FAILED_RETRY`, so a network that stays down is asked every half hour, not on every
tick. A site's failure is its answer and is not retried there; only a company its
lane never started is still unread. A company asked for by name during a run is
queued, taken by the run's writer between companies or on a short timer, and read
at the front of its lane or in a lane of its own at the next free slot
(`run_pipeline(join_requests=True)`); asking for every company during a run queues
nothing. A scan is stuck only when it finishes no company for a company's budget
plus 15 minutes while it still reads: the health job then asks the supervisor to
stop it (`watchdog.stop_stuck_scan`), and the plan never treats a run as abandoned
for its age. `schedule_plan_runs.kind` admits `continue` and its `outcome` admits
`interrupted`; a downgrade refuses while continuation rows exist. The "Scan ran out
of time" notice keeps its copy only to show notifications already stored; no run
produces it.
The background directory pass shares the scan's pacers, so it never reads while
a scan is live.
Progress is completed work (out-of-scope rows included), reported after any
deliberate wait such as an honoured `Retry-After`.

Page ceilings and time budgets are learned per binding in
`source_binding_tuning`: the rule is pure (`backend/tracker/workflows/tuning.py`),
the only writer a post-pass (`backend/tracker/workflows/tuning_pass.py`). A bound
that fired is multiplied; only a natural stop lowers one, slowly, never below p95,
always inside operator limits.

### Post-passes

`POST_PASSES` (`backend/tracker/workflows/post_passes.py`) is the one producer of
derived data: backfills, content fingerprint, search vectors, skills, embeddings,
disclosed pay, posting pages, place sets, lineage, twins, clusters, similarity,
demand, pay metrics, prices, tuning. Order matters (the fingerprint gates
embeddings and pay extraction). Each entry says whether it runs on capped or
discovery scans and whether its failure is fatal. A long run also runs the
discovery passes between companies, every `scan_refresh_minutes`, over the rows
written since the last refresh (`run_refresh_passes`). The whole-corpus passes
wait for the end of the run, where every pass runs over all the run's rows. One entry, `prices`, is
`scheduled`: a pipeline run skips it, and the supervisor's `prices` job runs it
through `run_scheduled_pass`, which records it as a pipeline run would. It is
still the one writer of `company_price` and `company_price_history`. Every
request to the price feed is reserved in `price_feed_requests` before it is sent,
and the hour, the New York day and the month's symbols are counted from those
rows (limits are settings, the free plan's by default).

Groupings stack postings, never merge them: lineage, duplicates, twins and place
sets leave every posting and its history in place, and the detector never
overwrites a human review decision.

## Source policy

How sources are reviewed, walled, consented to and fetched, and the one place a
request is refused, is in [sources.md](sources.md). Copied upstream code is
covered in [third-party.md](third-party.md).

## Companies

**Built-ins** are one `BLUEPRINT` entry each in `backend/tracker/blueprint.py`
(slug, name, adapter, public, ticker, colour, curated). `config.COMPANIES` derives
from it, and `ensure_builtins()` re-seeds `tracked_company` on every API start,
run and tick, so remove a built-in in code before touching data. Every
per-company artifact registers an `ARTIFACT_CHECKS` entry;
`backend/tests/test_company_blueprint.py` runs each for every company and names
what a new one lacks.

**Discovery, catalog and directory.** `backend/tracker/company_discovery.py`
(`COMPANY_DISCOVERY`) is the product's recommendation, a short list per sector;
`backend/tracker/company_catalog.py` (`CATALOG`) holds the boards that can be
enabled at once, each with its adapter and token; `backend/tracker/company_directory.json`,
read through `company_directory.py`, is the larger set of live boards nobody
recommends, searched by name.
`tracked_company` is the single record of what the user follows.

**Board tokens are guesses** until `python -m scripts.check_catalog_tokens`
confirms them live and naming the right company. A dead token is loud (404, and
the user is offered the new careers page); a wrong one is quiet, because another
company's live board passes every check. Multi-tenant adapters declare a
`BoardProbe`; multi-region boards store `tracked_company.board_region`. An empty
board is not dead. A pasted careers URL is fetched through
`backend/tracker/platform/safe_fetch.py`, which refuses non-public addresses.

**Profiles** hang off the slug: `company_profile`, `company_comp_level` (per-level
pay a plugin publishes), `company_benefit`, and `company_fact`, append-only
claims. Fields resolve by trust then recency (`backend/tracker/profiles/sources.py`):
a manual entry always wins, a plugin ranks at most 50. RoleBand's own benefits
come from `backend/tracker/profiles/benefits_dataset/`: `observations.jsonl` is
the dataset (one evidence record per line, never built; a benefit with no record
is unknown) and `taxonomy.json` names the types. Both datasets are pinned copies
of `roleband/roleband-data`, named in `backend/tracker/datasets.lock.json`
([development.md](development.md#7-change-a-dataset)); `scripts.check_datasets`
holds every file to the app's rules.

## Enrichment

`backend/tracker/enrich/` turns a `RawJob` into an `EnrichedJob` before
descriptions are fetched, so only kept postings cost a detail request.

- **Levels come from our dataset**, the level atlas
  (`backend/tracker/levels/atlas/`, see its README), never an outside pay source's
  pairing. A plugin rung the atlas cannot place is banded from its words
  (`band_source = "words"`). Fix a wrong rung in the atlas, not in
  `company_comp_level`. Tickers come from the atlas's `company_identity.csv`; a
  price feed answers prices, never identity.
- **Roles.** The taxonomy is `backend/tracker/taxonomy/roles.py`; which roles are
  tracked lives in the settings store. No dashboard-only role filters.
- **Locations fail closed.** A stated place must classify into a location group,
  or the posting is shown to nobody (`backend/tests/contracts/test_place_classification.py`,
  `python -m scripts.check_location_coverage`). Fixtures carry the shape the
  board really sends.
- **Pay** is in [pay.md](pay.md); who may write a posting's level, description,
  places or pay is in [field-authority.md](field-authority.md).

## Intelligence

Semantic features run locally: a bundled ONNX embedding model (768 dimensions,
CPU), downloaded once from a pinned revision and checked against our sha256 per
file (`backend/tracker/semantic/manifest.py`). Vectors live in pgvector;
embeddings, clusters and similarity are post-passes.

**No automatic pass calls a model.** Pay extraction is a deterministic scanner
(`backend/tracker/intelligence_runtime/disclosed_comp.py`); the relevance
advisory compares embeddings in-process. Model backends are optional: local
OpenAI-compatible profiles (`backend/tracker/local_llm/`, loopback only) and
cloud profiles (`backend/tracker/cloud_llm/`), unreachable unless the user turns
on AI egress (`ai_egress_enabled`, off by default). The one model task the
product runs is duplicate review, on a pair the user picks, by their local model
(`backend/tracker/intelligence/duplicate_review.py`). The one line that can add a
cloud tier is in `backend/tracker/intelligence_runtime/routing.py`, a ladder only
the model bench drives; search query parsing (`backend/tracker/search/llm.py`) is
the only other path to a cloud model, and it takes the same switch.

Offline level experiments use `analytics/level_context.py` to extract quoted
facts without writing canonical fields. Component ownership refers to the
technical or physical product itself; customer activation, adoption and usage
are separate duties. Organizational impact requires direct responsibility for
an organization-wide strategy, standard, initiative or other named outcome;
collaboration and meetings across the organization do not establish it. These
facts describe stated work, not a level or a probability. Missing evidence stays
missing, and qualification clauses retain their own modality and negation.
Explicit multi-level availability with matching in-content route headings keeps
each alternative in `experience_routes`, with exact availability, heading and
years-field spans. Route identity uses source positions, including when hard
masking removes the heading's seniority words. A missing or unsupported years
field stays null. Route-specific years and duties never become posting-wide
features. The standalone label/value reader shares the numeric years grammar
and does not change runtime qualification extraction or infer a universal minimum.

Offline manual level review uses `analytics/level_review.py`. Reviewer packets
contain only an opaque assignment code and captured company, title and description;
candidate output, incumbent classifications, sampling strata and group identities
stay outside them. The private assignment key binds source fingerprints and gives
independent reviewers different codes for repeated cases. The protocol requires
600 group-disjoint cases in 250 high-confidence, 250 representative and 100 edge
strata, with Apple capped at 40% of each; 150 receive a second blind review.
High-confidence selections must belong to a supplied frozen candidate pool.
Quote validation checks exact offsets in the text shown to reviewers. Permissible
band sets and not-identifiable judgments remain distinct; agreement treats label
sets as categories and leaves kappa undefined for a single observed category.
Collection never adjudicates automatically. Explicit human adjudications produce
a scope benchmark, not proof of an employer's undisclosed internal level.

`analytics/level_study_sources.py` separately admits reviewed employer-source
targets. Source decisions bind captured facts and eligibility inputs, without
using stored level verdicts. An approved target requires source-grade evidence,
a reviewed role, a mapping grounded in a fingerprinted document and an explicitly
reviewed group with unchanged members and source fingerprints. A structured
grade matches the employer's configured field and normalized captured value;
this does not reconstruct the original board payload. Description grades retain
every quoted rung. Company vocabulary requires an independent vocabulary review;
generic title, salary and model-derived mapping bases are rejected. Mappings are
limited to their reviewed families and tracks. Management, commercial and explicit
leadership roles remain outside the initial study slice, including a director
classified into a product track. All reviewed grade alternatives map to a full
permissible band set. Multiple native rungs can support one coarse band, but
cross-band alternatives cannot become a single-band target. Exclusion versus
set preservation is an explicit study policy. Pending or incomplete reviews
produce no targets; admission alone does not pass grouping or promotion gates.

## API contract

**Routers** live in `backend/tracker/api/routers/`; `app.py` only composes them
(`backend/tests/test_api_composition.py`). A router is transport and wire shape;
a read several surfaces share lives in its domain module (job visibility, filters
and sort in `backend/tracker/db/queries/jobs.py`, Best match in
`backend/tracker/search/best_match.py`). A serializer lives in the router that
sends it, or in `backend/tracker/api/serializers/` when more than one router sends
that shape; MCP never imports one.

**Transactions.** Each request gets one session. A route that waits on the
outside (a careers site, a model server, a cloud provider) reads what it needs,
ends the read with `end_read` (`backend/tracker/api/deps.py`), and writes after
the answer, so no pooled connection sits in a transaction while the outside
answers (`backend/tests/test_api_outbound_transactions.py`).

**Response models.** Every JSON route declares a Pydantic `response_model`
(`backend/tracker/api/schemas/`), except the `NON_JSON_ROUTES` named in
`backend/tests/test_api_route_table.py`. Shapes the code builds (`Built`,
`backend/tracker/api/schemas/base.py`) forbid unknown keys; a shape read back
from JSONB (`Stored`) keeps the keys it does not name.

**Generated types.** `python -m scripts.export_openapi` writes
`dashboard/openapi.json`; `npm run gen:api` writes `dashboard/src/api.gen.ts`.
Commit both; CI diffs them (`.github/workflows/contract-drift.yml`). Never edit
the generated file or hand-write a response type.

**Errors and text.** API errors are codes, and every API string field declares
its text class: both are in [copy.md](copy.md).

**Trust boundary.** The API authenticates nobody; the loopback is its access
control. `LoopbackBoundary` (`backend/tracker/api/boundary.py`, outermost)
refuses a Host that does not name this machine and an unsafe request from a
foreign origin or with a form-style body. No GET commits.
`backend/tests/test_api_trust_boundary.py` walks every unsafe route.
The dashboard shell is served under a Content-Security-Policy
(`dashboard/csp-policy.json`, rendered by `backend/tracker/api/csp.py` with the
configured usage-statistics host): scripts from this origin only, and
connections to this origin and that host alone. `vite preview` serves the same
file, and `dashboard/tests/ux/csp.spec.ts` walks every route of the build for a
refusal.

**Profile background and sign-in.** There are no profile background, activity or
LinkedIn routes, and no LinkedIn app, grant or sign-in state is stored. Such a
feature arrives only with a screen that uses it, its secrets encrypted as
[SECURITY.md](../SECURITY.md#the-security-model) describes.

## Dashboard

**Layers.** Imports run downward only:

| Tier | Where | Holds |
|---|---|---|
| F0 tokens | `dashboard/src/design/tokens.css` | Every design value, as `--app-*` custom properties |
| F1 primitives | `dashboard/src/ui/` | Controls, overlays, badges, loading and empty states, icons; import from `src/ui` |
| F2 services | `api/`, `context/`, `hooks/`, `routing/`, `format.ts` | No presentation |
| F3 patterns | `dashboard/src/patterns/` | Shared compositions: `Cover`, `FilterSurface`, `RailShell`, `PageHeader`, `ResultsSummary`, `Pager`, job rows in `patterns/jobs/` |
| F4 features | `features/`, one directory per domain | One screen each, with co-located CSS |
| F5 routes | `dashboard/src/routes/` | Route components |
| F6 shell | `dashboard/src/shell/`, `App.tsx`, `main.tsx` | Nav rail, top bar, command palette, sync button, shortcuts sheet |

A feature never imports a sibling feature; nothing below F6 imports `shell/`; the
shell never imports `routes/` or `dashboard/src/routeRegistry.tsx`. The zones are
eslint errors (`dashboard/eslint.config.js`, `npm run lint`) whose exception list
stays empty (`dashboard/src/test/layer-edges.test.ts`). Import cycles are errors
with no allowlist; `dashboard/src/test/import-cycles.test.ts` keeps a planted
cycle failing so the rule cannot go quiet.

**Routing.** Metadata is `dashboard/src/navigation.ts`; screens are
`preloadable()` loaders in `dashboard/src/routeRegistry.tsx`, fetched one after
another once the first screen has drawn. A new screen is a `NAV_TABS` row plus a
`preloadable()` entry, never a static import in the shell
(`dashboard/src/route-registry.test.ts`). URL state goes through
`dashboard/src/routing/`: path is the view, query is the lens.

**Typed client.** `dashboard/src/api/` is split by domain; `transport.ts` is the
one request boundary, `index.ts` composes `api`. Every response type aliases
`dashboard/src/api.gen.ts` (`dashboard/src/test/api-contract.types.ts` fails the
type check otherwise), and so does each query a screen sends: the same file
holds every hand-written params type to its route's generated query. The shell imports only `dashboard/src/api/shell.ts`, so the
startup chunk stays small.

**Shared state** is three providers under `AppProviders`
(`dashboard/src/context/`): `JobWorkspace` (compare, viewed, saving),
`MissionState` (stats, board query, lenses), `SyncState` (run status, polling,
trigger, cancel). Nine hooks split them by cadence and by value versus action;
subscribe to the narrowest, because a context re-renders every reader when its
value changes. SyncState reads MissionState, so order matters. The shell's
routed screen is memoized on its location (`dashboard/src/App.tsx`), so what
only the chrome reads, like the header counts, never re-renders the open screen.
`dashboard/src/context/isolation.test.tsx` pins this as render counts. The
board's lenses are page state, not query: `/?lens=new` is an entry from outside
the page (the Mac panel), which `MissionState` reads once, turns into the New
lens and drops from the address (`dashboard/src/context/missionLensEntry.test.tsx`). Async
reads use `hooks/useAsyncResource`; several writers to one subject order through
`hooks/useWriteQueue`. A read-mostly read passes `keep`, so a screen opened again
paints its last answer and refreshes it in place; every write through
`transport.ts` forgets all kept answers (`dashboard/src/api/keptAnswers.ts`). A
read whose rows must not move under the reader, like the Board's list, keeps
nothing.

**Look and wording.** The visual system is in [ui.md](ui.md). Every user-facing
string is a catalog message, never a literal: see [copy.md](copy.md).

## What can leave the computer

Everything that can leave the machine, and when, is listed in
[SECURITY.md](../SECURITY.md).

### Usage sharing

What can be sent, and how a user turns it on or off, is in
[usage-data.md](usage-data.md), held equal to the code in both directions by
`backend/tests/test_usage_docs.py`. The engineering is in
`backend/tracker/usage_stats/`:

- `registry.py` declares every backend event and each property's type (enums,
  flags, bounded numbers, short patterned strings, never free text).
- `consent.py` stores per group the answer, the exact text and language shown,
  and a fingerprint of the kinds of data covered. Widening a group re-asks its
  sharers; narrowing never does. Consent edits and the sender's final consent
  read, rollup and claim share a transaction lock; every write to the outbox
  reads consent under it in shared mode, so an edit waits for rows not yet
  committed and withdraws them with the rest. A committed claim is the
  boundary after which a batch is already in flight; the network call holds
  no database transaction.
- `kill.py` reads `ROLEBAND_NO_USAGE_STATS`, `DO_NOT_TRACK` and `CI` live; the
  environment can only turn sharing off.
- `recorder.py` is the one door into the `usage_events` outbox (switches,
  consent, catalogue first); `backend/tracker/api/usage_counter.py` counts API
  actions.
- `flush.py` sends at most once a day from the supervisor's `usage_send` job
  (every 6 h; the send decides whether one is due), never in a maintenance wake, with no transaction open; `batch.py` re-checks every row
  against the catalogue; `scrub.py` reduces crashes to exception types and
  RoleBand frames, with company-named modules anonymised.
- `dashboard/src/diagnostics/sharing.ts` loads the browser library only after
  the user shares, loads no remote code, never records sessions and rewrites
  URLs to screens.

## Plugins

A plugin adds an outside source (per-level pay, company facts, benefits) without
the core importing it. It depends only on the plugin SDK, runs as a separate
process talking to the host over stdio, fetches only its manifest's hosts, paced
no faster than the core, and publishes validated rows into fixed slots. The core
reads only what the host stored, filtered by `backend/tracker/plugins/registry.py`;
turning a plugin off brings RoleBand's own answers back.
`backend/tests/test_plugin_registry.py` imports the API and pipeline without the
SDK to prove it, and `backend/tests/test_release_gate.py` fails on an outside
data source's name anywhere in the tree. Writing one: [plugins.md](plugins.md).
