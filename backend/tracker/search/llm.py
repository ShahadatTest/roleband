"""Optional LLM query understanding — enhances the local NL parser, never blocks it.

When `search_llm_enabled` is true, an Anthropic API key is configured and the user
has turned AI egress on, a single
tool-call to `search_llm_model` maps free text onto the same `ParsedQuery` fields the local
parser produces (company / level / family / workplace / location / comp bounds +
semantic remainder). It runs behind a hard timeout and a broad except: any failure
— disabled, keyless, slow, network error, malformed response — returns None so the
caller falls back to `parse_query`. Search must never break because of this layer.

Off by default. The Anthropic model handles the parse; validation happens against
our own taxonomy in `_coerce`, so a hallucinated company/level is dropped rather
than trusted. Uses `httpx`, not the Anthropic SDK.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Mapping

from tracker.config import get_settings
from tracker.platform.http import make_client
from tracker.schema import LevelBand, WorkplaceType
from tracker.search.parse import ParsedQuery, parse_query
from tracker.taxonomy.locations import search_vocabulary_slugs
from tracker.taxonomy.roles import ROLE_GROUPS

logger = logging.getLogger(__name__)

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"

# Enumerations the model must choose from, so it can't invent values. The
# companies are not here: the caller passes them per query (`companies`), the
# same set `parse_query` reads.
# Metros, regions and prominent countries, not every country. The enum is inlined
# into every structured-query prompt, so the long tail would cost tokens on
# every call to name markets a query will essentially never mention. Nothing is
# lost: `search/parse.py` matches every display name deterministically before
# the model is consulted. Tracked-vs-not is a runtime DB setting and `in_scope`
# filters downstream, so this stays an import-time superset of the tracked set.
_LOCATION_SLUGS = search_vocabulary_slugs()
# Every stage is first-class and searchable.
_LEVEL_VALUES = [b.value for b in LevelBand]
_FAMILY_SLUGS = [g.slug for g in ROLE_GROUPS]
_WORKPLACE_VALUES = [w.value for w in WorkplaceType if w is not WorkplaceType.UNKNOWN]


def _tool(company_slugs: list[str]) -> dict:
    """The tool the model must call. With no company to choose from, the
    company list must stay empty: an empty enum is not a schema every reader
    accepts."""
    company: dict = (
        {"type": "array", "items": {"type": "string", "enum": company_slugs}}
        if company_slugs
        else {"type": "array", "maxItems": 0}
    )
    return {
        "name": "structured_query",
        "description": "Return the structured filters and the remaining free-text search terms parsed from a job-search query.",
        "input_schema": {
            "type": "object",
            "properties": {
                "company": company,
                "level_band": {"type": "array", "items": {"type": "string", "enum": _LEVEL_VALUES}},
                "family": {"type": "array", "items": {"type": "string", "enum": _FAMILY_SLUGS}},
                "workplace_type": {"type": "array", "items": {"type": "string", "enum": _WORKPLACE_VALUES}},
                "location_group": {"type": "array", "items": {"type": "string", "enum": _LOCATION_SLUGS}},
                "comp_min": {"type": ["integer", "null"], "description": "Minimum yearly base salary in whole USD, or null."},
                "comp_max": {"type": ["integer", "null"], "description": "Maximum yearly base salary in whole USD, or null."},
                "remainder": {"type": "string", "description": "The query text with recognized filters removed: the semantic search terms."},
            },
            "required": ["company", "level_band", "family", "workplace_type", "location_group", "comp_min", "comp_max", "remainder"],
            "additionalProperties": False,
        },
    }


_SYSTEM = (
    "You parse a job-seeker's search query into structured filters plus a semantic "
    "remainder. Only assign a filter value when the query clearly implies it; leave "
    "arrays empty and comp bounds null otherwise. Choose enum values only from the "
    "provided lists. The remainder is the query text minus the recognized filters — "
    "the free-text terms to match semantically (skills, keywords). Always call the tool."
)


def _coerce(raw: dict, fallback_remainder: str, company_slugs: list[str]) -> ParsedQuery:
    """Validate the model's output against our taxonomy and the companies it
    was offered; drop anything unrecognized."""

    def pick(key: str, allowed: list[str]) -> list[str]:
        vals = raw.get(key) or []
        return [v for v in vals if isinstance(v, str) and v in allowed]

    comp_min = raw.get("comp_min")
    comp_max = raw.get("comp_max")
    remainder = raw.get("remainder")
    return ParsedQuery(
        company=pick("company", company_slugs),
        level_band=pick("level_band", _LEVEL_VALUES),
        family=pick("family", _FAMILY_SLUGS),
        workplace_type=pick("workplace_type", _WORKPLACE_VALUES),
        location_group=pick("location_group", _LOCATION_SLUGS),
        comp_min=comp_min if isinstance(comp_min, int) else None,
        comp_max=comp_max if isinstance(comp_max, int) else None,
        remainder=(remainder if isinstance(remainder, str) and remainder.strip() else fallback_remainder),
    )


async def llm_parse(
    text: str, *, egress_allowed: bool, companies: Mapping[str, Iterable[str]]
) -> ParsedQuery | None:
    """Parse `text` via the Anthropic API. Returns None (never raises) on any issue.

    `egress_allowed` is the user's AI egress switch (`get_ai_egress_enabled`).
    The query is the user's own text, so it leaves the machine only with that
    switch on, whatever the search settings say. `companies` is what
    `parse_query` takes: the model may choose only among its slugs.
    """
    settings = get_settings()
    if not egress_allowed or not settings.search_llm_enabled or not settings.anthropic_api_key:
        return None
    if not text or not text.strip():
        return None

    payload = {
        "model": settings.search_llm_model,
        "max_tokens": 512,
        "system": _SYSTEM,
        "tools": [_tool(list(companies))],
        "tool_choice": {"type": "tool", "name": "structured_query"},
        "messages": [{"role": "user", "content": text}],
    }
    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": _ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    try:
        async with make_client(timeout=settings.search_llm_timeout_seconds) as client:
            resp = await asyncio.wait_for(
                client.post(_ANTHROPIC_URL, json=payload, headers=headers),
                timeout=settings.search_llm_timeout_seconds,
            )
        resp.raise_for_status()
        data = resp.json()
        for block in data.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == "structured_query":
                # Fall back to the local parser's remainder if the model omitted one.
                fallback = parse_query(text, companies=companies).remainder
                return _coerce(block.get("input") or {}, fallback, list(companies))
        return None
    except Exception as exc:  # noqa: BLE001 — search must never break on the LLM path.
        logger.warning("llm_parse failed, falling back to local parser: %s", exc)
        return None


async def resolve_query(
    text: str, *, egress_allowed: bool, companies: Mapping[str, Iterable[str]]
) -> ParsedQuery:
    """Parse a query, preferring the LLM when enabled, else the local parser."""
    return (
        await llm_parse(text, egress_allowed=egress_allowed, companies=companies)
    ) or parse_query(text, companies=companies)
