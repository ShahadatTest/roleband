"""Find, by AST, which modules write which tables.

Imported by `test_table_writers.py` (the gate) and usable on its own to see what
the code actually does:

    .venv/bin/python -c "from tests.table_writers import report; report()"

**What this can and cannot see.** It resolves model classes, import aliases
(`insert as pg_insert`), local bindings (`x = Model(...)`, `E = Model`), and rows
loaded through `select(Model)` / `session.get(Model, ...)` and then mutated by
attribute. It cannot see a row reached through a function argument, a tuple
unpack or a container — so a module it does NOT name may still write. That is
why the gate asserts found writers are a SUBSET of declared ones: the scan can
prove a declaration is missing, never that one is unnecessary.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

from tracker.db.models import Base

BACKEND = Path(__file__).resolve().parents[1]

#: Directories that can write rows. `scripts/` is not optional: seed and backfill
#: scripts live there, and a route that triggers one only spawns it — so leaving
#: scripts out reports a table as having no writer at all.
SCANNED = ("tracker", "scripts")

_CLASS_TABLE = {m.class_.__name__: m.local_table.name for m in Base.registry.mappers}
_TABLES = frozenset(Base.metadata.tables)

_ADDERS = {"add", "add_all", "merge", "bulk_save_objects", "bulk_insert_mappings"}
_VERBS = {"insert", "update", "delete"}
_RAW = re.compile(
    r"\b(insert\s+into|update|delete\s+from|truncate(?:\s+table)?)\s+(?:only\s+)?\"?([a-z_][a-z0-9_]*)\"?",
    re.I,
)
_TRUNCATE_KIND = {"insert": "insert", "update": "update", "delete": "delete", "truncate": "delete"}


class _Visitor(ast.NodeVisitor):
    def __init__(self, module: str, hits: dict[str, set[tuple[str, str]]]) -> None:
        self.module = module
        self.hits = hits
        self.alias: dict[str, str] = {}      # E = Model
        self.instance: dict[str, str] = {}   # x = Model(...)
        self.verb: dict[str, str] = {}       # pg_insert -> insert
        self.stmt: dict[str, str] = {}       # stmt = insert(Model) ...
        self.loaded: dict[str, str] = {}     # row = await session.get(Model, id)

    # -- resolution ------------------------------------------------------- #

    def _cls(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            if node.id in _CLASS_TABLE:
                return node.id
            if node.id in self.alias:
                return self.alias[node.id]
        if isinstance(node, ast.Attribute) and node.attr == "__table__":
            return self._cls(node.value)
        return None

    def _objects(self, node: ast.AST) -> list[str]:
        """Model classes an expression puts into the session."""

        if isinstance(node, ast.Call):
            found = self._cls(node.func)
            return [found] if found else []
        if isinstance(node, ast.Name):
            return [self.instance[node.id]] if node.id in self.instance else []
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return [c for element in node.elts for c in self._objects(element)]
        if isinstance(node, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
            return self._objects(node.elt)
        return []

    def _loads(self, node: ast.AST) -> str | None:
        """The model a `select(Model)` / `session.get(Model, ...)` expression loads."""

        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            func = inner.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in {"select", "get"}:
                for argument in inner.args:
                    found = self._cls(argument)
                    if found:
                        return found
        return None

    def _insert_target(self, node: ast.AST) -> str | None:
        """The model an insert CHAIN targets, following `stmt = insert(M)` bindings."""

        for inner in ast.walk(node):
            if isinstance(inner, ast.Name) and inner.id in self.stmt:
                return self.stmt[inner.id]
            if isinstance(inner, ast.Call):
                func = inner.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if self.verb.get(name, name if name in _VERBS else None) == "insert":
                    for argument in inner.args:
                        found = self._cls(argument)
                        if found:
                            return found
        return None

    def _record(self, table: str, kind: str) -> None:
        self.hits[table].add((self.module, kind))

    # -- binding ----------------------------------------------------------- #

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if (node.module or "").startswith("sqlalchemy"):
            for alias in node.names:
                if alias.name in _VERBS:
                    self.verb[alias.asname or alias.name] = alias.name
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
            if isinstance(value, ast.Name) and value.id in _CLASS_TABLE:
                self.alias[target] = value.id
            elif isinstance(value, ast.Call):
                found = self._cls(value.func)
                if found:
                    self.instance[target] = found
            insert_target = self._insert_target(value)
            if insert_target:
                self.stmt[target] = insert_target
            loaded = self._loads(value)
            if loaded:
                self.loaded[target] = loaded
        self._mutations(node.targets)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._mutations([node.target])
        self.generic_visit(node)

    def _for(self, node) -> None:
        if isinstance(node.target, ast.Name):
            loaded = self._loads(node.iter)
            if loaded:
                self.loaded[node.target.id] = loaded
        self.generic_visit(node)

    visit_For = _for
    visit_AsyncFor = _for

    def _mutations(self, targets) -> None:
        """`row.field = ...` on a row the scan watched being loaded."""

        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id in self.loaded
            ):
                self._record(_CLASS_TABLE[self.loaded[target.value.id]], "update")

    # -- writes ------------------------------------------------------------ #

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)

        if name in _ADDERS:
            for argument in node.args:
                for found in self._objects(argument):
                    self._record(_CLASS_TABLE[found], "insert")
                if name == "bulk_insert_mappings":
                    found = self._cls(argument)
                    if found:
                        self._record(_CLASS_TABLE[found], "insert")

        verb = self.verb.get(name, name if name in _VERBS else None)
        if verb:
            for argument in node.args:
                found = self._cls(argument)
                if found:
                    self._record(_CLASS_TABLE[found], verb)
                # `await session.delete(row)` hands over an INSTANCE, not a class:
                # the row was loaded or built earlier, so the class name never
                # appears at the call. Missing it reads a table such as `favorites`
                # as insert-only, i.e. as history.
                elif isinstance(argument, ast.Name):
                    held = self.loaded.get(argument.id) or self.instance.get(argument.id)
                    if held:
                        self._record(_CLASS_TABLE[held], verb)
            if isinstance(func, ast.Attribute):  # Model.__table__.delete()
                found = self._cls(func.value)
                if found:
                    self._record(_CLASS_TABLE[found], verb)

        # An insert that resolves a conflict is an UPSERT: the row already there
        # is rewritten. Counting it as a plain insert would read a canonical
        # table as append-only, which is the one direction that must not be wrong.
        if name in {"on_conflict_do_update", "on_conflict_do_nothing"} and isinstance(func, ast.Attribute):
            target = self._insert_target(func.value)
            if target:
                self._record(
                    _CLASS_TABLE[target],
                    "upsert" if name == "on_conflict_do_update" else "insert",
                )

        if name == "text":
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    for raw_verb, table in _RAW.findall(argument.value):
                        if table in _TABLES:
                            self._record(table, _TRUNCATE_KIND[raw_verb.lower().split()[0]])

        # A bare `Model(...)` is a row being built. It reaches the database
        # through a relationship cascade when nothing adds it directly, which is
        # how `job_skill_evidence` is written and why constructors count.
        if isinstance(func, ast.Name):
            found = self._cls(func)
            if found:
                self._record(_CLASS_TABLE[found], "insert")

        self.generic_visit(node)


class _ReaderVisitor(ast.NodeVisitor):
    """Modules that QUERY a table: `select(Model)`, `session.get(Model, ...)`, `Model.column`.

    Deliberately generous — a column reference counts — because the only reader
    claim the gate enforces is the EMPTY one. Over-reporting can wrongly accuse a
    `readers=()` declaration, which a human then corrects; under-reporting would
    let dead data keep claiming a reader.
    """

    def __init__(self, module: str, hits: dict[str, set[str]]) -> None:
        self.module = module
        self.hits = hits
        self.alias: dict[str, str] = {}

    def visit_Assign(self, node: ast.Assign) -> None:
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = node.value
            if isinstance(value, ast.Name) and value.id in _CLASS_TABLE:
                self.alias[node.targets[0].id] = value.id
        self.generic_visit(node)

    def _name(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id if node.id in _CLASS_TABLE else self.alias.get(node.id)
        return None

    def visit_Attribute(self, node: ast.Attribute) -> None:
        found = self._name(node.value)
        if found and not node.attr.startswith("__"):
            self.hits[_CLASS_TABLE[found]].add(self.module)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name in {"select", "get", "exists"}:
            for argument in node.args:
                found = self._name(argument)
                if found:
                    self.hits[_CLASS_TABLE[found]].add(self.module)
        self.generic_visit(node)


def scan_readers(backend: Path = BACKEND) -> dict[str, set[str]]:
    """`table -> {module}` for every query the scan can resolve."""

    hits: dict[str, set[str]] = defaultdict(set)
    for directory in SCANNED:
        for path in sorted((backend / directory).rglob("*.py")):
            module = path.relative_to(backend).as_posix()
            if module == "tracker/db/models.py":
                continue  # the definitions themselves are not a reader
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:  # pragma: no cover
                continue
            _ReaderVisitor(module, hits).visit(tree)
    return dict(hits)


def scan_writers(backend: Path = BACKEND) -> dict[str, set[tuple[str, str]]]:
    """`table -> {(module, kind)}` for every write the scan can resolve."""

    hits: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for directory in SCANNED:
        for path in sorted((backend / directory).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:  # pragma: no cover - nothing here fails to parse
                continue
            _Visitor(path.relative_to(backend).as_posix(), hits).visit(tree)
    return dict(hits)


def writers_by_table(backend: Path = BACKEND) -> dict[str, set[str]]:
    return {table: {module for module, _ in hits} for table, hits in scan_writers(backend).items()}


def kinds_by_table(backend: Path = BACKEND) -> dict[str, set[str]]:
    return {table: {kind for _, kind in hits} for table, hits in scan_writers(backend).items()}


def report() -> None:  # pragma: no cover - a human's tool
    hits = scan_writers()
    for table in sorted(_TABLES):
        rows = sorted(hits.get(table, ()))
        kinds = ",".join(sorted({k for _, k in rows})) or "-"
        print(f"{table:38s} {kinds:22s} {[m for m, _ in rows]}")
