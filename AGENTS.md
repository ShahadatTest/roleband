# RoleBand: instructions for coding agents

RoleBand is a local-first job radar: a Python/FastAPI backend with
embedded Postgres (`backend/`) and a React/Vite dashboard (`dashboard/`).

Every fact about the project has one document that owns it; another may repeat it in
a line that links the owner. Start with [docs/development.md](docs/development.md):
its first table names the document that owns each subject. Read the owner of what
you change before you change it; it holds the rules a reviewer will reject a change
for.

Before you call a change done, run the [change-scoped gate](docs/testing.md#change-scoped-gate)
for every surface you touched and say what you ran. The two you will need most:

- Backend, from `backend/`: `.venv/bin/ruff check tracker tests scripts ../sdk/python ../examples`,
  `.venv/bin/lint-imports`, `.venv/bin/mypy`, `.venv/bin/python -m pytest`.
- Dashboard, from `dashboard/`: `npm run lint`, `npm run test:unit`, `npm run build`, and
  `npm run test:ux` for a screen.

Pull requests also get an automated review; [CONTRIBUTING.md](CONTRIBUTING.md#automated-review)
says how to answer it.

This file owns two rules that apply to every change, by people and agents alike.

## Data safety

The database is a longitudinal record: observation history cannot be rebuilt
once it is gone.

- Never drop, truncate, reset or bulk-delete user data, in a migration, a script
  or a command you run, unless the person you work for asked for exactly that.
- A command that rewrites many rows commits per batch and resumes (a version gate
  or a printed cursor), so a killed process does not roll back hours of work. A
  function the post-passes also call stays commit-free; the command around it owns
  the batches.
- Work against a throwaway database (`ROLEBAND_PGDATA`) whenever you are not sure
  which one a command will reach.

## Comments

A comment is read by every future contributor, for as long as the code lives. It
earns its place only if it stays true and useful without its author.

**Write** a comment when the code cannot say something itself: an invariant, why
an order or a precedence matters, a quirk of an outside system the code works
around, a trade-off that would otherwise look like a mistake. Present tense, about
the code as it is.

**Do not write**, in code, comments, docstrings, help text, data notes or catalog
notes:

- who decided, or when: "owner decision", "agreed on 2026-10-03", a person's name;
- process references: plan or review IDs (`D7`, `P3`, `R6`, `review #26`), phases,
  stages, waves, cohorts, section marks of documents that are not in the tree;
- history: what the code used to do, what was renamed, moved or fixed, which
  incident caused it;
- evidence that ages: counts from a live database, "measured on", "as of", how
  many companies did something this month, where or when a dataset was fetched.
  Data changes; the sentence about last month's copy of it becomes false and stays
  in the code;
- anything the code already says plainly.

**Where that information goes instead:**

| Information | Home |
|---|---|
| Why a decision was made, and what it rules out | a decision record in `docs/decisions/` |
| Evidence that a rule holds (the case that broke it, the numbers) | a test, ideally with the failing case as a negative control |
| What changed and why, this time | the commit message and the pull request |
| Where a dataset comes from and when it was read | the dataset's own columns (`as_of`, `basis`) and its README |

`python backend/scripts/check_comment_hygiene.py` checks the mechanical part of
this in CI. A line that genuinely needs a flagged form carries `hygiene: allow`
with the reason.
