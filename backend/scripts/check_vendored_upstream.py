"""Has upstream moved under our vendored snapshots?

Vendored code deliberately never auto-follows upstream, but "never auto-update"
is not "never notice". For each entry in
`tracker.vendored` this:

1. **verifies the pin** — re-fetches the upstream blob at the recorded immutable
   ref and checks it still hashes to the recorded sha256. A mismatch means the
   record is wrong or the tag moved, and every other answer here is worthless
   until it is fixed;
2. **reports drift** — resolves the project's latest release and compares the
   same file there. Different hash = upstream changed the code we copied, so a
   human diffs it and decides.

The comparison is per **artifact**, not per release, and that distinction is the
difference between a check people read and one they mute: a Scrapling release
can rewrite other modules and leave `core/shell.py` byte-identical, so a
release-level check would cry wolf while telling us nothing about the
sanitizer.

Deliberately a script and not a test: tests never fetch live sources
(`docs/testing.md`), and a network failure must never be able to fail the
build. Exit codes are for CI:

    0  every pin verified, no artifact drift
    1  DRIFT — an upstream artifact changed; review it
    2  PIN BROKEN — a recorded hash does not match its own ref
    3  UNKNOWN — could not complete the check (network/API); not a failure

Usage (from `backend/`):

    .venv/bin/python -m scripts.check_vendored_upstream
    .venv/bin/python -m scripts.check_vendored_upstream --json

Set `GITHUB_TOKEN` to lift the 60/hour unauthenticated GitHub API limit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

import httpx

from tracker.vendored import VENDORED, VendoredArtifact

_TIMEOUT = 30.0
_UA = "roleband-vendored-provenance"

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_PIN_BROKEN = 2
EXIT_UNKNOWN = 3


class UpstreamUnavailable(RuntimeError):
    """The check could not be completed. Never a verdict about the code."""


def _client() -> httpx.Client:
    # No credential on the client: blob fetches from raw.githubusercontent.com
    # need none, and a token set here would ride along on every request. The
    # API call attaches its own.
    return httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": _UA})


def _api_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _blob_sha256(client: httpx.Client, url: str) -> str:
    resp = client.get(url)
    if resp.status_code != 200:
        raise UpstreamUnavailable(f"HTTP {resp.status_code} for {url}")
    return hashlib.sha256(resp.content).hexdigest()


def _latest_release(client: httpx.Client, repo: str) -> str:
    resp = client.get(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers=_api_headers(),
    )
    if resp.status_code != 200:
        raise UpstreamUnavailable(f"HTTP {resp.status_code} resolving latest release of {repo}")
    tag = resp.json().get("tag_name")
    if not tag:
        raise UpstreamUnavailable(f"{repo}: latest release carries no tag_name")
    return str(tag)


def check(artifact: VendoredArtifact, client: httpx.Client) -> dict:
    """One artifact's verdict. Never raises for a network problem."""
    result: dict = {
        "name": artifact.name,
        "local_path": artifact.local_path,
        "upstream": f"{artifact.github_repo}/{artifact.upstream_path}",
        "pinned_ref": artifact.ref,
        "status": "unknown",
    }
    if artifact.rolling:
        result["upstream"] = artifact.source_url
        return _check_rolling(artifact, client, result)
    try:
        pinned = _blob_sha256(client, artifact.raw_url)
        result["pinned_sha256_now"] = pinned
        if pinned != artifact.sha256:
            # The ref is supposed to be immutable, so this is our record being
            # wrong (or a retagged upstream) — not a code change to review.
            result["status"] = "pin-broken"
            result["expected_sha256"] = artifact.sha256
            return result

        if artifact.source_url:
            result["upstream"] = artifact.source_url
            result["status"] = "pin-verified"
            return result

        latest = _latest_release(client, artifact.github_repo)
        result["latest_ref"] = latest
        if latest == artifact.ref:
            result["status"] = "current"
            return result

        result["latest_url"] = artifact.raw_url_at(latest)
        latest_sha = _blob_sha256(client, result["latest_url"])
        result["latest_sha256"] = latest_sha
        # Upstream released, but did it touch OUR file?
        result["status"] = "drift" if latest_sha != artifact.sha256 else "release-only"
    except UpstreamUnavailable as exc:
        result["status"] = "unknown"
        result["error"] = str(exc)
    return result


def _check_rolling(artifact: VendoredArtifact, client: httpx.Client, result: dict) -> dict:
    """A rolling dump (GeoNames) keeps no versions, so its pin cannot break:
    the only question is whether today's file differs from our snapshot. A
    difference is news, not drift in code we copied; regenerate when newer data
    is wanted, reviewing the table diff."""
    try:
        now = _blob_sha256(client, artifact.source_url)
    except UpstreamUnavailable as exc:
        result["status"] = "unknown"
        result["error"] = str(exc)
        return result
    result["latest_sha256"] = now
    result["status"] = "snapshot-current" if now == artifact.sha256 else "snapshot-moved"
    return result


_LINES = {
    "pin-verified": "OK        the versioned source archive matches its recorded hash; releases are reviewed manually",
    "current": "OK        pinned ref is the latest release; nothing to review",
    "release-only": "OK        upstream released {latest_ref}, but this file is byte-identical",
    "drift": "DRIFT     {latest_ref} changed this file — diff it and decide",
    "pin-broken": "PIN BROKEN  {pinned_ref} no longer hashes as recorded",
    "snapshot-current": "OK        the rolling dump still matches our {pinned_ref} snapshot",
    "snapshot-moved": "NEWER     the rolling dump moved since our {pinned_ref} snapshot; regenerate when wanted",
    "unknown": "UNKNOWN   could not check: {error}",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    args = parser.parse_args()

    with _client() as client:
        results = [check(a, client) for a in VENDORED]

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            print(f"{r['name']}  ({r['local_path']})")
            print(f"  upstream {r['upstream']} @ {r['pinned_ref']}")
            print("  " + _LINES[r["status"]].format(**{**r, "error": r.get("error", "")}))
            if r["status"] == "drift":
                print(f"    pinned {r['pinned_ref']}: {r['pinned_sha256_now']}")
                print(f"    latest {r['latest_ref']}: {r['latest_sha256']}")
                print(f"    {r['latest_url']}")
            if r["status"] == "pin-broken":
                print(f"    recorded: {r['expected_sha256']}")
                print(f"    actual:   {r['pinned_sha256_now']}")
            print()

    statuses = {r["status"] for r in results}
    # Worst finding wins, and "could not check" is never a verdict about code.
    if "pin-broken" in statuses:
        return EXIT_PIN_BROKEN
    if "drift" in statuses:
        return EXIT_DRIFT
    if "unknown" in statuses:
        return EXIT_UNKNOWN
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
