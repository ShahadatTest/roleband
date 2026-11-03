"""Admit explicitly reviewed source targets without copying classifier verdicts."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from tracker.analytics.level_evaluation import LabelTier, independent_label, usable_base
from tracker.levels.ladder import printed_field
from tracker.schema import LEVEL_BAND_ORDER, RoleTrack
from tracker.taxonomy.roles import all_slugs
from tracker.taxonomy.stated_level import stated_rungs

SOURCE_FIELDS = ("id", "company", "req_id", "title", "department", "team", "description_text",
                 "description_sections", "raw_level", "family", "track", "location_groups", "level_year",
                 "disclosed_base_min", "disclosed_base_max", "disclosed_currency", "disclosed_pay_basis",
                 "disclosed_pay_period", "disclosed_confidence", "disclosed_source")
_LEADERSHIP = re.compile(r"\b(?:director|vice[- ]president|head of|chief .{0,60} officer)\b|\b(?:svp|evp|vp)\b", re.I)
_EXCLUDED_FAMILIES = {"engineering_management", "sales_business_development", "solutions_sales_eng", "customer_success"}


def source_fingerprint(row: Mapping[str, Any]) -> str:
    """Bind captured source and eligibility facts; derived level guesses are absent."""
    source = {key: row.get(key) for key in SOURCE_FIELDS}
    return hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _human(record: Mapping[str, Any]) -> None:
    if (record.get("method") != "human" or not isinstance(record.get("reviewer"), str)
            or not record["reviewer"].strip() or not isinstance(record.get("reason"), str) or not record["reason"].strip()):
        raise ValueError("explicit human reviewer and reason required")


def _quote(content: str, span: Mapping[str, Any]) -> str:
    start, end, quote = (span.get(key) for key in ("start", "end", "quote"))
    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(content)
            or content[start:end] != quote):
        raise ValueError("review quote does not ground in source")
    return str(quote)


def _source_quote(row: Mapping[str, Any], span: Mapping[str, Any]) -> str:
    field = span.get("field")
    if field not in {"title", "description_text"} or not isinstance(row.get(field), str):
        raise ValueError("quote requires a captured source field")
    return _quote(row[field], span)


def _unique(records: Sequence[Mapping[str, Any]], keys: tuple[str, ...]) -> dict[tuple[Any, ...], Mapping[str, Any]]:
    result = {}
    for record in records:
        key = tuple(record.get(k) for k in keys)
        if any(v is None or isinstance(v, (dict, list)) for v in key) or key in result:
            raise ValueError("missing or duplicate review identity")
        if record.get("status") not in {"pending", "approve", "exclude"}:
            raise ValueError("explicit pending, approve or exclude status required")
        result[key] = record
    return result


def _codes(row: Mapping[str, Any], evidence: Mapping[str, Any]) -> tuple[str, list[str]]:
    raw = row.get("raw_level")
    text_codes = stated_rungs(str(row["company"]), row.get("description_text"))
    raw_codes = [s.strip() for s in raw.split("/") if s.strip()] if isinstance(raw, str) and raw.strip() else []
    if raw_codes and text_codes and set(raw_codes) != set(text_codes):
        raise ValueError("structured and description grade evidence disagree")
    if evidence.get("kind") == "structured_field":
        field = printed_field(str(row["company"]))
        if not raw_codes or field is None or evidence.get("field") != field or evidence.get("value") != raw:
            raise ValueError("structured grade does not match its captured source field")
        return "A", list(dict.fromkeys(raw_codes))
    if evidence.get("kind") == "description_grade":
        spans = evidence.get("spans")
        if not isinstance(spans, list) or not spans or not text_codes:
            raise ValueError("complete description grade evidence required")
        observed = {code for span in spans for code in stated_rungs(str(row["company"]), _source_quote(row, span))}
        if observed != set(text_codes):
            raise ValueError("description grade evidence omits stated alternatives")
        return "A", text_codes
    if evidence.get("kind") == "company_vocabulary":
        label = independent_label(row)
        phrase = evidence.get("phrase")
        if (label is None or label.tier is not LabelTier.COMPANY or raw_codes or text_codes
                or not isinstance(phrase, str) or not phrase.strip()):
            raise ValueError("independently reviewed company vocabulary required")
        if evidence.get("field") != "title" or phrase.casefold() not in _source_quote(row, evidence).casefold():
            raise ValueError("company vocabulary does not ground in title")
        return "B", ["title:" + " ".join(phrase.casefold().split())]
    raise ValueError("employer-grade or independently reviewed company vocabulary source required")


def _mapping(record: Mapping[str, Any], documents: Mapping[str, str], tier: str) -> str:
    _human(record)
    expected_basis = "employer_ladder" if tier == "A" else "independently_reviewed_vocabulary"
    if record.get("basis") != expected_basis:
        raise ValueError("independent mapping basis required; salary and model labels are excluded")
    digest = record.get("document_sha256")
    if not isinstance(digest, str) or digest not in documents:
        raise ValueError("frozen mapping document required")
    quote = _quote(documents[digest], record["evidence"])
    code = str(record["code"])
    token = code.removeprefix("title:")
    if re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", quote, re.I) is None:
        raise ValueError("mapping quote does not name its code or vocabulary")
    if record.get("band") not in LEVEL_BAND_ORDER:
        raise ValueError("mapping requires a permissible band")
    if (not isinstance(record.get("allowed_families"), list) or not record["allowed_families"]
            or not isinstance(record.get("allowed_tracks"), list) or not record["allowed_tracks"]
            or any(f not in all_slugs() for f in record["allowed_families"])
            or any(t not in {track.value for track in RoleTrack} for t in record["allowed_tracks"])):
        raise ValueError("mapping requires explicit role scope")
    return str(record["band"])


def compile_sources(rows: Sequence[Mapping[str, Any]], reviews: Sequence[Mapping[str, Any]], *,
                    mappings: Sequence[Mapping[str, Any]], documents: Mapping[str, str], groups: Mapping[int, str],
                    group_reviews: Sequence[Mapping[str, Any]], multi_level: str) -> dict[str, Any]:
    """Compile approved evidence while preserving exclusions and permissible sets.

    Review declarations and exact source links are verified, not the identity of
    a human or the semantic correctness of their mapping judgment. Admission
    cannot replace the study's separate grouping, sampling and evaluation gates.
    """
    if multi_level not in {"exclude", "preserve"}:
        raise ValueError("explicit multi-level policy required")
    index = {}
    members: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        job_id = row.get("id")
        if type(job_id) is not int or job_id in index or not isinstance(groups.get(job_id), str) or not groups[job_id]:
            raise ValueError("unique source identities and complete frozen groups required")
        index[job_id] = row
        members[groups[job_id]].add(job_id)
    for digest, text in documents.items():
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError("mapping document fingerprint changed")
    source_reviews = _unique(reviews, ("id",))
    mapping_reviews = _unique(mappings, ("company", "code"))
    group_decisions = _unique(group_reviews, ("group",))
    targets = []
    decisions = []
    for (job_id,), review in source_reviews.items():
        if type(job_id) is not int or job_id not in index:
            raise ValueError("review names an unknown frozen source")
        row = index[job_id]
        fingerprint = source_fingerprint(row)
        if review.get("source_sha256") != fingerprint:
            raise ValueError("source review fingerprint changed")
        reason = "pending source review"
        if review["status"] != "pending":
            _human(review)
            reason = "source excluded by reviewer"
        if review["status"] == "approve":
            role = review.get("role")
            if (not isinstance(role, dict) or role.get("family") not in all_slugs()
                    or role.get("track") not in {t.value for t in RoleTrack}):
                raise ValueError("reviewed family and track required")
            _source_quote(row, review["role_evidence"])
            if (role["track"] not in {"technical", "product_program"} or role["family"] in _EXCLUDED_FAMILIES
                    or _LEADERSHIP.search(str(row.get("title") or ""))):
                reason = "role outside initial study scope"
            elif role != {"family": row.get("family"), "track": row.get("track")}:
                reason = "reviewed role differs from frozen classification"
            elif not usable_base(row):
                reason = "ineligible frozen compensation"
            else:
                tier, codes = _codes(row, review["grade_evidence"])
                selected_mappings = [mapping_reviews.get((row["company"], code)) for code in codes]
                if any(m is None or m["status"] != "approve" for m in selected_mappings):
                    reason = "unreviewed mapping"
                else:
                    approved = [m for m in selected_mappings if m is not None]
                    bands = sorted({_mapping(m, documents, tier) for m in approved}, key=LEVEL_BAND_ORDER.__getitem__)
                    stated = review.get("permissible_bands")
                    if not isinstance(stated, list) or len(stated) != len(set(stated)) or set(stated) != set(bands):
                        raise ValueError("permissible bands do not preserve all reviewed grade alternatives")
                    if any(role["family"] not in m["allowed_families"] or role["track"] not in m["allowed_tracks"] for m in approved):
                        reason = "mapping outside reviewed role scope"
                    elif len(codes) > 1 and multi_level == "exclude":
                        reason = "multi-level source excluded by policy"
                    else:
                        group = groups[job_id]
                        group_review = group_decisions.get((group,))
                        reason = "unreviewed source group"
                        if group_review is not None and group_review["status"] == "approve":
                            _human(group_review)
                            ids = group_review.get("members")
                            if not isinstance(ids, list) or any(type(i) is not int for i in ids) or len(set(ids)) != len(ids) or set(ids) != members[group]:
                                raise ValueError("source group membership changed")
                            expected = {str(i): source_fingerprint(index[i]) for i in ids}
                            if group_review.get("source_sha256") != expected:
                                raise ValueError("source group fingerprint changed")
                            role_keys = {(index[i].get("company"), index[i].get("family"), index[i].get("track")) for i in ids}
                            if len(role_keys) != 1:
                                reason = "source group has incompatible frozen roles"
                            else:
                                targets.append({"id": job_id, "company": row["company"], "tier": tier,
                                                "codes": codes, "bands": bands, "primary_single_band": len(bands) == 1,
                                                "family": role["family"], "track": role["track"], "group": group,
                                                "source_sha256": fingerprint, "mapping_documents": [m["document_sha256"] for m in approved],
                                                "source_capture": "normalized field" if review["grade_evidence"]["kind"] == "structured_field" else "quoted text"})
                                reason = "admitted"
        decisions.append({"id": job_id, "reason": reason})
    counts = Counter(d["reason"] for d in decisions)
    return {"targets": targets, "decisions": decisions, "multi_level_policy": multi_level,
            "counts": {"submitted": len(reviews), "reviewed": sum(r["status"] != "pending" for r in reviews),
                       "admitted": len(targets), "single_band": sum(t["primary_single_band"] for t in targets),
                       "by_reason": dict(counts)},
            "authority": "reviewed source targets only; no study or promotion gate implied"}
