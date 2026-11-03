"""Deterministic recipe runner.

Executes an `ExecutablePlan` against fetched responses and returns `RawJob`s in
a `RecipeRunResult` whose `list_complete` is honest closure evidence. It is
deliberately paranoid about the two things that corrupt the longitudinal asset:

- `list_complete` is True only when pagination terminated *naturally* (an empty
  or exhausted page), never when a bound (`max_pages`, a per-run item cap) was
  hit. Hitting a bound -> incomplete -> closure suppressed downstream.
- A page that adds no new `req_id` stops the run and marks it incomplete, as
  `platform.paging.paginate` does: a site that ignores the page parameter
  serves its first page again, and reading it to `max_pages` proves nothing.
- Every request URL — start, each pagination step — is host-checked against the
  plan's declared domains. A cross-host pagination target is a hard stop that
  also marks the listing incomplete: a recipe cannot wander to a host it did
  not declare.

HTML extraction is selectolax CSS only (no XPath ever reaches here). JSON
extraction is dotted key/index paths owned by RoleBand. Field failures degrade to
drift + validation, never to a crash.
"""

from __future__ import annotations

from dataclasses import dataclass

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from tracker.connectors.recipes.compiler import ExecutablePlan
from tracker.connectors.recipes.transforms import TransformError, apply_transforms
from tracker.connectors.sdk import FetchRequest, FetchResponse
from tracker.platform.util import parse_datetime
from tracker.schema import RawJob
from tracker.source_policy import CollectionAccess, collection_access

__all__ = ["RecipeRunResult", "extract_items", "run_plan"]


@dataclass
class RecipeRunResult:
    jobs: list[RawJob]
    list_complete: bool
    diagnostics: dict


# --------------------------------------------------------------------------- #
# JSON key/index path
# --------------------------------------------------------------------------- #
def json_path(data, path: str):
    """Dotted key/index navigation. `a.b.0.c`; missing -> None, never raises."""
    cur = data
    for part in path.split("."):
        if part == "":
            continue
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if cur is None:
            return None
    return cur


# --------------------------------------------------------------------------- #
# Field extraction
# --------------------------------------------------------------------------- #
def _extract_html_field(item: Node, spec: dict, base_url: str):
    if "literal" in spec:
        value = spec["literal"]
    elif "css_all" in spec:
        nodes = item.css(spec["css_all"])
        value = [_node_value(n, spec) for n in nodes]
        value = [v for v in value if v]
    elif "css" in spec:
        node = item.css_first(spec["css"])
        value = _node_value(node, spec) if node is not None else None
    else:
        # No sub-selector: the field reads from the item element itself (e.g.
        # `req_id: {attr: data-job-id}` where the id lives on the item tag).
        value = _node_value(item, spec)
    return _apply(value, spec, base_url)


def _node_value(node: Node, spec: dict):
    if node is None:
        return None
    if "attr" in spec:
        return (node.attributes or {}).get(spec["attr"])
    if spec.get("text"):
        return node.text(separator=" ", strip=True)
    return node.text(separator=" ", strip=True)


def _extract_json_field(item, spec: dict, base_url: str):
    if "literal" in spec:
        value = spec["literal"]
    elif "json_path" in spec:
        value = json_path(item, spec["json_path"])
    else:
        value = None
    return _apply(value, spec, base_url)


def _apply(value, spec: dict, base_url: str):
    if value is None:
        return None
    transforms = list(spec.get("transforms", []))
    # `absolute: true` is sugar for a resolve_url transform at the end.
    if spec.get("absolute"):
        transforms = [*transforms, {"op": "resolve_url"}]
    if transforms:
        try:
            value = apply_transforms(value, transforms, {"base_url": base_url})
        except TransformError:
            return None
    return value


# --------------------------------------------------------------------------- #
# Item extraction
# --------------------------------------------------------------------------- #
def _empty_state_present(plan: ExecutablePlan, response: FetchResponse) -> bool:
    """Whether the recipe's declared empty-state selector matches an empty page.

    A recipe may *describe* emptiness (`validation.empty_state_selector`); it can
    never *declare* its empty result authoritative — that stays a runtime
    decision. This only reports the structural fact.
    """
    selector = plan.validation.get("empty_state_selector")
    if not selector or plan.response != "html":
        return False
    return HTMLParser(response.text()).css_first(selector) is not None


def extract_items(plan: ExecutablePlan, response: FetchResponse) -> list:
    """The located item elements/objects, before field extraction."""
    if plan.response == "html":
        tree = HTMLParser(response.text())
        return list(tree.css(plan.item))
    payload = response.json()
    items = json_path(payload, plan.item)
    return items if isinstance(items, list) else []


def _build_rawjob(plan: ExecutablePlan, item, company: str, base_url: str) -> tuple[RawJob | None, dict]:
    extract = _extract_html_field if plan.response == "html" else _extract_json_field
    values = {name: extract(item, spec, base_url) for name, spec in plan.fields.items()}

    missing = [
        name
        for name, spec in plan.fields.items()
        if spec.get("required") and not values.get(name)
    ]
    # req_id/title/url are structurally required regardless of the `required` flag.
    for core in ("req_id", "title", "url"):
        if not values.get(core) and core not in missing:
            missing.append(core)
    if missing:
        return None, {"missing_required": missing}

    locations = values.get("locations")
    if isinstance(locations, str):
        locations = [locations]

    job = RawJob(
        company=company,
        req_id=str(values["req_id"]),
        title=str(values["title"]),
        url=str(values["url"]),
        locations=[str(loc) for loc in (locations or []) if loc],
        department=_opt_str(values.get("department")),
        team=_opt_str(values.get("team")),
        # `parse_date` yields ISO text; without it the raw value (text or an
        # epoch number) is parsed here. A value that reads as no date leaves
        # the posting undated rather than dropping it.
        posted_at=parse_datetime(values.get("posted_at")),
    )
    return job, {}


def _opt_str(value):
    return str(value) if value else None


# --------------------------------------------------------------------------- #
# Pagination target
# --------------------------------------------------------------------------- #
def _next_request(plan: ExecutablePlan, response: FetchResponse, page_index: int) -> FetchRequest | None:
    pag = plan.pagination
    if not pag:
        return None
    mode = pag["mode"]
    if mode == "next_link":
        if plan.response != "html":
            return None
        node = HTMLParser(response.text()).css_first(pag["selector"])
        href = (node.attributes or {}).get("href") if node is not None else None
        if not href:
            return None
        from urllib.parse import urljoin

        return FetchRequest(url=urljoin(str(response.final_url), href))
    if mode in {"page_number", "offset"}:
        size = pag.get("size", 1) if mode == "offset" else 1
        value = (page_index + 1) * size if mode == "offset" else page_index + 1
        from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

        parts = urlparse(plan.start_url)
        query = dict(parse_qsl(parts.query))
        query[pag["param"]] = str(value)
        return FetchRequest(url=urlunparse(parts._replace(query=urlencode(query))))
    if mode == "cursor":
        cursor = json_path(response.json(), pag["cursor_path"]) if plan.response == "json" else None
        if not cursor:
            return None
        from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

        parts = urlparse(plan.start_url)
        query = dict(parse_qsl(parts.query))
        query[pag.get("param", "cursor")] = str(cursor)
        return FetchRequest(url=urlunparse(parts._replace(query=urlencode(query))))
    return None


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
async def run_plan(
    plan: ExecutablePlan,
    context,
    company: str,
    *,
    max_items: int | None = None,
    access: CollectionAccess | None = None,
) -> RecipeRunResult:
    """Execute a compiled plan through the SDK context.

    `context` is any `ConnectorContext`; tests inject a fake that replays canned
    `FetchResponse`s. `max_items` is the per-run cap (the pipeline's `--max-list`
    analogue); hitting it makes the listing incomplete, as a capped scan is.
    """
    decision = access if access is not None else collection_access("recipe", company=company)
    decision.require()
    diagnostics: dict = {"pages": 0, "items": 0, "dropped": 0, "errors": []}
    jobs: list[RawJob] = []
    seen_ids: set[str] = set()
    max_pages = (plan.pagination or {}).get("max_pages", 1)

    request = FetchRequest(url=plan.start_url, method=plan.method, json_body=plan.body)
    list_complete = True
    capped = False

    for page_index in range(max_pages):
        if not plan.host_allowed(request.url):
            diagnostics["errors"].append(f"cross-host request blocked: {request.url}")
            list_complete = False
            break

        response = await context.fetch(request)
        diagnostics["pages"] += 1
        if not response.ok:
            diagnostics["errors"].append(f"page {page_index}: status {response.status}")
            list_complete = False
            break

        try:
            items = extract_items(plan, response)
        except Exception as exc:  # noqa: BLE001 - malformed payload -> drift, not crash
            diagnostics["errors"].append(f"page {page_index}: parse error {type(exc).__name__}")
            list_complete = False
            break

        if not items:
            # Natural termination: an empty page is the end of the listing. On
            # the FIRST page, record whether the recipe's structural empty-state
            # sentinel is present — an empty result with the sentinel is a
            # *confirmed* empty, an empty result without one is suspicious.
            if page_index == 0:
                diagnostics["structural_empty"] = _empty_state_present(plan, response)
            break

        added = 0
        for item in items:
            if max_items is not None and len(jobs) >= max_items:
                capped = True
                break
            job, why = _build_rawjob(plan, item, company, str(response.final_url))
            diagnostics["items"] += 1
            if job is None:
                diagnostics["dropped"] += 1
                continue
            if job.req_id in seen_ids:
                continue
            seen_ids.add(job.req_id)
            jobs.append(job)
            added += 1

        if capped:
            list_complete = False
            break
        if not added:
            diagnostics["errors"].append(
                f"page {page_index}: no new posting (every item repeated or was dropped); stopped paging"
            )
            list_complete = False
            break

        request = _next_request(plan, response, page_index)
        if request is None:
            break
    else:
        # Ran the full max_pages range without a natural stop: bound was hit.
        list_complete = False

    _validate(plan, jobs, diagnostics)
    if diagnostics["errors"]:
        list_complete = False

    return RecipeRunResult(jobs=jobs, list_complete=list_complete, diagnostics=diagnostics)


def _validate(plan: ExecutablePlan, jobs: list, diagnostics: dict) -> None:
    v = plan.validation
    min_items = v.get("min_items")
    if min_items is not None and len(jobs) < min_items:
        diagnostics["errors"].append(f"min_items {min_items} not met ({len(jobs)})")
    ratio = v.get("required_field_ratio")
    attempted = diagnostics["items"]
    if ratio is not None and attempted:
        kept_ratio = len(jobs) / attempted
        if kept_ratio < ratio:
            diagnostics["errors"].append(
                f"required_field_ratio {ratio} not met ({kept_ratio:.2f})"
            )


