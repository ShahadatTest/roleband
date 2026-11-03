"""Reduce captured listing fixtures to what their parsers read, and scrub them.

A captured page carries far more than its parser reads: page chrome, analytics,
other routes' loader data, translations. Some of it is not ours to commit (an
analytics container id, an ATS's user ids, the people on a hiring team), and
all of it is weight.

Two passes, both deterministic and idempotent (a second run changes nothing,
which `--check` asserts):

* **Reduce** (the fixtures named in `REDUCERS`): keep only what the parser
  reads, copied from the capture so the extraction shapes stay the source's.
  - SuccessFactors posting page: the JobPosting microdata properties (places,
    date, employer, title, description) inside their itemscope.
  - SuccessFactors results page: the result rows and the pagination label.
  - Shopify (React Router) pages: the turbo-stream table pruned to the one
    route the adapter reads, indices renumbered, shared values still shared,
    plus the posting links the page renders. Only the first stream line is
    kept, the one `extract.turbo_stream` reads.
* **Scrub** (every fixture under `tests/fixtures/listings`): a Google Tag
  Manager container id becomes `GTM-0000000` and a CSRF token header value the
  zero UUID. In a turbo-stream table, a record carrying an `email` is a person:
  its names and email become `Given`, `Family` and `person@example.com`, and
  its `id`/`userId` a placeholder numbered by first appearance
  (`00000000-0000-4000-8000-000000000001`, ...); an ATS job record's internal
  `title` becomes `Internal job title`. The originals are never written, not
  even as unreferenced table entries.

A reduced page is checked before it is written: its decoded route data must
equal the capture's except for the scrubbed person fields, so a reduction that
lost or changed anything the adapter reads refuses to write.

A fresh capture goes through the same command before it is committed:

    .venv/bin/python -m scripts.scrub_fixtures            # rewrite in place
    .venv/bin/python -m scripts.scrub_fixtures --check    # exit 1 if any would change
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from tracker.connectors.extract.turbo_stream import decode_turbo_stream

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "listings"

_GTM = re.compile(r"\bGTM-[A-Z0-9]{6,9}\b")
GTM_PLACEHOLDER = "GTM-0000000"
_CSRF = re.compile(r'(\\?"X-CSRF-Token\\?"\s*:\s*\\?")[^"\\]*(\\?")')
ZERO_UUID = "00000000-0000-0000-0000-000000000000"

_ENQUEUE = re.compile(r"streamController\.enqueue\((\"(?:[^\"\\]|\\.)*\")\);", re.S)
PERSON_NAMES = {"firstName": "Given", "lastName": "Family", "email": "person@example.com"}
PERSON_IDS = ("id", "userId")
INTERNAL_TITLE = "Internal job title"
_PERSON_ID = "00000000-0000-4000-8000-{:012d}"


def scrub_text(text: str) -> str:
    """The pass every fixture takes: analytics container ids and CSRF values."""
    text = _GTM.sub(GTM_PLACEHOLDER, text)
    return _CSRF.sub(lambda m: f"{m.group(1)}{ZERO_UUID}{m.group(2)}", text)


# --------------------------------------------------------------------------- #
# SuccessFactors
# --------------------------------------------------------------------------- #

_JOB_POSTING = '[itemscope][itemtype="http://schema.org/JobPosting"]'


def _own_scope(node: Node) -> Node | None:
    parent = node.parent
    while parent is not None and "itemscope" not in parent.attributes:
        parent = parent.parent
    return parent


def reduce_sf_detail(page: str) -> str:
    """The JobPosting itemscope with only its own properties, each verbatim."""
    scope = HTMLParser(page).css_first(_JOB_POSTING)
    if scope is None:
        raise ValueError("no JobPosting microdata on the page")
    props = [n.html or "" for n in scope.css("[itemprop]") if _own_scope(n) is not None
             and _own_scope(n).mem_id == scope.mem_id]
    if not props:
        raise ValueError("the JobPosting states no property")
    return (
        '<!DOCTYPE html>\n<html><body>\n<div itemscope="" itemtype="http://schema.org/JobPosting">\n'
        + "\n".join(props)
        + "\n</div>\n</body></html>\n"
    )


def reduce_sf_results(page: str) -> str:
    """The pagination label and the result rows, each verbatim."""
    tree = HTMLParser(page)
    label = tree.css_first(".paginationLabel")
    rows = [tr.html or "" for tr in tree.css("tr.data-row")]
    if label is None or not rows:
        raise ValueError("no pagination label or no result row")
    return (
        "<!DOCTYPE html>\n<html><body>\n"
        + (label.html or "")
        + '\n<table class="searchResults"><tbody>\n'
        + "\n".join(rows)
        + "\n</tbody></table>\n</body></html>\n"
    )


# --------------------------------------------------------------------------- #
# React Router (turbo-stream) pages
# --------------------------------------------------------------------------- #


def _stream_table(page: str) -> list:
    chunks = _ENQUEUE.findall(page)
    if not chunks:
        raise ValueError("no turbo-stream on the page")
    text = "".join(json.loads(chunk) for chunk in chunks)
    first = next(line for line in text.split("\n") if line.strip())
    table = json.loads(first)
    if not isinstance(table, list) or not table:
        raise ValueError("the stream's first line is not a table")
    return table


def prune_table(table: list, keep: dict) -> list:
    """The table reachable from the root along `keep`, renumbered.

    `keep` names, level by level, the keys to follow (`None`: everything
    below). A shared value stays one entry; a tagged value is copied as it
    stands. A person record's names, email and ids, and an ATS job record's
    internal title, are replaced on the way, so the originals never reach the
    output table."""
    out: list = []
    moved: dict[int, int] = {}
    strings: dict[str, int] = {}
    person_ids: dict[str, str] = {}

    def literal(value: str) -> int:
        if value not in strings:
            strings[value] = len(out)
            out.append(value)
        return strings[value]

    def label(key: str) -> str | None:
        # A key naming no string is dropped, as the decoder drops it.
        index = int(key[1:]) if key[1:].isdigit() else -1
        name = table[index] if 0 <= index < len(table) else None
        return name if isinstance(name, str) else None

    def place(index: object, spec: dict | None) -> object:
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            return index
        if spec is None and index in moved:
            return moved[index]
        raw = table[index]
        slot = len(out)
        out.append(None)
        if spec is None:
            moved[index] = slot
        if isinstance(raw, dict):
            labels = {label(k) for k in raw}
            person = "email" in labels
            ats_job = "hiringTeam" in labels and "title" in labels
            entry: dict[str, object] = {}
            for key, item in raw.items():
                name = label(key)
                if name is None or (spec is not None and name not in spec):
                    continue
                new_key = f"_{place(int(key[1:]), None)}"
                if person and name in PERSON_NAMES and _is_string(item):
                    entry[new_key] = literal(PERSON_NAMES[name])
                elif person and name in PERSON_IDS and _is_string(item):
                    original = table[item]
                    person_ids.setdefault(original, _PERSON_ID.format(len(person_ids) + 1))
                    entry[new_key] = literal(person_ids[original])
                elif ats_job and name == "title" and _is_string(item):
                    entry[new_key] = literal(INTERNAL_TITLE)
                else:
                    entry[new_key] = place(item, None if spec is None else spec[name])
            out[slot] = entry
        elif isinstance(raw, list) and not (raw and isinstance(raw[0], str)):
            out[slot] = [place(item, None) for item in raw]
        else:
            out[slot] = raw
            if isinstance(raw, str) and spec is None:
                strings.setdefault(raw, slot)
        return slot

    def _is_string(index: object) -> bool:
        return (isinstance(index, int) and not isinstance(index, bool)
                and 0 <= index < len(table) and isinstance(table[index], str))

    place(0, keep)
    return out


def _same_but_people(before: object, after: object, path: str = "") -> None:
    """Raise unless `after` is `before` with only person fields replaced."""
    if isinstance(before, dict) and isinstance(after, dict):
        if set(before) != set(after):
            raise ValueError(f"{path}: keys changed")
        person = "email" in before
        ats_job = "hiringTeam" in before and "title" in before
        for key in before:
            if person and key in PERSON_NAMES and isinstance(before[key], str):
                if after[key] != PERSON_NAMES[key]:
                    raise ValueError(f"{path}.{key}: not replaced")
            elif person and key in PERSON_IDS and isinstance(before[key], str):
                if not str(after[key]).startswith("00000000-0000-4000-8000-"):
                    raise ValueError(f"{path}.{key}: not replaced")
            elif ats_job and key == "title" and isinstance(before[key], str):
                if after[key] != INTERNAL_TITLE:
                    raise ValueError(f"{path}.{key}: not replaced")
            else:
                _same_but_people(before[key], after[key], f"{path}.{key}")
    elif isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            raise ValueError(f"{path}: length changed")
        for i, (b, a) in enumerate(zip(before, after, strict=True)):
            _same_but_people(b, a, f"{path}[{i}]")
    elif before != after and not (before != before and after != after):  # NaN equals NaN here
        raise ValueError(f"{path}: {before!r} became {after!r}")


def reduce_react_router(page: str, route: str, keys: tuple[str, ...], *, links: str | None = None) -> str:
    """One route's loader data, the given keys only, as a minimal page."""
    table = _stream_table(page)
    pruned = prune_table(table, {"loaderData": {route: dict.fromkeys(keys)}})
    stream = json.dumps(pruned, separators=(",", ":"), ensure_ascii=False) + "\n"
    anchors = ""
    if links is not None:
        found = HTMLParser(page).css(f'a[href^="{links}"]')
        anchors = "".join(
            f'<a href="{html.escape(a.attributes.get("href") or "", quote=True)}">'
            f"{html.escape(a.text(separator=' ', strip=True))}</a>\n"
            for a in found
        )
    reduced = (
        "<!DOCTYPE html>\n<html><body>\n"
        + anchors
        + "<script>window.__reactRouterContext.streamController.enqueue("
        + json.dumps(stream, ensure_ascii=False)
        + ");</script>\n</body></html>\n"
    )
    before = decode_turbo_stream(page)["loaderData"][route]  # type: ignore[index]
    after = decode_turbo_stream(reduced)["loaderData"][route]  # type: ignore[index]
    _same_but_people({k: before[k] for k in keys}, after, route)
    return reduced


# --------------------------------------------------------------------------- #
# The register
# --------------------------------------------------------------------------- #

Html = Callable[[str], str]


def _json_html(transform: Html) -> Html:
    """A fixture stored as `{"html": "..."}`, written as it was (`json.dumps`)."""
    def apply(text: str) -> str:
        data = json.loads(text)
        data["html"] = transform(data["html"])
        return json.dumps(data)
    return apply


REDUCERS: dict[str, Html] = {
    "successfactors/detail_1431618233.html": reduce_sf_detail,
    "successfactors/page1.json": _json_html(reduce_sf_results),
    "shopify/page1.json": _json_html(
        lambda page: reduce_react_router(
            page, "($locale)/careers", ("jobPostingsWithJobs", "atsLocations"), links="/careers/",
        )
    ),
    "shopify/roles.json": _json_html(
        lambda page: reduce_react_router(page, "($locale)/careers", ("roles",), links="/careers/")
    ),
    "shopify/posting_ef12f6c3.html": lambda page: reduce_react_router(
        page, "($locale)/careers/$posting", ("jobPosting",),
    ),
}


def process(path: Path, root: Path = FIXTURES) -> str:
    """The fixture's text after both passes."""
    text = path.read_text(encoding="utf-8")
    reducer = REDUCERS.get(path.relative_to(root).as_posix())
    if reducer is not None:
        text = reducer(text)
    return scrub_text(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="change nothing; exit 1 if a fixture would change")
    args = parser.parse_args(argv)
    changed: list[tuple[str, int, int]] = []
    for path in sorted(p for p in FIXTURES.rglob("*") if p.is_file()):
        try:
            before = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        after = process(path)
        if after != before:
            changed.append((path.relative_to(FIXTURES).as_posix(), len(before.encode()), len(after.encode())))
            if not args.check:
                path.write_text(after, encoding="utf-8")
    for name, old, new in changed:
        print(f"{'would change' if args.check else 'wrote'} {name}: {old:,} -> {new:,} bytes")
    if not changed:
        print("every fixture is reduced and scrubbed")
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    sys.exit(main())
