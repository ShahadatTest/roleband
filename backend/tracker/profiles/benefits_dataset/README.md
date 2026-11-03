# Benefits dataset

What each company RoleBand names offers its people beyond cash pay, one benefit type
at a time, with the evidence for each. The company profile's benefits section reads it
through `tracker/profiles/benefits_builtin.py` (`dataset_benefits`,
`dataset_benefit_notes`), served by `tracker/api/routers/companies.py`, whenever no
plugin is selected for company benefits; the same taxonomy classifies a plugin's rows.
The runtime only reads these files: nothing builds them and nothing writes them back.

## Files

| File | One row is | Key |
|---|---|---|
| `observations.jsonl` | one evidence record: one company, one benefit type, one observation, as one JSON object per line | `observation_id` |
| `taxonomy.json` | one JSON document: the benefit categories, and the benefit types with the labels that map to each | category `id`, benefit type `id` |

`observations.jsonl` is layout version 2.0.0. It is edited in place, in UTF-8. A
company's records for one benefit type form that benefit's cell on the profile, in
the order the file lists them; a company and benefit type with no record is unknown,
which is not "not offered" and is never shown.

## Columns

### `observations.jsonl`: an evidence record

| Field | Type, values | Meaning |
|---|---|---|
| `company` | string | the company slug, one `tracker.company_discovery.named_companies()` returns |
| `benefit_type` | string | a benefit type `id` from `taxonomy.json` |
| `observation_id` | string, unique in the file | the record's stable id; keep it when correcting the record |
| `kind` | `employer` or `dataset` | `employer`: the employer's own words from a job posting or its careers pages. `dataset`: a structured record with no employer wording |
| `assertion` | `listed` | the record says the benefit is offered; the reader shows only `listed` |
| `context` | `job_specific`, `captured_posting`, `company_page`, `company_unknown_scope` | where the record was found; `company_page` is a careers or benefits page, `company_unknown_scope` marks a `dataset` record, whose scope within the company is unknown |
| `terms` | string, may be empty | `employer`: the whole line the benefit was named in. `dataset`: reference text (structured fields, an estimate note), never shown as wording |
| `display_excerpt` | string, may be absent | the wording the profile shows: for `employer`, the sentence that names the benefit; list markers are stripped |
| `has_terms` | boolean | `terms` says something beyond the benefit's name or an estimate note |
| `estimated_annual_value_usd` | integer or null | an estimated annual value in US dollars; null is unknown, and 0 is an explicit zero estimate. Shown per benefit, never summed into a total |
| `scope` | object | where the record applies: `country` (ISO 3166-1 alpha-2), `region`, `employee_group` (e.g. `full_time`), `role_family`, `level`, each null when unknown. Null is unknown, never "everywhere". `employer` records also keep `scope_title`, the heading the words sat under |
| `review_status` | `unreviewed`, `reviewed`, `disputed` | a record reads as reviewed only when this is `reviewed` |
| `supporting_capture_count` | integer, `employer` only | how many stored copies of postings or pages carry the sentence: copies, not independent sources |

### `taxonomy.json`

| Field | Type | Meaning |
|---|---|---|
| `version` | string | the taxonomy's version |
| `classification_rule` | string | the matching rule, in words |
| `categories[]` | `{id, label}` | a benefit category, in display order |
| `benefit_types[]` | `{id, category, label, aliases}` | a benefit type, its one category `id`, its name, and the labels that map to it |

A label maps to a type when it equals the type's `label` or one of its `aliases` after
collapsing whitespace and ignoring case; nothing else is matched. A plugin label no
alias maps is kept under its own name in an `other` group on the profile.

## Evidence standard

- A benefit is listed only on evidence: at least one record. With none it is unknown,
  which a profile does not show.
- An `employer` observation quotes the employer: its words go in `terms`, verbatim,
  with `display_excerpt` the sentence that names the benefit.
- `scope.country` is set only when the employer names the country, in the words or in
  the heading above them (`scope_title`). It is never inferred from currency,
  headquarters or where the page was read. A benefit with no country is shown with a
  note that where it applies is not recorded.
- `estimated_annual_value_usd` holds an available annual estimate, including an imported estimate. It never implies the employer stated the amount. With no estimate it is null.
- Where a record comes from is in the record: `kind`, `context`, `scope_title` and
  `supporting_capture_count`, row by row.

## Contributing

The dataset is edited in the `roleband/roleband-data` repository, in `benefits/`. The app,
`roleband/roleband`, carries a pinned, read-only copy at
`backend/tracker/profiles/benefits_dataset/`, and every module, test and command named in
this card is in the app.

- To add evidence, add one line. To correct a record, edit its line and keep its
  `observation_id`. A new record needs an `observation_id` no other record uses. Line order
  matters only within one company and benefit: when two wordings tie, the earlier line
  leads.
- A new benefit type is a row in `taxonomy.json` and its name in
  `dashboard/src/copy/en/profiles.ftl` (`profiles-benefits-type`; a new category also
  in `profiles-benefits-category`), then `npm run gen:copy` in `dashboard/`.
- A newly named company needs no lines until there is evidence for it.
- A new file in this directory is declared in `tracker/plugins/data_kinds.py`.

Check, from the app's `backend/` after `./setup.sh`, with this repository checked out at
`../../roleband-data`:

```
.venv/bin/python -m scripts.check_datasets --root ../../roleband-data
.venv/bin/python -m scripts.data pin --try ../../roleband-data
.venv/bin/python -m pytest tests/test_benefits_builtin.py tests/test_data_kinds.py
```

`scripts.check_datasets` names the line of a record that is not a JSON object,
has a field the table above does not list, names a company the app does not name or a
type the taxonomy does not have, reuses an `observation_id`, or has a `kind`, `context`,
`scope` or `supporting_capture_count` that does not fit, and a taxonomy label that names
two benefit types. `tests/test_benefits_builtin.py` also fails on a country heading
without its `scope.country`, and on any write the runtime makes to these files.

## Licence and provenance

`observations.jsonl` and `taxonomy.json` are licensed
[CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/); attribute "RoleBand
contributors". Built from employers' official websites and job posts. Quoted
passages remain the employers' words.
