"""The outside sources the core must never name, for the scans that look for them.

A scan has to spell what it looks for, and then its own file is a hit. So the
names are assembled from parts here: this file, and every test that imports it,
reads as clean to the same scans (`tests/test_release_gate.py`,
`tests/test_level_atlas.py`). `planted` builds a sample a scan must catch.
"""

from __future__ import annotations

import re

_LEVELS = "levels"
_FYI = "fyi"
_BLIND = "bl" + "ind"

#: Content: a vendor's name or domain anywhere in text,
#: including the spelling a regular expression escapes it to.
CONTENT = re.compile("|".join((
    _LEVELS + r"\\*\." + _FYI,
    _LEVELS + _FYI,
    "team" + _BLIND,
    _BLIND + "_20",
)), re.I)

#: Paths: a tracked file whose name names a vendor.
PATH = re.compile(_BLIND + "|" + _LEVELS + "_?" + _FYI, re.I)

#: Identifiers: the vendor's name as a word or an identifier part. English
#: uses the word too, so `vendor_word` decides which hits are the vendor.
IDENTIFIER = re.compile(r"\b" + _BLIND + r"\b|\b" + _BLIND.upper() + r"_\w*|" + _LEVELS + r"[-_]" + _FYI, re.I)


def vendor_word(line: str, match: re.Match[str]) -> bool:
    """Whether an identifier hit names the vendor rather than the English word:
    a capitalised name, a quoted value, a possessive, a constant, or the levels
    identifier. The lowercase word in "... to it", "... spot" or "location-..."
    is English; a sentence that opens on the English word is rare enough to list."""
    word = match.group(0)
    if word.lower() != _BLIND:
        return True
    before, after = line[: match.start()], line[match.end():]
    quoted = before[-1:] in ("'", '"', "`") and after[:1] in ("'", '"', "`")
    return quoted or after.startswith("'s") or word[0].isupper()


#: Other outside pay sources the bundled dataset must not name either.
OTHERS = ("glass" + "door", "fish" + "bowl")


def planted(kind: str) -> str:
    """A sample line each scan must catch."""
    return {
        "content": "read on " + _LEVELS + "." + _FYI,
        "path": "scripts/import_" + _BLIND + ".py",
        "identifier": "a " + _BLIND.title() + " thread",
        "quoted": 'source="' + _BLIND + '"',
        "english": "the scan went " + _BLIND + " to it",
    }[kind]
