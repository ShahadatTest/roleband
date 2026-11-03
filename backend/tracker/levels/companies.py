"""Every company's ladder, stated once, loaded from the
level atlas files: `tracker/levels/atlas/companies.csv`,
`ladders.csv`, `rungs.csv` and `printed.csv`. Edit the files, not this module;
`levels.atlas` validates them and states their shape once.

These facts (rung -> band, printed code -> band, band -> pay lookup label,
band -> seed pay, band -> bonus target, the Walk guide's cells, the display
aliases) are functions over these rungs (`ladder.py`, `pay.py`), never tables
of their own.

A band is the company's own rung word: a
rung titled Senior is senior, Principal is principal, and a company with no
Staff rung (Amazon, Microsoft) has none. Rungs are listed lowest first.

Seed pay is a coarse median total comp (USD a year), used only when no live
figure resolves. A band with no
rung of its own reads the nearest rung below it (`ladder.rung_for_band`).

The evidence behind each company's rungs is the `note` column of the files.
"""

from __future__ import annotations

from tracker.levels.atlas import load_companies
from tracker.levels.model import CompanyLevels

COMPANIES: dict[str, CompanyLevels] = load_companies()
