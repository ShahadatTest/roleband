# Pay

How RoleBand turns a posting plus its own dataset into base, bonus, equity and
total figures, what each figure means, and where each rule and seed lives.
Paths are under `backend/tracker/` unless written in full. Who writes each pay
column, and what clears it, is in [field-authority.md](field-authority.md). A
plugin can supply per-level pay instead of RoleBand's dataset; how a plugin
publishes rows is in [plugins.md](plugins.md).

## Three layers

| Layer | Stored in | Built by | Meaning |
|---|---|---|---|
| Stated pay | `jobs.disclosed_*` | connectors, the text pass, the posting page | The band the posting itself states. A fact about this posting. |
| Estimate | `job_comp_estimate` (one row per source), copied to `jobs.comp_*` | `enrich/comp.py` | What this company pays at this level and family. Never a fact about this posting. |
| Package | not stored; built per request | `analytics/comp_package.build_job_package`, called by `api/routers/jobs.py` | Base, bonus, equity and total for the job detail, each marked `stated` or `estimated`. |

A component is `stated` only when the posting stated it. Everything else is
`estimated`, and the package says which estimator produced it.

## Reading stated pay

All of this lives in `pay_disclosure.py`, `pay_period.py` and `pay_numbers.py`,
and only reports what the posting literally says.

- **Basis** (`base`, `total`, `unclear`): `derive_pay_basis` reads the window
  `basis_context` returns around the band: its paragraph plus a pad each
  side, capped in length. Every writer then passes the basis through
  `settle_band`: an `unclear` band becomes base or total when the posting
  defines its bands per kind of role (sales reads total), or base when its
  paragraph calls the band a salary. An explicit statement that this position's
  annual salary range is displayed below may cross the benefits paragraph to
  one labelled pay range; multiple ranges, conditional definitions and inclusive
  compensation wording leave that reference unresolved.
- **Period** (`year`, `month`, `hour`, `unclear`): size decides first, words
  second, and only words next to the amount count (`decide_period`). In US
  dollars a yearly amount sits in 10,000..5,000,000, monthly in 1,000..30,000,
  hourly in 7..1,000; other currencies are sized through
  `pay_numbers.USD_PER_UNIT`, never converted for display. A word that
  contradicts the size gives `unclear`: shown with no unit, never split, never
  counted. Every reader of a stored period goes through `effective_period`.
- **Several bands, one per place**: `extract_grounded_band` takes the band
  whose label names the posting's first city or metro (`enrich/classify.first_place`)
  when exactly one does, else the first stated. A connector knows no place, so a reader
  that scans a shared source's prose for every tenant (`detail/eightfold.one_band`)
  states a band only when the posting prints one range, and leaves a posting
  with a range per place to the text pass.
- **Bonus percentage**: `derive_bonus_pct` reads "+ 25% bonus target" and
  similar around the band, only when the basis is `base`, and drops anything
  above 60%. Writers read it in `settle_band`, after the basis is settled, so a
  band only its salary wording makes base keeps the target its paragraph
  states. A connector's own read of its pay block stands over the stored
  text's.
- **Pay section**: `connectors/detail/base.promote_section` carves the pay
  sentence into its own section and grows the cut to sentence bounds, so the
  body never holds half a statement.
- Changing how a band is read means bumping `PAY_PARSER_VERSION`; the text
  pass then re-reads the bands it wrote, a capped number per run.

**Who may write a band.** Three sources state one, and `correct_pay_periods`
corrects one; `db/pay_band.py` holds the rule all of them apply.

- **Precedence.** A band has one owner, `jobs.disclosed_source`. A writer
  replaces a band its own source owns, or one a weaker source owns. Strongest
  first: a structured field on the listing, then the posting's text, then its
  page, which is read only while the text states no pay and so fills that gap.
  The full rule is in [field-authority.md](field-authority.md#4-pay).
- **Clearing.** A writer clears only a band it owns, and only when its source
  can say there is no pay. A connector that scans the posting's text where its
  source prints pay (`pay_from_text` in `connectors/detail/`) clears its own
  band when a complete read with text finds none there. A connector that reads
  a structured salary field (Ashby, OpenAI) never clears: a posting with no pay
  field and one whose employer withdrew a band both arrive as no field at all.
- **The place key.** Every writer records the place it chose the band for, so
  a posting that moves city is owed a fresh read though its text never moved.
- **The stamp.** Every writer records when it wrote and which reader produced
  the figure, and never another reader's version. A correction moves the
  stamp and keeps the source: it corrects what that source stated.
- **History.** Each of the three sources records `disclosed_base` when it
  moves the stated figures, so the same move is visible wherever it was
  published. A correction records nothing: it fixes our reading, not the
  posting. Where a move is shown is in [field-authority.md](field-authority.md#4-pay).

## The estimate

`enrich/comp.CompResolver` asks its providers in order. The first answer is the
headline; every answer is kept in `comp_sources` for the job detail. No band
below Senior gets an estimate, because no reference data starts lower.

Each provider answers a `CompEstimate`: a total (`median`, `low`, `high`), a
base range (`base_median`, `base_low`, `base_high`), or both. A missing part is
unknown, never zero.

### RoleBand's own estimate

Built in `plugins/reestimate.SourceInputs.resolver`, in this order:

| Order | Provider | Reads | Range |
|---|---|---|---|
| 1 | `comp_providers/table.ReferenceTableProvider` | Stored per-level rows from RoleBand's own sources, keyed by company, the job's family and band; a family with no row reads `REFERENCE_FAMILY` | median ±15% |
| 2 | `comp_providers/static.StaticCompProvider` | The seed on the rung the band reads (`levels/pay.seed_range`, `seed_median_usd` in `levels/atlas/rungs.csv`) | median ±20% |
| 3 | `enrich/builtin_pay.BuiltinPayProvider` | Our dataset's per-level base | base ±15%, no total |

The built-in provider is on by default; `ROLEBAND_BUILTIN_PAY=false` turns it
off (`config.Settings.builtin_pay_enabled`). Its base comes from
`enrich/level_pay.level_bases`, one figure per company, family and band, from
one kind of evidence, never mixed:

1. **filed**: government wage filings (`levels/atlas/title_pay.csv`). The
   filed title goes through the same `classify_family` and `read_level` a
   posting does, at use time.
2. **posted**: ranges the company posts at a known rung or band
   (`pay_grades.csv`, `pay_bands.csv`, `posted_pay.csv`).
3. **estimated**: collected aggregate points (`estimated_pay.csv`), placed on a
   rung by the atlas alone (`enrich/estimated_pay.py`).

A filed or posted base wins; a collected aggregate fills the keys left. No
fallback to another family, year or parent company: a key with no evidence is
absent. The published `level_base.csv` contains company, family, band, base and
stock amounts only; the company API adds policy-based bonus and a total only
where all components are known. It carries no source labels, original-rung
references, collection dates or evidence counts.

The company baseline calls these values **Estimated**: they describe a level,
not the salary stated for a particular posting. A posted midpoint is calculated,
while its underlying range is employer-stated. Job detail keeps the distinction
between a posting's stated components and estimated ones. The vocabulary for
collected base, bonus and equity is Estimated throughout the application.

`enrich/builtin_pay.build_rows` adds a bonus row only where the company policy
answers one (a target, or 0 at a company that pays none) and no equity row,
so this provider answers a base and never a total. Its rows contain values and
matching keys without traceability metadata, and are cached on disk by a
fingerprint of `BUILD_SOURCES`.

A stored rung answers the components it states (`comp_providers/table.py`):
a total and a base, or a base alone, which is a base estimate with the total
unknown. Components are never added up into a total. Within one source the
widest answer leads (`enrich/comp.CompResolver`): a base-only answer stands
only when nothing else in that source answers the total, so a plugin that
publishes base pay alone moves the base estimate, and ours keeps the seed's
total beside a stored base.

### A plugin's estimate

While a plugin is selected for `pay.levels`, a second resolver reads that
plugin's rows and nothing else. Every job keeps both estimates in
`job_comp_estimate`; `jobs.comp_*` is a copy of the selected source's, which
every list, sort and filter reads. Neither source fills a gap in the other: a
company the plugin has not read has no plugin estimate, and the job detail
says it is not covered.

### Re-estimating

An estimate is a function of the job's stored fields and the reference set.
`plugins/reestimate.py` hashes that set (the estimate's code and atlas files in
`ESTIMATE_SOURCES`, the provider record, and the exact rows read). When the
hash moves, every job is re-estimated in batches, and the switch lands in one
transaction with one `reference_change` record instead of a per-job event. If
you make the estimate read a new file, add it to `ESTIMATE_SOURCES`
(`tests/test_reestimate.py` checks each path exists, and follows the estimate's
imports into `tracker.levels` and `tracker.comp_providers` so a module it reads
cannot be left out).

The hash never covers a job's own fields (company, band, family, place, title).
Code that moves them outside a scan calls `reestimate.refresh_jobs(ids)`: the
levels backfill, the role reclassify (pass and script) and a held row's fresh
read do. It re-estimates those jobs under the set that applies: settled, their
rows and the list's copy; mid-switch, the jobs the move has already passed (the
move reaches the rest); if the set itself moved, nothing, since the re-estimate
that follows recomputes every job. A new writer of those fields must call it too.

### Which rung a band reads

A band is coarser than a ladder (Microsoft's 65, 66 and 67 are all
`principal`). `levels/ladder.rung_for_band` picks the rung a band reads its pay
from: inside the band, the lowest rung with seed pay, else the lowest; a band
the company has no rung in reads the nearest rung below. `levels/pay.pay_label`
names that rung's lookup label. `comp_package.choose_rung_row` prefers the
stored row that names that rung, by its label or any alias against any
spelling the atlas holds for the rung (its lookup label, code or aliases), so
two sources that spell one rung differently read the same row; else the
median candidate by base, never row order.
The estimate (`pay_level_index`) and the package (`select_baselines`) both go
through it, so the median beside the package is read from the same row.

**Every figure is for one country, and prices postings in that country only.**
A posting's pay country is the one country every place it names lies in
(`taxonomy/locations.pay_country`): a posting naming places in two countries,
or none, has no pay country and shows no estimate and no measured split. Our
own data (the dataset, the seed pay and our stored rows) is US pay
(`comp_providers/base.OUR_PAY_COUNTRY`), so it answers US postings only. A
plugin's rung is for the `country` it states; one that states none prices no
posting. Readers match a row to the posting by country (`pay_level_index`,
`package_rows`, `comp_package.country_rows`); the company page and Statistics
show US rows.

Of the US rows, only those that can stand for US pay are read
(`analytics/comp_market.us_rows`), by the estimate, the package, the company
page and Statistics alike. A row that states its country is US pay exactly
when it states the US. A row that states none (ours, read for the US) is held
to the floor: a median base under $45,000 is set aside, and so is every such
row of a company and family whose priced rows are at least half under it.
Interns are exempt. Another country's rows are not held to the US floor.

## The package, component by component

`build_job_package` looks up the measured split for the job: the stored row at
company, family and band whose base, bonus and stock are all known
(`is_split`; a measured 0 is a value). The job's own family gives
`split_source = measured`; otherwise it borrows another family at the same
band in `taxonomy/comp_families.BORROW_ORDER` order (`cross_family`); with no
row it falls back to `heuristic`. A measured or borrowed split carries the row's
`provider` and `as_of` as `split_provider` and `split_as_of`, and Job detail
names them under the split ("Split from Levels, as of Oct 1").

### When the posting states a yearly base band

| Component | Estimator, first that applies | Provenance |
|---|---|---|
| Base | The stated band | `stated` |
| Bonus | 1. the posting's stated percentage × base; 2. the row's bonus/base ratio × base; 3. the company policy's target midpoint (`levels/pay.bonus_ratio_for`); 4. the `analytics/comp_split.split_tc` heuristic | `stated` for 1, else `estimated` |
| Equity | 1. the row's annualised grant (`stock_usd`) as a point, widened to 0.60..1.40 (`_EQUITY_SPREAD_LOW/HIGH`), `equity_basis = measured_grant`; 2. otherwise a share of the stated base, `equity_basis = ratio` | `estimated` |
| Total | The sum of the segments shown | `estimated` |

Bonus is a ratio of base because companies set it that way: a level-set target
percentage. Equity is a dollar grant sized by level from its own budget, so it
is never scaled off the two ends of a base band; doing that would turn a band's
geographic spread into an equity spread. The package shows annualised equity
(per year, vesting over time), not year-1 cash.

A segment that comes to zero (a company that pays no bonus, or grants no stock)
is left out rather than drawn as an empty sliver. The total is always the sum
of the segments the user sees.

### When the posting states no band

With an estimated total, the total is split by the same ratios (row, then
policy bonus, then heuristic) and every segment, including base, is
`estimated`, with `equity_basis = ratio`. With only an estimated base (the
built-in provider), the package shows one estimated base segment and no total:
bonus and equity are unknown, not zero.

### When a band is not split

`no_split_reason` says why the stated figure is shown whole:

| Reason | When |
|---|---|
| `hourly`, `monthly`, `period_unclear` | The period is not a year. RoleBand never annualises. |
| `basis_unclear` | The posting did not say what the band covers. Splitting it would assume base. |
| `total_compensation` | The band is total pay; it is the headline, `stated`. |
| `employee_election` | Netflix: total pay whose cash and stock mix the employee chooses. |
| `plugin_without_split` | A plugin answers pay and its rows give no split for this level. Our heuristic and policy are our data and never split a plugin's figure. |
| `plugin_not_covered` | A plugin answers pay and has not read this company. |
| `not_us_pay` | RoleBand answers pay and the posting's pay is not US pay: another country, or places in several. Our split is measured on US pay only. |

While a plugin answers pay, the package also omits the offer `policy` line,
which is RoleBand's data.

## A role list's Base column

The Board and Saved lists show one figure per row, of one kind: base
salary. A total is never shown there, because postings state a base and the
built-in estimate answers no total; job detail shows the package.

| The row knows | The cell shows | Its hover, also read to screen readers |
|---|---|---|
| A posted base range (`jobs.disclosed_*`, basis `base`, a period the row can write) | The low end with `+` (`$150K+`), or one figure when both ends read the same; per hour or month with its unit, in the posting's currency, never converted | The posted range |
| Otherwise an estimated base (`jobs.comp_base_median`) | That figure (`$180K`), in its currency | Our estimate for this level |
| Neither | Nothing; screen readers hear that it is not known | Why, when a plugin answers pay and has not read the company |

`api/serializers/jobs.posted_base` decides which posted range a row carries
(`pay_disclosure.ROW_PAY_PERIODS`, checked by `pay_period.effective_period`:
a stored period the amount's size rules out shows the estimate instead, and a
band with no stored period reads by its size), and the dashboard's
`payShown.baseShown` writes the cell. The `base_pay` sort and the `base_min`
and `base_max` filters read `db/queries/jobs.base_pay`, the same rule in SQL,
as yearly US dollars: a posted range per hour or month or in another currency,
and an estimate in another currency, are shown but compare with nothing, and a
shown range never falls back to the estimate the row does not show
(`test_api_jobs_sort.py` checks the two agree on every case). Money a search
query names applies as these bounds. The agent tools keep their own estimate filter and sort
(`comp_min`, `comp_median`: the total, else the estimated base).

## Checks beside the headline

Both checks say an input (the level or the family) is probably wrong, never
that the employer pays unusually. Neither rewrites `split_source`.

| Field | Question | Fires |
|---|---|---|
| `reconciliation` | Does the stated band's top match the measured base for this level? Only for a USD yearly base band against an exact-family row. | ratio above 1.50 (`stated_above_measured`) or below 0.75 (`stated_below_measured`) |
| `market_gap` | Does the package total match the estimate's median? USD only. | `abs(ratio - 1) > 0.50` (`diverges`) |

The thresholds sit outside the ordinary spread on purpose: a range that spans
locations and adjacent levels has a top well above a median, and the package
total and a median total disagree by a wide margin as normal statistics.

## Company offer policy

`levels/pay.PAY_POLICIES` loads one `levels/model.PayPolicy` per company from
`levels/atlas/company_facts.csv` (one fact per row, with who states it:
`employer` or `estimated`).

| Fact | Values |
|---|---|
| `bonus_rule` | `pct_of_base`, `none`, `unverified` |
| `equity_rule` | `dollar_grant_by_level`, `tc_target_minus_base`, `employee_election`, `none`, `unverified` |
| `vesting` | annual fractions as stated, e.g. `25/25/25/25` |
| `grant_term` | `one_year` or `vested_at_grant`; company profile only, a job package never reads it |
| `sign_on_bridges_vesting`, `base_cap_usd`, `annual_refresh`, `equity_vehicle` | as stated |

Per-rung facts sit on the rungs in `levels/atlas/rungs.csv`: `seed_median_usd`
and the bonus target range `bonus_low`, `bonus_high`. `bonus_ratio_for` returns
`0.0` for a `none` company, the target midpoint for a `pct_of_base` rung, and
`None` (use the next estimator) when unverified. A company that pays no bonus
and a company nobody checked are different answers, and the UI shows unknown,
never zero, for the second. `levels/pay.describe` puts the policy on the
package so the panel can state the vest schedule and bonus rule.

Every built-in company must have a policy entry and a seeded rung at Senior,
Staff and Principal: blueprint checks `offer_policy` and `pay_reference` in
`blueprint.py` name what is missing.

## Where things live

| Question | Lives in |
|---|---|
| Which rung is which band | `levels/atlas/` files, loaded by `levels/companies.py`; `levels/ladder.band_for`, `levels/words.resolve_band` |
| The rung the employer printed on the posting | `taxonomy/stated_level.py` into `jobs.raw_level`; banded through `levels/atlas/printed.csv` |
| Which family a role borrows from | `taxonomy/comp_families.py` (`REFERENCE_FAMILY`, `BORROW_ORDER`, `borrow_rank`) |
| The heuristic split, where nothing is measured | `analytics/comp_split.py` (`_EQUITY_PCT_BY_BAND`, `_EQUITY_MULT`) |
| The equity model checked against stated bases | `analytics/comp_residual.py`, `GET /api/statistics/equity-validation` |
| Stated pay against the user's pay floor | `analytics/pay_floor.floor_check` |
| Comparing our base with a plugin's per-level rows | `python -m scripts.bench_level_pay compare` |

## Rules

- Never split a band whose basis is `unclear`, never annualise an hourly or
  monthly rate, never split a stated total.
- Equity's range comes from equity's own tolerance, never from the width of
  the base band. For the same reason `tc_target_minus_base` is not used as a
  second equity estimator: evaluated at both ends of a posted band it rebuilds
  equity's spread from the base band.
- Never add a pay multiplier for a family (for example `ml_ai_research`). A
  family with no row of its own borrows and is labelled `cross_family`; a
  borrowed split is never called measured.
- At a company whose `bonus_rule` is `none`, a measured bonus is a one-time
  sign-on, not annual pay.
- A posted band can rule a rung out, never locate one: posted bands are wider
  than the gap between adjacent rungs. So never fit a rung mapping to pay, and
  never feed `reconciliation` back as an automatic re-level; that would turn a
  guess into a fact and make the check meaningless.
- The package and the median beside it read the same row (`choose_rung_row`).
- The pay floor is compared, never converted: only a yearly band in the
  floor's currency is checked; a total or unstated band can only be below.
- Per-company level and pay literals live in `levels/atlas/` and nowhere else;
  `tests/test_levels_model.py` fails if a known per-company table name is
  defined anywhere under `tracker/`.
