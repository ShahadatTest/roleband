# Level atlas

How each company levels its people and how it builds pay, as CSV tables with a
generated Frictionless Data Package descriptor. The leveling
model RoleBand runs is exactly what these files say: `tracker/levels/atlas.py` states
each table's shape once, and validates, reads and writes every file from that
statement.

What reads it:

- `tracker.levels.companies` loads the ladders (`companies`, `ladders`, `rungs`,
  `printed`); every level reading and the level guide go through it.
- `tracker.levels.titles` loads `rung_titles`.
- `tracker.levels.pay` loads `company_facts`: how a company builds an offer.
- `tracker.levels.pay_grades` loads `pay_grades` and `pay_bands`: a posting whose
  title names no rung is placed by its posted range.
- `tracker.enrich.level_pay` reads every pay table; `tracker.enrich.builtin_pay`
  serves its figures as RoleBand's built-in pay source (on unless
  `ROLEBAND_BUILTIN_PAY=false`; see the app's `docs/pay.md`).
- `tracker.levels.identity` loads `company_identity`: tickers, the stock a grant
  tracks, and which listings get a price.
- The company profile (`tracker.api.routers.companies`) shows `level_base`.
- `tracker.levels.completeness` scores which named companies each section answers.

## Files

| File | One row is | Key | Written by |
|---|---|---|---|
| `companies.csv` | an employer the model knows, in the model's order | `slug` | hand |
| `ladders.csv` | a ladder of one company, in the company's order | `company`, `family` | hand |
| `rungs.csv` | a rung; row order within a ladder is rank, lowest first | `company`, `family`, `code` | hand |
| `printed.csv` | a level code an employer prints on a posting or in a board field | `company`, `code` | hand |
| `rung_titles.csv` | a phrase a company's titles use for one of its rungs | `company`, `family`, `phrase` | hand |
| `company_facts.csv` | one fact about how a company builds an offer | `company`, `fact` | hand |
| `company_identity.csv` | who a company is: name, listing, site, size | `company` | hand |
| `pay_grades.csv` | a posted US base range a company pays at one rung | `company`, `family`, `base_min`, `base_max`, `year` | hand, from `scripts.bench_level_bands pay-grades` |
| `pay_bands.csv` | a posted US base range at one band, for companies with no rung table | `company`, `family`, `base_min`, `base_max`, `year` | `scripts.bench_level_bands pay-bands --write` |
| `title_pay.csv` | government pay filings for one company, title, US state and year | `company`, `title`, `state`, `year` | `scripts.build_title_pay` |
| `posted_pay.csv` | a US annual base range from stored postings, with its title context | `company`, `title`, `department`, `team`, `raw_level`, `year`, `base_min`, `base_max` | `scripts.build_posted_pay` |
| `estimated_pay.csv` | a collected aggregate pay point at one company rung | `company`, `family`, `rung` | `scripts.build_estimated_pay` |
| `level_base.csv` | our base pay for one company, family and band | `company`, `family`, `band` | `scripts.build_level_base` |
| `datapackage.json` | the Frictionless descriptor of every table above | | generated from `atlas.py` |

The scripts behind `pay_grades`, `pay_bands`, `title_pay`, `posted_pay` and
`estimated_pay` read stored postings, raw filings or a reviewed capture, none of which is in the
repository.
`level_base` is built from the files here alone. Never edit a built file by hand.

## Columns

Cells are UTF-8 CSV. Types: `integer` (digits, optional leading minus), `boolean`
(`true` or `false`), `date` (`YYYY-MM-DD`), `band` (one of `intern`, `entry`, `mid`,
`senior`, `staff`, `principal`, `director_plus`). A list is `a|b|c`. An empty cell
means none or unknown, never zero or false. **Req** marks a column that may not be
empty. `note` is for the person reading the file: nothing reads it.

`family` is a taxonomy family slug (`software_engineering`, `product_management`),
or `company` on a company-wide ladder. `company` is a `companies.csv` slug.

### companies.csv

| Column | Type | Req | Meaning |
|---|---|---|---|
| `slug` | string | yes | The company's slug, as everywhere else in RoleBand. |
| `parent` | string | | A sibling employer whose ladders this one shares; its own ladders come first. |
| `printed_field` | string | | The board field the employer prints its rung in; empty: the rung, if printed, is in the posting's text. |
| `senior_unconfirmed` | boolean | | A bare "Senior" in this employer's titles reads senior but never confirmed. Empty is false. |
| `as_of` | date | yes | When the evidence for the row was read. |
| `note` | string | | |

### ladders.csv

| Column | Type | Req | Meaning |
|---|---|---|---|
| `company` | string | yes | |
| `family` | string | yes | The ladder's family, or `company` for the company-wide row. |
| `guide` | boolean | yes | Shown in the level guide: a reviewed ladder. |
| `company_wide` | boolean | yes | The code grades every function; `false`: only `tracks`. |
| `tracks` | list | | Role tracks the code grades when not company-wide. |
| `families` | list | | Other taxonomy families this ladder levels. |
| `flat` | boolean | | The employer's titles state no level beyond these rungs: a level with no rung is unstated, not skipped. |
| `as_of` | date | yes | |
| `note` | string | | |

### rungs.csv

| Column | Type | Req | Meaning |
|---|---|---|---|
| `company`, `family` | string | yes | The ladder the rung is on; it must exist in `ladders.csv`. |
| `code` | string | yes | How the company names the rung. |
| `band` | band | yes | The company's own rung word: a rung titled Senior is `senior`. |
| `aliases` | list | | Every other spelling of the rung. |
| `pay_label` | string | | The label estimated pay keys this rung by, when it is not `code`. |
| `people_manager` | boolean | yes | |
| `seed_median_usd` | integer | | Seed median total pay, USD a year, used only when no live figure resolves. Empty: no seed. |
| `bonus_low`, `bonus_high` | integer | | Annual bonus target range, percent of base; read only when both are filled. |
| `as_of` | date | yes | |
| `note` | string | | |

### printed.csv

| Column | Type | Req | Meaning |
|---|---|---|---|
| `company` | string | yes | |
| `code` | string | yes | The code as the employer prints it. |
| `band` | band | yes | The band the code reads. |

### rung_titles.csv

| Column | Type | Req | Meaning |
|---|---|---|---|
| `company`, `family`, `code` | string | yes | The rung the phrase reads; it must exist in `rungs.csv`. |
| `phrase` | string | yes | The title's words, lowercase and single-spaced (`senior engineering manager`); never a regular expression. |
| `match` | `exact`, `prefix`, `word` | yes | exact: the title's words are the phrase; prefix: they start with it; word: it appears among them as whole words. |
| `as_of` | date | yes | |
| `basis` | basis | yes | The kind of evidence (see below). |
| `note` | string | | |

The longest phrase a title meets wins. A printed code and an intern marker outrank a
phrase, and a phrase never pulls a Director title down.

### company_facts.csv

| Column | Type | Req | Meaning |
|---|---|---|---|
| `company` | string | yes | |
| `fact` | see below | yes | |
| `value` | string | yes | The fact, or `unknown`. |
| `stated_by` | `employer`, `estimated` | see below | Who states the fact. |
| `as_of` | date | yes | |

| Fact | Value |
|---|---|
| `bonus_rule` | `pct_of_base` (a target percentage of base, set by level) or `none` (no annual cash bonus) |
| `equity_rule` | `dollar_grant_by_level` (a dollar grant set by level), `tc_target_minus_base` (the grant fills a per-level total-pay target), `employee_election` (the employee picks the cash and stock mix) or `none` |
| `equity_vehicle` | the vehicle where no posting field states it (`rsu`, `options`, `cash_election`) |
| `vesting` | annual vest percentages, `/`-separated (`25/25/25/25`) |
| `grant_term` | `one_year` (equity granted a year at a time) or `vested_at_grant`; shown on the company profile only, and a stated `vesting` wins over it |
| `sign_on_bridges_vesting` | `true`: early-year cash offsets a back-loaded vest |
| `base_cap_usd` | whole USD: the company's cap on base salary |
| `annual_refresh` | `true`: an annual equity refresh sized by performance |
| `verified` | the date the company's policy entry was verified |

A fact that is not in the file is unverified, never zero. `stated_by` is required on
every fact and empty on `verified` and any `unknown` value.

### company_identity.csv

Every column but `company` may be empty: empty means not researched yet, never "no".

| Column | Type | Meaning |
|---|---|---|
| `company` | string | Req. |
| `display_name` | string | The name the company goes by. |
| `listed` | boolean | Its shares trade publicly. Empty is not researched, never private. |
| `ticker` | string | Its primary listing's symbol, when listed. |
| `exchange` | string | That listing's exchange, as the SEC names it (`NYSE`, `Nasdaq`), or its home exchange. |
| `cik` | integer | The SEC registrant number the listing is checked against; it survives a ticker change. |
| `grant_ticker` | string | The listed symbol its equity grants track when that is not its own (a subsidiary paid in its parent's stock). |
| `website` | string | Its own site's domain, without a scheme. |
| `hq_city` | string | Its headquarters city, as the company names it. |
| `headcount` | integer | Roughly how many people it employs. |
| `year_founded` | integer | |
| `logo` | string | A bundled logo asset's name; empty: the dashboard's monogram. |
| `brand_color` | string | `#rrggbb`. |
| `basis` | basis | The kind of evidence for the filled cells. |
| `as_of` | date | When the filled cells were read; empty while none is. |
| `note` | string | |

### pay_grades.csv and pay_bands.csv

| Column | Type | Req | Meaning |
|---|---|---|---|
| `company`, `family` | string | yes | |
| `base_min`, `base_max` | integer | yes | The posted annual US base range, USD. |
| `year` | integer | yes | The year the range was posted; a range seen in a later year is unknown until measured again. |
| `rung` (`pay_grades`) | string | yes | The rung code the range pays. |
| `band` (`pay_bands`) | band | yes | The band the range pays. |
| `anchor` | string | yes | A title that states the rung or band. |
| `anchors` | integer | yes | Postings at this range whose title stated it. |

A row exists only where at least two anchoring postings agree on four of every five.

### title_pay.csv

| Column | Type | Req | Meaning |
|---|---|---|---|
| `company` | string | yes | |
| `title` | string | yes | As filed, lowercase and single-spaced. Level and family are read from it at use time. |
| `state` | string | yes | The worksite's US state or territory code. |
| `year` | integer | yes | The year the filings were made. The latest year a key has is read; an older year is history. |
| `n` | integer | yes | Filings in the cell. |
| `base_p10` ... `base_p90` | integer | yes | The offered annual base (the filing's wage from) at the 10th, 25th, 50th, 75th and 90th percentile of the cell's filings. |
| `level_i` ... `level_iv` | integer | | Filings at prevailing-wage level I to IV; empty: none. |
| `as_of` | date | yes | The date the dataset starts for the company. |

A cell with `n = 1` is one filing's offered base, so its `base_p10` to `base_p90`
are that one figure. The file keeps such cells because each filing is published
individually and names no person.

### posted_pay.csv

| Column | Type | Req | Meaning |
|---|---|---|---|
| `company`, `title` | string | yes | The posting's company and title. |
| `department`, `team` | string | | As the posting states them. |
| `raw_level` | string | | The level code the employer printed on the posting. |
| `year` | integer | yes | |
| `base_min`, `base_max` | integer | yes | The posted annual US base range, USD. |
| `n` | integer | yes | Distinct postings in the cell. |
| `as_of` | date | yes | |

The row keeps the title context, never a classified band: the level is read from it
at use time, and a range alone never places a level.

### estimated_pay.csv

| Column | Type | Req | Meaning |
|---|---|---|---|
| `company`, `family` | string | yes | |
| `rung` | string | yes | The company's own rung label as collected; the atlas places it on a rung of the family's ladder. |
| `base_usd` | integer | yes | Estimated annual base. |
| `equity_usd` | integer | | Estimated annualised equity. Empty is unknown. |
| `cash_bonus_usd` | integer | | Estimated cash bonus; it may include sign-on cash, so it is not a bonus policy. Empty is unknown. |

### level_base.csv

Built from `title_pay`, `pay_grades`, `pay_bands`, `posted_pay` and `estimated_pay`.
Base prefers a filed offer, then a posted range, then an estimated aggregate.
Annualised equity comes from the aggregate, or is zero where the company grants
none. An empty equity cell is unknown, never zero.

| Column | Type | Req | Meaning |
|---|---|---|---|
| `company`, `family` | string | yes | Matching keys. |
| `band` | band | yes | The level the estimate prices. |
| `base_usd` | integer | yes | Estimated annual US base. |
| `stock_usd` | integer | | Estimated annualised equity. |

The published baseline contains amounts and matching keys only. The aggregate's
own `rung` remains an input to level matching.

## Evidence standard

Provenance lives in the rows, not in this file.

- **`as_of`** is when the evidence for a row was read. It is required in
  `companies`, `ladders`, `rungs`, `rung_titles`, `company_facts` and `posted_pay`, and a row without one is refused. Change a row, change its date.
  `title_pay.as_of` is the date the dataset starts; `company_identity.as_of` covers
  its filled cells. `pay_grades` and `pay_bands` carry the posting `year` instead.
- **`basis`** (`rung_titles`, `company_identity`) is the kind of evidence, never a
  site: `employer_titles` (the company's own titles), `employer_posted_ranges`
  (its exact posted pay ranges), `government_disclosure` (public filings),
  `employer_published` (its own pages and reports), `reviewed_judgement` (a
  reviewed call where the evidence leaves a choice),
  `unverified` (not yet checked against an employer or a filing;
  re-verifying the row replaces it).
- **`stated_by`** (`company_facts`) is who states a fact: `employer`
  (its filings, postings and pages) or `estimated` (used where the employer does not state the fact). The company profile labels each fact by it.
- **`unknown`** is a searched-for answer: employer sources and estimated pay were
  read and nobody states the fact. Only `bonus_rule`, `equity_rule`,
  `equity_vehicle`, `vesting` and `annual_refresh` may be `unknown`. Pay math reads
  it as unverified; the completeness score counts it as answered.
- **No vendor name and no URL** in any file in this directory
  (`tests/test_level_atlas.py` scans them). Describe evidence by its kind.
- **A rung phrase needs evidence that names the rung**: the company's published
  ladder or job-architecture page, a printed code, or exact posted ranges anchored
  by titles that state the rung. Pay alignment alone ("a manager title paid like
  band X") is a hint, never a row. A method that proposes bands for groups of titles
  must first pass `scripts.bench_level_bands evidence-check <groups.csv>`: 94% or
  more agreement over at least 10 groups whose titles state their own band, and no
  director title lowered.
- **A band follows the company's own rung word**, except at professional-services
  firms, whose rank words are not a tech ladder's; their `ladders.csv` notes state
  the exception.

## Contributing

The atlas is edited in the `roleband/roleband-data` repository, in `atlas/`. The app,
`roleband/roleband`, carries a pinned, read-only copy at `backend/tracker/levels/atlas/`,
and every module and test named in this card is in the app. Edit the CSV in place: keep the columns, their order and the row order (rows of
`companies`, `ladders` and `rungs` are in the model's order). The loader refuses, naming the file and line, a changed
header, a short or long row, an empty required cell, a value outside its enum, a
malformed integer, boolean or date, a duplicate key, a ladder or printed code for
an unknown company, a rung without its ladder, a phrase for a rung that does not
exist or not written as lowercase words, and a `company_facts` row that breaks the
`stated_by` and `unknown` rules above.

Editing `companies`, `ladders`, `rungs`, `printed` or `rung_titles` moves the
classifier fingerprint (`tracker.enrich.inventory.CLASSIFIER_SOURCES`), so stored
postings are re-levelled. A `rung_titles.csv` row for a company not
yet listed in `REVIEWED` in `tests/test_rung_titles.py` adds the company there, with
the evidence, in the same change.

From the app's `backend/`, with this repository checked out at `../../roleband-data`:

```sh
# the files keep their statements, load, round-trip byte for byte, and the
# descriptor is current
.venv/bin/python -m scripts.check_datasets --root ../../roleband-data

# copy the working files into the app as a trial, then the atlas tests
# (no file names a vendor or a URL; gaps, levels and rung titles hold)
.venv/bin/python -m scripts.data pin --try ../../roleband-data
.venv/bin/python -m pytest tests/test_level_atlas.py tests/test_rung_titles.py tests/test_level_base.py tests/test_atlas_completeness.py

# after any pay table changes: rebuild our per-level base into the checkout
.venv/bin/python -m scripts.build_level_base --out ../../roleband-data

# which named companies each section still lacks; --write shrinks
# tests/fixtures/atlas_gaps.json after a change fills gaps
.venv/bin/python -m scripts.atlas_completeness --gaps

# after a table's shape changes in atlas.py: regenerate the descriptor
PYTHONPATH=$PWD .venv/bin/python -c "from tracker.levels import atlas; print(atlas.descriptor_text(), end='')" > ../../roleband-data/atlas/datapackage.json

# identity rows with a cik: does the SEC still list each ticker? (network)
.venv/bin/python -m scripts.check_company_listings
```

`datapackage.json` carries `schema_version` (the table shapes, semver) and
`edition` (the data, raised by whoever changes it). See also this repository's
`CONTRIBUTING.md`, and the app's `docs/development.md`, "Change a dataset".

## Licence and provenance

The files in this directory are licensed CC-BY-4.0, Creative Commons Attribution
4.0 International. Attribution: "RoleBand contributors". The descriptor states the
licence (`licenses`).

`title_pay.csv`, and the filed figures in `level_base.csv` built from it, are derived
from US Department of Labor disclosure records, which are public domain.
