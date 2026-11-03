"""HTML sanitizer for model-facing text.

Ports the *behavior* of Scrapling's private ``Convertor._sanitize_for_ai`` onto
selectolax, the extraction engine. It is a reimplementation, not an import:
Scrapling's ``[ai]`` extra is never installed in the backend venv, and no
Scrapling type is referenced.

Derives from Scrapling (BSD-3-Clause), D4Vinci/Scrapling, ``_sanitize_for_ai``
and ``_HIDDEN_XPATH`` on ``Convertor`` in ``scrapling/core/shell.py`` @ v0.4.11.
The extended hidden-element rules below are RoleBand additions that cover
gaps in upstream's.

That origin is pinned by hash in `tracker.vendored`, and
`scripts.check_vendored_upstream` is what answers "has upstream moved?".

Trust posture: the sanitizer is defense in depth, NOT a trust
boundary. Scraped text stays untrusted evidence regardless. Its job is narrow
and testable: keep hidden / off-screen / zero-width / scripted text OUT of what
a model reads, without dropping visible content.
"""

from __future__ import annotations

import re

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

__all__ = ["sanitize_html", "visible_text"]

#: Structural noise removed wholesale: never user-visible job content.
_NOISE_TAGS = (
    "script",
    "style",
    "template",
    "noscript",
    "svg",
    "head",
    "meta",
    "link",
    "iframe",
    "object",
    "embed",
)

#: Class-name hints for accessibility/off-screen hiding. Substring match: real
#: sites use `visually-hidden`, `sr-only`, `screen-reader-text`, `a11y-hidden`.
_HIDDEN_CLASS_HINTS = (
    "visually-hidden",
    "visuallyhidden",
    "sr-only",
    "screen-reader",
    "screenreader",
    "offscreen",
    "off-screen",
    "a11y-hidden",
    "hidden-accessible",
)

#: Inline-style patterns that hide content. RoleBand extends the upstream set
#: (which missed off-screen positioning, text-indent, clip-path, opacity).
_HIDDEN_STYLE_MARKERS = (
    "display:none",
    "visibility:hidden",
    "visibility:collapse",
    "opacity:0",
    "left:-9999px",
    "left:-999em",
    "left:-10000px",
    "right:-9999px",
    "top:-9999px",
    "text-indent:-9999px",
    "text-indent:-999em",
    "clip-path:inset(100%)",
    "clip:rect(0,0,0,0)",
    "clip:rect(1px,1px,1px,1px)",
    "font-size:0",
    "width:0",
    "height:0",
    "max-height:0",
)

#: Zero-width and bidi-control characters used to smuggle instructions past a
#: human reader while staying "visible" text to a parser.
_ZERO_WIDTH_RE = re.compile(r"[​-‏‪-‮⁠-⁤﻿]")

_WS_RE = re.compile(r"\s+")


def _style_hides(style: str) -> bool:
    compact = style.lower().replace(" ", "").replace("!important", "")
    return any(marker in compact for marker in _HIDDEN_STYLE_MARKERS)


def _class_hides(class_attr: str) -> bool:
    lowered = class_attr.lower()
    return any(hint in lowered for hint in _HIDDEN_CLASS_HINTS)


def _node_is_hidden(node: Node) -> bool:
    attrs = node.attributes
    if attrs is None:
        return False
    if "hidden" in attrs:
        return True
    if attrs.get("aria-hidden") == "true":
        return True
    cls = attrs.get("class")
    if cls and _class_hides(cls):
        return True
    style = attrs.get("style")
    return bool(style and _style_hides(style))


def _strip(tree: HTMLParser) -> None:
    """Remove noise tags and every hidden element in place."""
    noise = tree.css(",".join(_NOISE_TAGS))
    for node in noise:
        node.decompose()
    # One pass over remaining elements; decomposing a parent takes its subtree,
    # and selectolax tolerates decomposing an already-detached node.
    for node in tree.css("*"):
        if _node_is_hidden(node):
            node.decompose()


def visible_text(html: str) -> str:
    """Model-facing plain text: hidden/scripted/zero-width content removed."""
    if not html:
        return ""
    tree = HTMLParser(html)
    _strip(tree)
    root = tree.body or tree
    raw = root.text(separator=" ", strip=True) if root is not None else ""
    without_zero_width = _ZERO_WIDTH_RE.sub("", raw)
    return _WS_RE.sub(" ", without_zero_width).strip()


def sanitize_html(html: str) -> str:
    """Cleaned HTML fragment (noise + hidden elements removed), for callers that
    need structure rather than flat text. Zero-width chars are stripped from the
    serialized output too."""
    if not html:
        return ""
    tree = HTMLParser(html)
    _strip(tree)
    root = tree.body or tree
    if root is None:
        return ""
    serialized = root.html or ""
    return _ZERO_WIDTH_RE.sub("", serialized)
