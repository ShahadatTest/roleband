"""Apple job-detail add-on: strict API schema plus schema-drift failover."""

from __future__ import annotations

from collections.abc import Iterator, Mapping

from tracker.connectors.detail.base import (
    PAY_SECTION_KEY,
    DetailParseResult,
    HtmlDetailConnector,
    clean_section,
    section_key,
    sections_to_text,
    source_disclosed_comp_from_text,
)
from tracker.schema import JobDescriptionSection

_CORE_FIELDS = (
    ("jobSummary", "summary", "Summary"),
    ("description", "description", "Description"),
    ("minimumQualifications", "minimum_qualifications", "Minimum Qualifications"),
    ("preferredQualifications", "preferred_qualifications", "Preferred Qualifications"),
)
_FALLBACK_ALIASES = {
    "jobsummary": ("summary", "Summary"),
    "summary": ("summary", "Summary"),
    "description": ("description", "Description"),
    "responsibilities": ("description", "Description"),
    "minimumqualifications": ("minimum_qualifications", "Minimum Qualifications"),
    "keyqualifications": ("minimum_qualifications", "Minimum Qualifications"),
    "preferredqualifications": ("preferred_qualifications", "Preferred Qualifications"),
    "payandbenefits": (PAY_SECTION_KEY, "Pay & Benefits"),
    "compensationandbenefits": (PAY_SECTION_KEY, "Pay & Benefits"),
}


def _normalized_key(value: object) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _dedupe(sections: list[JobDescriptionSection]) -> list[JobDescriptionSection]:
    seen: set[tuple[str, str]] = set()
    result = []
    for section in sections:
        marker = (section.key, section.content)
        if marker not in seen:
            seen.add(marker)
            result.append(section)
    return result


def _walk_mappings(value: object) -> Iterator[Mapping]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_mappings(child)


class AppleDetailConnector(HtmlDetailConnector):
    """Parse Apple's `jobDetails` JSON without coupling it to persistence/UI."""

    source = "apple"
    pay_from_text = True

    def parse_payload(
        self, payload: object, raw_html: str | None = None
    ) -> DetailParseResult:
        if isinstance(payload, Mapping) and isinstance(payload.get("res"), Mapping):
            res = payload["res"]
            sections = self._core_sections(res)
            footer_sections, footer_valid = self._footer_sections(res)
            if sections and footer_valid:
                result_sections = _dedupe([*sections, *footer_sections])
                return DetailParseResult(
                    result_sections,
                    source_disclosed_comp=_source_comp_from_sections(result_sections),
                )
            reason = "postingFooters schema changed" if sections else "core detail fields missing"
        else:
            reason = "detail envelope missing res object"

        sections = _dedupe(self._failover_sections(payload))
        core_keys = {spec[1] for spec in _CORE_FIELDS}
        # A failover that only recovers core text cannot prove footer content was
        # retained. Mark it incomplete so persistence preserves older full data.
        recovered_footer = any(section.key not in core_keys for section in sections)
        return DetailParseResult(
            sections,
            mode="failover",
            reason=reason,
            complete=recovered_footer,
            source_disclosed_comp=_source_comp_from_sections(sections),
        )

    def _core_sections(self, res: Mapping) -> list[JobDescriptionSection]:
        sections = []
        for field, key, title in _CORE_FIELDS:
            section = clean_section(key, title, res.get(field))
            if section:
                sections.append(section)
        return sections

    def _footer_sections(self, res: Mapping) -> tuple[list[JobDescriptionSection], bool]:
        footers = res.get("postingFooters")
        if footers is None:
            return [], False
        if not isinstance(footers, list):
            return [], False

        locale = str(res.get("selectedLocale") or "en_US")
        sections: list[JobDescriptionSection] = []
        had_footer_entries = bool(footers)
        for footer in footers:
            if not isinstance(footer, Mapping):
                continue
            localizations = footer.get("localizations")
            if not isinstance(localizations, Mapping):
                continue
            localized = localizations.get(locale) or localizations.get("en_US")
            if localized is None and localizations:
                localized = next(iter(localizations.values()))
            if not isinstance(localized, list):
                continue
            ordered = sorted(
                (item for item in localized if isinstance(item, Mapping)),
                key=lambda item: item.get("displayOrder") if isinstance(item.get("displayOrder"), int) else 999,
            )
            for item in ordered:
                title = str(item.get("name") or item.get("label") or "Additional information")
                section = clean_section(section_key(title), title, item.get("content"))
                if section:
                    sections.append(section)
        return sections, not had_footer_entries or bool(sections)

    def _failover_sections(self, payload: object) -> list[JobDescriptionSection]:
        sections: list[JobDescriptionSection] = []
        # Recover known semantic fields at any nesting depth. This survives a
        # renamed envelope or fields moving into localization objects.
        for mapping in _walk_mappings(payload):
            for raw_key, value in mapping.items():
                alias = _FALLBACK_ALIASES.get(_normalized_key(raw_key))
                if alias and isinstance(value, str):
                    section = clean_section(alias[0], alias[1], value)
                    if section:
                        sections.append(section)

            # Footer-like objects remain recoverable even if Apple renames the
            # postingFooters/localizations containers.
            title = mapping.get("name") or mapping.get("label") or mapping.get("title")
            content = mapping.get("content") or mapping.get("body") or mapping.get("text")
            if isinstance(title, str) and isinstance(content, str):
                section = clean_section(section_key(title), title, content)
                if section:
                    sections.append(section)
        return sections


def _source_comp_from_sections(sections: list[JobDescriptionSection]):
    full_text = sections_to_text(sections)
    for section in sections:
        if section.key == PAY_SECTION_KEY:
            return source_disclosed_comp_from_text(section.content, full_text)
    return None
