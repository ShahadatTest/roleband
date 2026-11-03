"""Questions asked of the ladders. Every answer is computed from
`companies.COMPANIES`; nothing here stores a fact of its own."""

from __future__ import annotations

import re
from collections.abc import Iterator

from tracker.levels.companies import COMPANIES
from tracker.levels.model import COMPANY_ROW, ENGINEERING, CompanyLevels, Ladder, Rung
from tracker.schema import LEVEL_BAND_ORDER, LevelBand, RoleTrack


def _lineage(company: str) -> Iterator[CompanyLevels]:
    """The company, then its parent, then the parent's parent (cycle-safe)."""
    seen: set[str] = set()
    slug: str | None = company
    while slug and slug not in seen:
        seen.add(slug)
        record = COMPANIES.get(slug)
        if record is None:
            return
        yield record
        slug = record.parent


def lineage(company: str) -> list[str]:
    """This company's slug, then its parents' (a company the model does not
    know is its own lineage)."""
    return [record.slug for record in _lineage(company)] or [company]


def ladders_of(company: str) -> tuple[Ladder, ...]:
    """Own ladders first, then the parent's."""
    return tuple(ladder for record in _lineage(company) for ladder in record.ladders)


def rung_in(ladder: Ladder, code: str) -> Rung | None:
    """The rung of this ladder any spelling of `code` names, or None."""
    for rung in ladder.rungs:
        if code in rung.spellings:
            return rung
    return None


def rung_for_code(company: str, code: str, ladder: Ladder | None = None) -> Rung | None:
    """The rung `code` names: in `ladder` when given (a family rule names a rung
    of its own ladder), else on the company row first, then every other ladder
    in order. One code may name a rung on two ladders of one company (Google's
    L8 is Principal on the IC ladder, Director on the row); a ladder holds it
    once."""
    if ladder is not None:
        return rung_in(ladder, code)
    for candidate in ladders_of(company):
        rung = rung_in(candidate, code)
        if rung is not None:
            return rung
    return None


def band_for(company: str, code: str, ladder: Ladder | None = None) -> LevelBand | None:
    """Band for a company rung by any of its spellings, or None when the rung isn't known."""
    rung = rung_for_code(company, code, ladder)
    return rung.band if rung is not None else None


def printed_key(code: str) -> str:
    """A printed code as it is compared: letter case and runs of spaces are a
    board field's styling, not the rung ("senior manager" is "Senior Manager")."""
    return " ".join(code.split()).casefold()


def band_for_stated_rung(company: str, code: str | None) -> LevelBand | None:
    """Band for a code the employer printed on the posting, or None when we
    cannot map it. None is the answer for every company that prints nothing
    and for a printed code not calibrated (Nvidia's family-relative "Level 4",
    a Microsoft "Partner" posting): falling through to the title is correct,
    inventing a band is not."""
    if not code:
        return None
    want = printed_key(code)
    for record in _lineage(company):
        for printed, band in record.printed.items():
            if printed_key(printed) == want:
                return band
    return None


def prints_rungs_in_text(company: str) -> bool:
    """True when the company prints rung codes `band_for_stated_rung` can band
    in the posting's TEXT (Microsoft's IC/M): reading the posting can then
    state its level. A rung printed in a listing field is read with the
    listing, never by reading the page."""
    return any(record.printed and record.printed_field is None for record in _lineage(company))


def printed_field(company: str) -> str | None:
    """The board field this company prints its rung in, or None."""
    for record in _lineage(company):
        if record.printed_field:
            return record.printed_field
    return None


def ladder_for(company: str, family: str | None = None) -> Ladder | None:
    """The ladder named `family`, else the company row, else the engineering
    ladder. With no family it is the row: what pay and the guide read."""
    ladders = ladders_of(company)
    for wanted in (family, COMPANY_ROW, ENGINEERING):
        for ladder in ladders:
            if wanted is not None and ladder.family == wanted:
                return ladder
    return None


def reading_ladder(company: str, family: str | None) -> Ladder | None:
    """The family ladder a posting of this taxonomy family reads its title by,
    or None when the company states none for it (the company row's rules
    then apply). Run after `classify_family`."""
    for ladder in ladders_of(company):
        if ladder.family != COMPANY_ROW and ladder.levels(family):
            return ladder
    return None


def rung_for_band(company: str, band: LevelBand, family: str | None = None) -> Rung | None:
    """The rung a posting in `band` reads its pay from.

    Inside the band, the lowest rung that carries seed pay, else the lowest
    rung: a posting banded principal at Microsoft is most often its entry rung
    65. A band the company has no rung in reads the nearest rung BELOW it
    (Amazon has no Staff rung, so staff reads Senior SDE), and only failing
    that the nearest above.
    """
    ladder = ladder_for(company, family)
    if ladder is None or not ladder.rungs:
        return None
    inside = [rung for rung in ladder.rungs if rung.band is band]
    if inside:
        seeded = [rung for rung in inside if rung.seed_median_usd is not None]
        return (seeded or inside)[0]
    order = LEVEL_BAND_ORDER[band.value]
    below = [rung for rung in ladder.rungs if LEVEL_BAND_ORDER[rung.band.value] < order]
    if below:
        return below[-1]
    above = [rung for rung in ladder.rungs if LEVEL_BAND_ORDER[rung.band.value] > order]
    return above[0] if above else None


_NUMBERED = re.compile(r"([A-Za-z]*)(\d+)")


def _guide_label(rungs: list[Rung]) -> str:
    """One rung shows its code; several show their span: "63–64" when both ends
    are numbered alike, else the first and a plus ("IC7+" for IC7 and
    Distinguished Engineer), which never reads as a code of its own."""
    if len(rungs) == 1:
        return rungs[0].code
    first, last = (_NUMBERED.fullmatch(rung.code) for rung in (rungs[0], rungs[-1]))
    if first and last and first.group(1) == last.group(1):
        return f"{rungs[0].code}–{rungs[-1].code}"
    return f"{rungs[0].code}+"


def _guide_entries(ladder: Ladder) -> dict[str, dict]:
    """band slug -> ``{"label", "spellings"}`` for the rungs this ladder puts
    in that band: the label the guide shows, and every spelling of those
    rungs, so a search finds a rung its label hides (66 inside "65–67")."""
    by_band: dict[LevelBand, list[Rung]] = {}
    for rung in ladder.rungs:
        by_band.setdefault(rung.band, []).append(rung)
    return {
        band.value: {
            "label": _guide_label(rungs),
            "spellings": [spelling for rung in rungs for spelling in rung.spellings],
        }
        for band, rungs in by_band.items()
    }


def level_guide(company: str) -> dict[str, dict]:
    """The level guide's cells for one company: band slug -> cell, each entry
    ``{"label", "spellings"}``.

    A cell is ``{"company_wide": entry}`` (one grade spans every function) or
    ``{"per_track": {"technical": entry}}`` (a grade for those tracks only;
    the client falls other tracks back to the seniority word). It shows
    exactly the rungs the mapper puts in that band, as a range when there are
    several ("63–64"), so the guide and the Board cannot disagree.
    Display only, never a pay lookup.

    A company-wide row and a track ladder that bands a grade differently
    (Google's L8 is Director on the row, Principal Engineer on the technical
    ladder) give that band a cell per track: the track ladder's entry for its
    tracks, the row's for every other. Bands where they agree stay company-wide.
    """
    cells: dict[str, dict] = {}
    record = COMPANIES.get(company)
    if record is None:
        return cells
    guides = [ladder for ladder in record.ladders if ladder.guide]
    rows = [_guide_entries(ladder) for ladder in guides if ladder.company_wide]
    wide = rows[0] if rows else {}
    by_track = {track: _guide_entries(ladder) for ladder in guides
                if not ladder.company_wide for track in ladder.tracks}
    for band in (level.value for level in LevelBand):
        # A track ladder speaks for its tracks, even by having no rung here.
        tracks = {track: entries[band] for track, entries in by_track.items() if band in entries}
        if band in wide:
            if all(by_track[track].get(band) == wide[band] for track in by_track):
                cells[band] = {"company_wide": wide[band]}
                continue
            for track in RoleTrack:
                if track.value not in by_track:
                    tracks[track.value] = wide[band]
        if tracks:
            cells[band] = {"per_track": tracks}
    return cells


def walk_guide(company: str) -> dict[str, dict]:
    """`level_guide` with labels only: ``{"company_wide": "L5"}`` or
    ``{"per_track": {"technical": "ICT4"}}``, the cells the Walk's level
    table reads."""
    out: dict[str, dict] = {}
    for band, cell in level_guide(company).items():
        if "company_wide" in cell:
            out[band] = {"company_wide": cell["company_wide"]["label"]}
        else:
            out[band] = {"per_track": {track: entry["label"] for track, entry in cell["per_track"].items()}}
    return out


def flat_guide(company: str) -> bool:
    """Whether the company's titles state no level beyond its guide rungs
    (`Ladder.flat`), so a band without a cell is unstated, not skipped."""
    record = COMPANIES.get(company)
    return record is not None and any(ladder.flat for ladder in record.ladders if ladder.guide)


def stage_decoder() -> dict[str, dict[str, dict]]:
    """``company -> band slug -> cell`` for every company with a guide ladder.
    Companies with none are omitted; the scope catalog shows a few of these."""
    out: dict[str, dict[str, dict]] = {}
    for slug, record in COMPANIES.items():
        if any(ladder.guide for ladder in record.ladders):
            out[slug] = walk_guide(slug)
    return out


def duplicate_spellings(record: CompanyLevels) -> list[str]:
    """Spellings that name two rungs of one ladder. Must be empty: a rung is
    stated once, and a shared spelling would make a lookup's answer depend on
    list order. Two ladders of one company may share a grade code (Google's
    L8 on the row and on the IC ladder): `rung_for_code` names the ladder."""
    problems: list[str] = []
    for ladder in record.ladders:
        owner: dict[str, str] = {}
        for rung in ladder.rungs:
            for spelling in rung.spellings:
                key = f"{ladder.family}/{rung.code}"
                if spelling in owner and owner[spelling] != key:
                    problems.append(f"{record.slug}: {spelling!r} names {owner[spelling]} and {key}")
                owner.setdefault(spelling, key)
    return problems


def senior_unconfirmed(company: str) -> bool:
    """Whether a bare "Senior" in this company's titles stays unconfirmed: the
    atlas's `companies.senior_unconfirmed`, own row then parent's."""
    return any(record.senior_unconfirmed for record in _lineage(company))
