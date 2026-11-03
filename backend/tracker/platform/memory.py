"""How much memory this computer has: the one reader every sizing choice uses."""

from __future__ import annotations

import os

#: Below this much installed memory a computer is small: the embedding model
#: takes its small artifact and the database its Small preset, so the two
#: choices never disagree about the same computer.
SMALL_BELOW = 16 * 2**30


def total_memory_bytes() -> int | None:
    """Total physical RAM via POSIX sysconf (macOS + Linux). None on failure."""
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
        if page > 0 and pages > 0:
            return page * pages
    except (ValueError, OSError, AttributeError):
        pass
    return None
