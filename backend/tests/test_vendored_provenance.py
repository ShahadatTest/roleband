"""Vendored code must stay traceable to an upstream we can re-check.

RoleBand ships no scraper engine — the only upstream code here is a vendored
snapshot, updated by reviewed change and never by dependency automation. The
failure mode that policy creates is silence: a stale snapshot looks exactly like
a current one, so upstream fixes never arrive and nothing says so.

The registry is what makes staleness decidable, and these tests are what stop it
rotting: a recorded origin can name a module the vendored symbol never lived
in, and nothing catches it unless something executes the claim.

Live fetching belongs in `scripts.check_vendored_upstream`, never here
(`docs/testing.md`: tests do not fetch live sources). What is tested here is
the registry's completeness and the checker's verdict logic, against a mocked
transport.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import httpx
import pytest

from scripts.check_vendored_upstream import check
from tracker.vendored import VENDORED, VendoredArtifact, by_name

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
#: backend/tests/<this file> -> repo root; `local_path` is repo-relative.
_REPO_ROOT = Path(__file__).resolve().parents[2]


# --- the registry itself ---------------------------------------------------- #


def test_registry_is_not_empty():
    """A guard against the registry being emptied to make the gate quiet."""
    assert VENDORED, "vendored code exists; the registry is how it stays traceable"


@pytest.mark.parametrize("artifact", VENDORED, ids=lambda a: a.name)
def test_every_artifact_carries_complete_provenance(artifact: VendoredArtifact):
    """Every field a reviewer needs to diff a candidate update, or the entry is
    decoration. The sha256 in particular: without it "has upstream moved?" is a
    memory rather than a question anyone can answer."""
    assert artifact.name and artifact.local_path
    if artifact.source_url:
        assert artifact.source_url.startswith("https://") and not artifact.github_repo
    else:
        assert artifact.github_repo.count("/") == 1, "owner/repo"
        assert not artifact.source_url, "a tagged GitHub file is fetched by its ref"
    # Source OR data: `countries.py` is generated from an upstream JSON blob
    # rather than copied from upstream Python. The provenance obligation is
    # identical either way — a dataset nobody can re-check is exactly as stale
    # as a code snapshot nobody can re-check.
    assert artifact.upstream_path.endswith((".py", ".json", ".zip", ".txt", ".tar.gz"))
    assert _SHA256.match(artifact.sha256), "sha256 of the upstream blob at `ref`"
    assert artifact.licence, "the notice is a licence obligation, not a nicety"
    assert artifact.symbols, "record WHAT was taken, or a diff has no scope"


@pytest.mark.parametrize("artifact", VENDORED, ids=lambda a: a.name)
def test_pin_is_an_immutable_ref_not_a_branch(artifact: VendoredArtifact):
    """A recorded hash against a moving branch is meaningless the moment
    upstream commits — it would report drift forever, or worse, be silently
    re-pinned to whatever HEAD happened to be."""
    assert artifact.ref not in {"main", "master", "HEAD", "latest"}
    if artifact.rolling:
        assert re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", artifact.ref), f"{artifact.ref!r} is not a snapshot date"
    else:
        assert re.match(r"^v?\d+\.\d+", artifact.ref), f"{artifact.ref!r} is not a version tag"


@pytest.mark.parametrize("artifact", VENDORED, ids=lambda a: a.name)
def test_local_file_exists_and_names_its_licence(artifact: VendoredArtifact):
    """The registry pointing at a file that moved is the same class of rot as
    a docstring pointing at the wrong upstream module."""
    local = _REPO_ROOT / artifact.local_path
    assert local.is_file(), f"{artifact.local_path} does not exist"
    assert artifact.licence in local.read_text(), "licence notice must live in the file too"


def test_registry_lookup_is_by_name():
    assert by_name("extract-sanitizer").github_repo == "D4Vinci/Scrapling"
    with pytest.raises(KeyError):
        by_name("no-such-artifact")


# --- the checker's verdict logic -------------------------------------------- #


def _artifact(sha: str) -> VendoredArtifact:
    return VendoredArtifact(
        name="fake",
        local_path="backend/tracker/x.py",
        github_repo="acme/widget",
        ref="v1.0.0",
        upstream_path="widget/core.py",
        sha256=sha,
        licence="BSD-3-Clause",
        symbols=("thing",),
    )


def _client(*, pinned: bytes, latest_tag: str, latest: bytes | None = None, api_status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.github.com" in url:
            return httpx.Response(api_status, json={"tag_name": latest_tag})
        if f"/{latest_tag}/" in url:
            return httpx.Response(200, content=latest if latest is not None else pinned)
        return httpx.Response(200, content=pinned)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_release_that_does_not_touch_our_file_is_not_drift():
    """The noise question, and the reason this compares artifacts rather than
    releases. An upstream release can rewrite code we do not use and leave our
    vendored file byte-identical; a release-level check would report that
    change, and a check that cries wolf gets muted."""
    body = b"upstream source"
    art = _artifact(hashlib.sha256(body).hexdigest())

    with _client(pinned=body, latest_tag="v1.1.0") as c:
        result = check(art, c)

    assert result["status"] == "release-only"
    assert result["latest_ref"] == "v1.1.0"


def test_changed_upstream_file_is_drift():
    body = b"upstream source"
    art = _artifact(hashlib.sha256(body).hexdigest())

    with _client(pinned=body, latest_tag="v2.0.0", latest=b"upstream source, patched") as c:
        result = check(art, c)

    assert result["status"] == "drift"
    assert result["latest_sha256"] != art.sha256
    assert result["latest_url"].endswith("/v2.0.0/widget/core.py"), "point the reviewer at it"


def test_pin_that_no_longer_hashes_as_recorded_beats_every_other_verdict():
    """A wrong record makes the drift answer meaningless, so it is reported as
    its own thing rather than as drift — the fix is different (re-verify the
    record) and it must not read as "upstream changed"."""
    art = _artifact(hashlib.sha256(b"what we recorded").hexdigest())

    with _client(pinned=b"something else entirely", latest_tag="v1.0.0") as c:
        result = check(art, c)

    assert result["status"] == "pin-broken"
    assert result["expected_sha256"] == art.sha256


def test_pinned_ref_already_latest_is_current():
    body = b"upstream source"
    art = _artifact(hashlib.sha256(body).hexdigest())

    with _client(pinned=body, latest_tag="v1.0.0") as c:
        assert check(art, c)["status"] == "current"


def test_versioned_source_archive_is_verified_without_a_github_release():
    from dataclasses import replace

    source = b"pinned source archive"
    artifact = replace(
        _artifact(hashlib.sha256(source).hexdigest()), github_repo="",
        source_url="https://example.org/widget-1.0.0.tar.gz",
    )
    def respond(request):
        assert str(request.url) == artifact.source_url
        return httpx.Response(200, content=source)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert check(artifact, client)["status"] == "pin-verified"


def test_changed_versioned_source_archive_is_a_broken_pin():
    from dataclasses import replace

    artifact = replace(
        _artifact(hashlib.sha256(b"expected source").hexdigest()), github_repo="",
        source_url="https://example.org/widget-1.0.0.tar.gz",
    )
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"changed"))) as client:
        assert check(artifact, client)["status"] == "pin-broken"


def _noop_client() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))


def _replaying_check(results):
    """A `check` stand-in that hands back one canned verdict per artifact."""
    pending = list(results)
    return lambda artifact, client: pending.pop(0)


def test_exit_code_precedence_is_worst_finding_first(monkeypatch):
    """CI branches on these numbers, and the ordering carries meaning: a broken
    pin outranks drift (a wrong record makes the drift answer worthless), and
    an unreachable upstream outranks nothing at all."""
    import scripts.check_vendored_upstream as mod

    cases = [
        ([{"status": "current"}], mod.EXIT_OK),
        ([{"status": "release-only"}, {"status": "current"}], mod.EXIT_OK),
        ([{"status": "unknown", "error": "boom"}, {"status": "current"}], mod.EXIT_UNKNOWN),
        ([{"status": "drift"}, {"status": "unknown", "error": "boom"}], mod.EXIT_DRIFT),
        ([{"status": "drift"}, {"status": "pin-broken"}], mod.EXIT_PIN_BROKEN),
    ]
    monkeypatch.setattr("sys.argv", ["check_vendored_upstream", "--json"])
    monkeypatch.setattr(mod, "_client", _noop_client)
    for results, expected in cases:
        monkeypatch.setattr(mod, "VENDORED", tuple(range(len(results))))
        monkeypatch.setattr(mod, "check", _replaying_check(results))
        assert mod.main() == expected, f"{[r['status'] for r in results]} -> {expected}"


def test_unreachable_upstream_is_unknown_never_a_verdict():
    """A network failure must never be able to say something about the code.
    `unknown` is why the scheduled job is non-blocking."""
    body = b"upstream source"
    art = _artifact(hashlib.sha256(body).hexdigest())

    with _client(pinned=body, latest_tag="v1.0.0", api_status=503) as c:
        result = check(art, c)

    assert result["status"] == "unknown"
    assert "503" in result["error"]


def _rolling(sha: str) -> VendoredArtifact:
    return VendoredArtifact(
        name="dump", local_path="backend/tracker/x.tsv", github_repo="", ref="2026.09.24",
        upstream_path="dump.zip", sha256=sha, licence="CC-BY-4.0", symbols=("row",),
        source_url="https://example.org/dump.zip", rolling=True,
    )


def test_a_rolling_dump_can_only_have_moved_never_a_broken_pin():
    """GeoNames republishes in place. Today's bytes differing from the snapshot
    is news for whoever wants newer data, not a broken pin, and the GitHub
    release API must not be asked about a source that is not on GitHub."""
    body = b"snapshot bytes"
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=b"newer bytes")

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        moved = check(_rolling(hashlib.sha256(body).hexdigest()), c)
        same = check(_rolling(hashlib.sha256(b"newer bytes").hexdigest()), c)

    assert moved["status"] == "snapshot-moved"
    assert same["status"] == "snapshot-current"
    assert all(url == "https://example.org/dump.zip" for url in seen)
