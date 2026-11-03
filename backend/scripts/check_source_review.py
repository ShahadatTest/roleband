"""Is the recorded source review evidence still true, and what would a gate pause?

Two questions, one command.

**1. Has the evidence moved?** `tracker/source_review.py` records, per provider,
the robots file it read, that file's sha256, the route evaluated, and the
directive that decided. This re-fetches and compares. As with `vendored.py`,
a verdict nobody can re-check is indistinguishable from a
current one, and a robots file is a live document that changes without telling
us. Drift is reported per artifact, not per host, so a cosmetic byte change in
a file whose VERDICT is unchanged is reported as `moved` rather than as a
finding — a check that cries wolf gets muted.

**2. What would a review gate pause?** A review gate must not activate until
the active bindings, review decisions and feeds it would pause are enumerated.
This reads the live roster and answers it: every enabled company whose
review is not `approved` is one the gate would pause.

A denied provider is **never fetched**, not even to re-verify its own denial
(zero outbound requests). Its row stays `unverified`, which is the
truthful state.

Deliberately a script, like `check_catalog_tokens` and
`check_vendored_upstream`: tests never touch the network (`docs/testing.md`),
and an operator changing their robots file must not fail the build. Run it by
hand on the monthly review.

    0  recorded evidence still holds
    1  DRIFT — a robots verdict changed, or a file moved under a recorded hash
    3  UNKNOWN — could not complete (network/DB); not a finding either way

Usage (from `backend/`):

    .venv/bin/python -m scripts.check_source_review
    .venv/bin/python -m scripts.check_source_review --json
    .venv/bin/python -m scripts.check_source_review --no-db   # evidence only
    .venv/bin/python -m scripts.check_source_review --packaged  # offline bundle capability check
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys

import httpx
from roleband_robots import path_allowed

from tracker.config import get_settings
from tracker.source_policy import collection_access
from tracker.source_review import (
    SOURCE_REVIEWS,
    FetchTier,
    ReviewResult,
    RobotsStatus,
    effective_review,
)

HOLDS, MOVED, DRIFTED, SKIPPED, UNKNOWN = "holds", "moved", "drifted", "skipped", "unknown"


def _looks_like_html(body: str) -> bool:
    """A host serving its app shell for an unknown path (jobs.apple.com does)
    answers with markup, which is not a robots file however it is statused."""
    return "<html" in body[:200].lower()


async def check_evidence(client: httpx.AsyncClient, provider: str) -> dict:
    """Re-read one provider's robots file and compare against the register."""
    entry = SOURCE_REVIEWS[provider]
    robots = entry.robots
    base = {"provider": provider, "recorded": robots.status.value,
            "review": entry.review.value}

    # Our own denial outranks re-verification. Re-reading the reason would still
    # be a request to a source we have decided not to contact.
    if collection_access(provider).denied or robots.status is RobotsStatus.UNVERIFIED:
        return {**base, "state": SKIPPED,
                "detail": "denied provider: not fetched, by policy"}
    if robots.robots_url is None:
        return {**base, "state": SKIPPED, "detail": "no robots URL recorded"}
    # The identified client gets this host's challenge, robots file included, as
    # the register records. Only a user's consent releases the walled tier, so
    # the check neither reads the challenge as drift nor escalates on its own.
    if entry.refuses_identified_client:
        return {**base, "state": SKIPPED,
                "detail": "refuses the identified client: re-read its robots file on its walled tier by hand"}

    try:
        response = await client.get(robots.robots_url)
    except httpx.HTTPError as exc:
        return {**base, "state": UNKNOWN, "detail": f"{type(exc).__name__}: {exc}"}

    body = response.text or ""

    # A broken server is not an answer about the file. RFC 9309 §2.3.1.4 puts
    # 5xx in its own class — "unreachable", where the file is *undefined* and a
    # crawler must assume complete disallow — as against a 404, which says the
    # file genuinely is not there. Collapsing them would report a 503 as
    # `holds`/"still unserved", i.e. re-confirm "no robots
    # file, nothing restricts us" on the strength of a server having fallen
    # over. That is the wrong direction to be wrong in: an outage read as
    # renewed permission. It reports `unknown` and fails the pass, so prior
    # evidence stands and someone re-reads it when the host is up.
    if response.status_code >= 500:
        return {**base, "state": UNKNOWN,
                "detail": f"unreachable (HTTP {response.status_code}); evidence not re-read"}

    served = response.status_code == 200 and not _looks_like_html(body)

    if not served:
        now = RobotsStatus.NOT_SERVED
        if robots.status is now:
            return {**base, "state": HOLDS, "detail": f"still unserved (HTTP {response.status_code})"}
        return {**base, "state": DRIFTED, "now": now.value,
                "detail": f"recorded {robots.status.value}, now HTTP {response.status_code}"}

    if robots.status is RobotsStatus.NOT_SERVED:
        return {**base, "state": DRIFTED, "now": "served",
                "detail": "a robots file now exists where none was served"}

    digest = hashlib.sha256(body.encode()).hexdigest()
    target = robots.target or "/"
    allowed, rule = path_allowed(body, target)
    now = RobotsStatus.ALLOWED if allowed else RobotsStatus.DISALLOWED
    rule_text = f"{rule[0]}: {rule[1]}" if rule else None
    result = {**base, "now": now.value, "rule": rule_text, "sha256": digest}

    # The verdict is the finding; the bytes are only how we noticed.
    if now is not robots.status or rule_text != robots.winning_rule:
        return {**result, "state": DRIFTED,
                "detail": f"verdict {robots.status.value} -> {now.value}"
                          f" (rule {robots.winning_rule!r} -> {rule_text!r})"}
    if digest != robots.sha256:
        return {**result, "state": MOVED,
                "detail": "file changed, same verdict for our route"}
    return {**result, "state": HOLDS, "detail": "byte-identical"}


async def check_all_evidence(delay: float) -> list[dict]:
    settings = get_settings()
    headers = {"user-agent": settings.scraper_user_agent}
    results: list[dict] = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as client:
        for index, provider in enumerate(sorted(SOURCE_REVIEWS)):
            if index:
                await asyncio.sleep(delay)
            results.append(await check_evidence(client, provider))
    return results


async def gate_impact() -> list[dict]:
    """Every enabled company, and what a review gate would do to it.

    Imported lazily so `--no-db` stays usable with no Postgres.
    """
    from tracker.company_store import get_active_targets
    from tracker.db.session import session_scope

    async with session_scope() as session:
        targets = await get_active_targets(session)

    rows = []
    for slug, target in sorted(targets.items()):
        provider = target["adapter"]
        decision = effective_review(provider, company=slug)
        rows.append({
            "company": slug,
            "provider": provider,
            "decision": decision.value,
            "would_pause": decision is not ReviewResult.APPROVED,
        })
    return rows


def exit_code(evidence: list[dict], error: str | None = None) -> int:
    """0 holds / 1 drift / 3 unverifiable.

    `moved` does not fail: the file changed and our route's verdict did not, so
    there is nothing to act on. `skipped` does not fail either — declining to
    contact a denied source is the policy working, not a gap.
    """
    states = [row["state"] for row in evidence]
    if DRIFTED in states:
        return 1
    return 3 if (UNKNOWN in states or error) else 0


def _render(evidence: list[dict], impact: list[dict], error: str | None) -> None:
    print("=== recorded robots evidence ===")
    for row in sorted(evidence, key=lambda r: (r["state"] != DRIFTED, r["provider"])):
        mark = {DRIFTED: "DRIFT ", MOVED: "moved ", HOLDS: "holds ",
                SKIPPED: "skip  ", UNKNOWN: "?     "}[row["state"]]
        print(f"  {mark} {row['provider']:<11} recorded={row['recorded']:<12} {row['detail']}")

    disallowed = [p for p, e in SOURCE_REVIEWS.items()
                  if e.robots.status is RobotsStatus.DISALLOWED]
    if disallowed:
        print(f"\n  robots DISALLOWS our recorded route for: {', '.join(sorted(disallowed))}")
        print("  (a technical directive, not the whole permission question —")
        print("   RFC 9309 §1 grants no authorization either way)")

    print("\n=== what a review gate would pause ===")
    if error:
        print(f"  could not read the roster: {error}")
    elif not impact:
        print("  no enabled companies")
    else:
        paused = [row for row in impact if row["would_pause"]]
        for row in impact:
            flag = "PAUSE" if row["would_pause"] else "run  "
            print(f"  {flag} {row['company']:<18} {row['provider']:<11} {row['decision']}")
        print(f"\n  {len(paused)} of {len(impact)} enabled companies would pause.")
        if len(paused) == len(impact):
            print("  Every enabled source is unreviewed, so activating the gate")
            print("  stops all collection. Whether to activate it is a maintainer")
            print("  decision; this register enforces nothing.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--delay", type=float, default=1.5, help="seconds between fetches")
    parser.add_argument("--no-db", action="store_true", help="skip the roster impact pass")
    parser.add_argument("--packaged", action="store_true", help="offline: fail if a source needs a tier absent from the app")
    args = parser.parse_args()

    if args.packaged:
        supported = {FetchTier.IDENTIFIED, FetchTier.BROWSER_IDENTITY, FetchTier.TLS_FINGERPRINT}
        missing = [(name, row.fetch_tier) for name, row in SOURCE_REVIEWS.items() if row.fetch_tier not in supported]
        for name, tier in sorted(missing):
            print(f"{name}: {tier.value} requires a browser runtime absent from the app")
        return 1 if missing else 0

    evidence = asyncio.run(check_all_evidence(args.delay))

    impact: list[dict] = []
    error: str | None = None
    if not args.no_db:
        try:
            impact = asyncio.run(gate_impact())
        except Exception as exc:  # noqa: BLE001 - any DB failure is the same answer
            error = f"{type(exc).__name__}: {exc}"

    if args.json:
        print(json.dumps({"evidence": evidence, "gate_impact": impact,
                          "db_error": error}, indent=2))
    else:
        _render(evidence, impact, error)

    return exit_code(evidence, error)


if __name__ == "__main__":
    sys.exit(main())
