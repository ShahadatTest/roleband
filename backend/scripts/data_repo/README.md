# RoleBand data

The datasets RoleBand reads, as plain files anyone can read, check and reuse:

| Folder | What it holds | Data card |
|---|---|---|
| [`atlas/`](atlas/) | The level atlas: how each company levels its people and builds pay, as CSV tables with a Frictionless Data Package descriptor (`datapackage.json`) | [atlas/README.md](atlas/README.md) |
| [`benefits/`](benefits/) | The benefits dataset: what each company offers beyond cash pay, one evidence record per line, and the taxonomy of benefit types | [benefits/README.md](benefits/README.md) |

Each data card describes every file and column, the evidence standard, and how
the files are checked.

## How RoleBand uses it

The app, [roleband/roleband](https://github.com/roleband/roleband), carries a
read-only copy of one commit of this repository, named with the hash of every
file in `backend/tracker/datasets.lock.json`. A clone of the app sets up offline,
and every install of a given app version reads exactly the same data.

Data is edited here, never in the app. A change reaches the app when a
maintainer pins its commit there, together with any code the change needs.

## Checking a change

The rules a file must keep are the app's: the tables it states, the rules its
loaders hold, and the companies it names. This repository's CI checks every
change against the app's `main`. To run the same check locally, with the app
cloned beside this repository and set up:

```sh
cd ../roleband/backend
.venv/bin/python -m scripts.check_datasets --root ../../roleband-data
```

Each problem is printed as one line naming the file, line and column.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence and provenance

The data in this repository is licensed
[CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) (see [LICENSE](LICENSE));
attribute "RoleBand contributors".

- `atlas/title_pay.csv`, and the filed figures in `atlas/level_base.csv` built
  from it, are derived from US Department of Labor disclosure records, which are
  public domain. The licence covers our curation, not those records.
- The benefits dataset is built from employers' official websites and job
  posts. Quoted passages remain the employers' words.
