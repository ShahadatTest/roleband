"""Extractor versioning.

A versioned document read by an unversioned interpreter is unsafe. A recipe that
says `css: h2, text: true` changes meaning when parser normalization or
sanitizer rules change, without the recipe itself changing. `EXTRACTOR_VERSION`
is the interpreter's version: bump it on ANY output-affecting change to parsing,
sanitization, or text extraction, so a recipe revision validated under an older
extractor is visibly stale and gets mechanically revalidated.
"""

from __future__ import annotations

import selectolax

__all__ = ["EXTRACTOR_VERSION", "PARSER_ID", "extractor_fingerprint", "validation_is_current"]

#: RoleBand-owned integer. Bump on any change that can alter extracted output:
#: a new hidden-element rule, a whitespace-collapsing change, an engine swap.
EXTRACTOR_VERSION = 2

#: Engine identity recorded in each revision's validation record, so "validated
#: under selectolax 0.3.30" is auditable and an engine change is detectable
#: even within one EXTRACTOR_VERSION during migration windows.
PARSER_ID = f"selectolax.lexbor {selectolax.__version__}"


def validation_is_current(validation: dict | None) -> bool:
    record = validation or {}
    return bool(record.get("validated_at") and record.get("extractor_version") == EXTRACTOR_VERSION
                and record.get("parser") == PARSER_ID)


def extractor_fingerprint(*, adaptive_threshold: float | None = None) -> dict:
    """Validation-record stamp for a recipe revision.

    Stored on `ConnectorRecipeRevision.validation` so Settings can flag a
    revision validated below the current `EXTRACTOR_VERSION` as stale.
    """
    record = {"extractor_version": EXTRACTOR_VERSION, "parser": PARSER_ID}
    if adaptive_threshold is not None:
        record["adaptive_threshold"] = adaptive_threshold
    return record
