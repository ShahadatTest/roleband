"""Recipe compiler: document -> immutable executable plan.

Two layers of defense, both required:

1. JSON Schema: structural. `additionalProperties: false` everywhere means an
   unknown/misspelled/smuggled key is rejected, and the absence of any `xpath`
   property means raw XPath cannot be expressed at all. A new or edited recipe
   meets the contract (`RECIPE_V1_SCHEMA`); a revision read back from the
   database meets the stored view (`STORED_RECIPE_V1_SCHEMA`, `stored=True`),
   so a revision outside the contract still loads and is refused by name where
   it would run.
2. Semantic checks here: things a schema cannot state. The `start_url` host
   must be in `match.domains` (a recipe cannot point at a host it did not
   declare), a JSON `item` is a dotted path and not an XPath, the method is
   GET (the guarded transport sends nothing else), and pagination has the
   selector, param or cursor path its mode needs.

`runtime_problems` is the one test of whether a compiled plan can run. The
scheduled run and preview, validate and shadow all ask it, so a recipe the
runtime refuses never passes a check either.

Output is a frozen `ExecutablePlan`. The compiler never fetches; it turns a
document into something the runner can execute deterministically, or raises
`RecipeError` listing every problem at once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from jsonschema import Draft202012Validator

from tracker.connectors.recipes.schema import (
    RECIPE_V1_SCHEMA,
    STORED_RECIPE_V1_SCHEMA,
    TRANSPORT_MODES,
)
from tracker.connectors.recipes.transforms import pattern_problem

__all__ = ["ExecutablePlan", "RecipeError", "compile_recipe", "runtime_problems"]

_VALIDATOR = Draft202012Validator(RECIPE_V1_SCHEMA)
_STORED_VALIDATOR = Draft202012Validator(STORED_RECIPE_V1_SCHEMA)


class RecipeError(ValueError):
    """Recipe rejected. Carries every diagnostic, so an author fixes one round."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("; ".join(problems))


@dataclass(frozen=True)
class ExecutablePlan:
    """Immutable compiled recipe. The runner consumes only this."""

    recipe_id: str
    domains: tuple[str, ...]
    transport_mode: str
    delay_ms: int
    start_url: str
    response: str
    item: str
    method: str
    body: dict | None
    fields: dict  # field_name -> field spec (dict)
    pagination: dict | None
    validation: dict = field(default_factory=dict)

    def host_allowed(self, url: str) -> bool:
        """Every URL the runner touches — start, pagination, extracted — is
        checked against the declared hosts. A recipe cannot introduce a new
        host implicitly."""
        host = (urlparse(url).hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in self.domains)


def runtime_problems(plan: ExecutablePlan) -> list[str]:
    """Why a compiled plan cannot run, or nothing when it can."""
    if plan.transport_mode not in TRANSPORT_MODES:
        return [
            f"transport: mode {plan.transport_mode!r} has no runtime; a recipe runs"
            f" {', '.join(TRANSPORT_MODES)}"
        ]
    return []


def _schema_problems(document: dict, validator: Draft202012Validator) -> list[str]:
    return [
        f"schema: {'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}"
        for err in sorted(validator.iter_errors(document), key=lambda e: list(e.path))
    ]


def _semantic_problems(document: dict) -> list[str]:
    problems: list[str] = []
    listing = document.get("listing", {})
    match = document.get("match", {})
    domains = [d.lower() for d in match.get("domains", [])]

    start_url = listing.get("start_url")
    if start_url and domains:
        host = (urlparse(start_url).hostname or "").lower()
        if not any(host == d or host.endswith("." + d) for d in domains):
            problems.append(
                f"semantic: listing.start_url host {host!r} is not in match.domains {domains}"
            )

    response = listing.get("response")
    item = listing.get("item")
    if response == "json" and item and item.strip().startswith("/"):
        problems.append("semantic: JSON item path must be a dotted key path, not an XPath")

    if listing.get("method", "GET") != "GET":
        problems.append(
            f"semantic: listing.method={listing['method']} has no runtime; a recipe fetches with GET"
        )

    pagination = document.get("pagination")
    if pagination:
        mode = pagination.get("mode")
        if mode == "next_link" and not pagination.get("selector"):
            problems.append("semantic: pagination.mode=next_link requires a selector")
        if mode in {"page_number", "offset"} and not pagination.get("param"):
            problems.append(f"semantic: pagination.mode={mode} requires a param")
        if mode == "cursor" and not pagination.get("cursor_path"):
            problems.append("semantic: pagination.mode=cursor requires a cursor_path")

    for name, spec in (listing.get("fields") or {}).items():
        transforms = spec.get("transforms", []) if isinstance(spec, dict) else []
        for transform in transforms:
            if isinstance(transform, dict) and transform.get("op") == "regex_capture":
                problem = pattern_problem(transform.get("pattern"))
                if problem is not None:
                    problems.append(f"semantic: listing.fields.{name}: {problem}")

    # Defense in depth: reject any stray xpath-looking key even though the schema
    # already forbids unknown properties. Cheap, and it makes the "no raw XPath"
    # invariant impossible to weaken by a future schema edit.
    if _contains_xpath_key(document):
        problems.append("semantic: raw XPath is not permitted anywhere in a recipe")

    return problems


def _contains_xpath_key(node) -> bool:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and key.lower() in {"xpath", "xpath_all"}:
                return True
            if _contains_xpath_key(value):
                return True
    elif isinstance(node, list):
        return any(_contains_xpath_key(item) for item in node)
    return False


def compile_recipe(document: dict, *, stored: bool = False) -> ExecutablePlan:
    """Validate + compile, or raise `RecipeError` with all problems.

    `stored=True` is for a revision read back from the database: it checks the
    stored view, so a revision that names a reserved transport or a field the
    runner does not read still loads. Everything that saves, previews,
    validates or shadows a document leaves it False.
    """
    if not isinstance(document, dict):
        raise RecipeError(["recipe must be a JSON object"])

    problems = _schema_problems(document, _STORED_VALIDATOR if stored else _VALIDATOR)
    # Only run semantic checks when the structure is valid enough to inspect.
    if not problems:
        problems = _semantic_problems(document)
    if problems:
        raise RecipeError(problems)

    listing = document["listing"]
    transport = document["transport"]
    return ExecutablePlan(
        recipe_id=document["id"],
        domains=tuple(d.lower() for d in document["match"]["domains"]),
        transport_mode=transport["mode"],
        delay_ms=transport.get("delay_ms", 0),
        start_url=listing["start_url"],
        response=listing["response"],
        item=listing["item"],
        method=listing.get("method", "GET"),
        body=listing.get("body"),
        fields=listing["fields"],
        pagination=document.get("pagination"),
        validation=document.get("validation", {}),
    )
