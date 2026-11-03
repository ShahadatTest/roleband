"""Small shared helpers: HTML→text, date parsing, location tidying, text normalization,
URL query stripping, the host's local calendar day."""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import UTC, datetime
from urllib.parse import urlsplit

from dateutil import parser as date_parser

from tracker.platform.local_zone import local_zone

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_MULTINL_RE = re.compile(r"\n\s*\n\s*")

_ALLWS_RE = re.compile(r"\s+")
# Map the common unicode dashes/hyphens to ASCII '-' so "$210,000—$260,000"
# matches regardless of which dash the source used. U+2043 (hyphen bullet) is
# included because NFKC leaves it alone; U+FE63/U+FF0D need no entry — NFKC
# already folds them to '-'. This is THE dash table: search identity
# (`search/policy.exact_title_key`) delegates here, so a codepoint added in one
# place folds identically for every comparison in the product.
_DASHES = {ord(c): "-" for c in "‐‑‒–—―−﹘－⁃"}


def normalize_text(s: str | None) -> str:
    """NFKC + unify dashes + collapse whitespace + casefold.

    Symmetric normalization used on both sides of any text comparison (pay-span
    grounding, title matching), so "$210,000—$260,000" and "$210,000 - $260,000"
    compare equal regardless of dash or spacing.
    """
    s = unicodedata.normalize("NFKC", s or "")
    s = s.translate(_DASHES)
    s = _ALLWS_RE.sub(" ", s)
    return s.strip().lower()


def html_to_text(raw: str | None) -> str | None:
    """Strip tags and unescape entities into readable plain text.

    Unescape FIRST: some sources deliver HTML-escaped
    markup (``&lt;div&gt;``), so entities must be decoded before tag stripping or
    the tags survive as literal text.
    """
    if not raw:
        return None
    text = html.unescape(raw)
    # Preserve block boundaries as newlines before stripping tags.
    text = re.sub(r"(?i)<\s*(br|/p|/li|/div|/h[1-6])\s*/?>", "\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)  # second pass for entities revealed inside tags
    text = _WS_RE.sub(" ", text)
    text = _MULTINL_RE.sub("\n\n", text)
    return text.strip() or None


def parse_datetime(value) -> datetime | None:
    """Best-effort parse of an ISO / epoch / free-form timestamp into aware UTC."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            # Heuristic: ms vs s epoch.
            ts = float(value)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=UTC)
        dt = date_parser.parse(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except (ValueError, OverflowError, TypeError):
        return None


def clean_location(value: str | None) -> str | None:
    if not value:
        return None
    # Some sources write "City,State,Country" with no spaces after commas.
    s = re.sub(r",(?=\S)", ", ", value).strip()
    return s or None


def without_query(url: str) -> str:
    """`url` with its query string and fragment removed; scheme, host and path kept."""
    return urlsplit(url)._replace(query="", fragment="").geturl()


def describe_exception(exc: BaseException) -> str:
    """`Type: message`, with a stand-in when the exception carries no message.

    Several transport failures arrive empty. `httpcore` maps `anyio.EndOfStream`
    — a socket that returned EOF, which is what every connection open across a
    host suspension does on resume — onto `ReadError`, and `EndOfStream` has no
    args, so plain interpolation yields the bare string ``"ReadError: "``, which
    on the notification bell tells the reader nothing at all. The type name is the whole signal in that case, so say so rather
    than trailing a colon into nothing.
    """
    detail = str(exc).strip()
    return f"{type(exc).__name__}: {detail}" if detail else f"{type(exc).__name__} (no detail)"


def local_day_start_utc(
    now: datetime | None = None,
    local_tz=None,
) -> datetime:
    """Start of the user's local calendar day, represented in UTC for DB reads."""
    tz = local_tz or local_zone()
    current = (now or datetime.now(UTC)).astimezone(tz)
    return current.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


#: The widest date window a request may name, in days: ten years, wider than
#: anything stored, so a larger window means "all". A million days would
#: overflow `datetime` into a 500.
MAX_WINDOW_DAYS = 3650
