# Plugins

> **Preview.** Plugins are a preview in the first release: the manifest, the SDK
> and the host protocol may change between releases. The first release ships no
> plugins; this page is for authors who want to build one.
>
> Settings > Plugins shows **Coming soon** in place of the plugin list unless
> `ROLEBAND_PLUGINS=true` is set (in `backend/.env`); `GET /api/plugins` then
> lists none and `GET /api/plugins/<id>` answers 404. More plugins and the
> install command show either way, and `scripts.plugin` works either way.

A plugin adds an outside data source to RoleBand without the core importing it.
RoleBand ships with its own dataset (the level atlas, the benefits dataset); a
plugin the user turns on answers what it covers, and turning it off brings
RoleBand's own answers back with nothing lost.

Every user decision (approve, enable, disable, pause, schedule, uninstall, remove
data, install) goes through `tracker/plugins/lifecycle.py`, shared by Settings >
Plugins and `scripts.plugin`.

Start from `examples/plugin-template/`. The SDK is `sdk/python/roleband_plugin_sdk`,
and it depends on `robots/python/roleband_robots`: the host and `FakeHost`
evaluate a robots file with the same code, so a path your tests fetch is a path
the live host will fetch. Neither is on an index yet, so both install from a
checkout (SDK version in `version.py`); a plugin depends on them and on
nothing that reaches the network.

## 1. Shape

| Piece | What |
|---|---|
| `roleband-plugin.toml` | The manifest: the plugin's whole permission set. The user approves this file; any change to it or to the code needs approval again. |
| A Python package | Depends only on `roleband-plugin-sdk`. Exposes a `Plugin` whose jobs receive a `JobContext`. Imports nothing from `tracker`. |
| `tests/` | Parsers on recorded documents; each job under the SDK's `FakeHost`; the no-network check. No test fetches live. |

The core never imports plugin code. A run is a separate process (`tracker.plugins.cli run`;
`scripts.plugin run` by hand) talking to the host over stdio; the API, scheduler and
pipeline read only what the host stored, filtered by the registry
(`tracker/plugins/registry.py`).

## 2. Manifest

| Key | Rule |
|---|---|
| `[plugin] id` | `[a-z0-9-]`, at most 32: the provider value on every row it writes. Stable forever. Core ids are refused (`plugin_manifest.RESERVED_IDS`). |
| `name`, `attribution`, `licence`, `repository` | Third-party text, shown as written. `attribution` is credited wherever the plugin's data answers. |
| `description` | Optional, at most 200 characters: what the plugin does, in its own words. Settings shows it under the name, on the list and on the plugin's page, as written. Without it, Settings says what it brings by kind of data. |
| `sdk` | A range with an upper bound: `">=1,<2"`. A manifest key or `ctx` method added in a later 1.x release names that release in this guide, and a plugin that uses it raises the lower bound to it. The SDK refuses a range that admits a release older than a key the manifest uses (`manifest.KEY_SINCE`); a method it cannot see, so the author raises the bound by hand. |
| `entry` | `package:attribute` of the `Plugin`. |
| `[[provides]] slot` | One of the v1 slots (section 3). `company.facts` lists its `fields`, which can only be `["headcount"]` (identity is RoleBand's), and may set `rank` (the core caps it at 50). |
| `[network]` | `hosts` (plain lowercase hostnames), `min_delay_seconds`, `identity` (`identified` unless the user consents to a stronger tier). |
| `[[jobs]]` | `name`, `publishes` (declared slots only), `schedule` (`weekly`, `manual`; the user may pick daily/weekly/monthly), `budget_seconds` (at most 4 h; the job sees it as `ctx.time_left()`), `needs` (`followed_companies`). |

## 3. Slots (v1)

Every row is validated on both sides; a missing amount is `None`, never `0`.

| Slot | Row (`roleband_plugin_sdk.slots`) | Core table | Core adds |
|---|---|---|---|
| `pay.levels` | `PayLevel`: taxonomy `family`, `vendor_family`, `label`, `aliases`, `tc`/`base`/`stock`/`bonus`, `currency`, `country`, `source_url`, `as_of`. One row per rung and country (the key is family, label, country); a rung with no `country` prices no posting | `company_comp_level` | band (atlas first, then words; `band_source`) |
| `pay.observations` | `PayObservation`: `source_level`, `function`, `family`, `location`, `yoe`, `total`/`base`/`equity`/`bonus` (each optional, at least one), `currency`, `country`, `snapshot_date`, `dedup_key`. Only a submission for the US in USD that states a total and its equity enters the US comparison; the rest are kept | `external_comp_observation` | band at read (atlas, then the label's words), `ingested_at` |
| `company.facts` | `FactClaim`: `field` (`FACT_FIELDS`), `value`, `observed_at` | `company_fact` (claims) | rank from the manifest, capped at 50 |
| `company.benefits` | `Benefit`: `name`, `category`, `value_usd`, `value_text`, `description`, `detail`, `perk_id`, `country`. One row per perk and country (the key is name, country); a perk with no `country` is shown as unscoped, never company-wide | `company_benefit` | benefit type (dataset aliases); never a summed total |

Rows that share a slot's key are one stored row (`slots.ROW_KEYS`, the
table's unique key): a rung or benefit sent again replaces the earlier one, and
an observation keeps the first. A `dedup_key` names one observation across all
the plugin's companies, not one per company. Fact claims have no key: every
claim is kept.

Publish only for companies the core knows (`ctx.companies()` with `needs`).
`complete=True` means "every row of this company in this slot this run": from
that publish the company's rows are read and the ones not repeated retire.
A snapshot larger than one publish (`slots.MAX_ROWS_PER_PUBLISH`, 5,000 rows)
goes in chunks: every chunk but the last `complete=False`, the last
`complete=True`, which closes the snapshot over all of them. A run that sends a
company only `complete=False` reads and retires nothing for it.

## 4. What the host enforces

- Every fetch is `ctx.get`, only to declared hosts, paced at no less than the core
  delay (`scraper_min_delay_seconds`, 2.0 s, whatever the manifest asks), robots
  honoured, under the job's budget. Importing `httpx`, `requests`, `socket`,
  `subprocess` (and kin) fails `python -m roleband_plugin_sdk.checks src`, and
  install refuses the plugin. The check is a review aid, not a sandbox: it reads
  import statements only, and the plugin process runs as the user with no OS
  isolation. Approval is the user's trust in the code; the check catches honest
  mistakes, never a plugin written to evade it.
- The code that runs is the code that was approved: the host re-hashes the
  installed copy (`<home>/src`), its bytecode caches included, before every
  run and puts it, with the core's
  SDK, ahead of the venv's site-packages on the runner's path. The runner is
  isolated (`python -I`) and starts in a directory no plugin can write, so
  nothing a plugin saves (its data directory included) is ever imported: open
  your files through `ctx.data_dir`, never the working directory.
  Known gap: the venv itself is writable and not hashed, so a plugin that
  rewrites its own dependencies is not caught; nor are the build outputs pip
  may leave beside the source (`build/`, `dist/`, `*.egg-info`), which run
  only if approved code imports them.
- Robots rules are matched on path AND query, from the group that names the
  agent we send, else `*`. A disallowed URL is refused (`refused`, the
  run ends `partial`; pass over it). The user may allow your plugin past its
  sites' rules: the approval quotes each declared
  site's rules, and the choice covers everything your plugin reads, for the files
  shown; a site that changes its file is skipped again until the user reviews it.
  Never rely on it: a plugin must work, with fewer pages, when the user says no.
  A site that refuses its robots file (401, 403, 5xx) is closed to the plugin
  whatever the user chooses. The approval and the run read a site's file the
  same way (`plugins.robots.read_robots`): redirects followed, up to five, each
  hop re-checked as public; a file that cannot be read now fails that request.
- One run per plugin at a time (a run lock in its data directory), whoever starts it.
- Pick an id no data uses: `mixed` and the core's sources are reserved, and a new
  plugin is refused under an id that already names rows RoleBand stored.
- An update is built beside the installed version and swapped in only once its
  venv builds; a failed build leaves the installed version running.
- Outcome is the host's: `clean`, `partial` (a refusal), `bounded` (budget spent),
  `stopped` (the user's Stop or Disable), `error` (the plugin failed, the host
  failed, or the manifest fails the core's checks; each recorded with its
  reason). `clean` and `partial` went through the job: either ends or continues
  a pass, and the refusals stay on a `partial` run. The others are retried 6 hours
  after they started.
- **One source per slot, app-wide**: once on (enabled, approved), a
  plugin answers every slot it declares for every company, replacing RoleBand's
  data there whole; a second plugin on the same slot answers only if it is first
  in the user's order. Nothing of RoleBand's fills a gap in it.
- **Company by company**: its rows for a company are read from the
  moment it publishes that company `complete` (`plugin_coverage.complete_at`),
  whatever the run's outcome, never waiting for the rest of a pass. That publish
  also retires the company's rows this run did not repeat. A company it has not
  read whole is "not covered": it shows nothing from the plugin and nothing of
  RoleBand's. Rows are retired, never deleted; only the user's Remove data
  deletes. So publish `complete=True` only when every request for the company was
  answered.
- **What the core reads of each slot**: pay levels as sent, banded by RoleBand's
  atlas when read (send `aliases` for a rung the atlas may not know; the stored
  row is never re-banded); benefits whole; `company.facts` only `headcount`
  (identity, equity vehicle and vesting are always RoleBand's, and a plugin
  cannot claim another field); pay observations banded by the atlas from
  `source_level`, a level it cannot place not read.
- `ctx.state.get/set` keeps a small JSON store between runs, committed as it is
  written: at most 10,000 keys (`protocol.MAX_STATE_KEYS`) of at most 64 KiB
  each (`protocol.MAX_STATE_BYTES`). A key past the cap is refused; rewriting
  a kept key never is.

- `ctx.report(key, value, label)` shows the
  user a number beside the plugin: Settings > Plugins > the plugin > What it brings,
  under **The plugin says**, as "{value} {label}" with **As of {date}**. `label` is
  the plugin's own words (third-party text, shown as written); the host keeps the
  latest value per key (`[a-z][a-z0-9_.-]`, at most 64) in `plugin_report`, across
  runs and updates; `value=None` withdraws it; at most 8 keys
  (`protocol.MAX_REPORTS`). It is display only: nothing reads it to decide.
- `ctx.summary(text)` says what the run has done,
  in the plugin's own words, at most 160 characters
  (`protocol.MAX_SUMMARY_CHARS`). The host keeps the latest on the run
  (`plugin_run.summary`), whatever the run's end, so call it as the run goes: a
  run the host stops keeps the last one. Settings shows it after the host's own
  words for how the run ended and when ("Stopped 2 days ago: {summary}"), on the
  list row, the plugin's Last update and each of its recent updates, in place of
  RoleBand's count of the companies the run read. How it ended stays the host's:
  a plugin cannot know it was stopped.

## 5. Long jobs resume

A refresh over many companies outlives one run. Use `ctx.resume`:

```python
@plugin.job("refresh")
def refresh(ctx):
    ctx.resume("refresh", ctx.companies(), lambda company: read(ctx, company), key=lambda c: c.slug)
```

- Units go in `key` order after the cursor the pass left in `ctx.state`
  (`resume.<name>`), saved after each unit; progress is reported for you.
- A unit whose code raises (a parse error, a refused or failed request) is logged
  and passed over, so one bad company never stops the plugin. A refusal still
  makes the run `partial`, which ends or continues the pass like a clean run:
  one failed request among thousands never turns a weekly plugin
  into one that reruns every 6 hours.
- With less than `margin` seconds of the budget left (`ctx.time_left()`; the host
  sends the budget in `start`), the job stops at a unit boundary and says `more`:
  the run ends `clean` (or `partial`, with its refusals; each company it read
  whole was read from its publish),
  and the scheduler continues the pass 30 minutes after that run ended
  (`schedule.CONTINUE_AFTER`) instead of waiting out the retry delay.
- At the last unit the cursor clears; the schedule's interval counts from the start
  of the pass, so a pass spread over many runs repeats every interval.
- A run the host ends (budget, Stop) keeps the cursor before the unit it
  interrupted.
- The progress `resume` reports is what Settings > Plugins tells the user:
  how far the pass is, and how long the rest takes at the pace your
  own runs kept (seconds per unit over the last 5 runs that moved, plus the
  30-minute wait between budget-cut runs). A job that goes through companies
  without `resume` should call `ctx.progress(done, total)` with `done` counted
  from the start of the pass, or the user is told no time.

At the core's 2.0 s floor, a source that needs about 40 requests per company
spends over a minute on each, so a pass over many followed companies spans many
runs. `FakeHost(budget_seconds=...)` splits a pass in a test;
`RunResult.more` and `RunResult.retires` say what the host would do.

## 6. Lifecycle

| Step | How | Effect |
|---|---|---|
| Install / update / remove | `cd backend && .venv/bin/python -m scripts.plugin install <plugin-folder>` (`remove <id>`; every `scripts.plugin` command runs from `backend/`) | Builds its venv: a `requirements.lock` with hashes is what gets installed (another lock format is refused; export one), else the SDK and the plugin resolve under the core constraints. pip and the build backend see none of our environment. Records commit, manifest and lock hashes and the SDK version. An update lapses approval: it stops answering at once and RoleBand's data answers again. |
| Approve | Settings > Plugins, or `scripts.plugin approve <id>` | Shows slots, hosts, schedule, needs, attribution; stores the fingerprint and the text shown. |
| Turn on / off | Settings > Plugins switch, or `scripts.plugin enable <id>` / `disable <id>` | Each ends with a re-estimate, and every slot changes source when it lands, together: on, it answers its slots (companies it has not read show "not covered"); off, every answer returns to RoleBand's data, unchanged, because both are stored side by side. Estimates read as updating from the click. |
| Start / Stop | Settings > Plugins, or `POST /api/plugins/<id>/refresh` / `pause` | Start releases a pause; Stop ends the run `stopped` and holds automatic runs. |
| Remove data | Typed confirmation, `scripts.plugin remove-data <id> --confirm <id>` | Deletes that provider's pay-level and benefit rows. Only while it is off and once the estimates stop reading it (`plugin-estimates-moving` until the re-estimate lands). Never automatic. |
| Schedule / Pause | Settings > Plugins, `scripts.plugin schedule <id> weekly` / `pause` / `resume` | Changes when it fetches, never what is read. |
| Order | `scripts.plugin order <slot> <id> <id>` | Which plugin answers first where several provide a slot; no ids = id order. |

## 7. Test

```bash
pip install -e <roleband-checkout>/robots/python
pip install <roleband-checkout>/sdk/python -e ".[test]"
python -m pytest -q
python -m roleband_plugin_sdk.checks src
```

`FakeHost(root, companies=..., responses=..., state=...)` runs a job in process (or
`subprocess=True`) against recorded responses; an unrecorded URL is a refusal.
With `subprocess=True` the runner starts as the host starts it
(`roleband_plugin_sdk.launch`): isolated, in `/`, with the SDK and your code on
its path and a data directory of its own, so a relative path fails in the test
as it would live.
It applies the real host's rules from the shared `policy`: the pacing floor (each
request costs at least 2.0 s of the budget), the default client only, taxonomy
families (`slots.TAXONOMY_FAMILIES`), the state and report caps, and robots
when a test records them (`robots={host: text}`). `rows(slot, company)` is what
the store would keep, one row per key; `published` holds every row as sent.
Pass an earlier run's `state` and `reports` to carry them into the next, as the
host does. Assert the outcome, the rows per slot and company, `complete`, the
requests made, the final `state` and `reports`, `more` and `retires`.

## 8. Never

- Name a vendor in the core: the release gate (`backend/tests/test_release_gate.py`)
  fails a tracked file that does.
- Ship a plugin inside the core repo; plugins live in their own repositories.
- Write outside declared slots, or for a company the core does not know.
