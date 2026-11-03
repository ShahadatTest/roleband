"""Versioned extraction engine + sanitizer.

The engine is selectolax. The RoleBand-owned sanitizer keeps
hidden/scripted/zero-width text out of model-facing output, and
`EXTRACTOR_VERSION` ensures a recipe document is never interpreted by an
unversioned engine.

There is no adaptive (`relocate`-style) element scorer: it is DOM-only and
needs XPath, which selectolax lacks, and a second parser is not worth adding
just to support it.
"""

from __future__ import annotations

from tracker.connectors.extract.sanitize import sanitize_html, visible_text
from tracker.connectors.extract.version import (
    EXTRACTOR_VERSION,
    PARSER_ID,
    extractor_fingerprint,
)

__all__ = [
    "EXTRACTOR_VERSION",
    "PARSER_ID",
    "extractor_fingerprint",
    "sanitize_html",
    "visible_text",
]
