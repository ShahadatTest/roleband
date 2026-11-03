"""Every file of our dataset, the kind of data it serves, and how that kind switches.

RoleBand ships with OUR dataset and gives the user the
choice. With every plugin off, every kind below is answered by our files only;
with one on, each kind it publishes switches to its data WHOLE, app-wide, never
mixed with ours, and turning it off brings ours back unchanged. Nothing is lost either way: our files are read-only to the
runtime, and a plugin's rows are retired or hidden, never deleted, except by
the user's own Remove data. Identity and the pay policy never switch.

A file in `levels/atlas/` or `profiles/benefits_dataset/` that is not declared
here fails `tests/test_data_kinds.py` by name: a new file must say which kind it
serves before the switch can be proven to cover it.
"""

from __future__ import annotations

from dataclasses import dataclass

from tracker.plugins.registry import COMPANY_BENEFITS, COMPANY_FACTS, PAY_LEVELS, PAY_OBSERVATIONS

ATLAS = "levels/atlas/"
BENEFITS = "profiles/benefits_dataset/"


@dataclass(frozen=True)
class DataKind:
    name: str
    #: The plugin slot that switches this kind; None = never switches.
    slot: str | None
    #: Where our dataset answers it (module), for a reader of this table.
    builtin: str
    #: Our files behind it, relative to `tracker/`.
    files: tuple[str, ...]
    #: What a person sees of it.
    shows: str


KINDS: tuple[DataKind, ...] = (
    DataKind(
        "levels", None, "tracker.levels",
        (f"{ATLAS}companies.csv", f"{ATLAS}ladders.csv", f"{ATLAS}rungs.csv", f"{ATLAS}printed.csv",
         f"{ATLAS}rung_titles.csv"),
        "each company's ladder, a posting's level and band, the Walk guide, level filters",
    ),
    DataKind(
        "per_level_pay", PAY_LEVELS, "tracker.enrich.builtin_pay",
        (f"{ATLAS}title_pay.csv", f"{ATLAS}posted_pay.csv", f"{ATLAS}pay_grades.csv", f"{ATLAS}pay_bands.csv",
         f"{ATLAS}estimated_pay.csv", f"{ATLAS}rungs.csv", f"{ATLAS}level_base.csv"),
        "a posting's estimated pay, its pay package, the company profile's pay ladder, pay statistics",
    ),
    # Equity vehicle and vesting are the pay policy's, never a plugin's facts.
    DataKind(
        "pay_policy", None, "tracker.levels.pay",
        (f"{ATLAS}company_facts.csv",),
        "the pay policy line: bonus rule and targets, vesting, refresh grants, equity vehicle",
    ),
    # Always ours: a plugin's identity claims are stored and never read.
    DataKind(
        "company_identity", None, "tracker.profiles.seed",
        (f"{ATLAS}companies.csv", f"{ATLAS}company_identity.csv"),
        "a company's name, public or private, ticker, headquarters, website, logo, brand colour",
    ),
    # The one company fact a plugin answers: ours (`company_identity.csv`)
    # answers while no plugin is selected for company facts.
    DataKind(
        "company_size", COMPANY_FACTS, "tracker.profiles.seed",
        (f"{ATLAS}company_identity.csv",),
        "a company's headcount",
    ),
    DataKind(
        "benefits", COMPANY_BENEFITS, "tracker.profiles.benefits_builtin",
        (f"{BENEFITS}observations.jsonl", f"{BENEFITS}taxonomy.json"),
        "a company's benefits by category and type",
    ),
    # Our dataset holds no estimated pay points: only a plugin answers this kind
    # (`pay.observations`), and with it off nothing does.
    DataKind(
        "estimated_observations", PAY_OBSERVATIONS, "",
        (),
        "individual estimated pay points, cross-checking the modelled equity (no screen today)",
    ),
)

#: Files in the dataset directories that serve no kind directly: the atlas
#: descriptor and the notes. Each with its reason.
TOOLING: dict[str, str] = {
    f"{ATLAS}datapackage.json": "the atlas package descriptor, generated",
    f"{ATLAS}README.md": "notes",
    f"{BENEFITS}README.md": "notes",
}


def kind_of_slot(slot: str) -> DataKind:
    return next(k for k in KINDS if k.slot == slot)
