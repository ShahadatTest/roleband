"""Offline exact-range vocabulary transfer with independent opening support."""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from tracker.analytics.level_evaluation import (
    GroupInput,
    independent_label,
    leakage_groups,
    usable_base,
)
from tracker.enrich.level_mapper import read_level
from tracker.lineage.normalize import title_key
from tracker.schema import LevelBasis, RawJob


@dataclass(frozen=True)
class TemplateLink:
    left: int
    right: int
    similarity: float


def _shingles(text: str) -> frozenset[tuple[str, ...]]:
    text = re.sub(r"\b(?:IC|ICT|L|E|M|P|T)\d{1,2}\b|\b(?:level|grade|rung)\s*[:#-]?\s*\d+\b",
                  " ", text, flags=re.I)
    text = re.sub(r"\$\s*\d[\d,.]*(?:\s*[km])?|\b\d[\d,.]*(?:\s*[km])?\s*USD\b", " money ", text, flags=re.I)
    words = re.findall(r"\w+", text.casefold())
    if len(words) < 40:
        return frozenset()
    return frozenset(tuple(words[i:i + 3]) for i in range(len(words) - 2))


def independent_groups(inputs: Sequence[GroupInput]) -> tuple[dict[int, str], list[TemplateLink]]:
    """Extend identity links with conservative same-employer near-template links.

    Title overlap and text similarity bound candidate links, which still require
    source review. Every pair of title-token sets in a merged component must be
    nested, so a generic title cannot bridge distinct specialties. Missing or
    short descriptions cannot establish independence.
    Similar templates are counted together, even across distinct requisitions.
    """
    groups = leakage_groups(inputs)
    parent = {group: group for group in groups.values()}

    def root(group: str) -> str:
        while parent[group] != group:
            parent[group] = parent[parent[group]]
            group = parent[group]
        return group

    component_titles: dict[str, set[frozenset[str]]] = defaultdict(set)
    for row in inputs:
        tokens = frozenset(title_key(row.title).split())
        if tokens:
            component_titles[root(groups[row.job_id])].add(tokens)

    candidates: dict[tuple[str, tuple[str, ...]], set[int]] = defaultdict(set)
    shingles: dict[int, frozenset[tuple[str, ...]]] = {}
    titles: dict[int, set[str]] = {}
    links = []
    employer = None
    for row in sorted(inputs, key=lambda item: (item.company, item.job_id)):
        if row.company != employer:
            candidates.clear()
            shingles.clear()
            titles.clear()
            employer = row.company
        body = _shingles(row.description)
        title = set(title_key(row.title).split())
        shingles[row.job_id], titles[row.job_id] = body, title
        if not body or not title:
            continue
        possible: Counter[int] = Counter()
        for shingle in body:
            possible.update(candidates[(row.company, shingle)])
        for other, overlap in sorted(possible.items()):
            previous = shingles[other]
            if overlap * 100 < 85 * max(len(body), len(previous)):
                continue
            title_overlap = len(title & titles[other]) / len(title | titles[other])
            similarity = overlap / len(body | previous)
            if title_overlap < 0.6 or similarity < 0.85:
                continue
            a, b = root(groups[row.job_id]), root(groups[other])
            if any(not (left <= right or right <= left)
                   for left in component_titles[a] for right in component_titles[b]):
                continue
            if a != b:
                merged = component_titles[a] | component_titles[b]
                parent[max(a, b)] = min(a, b)
                component_titles[min(a, b)] = merged
            links.append(TemplateLink(other, row.job_id, round(similarity, 6)))
        for shingle in body:
            candidates[(row.company, shingle)].add(row.job_id)
    members: dict[str, list[int]] = defaultdict(list)
    for job_id, group in groups.items():
        members[root(group)].append(job_id)
    result = {job_id: hashlib.sha256(",".join(map(str, sorted(ids))).encode()).hexdigest()
              for ids in members.values() for job_id in ids}
    return result, links


def release_eligible(row: Mapping[str, object]) -> bool:
    return (usable_base(row) and bool(row.get("family"))
            and row.get("track") not in {None, "", "unknown", "management"}
            and row.get("family") != "sales_business_development")


def group_inputs(rows: Sequence[Mapping[str, object]]) -> list[GroupInput]:
    if any("description_text" not in row or "req_id" not in row for row in rows):
        raise ValueError("captured descriptions and requisition identities are required")
    result = []
    for row in rows:
        job_id = row.get("id")
        if not isinstance(job_id, int) or isinstance(job_id, bool):
            raise ValueError("integer job identity required")
        places = row.get("place_set_id")
        result.append(GroupInput(job_id, str(row["company"]), str(row.get("req_id") or ""),
                                 str(row.get("title") or ""), str(row.get("description_text") or ""),
                                 place_set_id=places if isinstance(places, int) else None))
    return result


def signature_key(row: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(row.get(key) for key in ("company", "family", "track", "level_year",
                                        "disclosed_base_min", "disclosed_base_max"))


def measure(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    groups, links = independent_groups(group_inputs(rows))
    cells: dict[tuple[object, ...], list[dict[str, object]]] = defaultdict(list)
    excluded: Counter[str] = Counter()
    for row in rows:
        if not release_eligible(row):
            excluded["ineligible pay, family or release slice"] += 1
            continue
        title = str(row.get("title") or "")
        printed = str(row.get("raw_level") or "")
        ambiguous = re.search(
            r"\b(?:senior|sr\.?|staff|principal)\s*(?:[&/]|and\b)\s*\w|"
            r"\b(?:staff|principal)\s*\+", title, re.I,
        )
        codes = re.findall(r"\b(?:IC|ICT|L|E|M|P|T)\d{1,2}\b", printed, re.I)
        if ambiguous or len(set(codes)) > 1:
            excluded["multi-level or open-ended title/grade"] += 1
            continue
        source_row = {key: value for key, value in row.items() if key != "independent_raw_level"}
        label = independent_label(source_row)
        if label is None:
            excluded["no independent unambiguous title or employer grade"] += 1
            continue
        if not isinstance(row.get("level_year"), int):
            raise ValueError("frozen evidence year required")
        job_id = label.job_id
        # An opening identity and sufficient context are required, even for a singleton.
        if not row.get("req_id") or not _shingles(str(row.get("description_text") or "")):
            excluded["missing opening identity or sufficient description"] += 1
            continue
        cells[signature_key(row)].append({
            "id": job_id, "title": label.title, "band": label.band.value,
            "tier": label.tier.value, "source": label.source, "printed": label.printed,
            "group": groups[job_id], "identity": " ".join(label.title.lower().split()),
        })
    signatures = []
    for key, anchors in sorted(cells.items(), key=lambda pair: str(pair[0])):
        # Both a shared opening/template and a repeated title collapse support.
        parent = {int(str(anchor["id"])): int(str(anchor["id"])) for anchor in anchors}

        def root(job_id: int, parent: dict[int, int] = parent) -> int:
            while parent[job_id] != job_id:
                job_id = parent[job_id]
            return job_id

        seen: dict[tuple[str, str], int] = {}
        for anchor in anchors:
            job_id = int(str(anchor["id"]))
            for field in ("group", "identity"):
                identity = (field, str(anchor[field]))
                if identity in seen:
                    a, b = root(job_id), root(seen[identity])
                    parent[max(a, b)] = min(a, b)
                else:
                    seen[identity] = job_id
        units: dict[int, set[str]] = defaultdict(set)
        for anchor in anchors:
            units[root(int(str(anchor["id"])))].add(str(anchor["band"]))
        votes = Counter(next(iter(bands)) for bands in units.values() if len(bands) == 1)
        conflict = any(len(bands) > 1 for bands in units.values())
        band, support = votes.most_common(1)[0] if votes else (None, 0)
        accepted = not conflict and len(units) >= 2 and support * 5 >= len(units) * 4
        signatures.append({
            "key": list(key), "band": band, "support": support, "units": len(units),
            "votes": dict(votes), "eligible": accepted,
            "reason": ("independent exact-range title vocabulary" if accepted else
                       "conflicting labels within an opening/template" if conflict else
                       "fewer than two independent anchors" if len(units) < 2 else
                       "less than four-fifths agreement"),
            "anchors": anchors,
        })
    return {"signatures": signatures, "groups": groups,
            "template_links": [asdict(link) for link in links], "excluded": dict(excluded)}


def assignment(row: Mapping[str, object], signature: Mapping[str, object] | None,
               groups: Mapping[int, str]) -> tuple[str | None, str]:
    """Keep explicit level authority and refuse self-supported transfer."""
    if not release_eligible(row):
        return None, "outside comparable pay or initial release slice"
    if signature is None or not signature.get("eligible"):
        return None, "no independent exact-range signature"
    raw = RawJob(company=str(row["company"]), req_id="", title=str(row["title"]), url="",
                 raw_level=str(row["raw_level"]) if row.get("raw_level") else None)
    reading = read_level(raw, str(row["family"]))
    label = independent_label(row)
    if reading.basis is LevelBasis.STATED or (label is not None and label.tier.value == "A"):
        return None, "protected employer-stated grade"
    if row.get("raw_level"):
        return None, "unmapped employer grade requires review"
    if reading.basis not in {LevelBasis.NONE, LevelBasis.UNMAPPED}:
        return None, "title already names a band"
    anchors = signature.get("anchors")
    assert isinstance(anchors, list)
    target_group = groups[int(str(row["id"]))]
    target_title = " ".join(str(row["title"]).lower().split())
    if any(a["group"] == target_group or a["identity"] == target_title for a in anchors):
        return None, "target shares opening, template or title with an anchor"
    if signature.get("key") != list(signature_key(row)):
        return None, "signature context mismatch"
    return str(signature["band"]), "independent exact-range title vocabulary transfer"
