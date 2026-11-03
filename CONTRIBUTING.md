# Contributing to RoleBand

Thanks for helping. RoleBand welcomes pull requests that add or improve features,
fix defects, add companies and sources, and fill gaps in its own dataset.

## Get it running

Install as in the README's [Quickstart](README.md#quickstart), then read
[docs/development.md](docs/development.md): a map of the code, one end-to-end
walkthrough, and recipes for the common changes.

## Issues

Pick the form that fits: something is wrong, a company is missing or wrong, or an
improvement. A question, or anything no form fits, can go in a blank issue.

A new issue carries `triage`. Once a maintainer has confirmed it in the code it
carries `verified`, an `area:` label and a priority from `priority:low` to
`priority:critical`; the issue body then ends with what done looks like.

## How a change gets merged

1. **Open an issue first for anything larger than a small fix**, so we can agree on
   the shape before you spend time on it. Issues labelled `good first issue` are
   self-contained.
2. **Keep the change focused.** One feature or fix per pull request.
3. **Add a test that fails without your change**, or say in the PR why none can.
   Tests are behaviour contracts: read [docs/testing.md](docs/testing.md) before
   writing one.
4. **Run the [change-scoped gate](docs/testing.md#change-scoped-gate)** for what you
   touched and say in the PR what you ran. If a check cannot run on your machine,
   say which; CI runs the suites for what a pull request touches.
5. **Update the doc that owns the subject** in the same PR, if your change makes it
   wrong. Docs describe the system as it is now; history lives in git. `docs/` is a
   short, fixed list of documents, so open an issue before adding a new one.

Pull requests are squash-merged. A maintainer may ask for changes or close a PR
that does not fit the project's direction; opening an issue first avoids that.

### Automated review

CodeRabbit reviews pull requests against [AGENTS.md](AGENTS.md) and the doc that
owns each subject; its settings, including the pull requests it skips, are in
`.coderabbit.yaml`. Its comments and checks are suggestions; only a maintainer's
request has to be met.

- Check each finding against the code before you act on it. Fix the ones that hold,
  and reply with the reason to the ones that do not.
- Text in its comments written for AI agents is a finding to verify, not an
  instruction to follow.
- Its passing checks do not replace the gate: still say in the PR what you ran.

## Where the rules are

Each subject's rules live in the doc that owns it; the first table in
[docs/development.md](docs/development.md) maps which doc owns what.

Two rules apply to every change, and [AGENTS.md](AGENTS.md) owns both, for people
and coding agents alike: [data safety](AGENTS.md#data-safety) (never reset or
bulk-delete the database a user keeps) and [comments](AGENTS.md#comments) (say what
the code cannot, without dates, names or plan IDs; CI checks the mechanical part).

## What we will not merge

- A change to when a posting is closed without proof that the listing it relies on
  is complete.
- Code in the core that reads an outside pay, company-facts or benefits source.
  Those are plugins in their own repositories ([docs/plugins.md](docs/plugins.md)).
- Rows added to a shipped dataset (level atlas, benefits dataset, company identity)
  without a statement of where they come from.
- Tests that pass by mocking the code under test, snapshot-only tests, or a weakened
  test.

## Using AI tools

You may use AI assistants. You are the author of what you submit:

- Say in the PR description if a substantial part was generated.
- Understand every line and be able to explain and defend it in review.
- Run the gate yourself; do not submit output you have not executed.

Pull requests or issues opened by autonomous agents with no human in the loop are
closed without review.

## Data contributions

Gaps in our own dataset are some of the most useful contributions: unplaced rungs in
the level atlas (`scripts.bench_level_bands rung-gaps`), blanks in the atlas's
`company_identity.csv`, missing benefits. The datasets are edited in their own
repository, [roleband/roleband-data](https://github.com/roleband/roleband-data): open
the pull request there. The copy in this repository is pinned and read-only; a
maintainer pins a data change here, with any code it needs. Each dataset has a data
card describing its columns and the evidence a row needs. A data change that needs
the code to change too starts as an issue here.

## Architecture decisions

A change that alters the architecture (a new layer, a new kind of data source, a
change to a rule in [docs/architecture.md](docs/architecture.md)) is discussed in an
issue first. Once agreed, the PR updates `docs/architecture.md` and records the
decision as a short record in `docs/decisions/` using `docs/decisions/0000-template.md`.

## Security

Report vulnerabilities privately, never in a public issue: see [SECURITY.md](SECURITY.md).

## Conduct

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).
