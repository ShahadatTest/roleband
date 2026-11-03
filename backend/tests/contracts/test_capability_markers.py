"""Adapter capability markers, parametrized over ADAPTER_REGISTRY.

Two facts about a source are class-level declarations on its adapter:
how much of the board one listing reads (`listing_scope`) and where a
posting's text comes from (`detail`). Closure rests on the first: a filtered
listing is complete only over its filter, a windowed one only when its leaves
are audited to cover the parent. These tests hold each declaration to the code it describes,
so a new adapter that reads a slice cannot read as a whole board.

Each rule runs on every registered adapter AND on planted classes that break
it, so a checker that stopped seeing anything fails here rather than passing
by finding no violation.
"""

from __future__ import annotations

import ast
import functools
import inspect
from pathlib import Path
from typing import get_args

import pytest

from tracker.connectors import ADAPTER_REGISTRY
from tracker.connectors.listing import AdapterCapabilities, capability_table
from tracker.connectors.listing.base import BaseAdapter, DetailMode, ListingScope

#: Names that only a slice reader uses. `country_manifest` builds a per-country
#: query vocabulary, `expand_saturated` refines a query that hit the result
#: window, and the three `BaseAdapter` helpers run a query list term by term.
#: Counted as Name/Attribute uses, never as strings or bare imports.
MODULE_SLICE_NAMES = frozenset({"country_manifest", "expand_saturated"})
CLASS_SLICE_NAMES = frozenset(
    {"expand_saturated", "scan_location_queries", "planned_location_terms", "planned_location_items"}
)
#: The refinement that makes a query list windowed.
WINDOW_REFINER = "expand_saturated"
#: The leaf-coverage audit: `AmazonAdapter._audit_partition`, which
#: checks a sample of each saturated parent against what the leaves returned
#: and marks the run `truncated` when they miss it. A second windowed adapter
#: reuses this name or promotes the audit to the base, and this rule follows.
LEAF_AUDIT = "_audit_partition"


def _module_tree(cls: type) -> ast.Module:
    return _parse(inspect.getsourcefile(cls) or "")


@functools.cache
def _parse(path: str) -> ast.Module:
    return ast.parse(Path(path).read_text(), filename=path)


def _used_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            names.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            names.add(sub.attr)
    return names


def _own_classes(cls: type) -> list[type]:
    """The adapter's classes below `BaseAdapter`, most derived first."""
    return [k for k in cls.__mro__ if issubclass(k, BaseAdapter) and k is not BaseAdapter]


def _class_def(k: type, tree: ast.Module) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == k.__name__:
            return node
    raise AssertionError(f"{k.__name__}: no top-level class definition in its module")


def _method(cls: type, name: str, tree_of) -> ast.AST | None:
    """The definition of `name` that `cls` actually runs, from its MRO."""
    for k in _own_classes(cls):
        for node in _class_def(k, tree_of(k)).body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
                return node
    return None


def slice_evidence(cls: type, tree_of=_module_tree) -> list[str]:
    """Why `cls` reads a slice of its board rather than the whole of it.

    Module-level names count for every adapter class in that module: the
    manifest is built at module level and the class only names the result. A
    module that builds a manifest for one class and not another is split.
    """
    evidence = []
    if cls.location_queries is not None:
        evidence.append("declares location_queries")
    for k in _own_classes(cls):
        tree = tree_of(k)
        for name in sorted(MODULE_SLICE_NAMES & _used_names(tree)):
            evidence.append(f"its module uses {name}")
        for name in sorted(CLASS_SLICE_NAMES & _used_names(_class_def(k, tree))):
            evidence.append(f"{k.__name__} uses {name}")
    return evidence


def scope_violations(cls: type, tree_of=_module_tree) -> list[str]:
    scope = cls.listing_scope
    problems = []
    if scope not in get_args(ListingScope):
        problems.append(f"listing_scope {scope!r} is not a ListingScope")
    evidence = slice_evidence(cls, tree_of)
    if scope == "board" and evidence:
        problems.append(f"declares 'board' but {'; '.join(evidence)}")
    if scope != "board" and cls.location_queries is None:
        problems.append(f"declares {scope!r} but states no location_queries to filter by")
    fetch = _method(cls, "fetch", tree_of)
    fetch_names = _used_names(fetch) if fetch is not None else set()
    if WINDOW_REFINER in fetch_names and scope != "windowed":
        problems.append(f"fetch calls {WINDOW_REFINER} but declares {scope!r}, not 'windowed'")
    if scope == "windowed":
        if WINDOW_REFINER not in fetch_names:
            problems.append(f"declares 'windowed' but fetch never calls {WINDOW_REFINER}")
        if LEAF_AUDIT not in fetch_names or not callable(getattr(cls, LEAF_AUDIT, None)):
            problems.append(f"declares 'windowed' but fetch never runs the leaf audit {LEAF_AUDIT}")
    return problems


def detail_violations(cls: type) -> list[str]:
    overrides = cls.hydrate is not BaseAdapter.hydrate
    if cls.detail not in get_args(DetailMode):
        return [f"detail {cls.detail!r} is not a DetailMode"]
    if overrides and cls.detail != "per_posting":
        return [f"overrides hydrate but declares detail={cls.detail!r}"]
    if not overrides and cls.detail == "per_posting":
        return ["declares detail='per_posting' but inherits the no-op hydrate"]
    return []


#: What a stored posting does not carry: the listing row's own payload. A
#: hydrate that reads it cannot fill a posting rebuilt from storage.
LISTING_PAYLOAD = "detail_payload"


def _read_attrs(node: ast.AST) -> set[str]:
    """Attributes `node` reads (Load), not ones it only assigns."""
    return {
        sub.attr for sub in ast.walk(node)
        if isinstance(sub, ast.Attribute) and isinstance(sub.ctx, ast.Load)
    }


def text_violations(cls: type, tree_of=_module_tree) -> list[str]:
    """`text_from_posting`: a posting's text, from the posting alone."""
    if not cls.text_from_posting:
        return []
    if cls.detail != "per_posting":
        return [f"declares text_from_posting but detail={cls.detail!r}: nothing to fetch"]
    hydrate = _method(cls, "hydrate", tree_of)
    # A hydrate that reads the listing's payload fills a stored posting only
    # where the adapter rebuilds that payload from the posting.
    rebuilds = _method(cls, "payload_from_posting", tree_of) is not None
    if hydrate is not None and LISTING_PAYLOAD in _read_attrs(hydrate) and not rebuilds:
        return [f"declares text_from_posting but hydrate reads the listing's {LISTING_PAYLOAD}"]
    return []


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", sorted(ADAPTER_REGISTRY))
def test_an_adapter_overrides_hydrate_iff_it_declares_per_posting(name):
    assert detail_violations(ADAPTER_REGISTRY[name]) == [], name


@pytest.mark.parametrize("name", sorted(ADAPTER_REGISTRY))
def test_an_adapter_reads_text_from_the_posting_alone_only_if_its_hydrate_can(name):
    assert text_violations(ADAPTER_REGISTRY[name]) == [], name


@pytest.mark.parametrize("name", sorted(ADAPTER_REGISTRY))
def test_an_adapter_that_reads_a_slice_does_not_declare_the_whole_board(name):
    assert scope_violations(ADAPTER_REGISTRY[name]) == [], name


def test_the_registry_uses_every_marker_value():
    """The control for the parametrized rules: a registry where nothing is
    filtered, windowed or per-posting would pass them by checking nothing."""
    scopes = {cls.listing_scope for cls in ADAPTER_REGISTRY.values()}
    details = {cls.detail for cls in ADAPTER_REGISTRY.values()}
    assert scopes == set(get_args(ListingScope))
    assert details == set(get_args(DetailMode))
    per_posting = [cls for cls in ADAPTER_REGISTRY.values() if cls.detail == "per_posting"]
    assert {cls.text_from_posting for cls in per_posting} == {True, False}


# --------------------------------------------------------------------------- #
# Planted classes: each rule must name a class that breaks it
# --------------------------------------------------------------------------- #

_PLANTED_HEADER = """
from tracker.connectors.listing.base import BaseAdapter, country_manifest
from tracker.platform.paging import expand_saturated

TERMS = {"uk": ["London"]}
"""


def _plant(body: str) -> tuple[type, object]:
    """Exec a planted adapter module; return its `Planted` class and a tree lookup."""
    source = _PLANTED_HEADER + body
    namespace: dict = {"__name__": "planted_adapter"}
    exec(compile(source, "<planted>", "exec"), namespace)
    tree = ast.parse(source)
    real = _module_tree

    def tree_of(k: type) -> ast.Module:
        return tree if k.__module__ == "planted_adapter" else real(k)

    return namespace["Planted"], tree_of


_FETCH = """
    async def fetch(self):
        async for job in self.scan_location_queries(self.planned_location_terms(), self._term):
            yield job
"""


def test_a_planted_query_list_reader_declaring_board_is_named():
    """No `location_queries`, so only the code scan can see it."""
    cls, tree_of = _plant("""
class Planted(BaseAdapter):
    name = "planted"
    posted_date = "none"
""" + _FETCH)
    assert cls.listing_scope == "board" and cls.location_queries is None
    problems = scope_violations(cls, tree_of)
    assert any("uses scan_location_queries" in p for p in problems), problems


def test_a_planted_country_manifest_module_declaring_board_is_named():
    cls, tree_of = _plant("""
MANIFEST = country_manifest(lambda c: c.query_name)


class Planted(BaseAdapter):
    name = "planted"
    posted_date = "none"

    async def fetch(self):
        for _ in MANIFEST:
            yield None
""")
    problems = scope_violations(cls, tree_of)
    assert any("its module uses country_manifest" in p for p in problems), problems


def test_a_real_filtered_adapter_redeclared_board_is_named():
    cls, tree_of = _plant("""
from tracker.connectors import ADAPTER_REGISTRY


class Planted(ADAPTER_REGISTRY["google"]):
    listing_scope = "board"
""")
    problems = scope_violations(cls, tree_of)
    assert any("declares location_queries" in p for p in problems), problems
    assert any("GoogleAdapter uses scan_location_queries" in p for p in problems), problems


def test_a_planted_filtered_class_with_no_filter_is_named():
    cls, tree_of = _plant("""
class Planted(BaseAdapter):
    name = "planted"
    posted_date = "none"
    listing_scope = "filtered"

    async def fetch(self):
        yield None
""")
    assert scope_violations(cls, tree_of) == [
        "declares 'filtered' but states no location_queries to filter by"
    ]


_WINDOWED = """
class Planted(BaseAdapter):
    name = "planted"
    posted_date = "none"
    location_queries = TERMS
    listing_scope = "{scope}"

    async def fetch(self):
        queries = await expand_saturated(
            self.planned_location_items(), declared_total=None, refine=None, window=10
        )
        async for job in self.scan_location_queries(queries, self._term):
            yield job
        {audit}

    def _audit_partition(self, seen):
        return None
"""


def test_a_planted_windowed_class_that_skips_the_leaf_audit_is_named():
    cls, tree_of = _plant(_WINDOWED.format(scope="windowed", audit="pass"))
    assert scope_violations(cls, tree_of) == [
        "declares 'windowed' but fetch never runs the leaf audit _audit_partition"
    ]


def test_a_planted_windowed_class_that_runs_the_leaf_audit_passes():
    """The negative control: the same class with the audit call is clean."""
    cls, tree_of = _plant(_WINDOWED.format(scope="windowed", audit="self._audit_partition(set())"))
    assert scope_violations(cls, tree_of) == []


def test_a_planted_saturation_refiner_declaring_filtered_is_named():
    cls, tree_of = _plant(_WINDOWED.format(scope="filtered", audit="self._audit_partition(set())"))
    assert scope_violations(cls, tree_of) == [
        "fetch calls expand_saturated but declares 'filtered', not 'windowed'"
    ]


def test_planted_hydrate_mismatches_are_named():
    cls, _ = _plant("""
class Planted(BaseAdapter):
    name = "planted"
    posted_date = "none"

    async def fetch(self):
        yield None

    async def hydrate(self, job):
        return None
""")
    assert detail_violations(cls) == ["overrides hydrate but declares detail='inline'"]

    cls, _ = _plant("""
from tracker.connectors import ADAPTER_REGISTRY


class Planted(ADAPTER_REGISTRY["greenhouse"]):
    detail = "per_posting"
""")
    assert detail_violations(cls) == ["declares detail='per_posting' but inherits the no-op hydrate"]

    cls, _ = _plant("""
from tracker.connectors import ADAPTER_REGISTRY


class Planted(ADAPTER_REGISTRY["avature"]):
    pass
""")
    assert detail_violations(cls) == [], "an inherited override carries its declaration"


def test_planted_text_from_posting_mismatches_are_named():
    """A hydrate that needs the listing's payload and cannot rebuild it; a
    class with no hydrate. Workday reads the payload and rebuilds it from the
    posting url, so it is the control for the first."""
    cls, tree_of = _plant("""
class Planted(BaseAdapter):
    name = "planted"
    posted_date = "none"
    detail = "per_posting"
    text_from_posting = True

    async def fetch(self):
        yield None

    async def hydrate(self, job):
        job.description_html = job.detail_payload["html"]
""")
    assert text_violations(cls, tree_of) == [
        "declares text_from_posting but hydrate reads the listing's detail_payload"
    ]

    cls, tree_of = _plant("""
class Planted(BaseAdapter):
    name = "planted"
    posted_date = "none"
    detail = "per_posting"
    text_from_posting = True

    async def fetch(self):
        yield None

    def payload_from_posting(self, job):
        return {"html": job.url}

    async def hydrate(self, job):
        job.description_html = job.detail_payload["html"]
""")
    assert text_violations(cls, tree_of) == [], "a payload it rebuilds from the posting"
    assert _read_attrs(_method(ADAPTER_REGISTRY["workday"], "hydrate", _module_tree)) >= {LISTING_PAYLOAD}

    cls, tree_of = _plant("""
from tracker.connectors import ADAPTER_REGISTRY


class Planted(ADAPTER_REGISTRY["greenhouse"]):
    text_from_posting = True
""")
    assert text_violations(cls, tree_of) == [
        "declares text_from_posting but detail='inline': nothing to fetch"
    ]

    # The control: a hydrate that only WRITES the payload (Eightfold keeps the
    # detail it read) still reads its text from the posting alone.
    cls, tree_of = _plant("""
class Planted(BaseAdapter):
    name = "planted"
    posted_date = "none"
    detail = "per_posting"
    text_from_posting = True

    async def fetch(self):
        yield None

    async def hydrate(self, job):
        job.description_html = "<p>text</p>"
        job.detail_payload = {"read": True}
""")
    assert text_violations(cls, tree_of) == []


# --------------------------------------------------------------------------- #
# capability_table
# --------------------------------------------------------------------------- #


def test_the_capability_table_has_one_row_per_registered_adapter():
    rows = capability_table()
    assert [row.name for row in rows] == sorted(ADAPTER_REGISTRY)


@pytest.mark.parametrize(
    "row",
    [
        AdapterCapabilities(
            name="amazon", listing_scope="windowed", detail="inline", text_from_posting=False,
            declares_total=True, board_probe=False, posting_page=False, transport=None,
        ),
        AdapterCapabilities(
            name="greenhouse", listing_scope="board", detail="inline", text_from_posting=False,
            declares_total=False, board_probe=True, posting_page=True, transport=(),
        ),
        AdapterCapabilities(
            name="workday", listing_scope="filtered", detail="per_posting", text_from_posting=True,
            declares_total=True, board_probe=True, posting_page=False, transport=None,
        ),
        AdapterCapabilities(
            name="accenture", listing_scope="filtered", detail="per_posting", text_from_posting=True,
            declares_total=True, board_probe=True, posting_page=False, transport=("post",),
        ),
        AdapterCapabilities(
            name="apple", listing_scope="filtered", detail="per_posting", text_from_posting=True,
            declares_total=True, board_probe=False, posting_page=False, transport=None,
        ),
    ],
    ids=lambda row: row.name,
)
def test_the_capability_table_states_known_rows(row):
    assert {r.name: r for r in capability_table()}[row.name] == row


def test_the_table_and_the_posting_page_queue_agree():
    """Both read `read_posting_page` overrides; neither may restate the list."""
    from tracker.workflows.posting_pages import PAGE_PROVIDERS

    assert tuple(r.name for r in capability_table() if r.posting_page) == PAGE_PROVIDERS


@pytest.mark.asyncio
async def test_the_table_is_served_one_row_per_adapter_and_follows_the_class(api_client, monkeypatch):
    """`GET /api/connectors/capabilities` reads the classes now: a newly
    registered adapter adds a row, and a changed marker changes its value."""
    from tracker.connectors import listing
    from tracker.connectors.listing.greenhouse import GreenhouseAdapter

    served = (await api_client.get("/api/connectors/capabilities")).json()["items"]
    assert [row["name"] for row in served] == sorted(listing.ADAPTER_REGISTRY)
    greenhouse = next(row for row in served if row["name"] == "greenhouse")
    assert greenhouse["declares_total"] is GreenhouseAdapter.declares_total

    class Windowed(GreenhouseAdapter):
        listing_scope = "windowed"
        declares_total = not GreenhouseAdapter.declares_total

    monkeypatch.setitem(listing.ADAPTER_REGISTRY, "zz-windowed", Windowed)
    served = (await api_client.get("/api/connectors/capabilities")).json()["items"]
    added = next(row for row in served if row["name"] == "zz-windowed")
    assert (added["listing_scope"], added["declares_total"]) == ("windowed", not GreenhouseAdapter.declares_total)
    assert len(served) == len(listing.ADAPTER_REGISTRY)
