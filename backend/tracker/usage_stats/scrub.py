"""A crash, reduced to what can be sent: its type and where in our code it was.

An exception's message, its arguments, local variables and file paths can all
hold the user's data (a company in a scrape error, a home directory in a path),
so none of them survive: the shape is the exception's class, the chain of
classes that led to it, and the frames in RoleBand's own code as
module + function + line, which are code, never data. Frames outside `tracker`
(the standard library, httpx, SQLAlchemy) are dropped rather than reduced: a
third-party frame names a file under the user's home directory.

Some of our own code is named after an employer: the connectors for a company's
own careers site (`connectors/listing/amazon.py`, `connectors/detail/openai.py`)
and functions that handle one company's data. A crash there would tell which
employer the user follows, so such a frame keeps its place in the stack but not
its name: module `tracker.connectors.listing.single_company`, function
`single_company`. An exception class defined there, or named after an employer,
is reduced the same way wherever it appears, as the crash's type or in its
chain. The words are every connector module that is not a job-site
family (`registry.family_of`), read from the file names, so a new company
connector is covered the day it lands.
"""

from __future__ import annotations

import hashlib
import re
import traceback
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from tracker.usage_stats.registry import SINGLE_COMPANY, family_of

#: The innermost frames kept; a deeper stack keeps its last ones (where it broke).
MAX_FRAMES = 30
MAX_CHAIN = 5

_TYPE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,120}")
_MODULE = re.compile(r"tracker(?:\.[A-Za-z_][A-Za-z0-9_]*){0,12}")
_FUNCTION = re.compile(r"[A-Za-z0-9_<>.]{1,120}")

_CONNECTORS = Path(__file__).resolve().parents[1] / "connectors"
#: Connector modules that serve every company, never one.
_GENERIC_CONNECTORS = frozenset({"__init__", "base", "recipe_adapter", "sitemap_board"})


def _company_words() -> frozenset[str]:
    names = {path.stem for kind in ("listing", "detail") for path in (_CONNECTORS / kind).glob("*.py")}
    return frozenset(
        name for name in names - _GENERIC_CONNECTORS if family_of(name) == SINGLE_COMPANY
    )


#: Words that name one employer in our own code (see the module docstring).
COMPANY_WORDS = _company_words()


def _words(name: str) -> list[str]:
    """The words of a code name, lowercased: `amazon_detail` and `AmazonBlocked`
    both start with `amazon`."""
    return [word.lower() for word in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+", name)]


def _unnamed(module: str, function: str) -> tuple[str, str]:
    """`module`/`function` with any employer's name taken out. `function` may
    also be a class's qualified name."""
    head, _, last = module.rpartition(".")
    if head.startswith("tracker.connectors.") and last in COMPANY_WORDS:
        module = f"{head}.{SINGLE_COMPANY}"
        function = SINGLE_COMPANY
    if any(word in COMPANY_WORDS for word in _words(function)):
        function = SINGLE_COMPANY
    return module, function


@dataclass(frozen=True)
class Frame:
    module: str
    function: str
    lineno: int


@dataclass(frozen=True)
class Shape:
    type: str
    frames: tuple[Frame, ...]
    chain: tuple[str, ...]
    handled: bool

    def fingerprint(self) -> str:
        """Groups the same crash across days and installs: its type and the
        innermost frame of ours."""
        top = self.frames[-1] if self.frames else None
        where = f"{top.module}:{top.function}" if top else "-"
        return hashlib.sha256(f"{self.type}|{where}".encode()).hexdigest()[:32]


def _type_name(cls: type) -> str:
    module = getattr(cls, "__module__", "") or ""
    module, name = _unnamed(module, getattr(cls, "__qualname__", cls.__name__))
    return name if module in ("builtins", "") else f"{module}.{name}"


def scrub(exc: BaseException, *, handled: bool = False) -> Shape:
    frames: list[Frame] = []
    for frame, lineno in traceback.walk_tb(exc.__traceback__):
        module = frame.f_globals.get("__name__")
        if isinstance(module, str) and _MODULE.fullmatch(module):
            kept_module, function = _unnamed(module, frame.f_code.co_name)
            frames.append(Frame(module=kept_module, function=function, lineno=int(lineno or 0)))
    chain: list[str] = []
    seen: set[int] = {id(exc)}
    cause = exc.__cause__ or exc.__context__
    while cause is not None and len(chain) < MAX_CHAIN and id(cause) not in seen:
        seen.add(id(cause))
        chain.append(_type_name(type(cause)))
        cause = cause.__cause__ or cause.__context__
    return Shape(
        type=_type_name(type(exc)),
        frames=tuple(frames[-MAX_FRAMES:]),
        chain=tuple(chain),
        handled=handled,
    )


def to_props(shape: Shape) -> dict[str, object]:
    """The stored form (an outbox row's `props["exception"]`)."""
    return {
        "type": shape.type,
        "frames": [[frame.module, frame.function, frame.lineno] for frame in shape.frames],
        "chain": list(shape.chain),
        "handled": shape.handled,
    }


def validate_stored(stored: object) -> Shape:
    """The stored form back as a `Shape`; raises ValueError for anything that
    is not exactly what `to_props` writes (so a row written another way, with a
    message in it, cannot be sent)."""
    if not isinstance(stored, Mapping) or set(stored) != {"type", "frames", "chain", "handled"}:
        raise ValueError("not a scrubbed exception")
    type_, frames, chain, handled = stored["type"], stored["frames"], stored["chain"], stored["handled"]
    if not (isinstance(type_, str) and _TYPE.fullmatch(type_)):
        raise ValueError("exception type is not a class name")
    if not isinstance(handled, bool) or not isinstance(chain, list) or not isinstance(frames, list):
        raise ValueError("malformed scrubbed exception")
    if len(frames) > MAX_FRAMES or len(chain) > MAX_CHAIN:
        raise ValueError("scrubbed exception is too long")
    parsed: list[Frame] = []
    for item in frames:
        if not (isinstance(item, list) and len(item) == 3):
            raise ValueError("malformed frame")
        module, function, lineno = item
        if not (isinstance(module, str) and _MODULE.fullmatch(module)):
            raise ValueError("frame outside tracker")
        if not (isinstance(function, str) and _FUNCTION.fullmatch(function)):
            raise ValueError("frame function is not a name")
        if not (isinstance(lineno, int) and not isinstance(lineno, bool) and 0 <= lineno < 1_000_000):
            raise ValueError("frame line is not a number")
        parsed.append(Frame(module, function, lineno))
    for name in chain:
        if not (isinstance(name, str) and _TYPE.fullmatch(name)):
            raise ValueError("chained type is not a class name")
    return Shape(type=type_, frames=tuple(parsed), chain=tuple(chain), handled=handled)


def exception_list(shape: Shape) -> list[dict[str, object]]:
    """The sent `$exception_list`: one entry, no `value` (no message), raw frames."""
    return [
        {
            "type": shape.type,
            "mechanism": {"handled": shape.handled, "synthetic": False},
            "stacktrace": {
                "type": "raw",
                "frames": [
                    {
                        "platform": "custom",
                        "lang": "python",
                        "module": frame.module,
                        "function": frame.function,
                        "filename": frame.module.replace(".", "/") + ".py",
                        "lineno": frame.lineno,
                        "in_app": True,
                    }
                    for frame in shape.frames
                ],
            },
        }
    ]
