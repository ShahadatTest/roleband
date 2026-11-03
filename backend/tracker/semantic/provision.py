"""Model provisioning — the app fetches its own weights, once, verified.

Zero user interaction by *default*: no token, no dialog, nothing to answer on
first run. The tier (fp32 vs int8) is chosen ONCE from detected **total
physical RAM** and persisted — available RAM fluctuates, and a re-decision on a
later launch would re-download and force a re-embed. Detection failure defaults
to int8 (fail safe, smaller).

The decision is **overridable**. Auto-detection is not evidence:
`detect_total_ram_bytes()` returning None pins a 64 GiB Mac to the smaller,
slower, less exact artifact permanently, and nothing on the machine could
correct it. So the file records **who decided** — `chosen_by: "auto" | "user"`
— and `set_tier()` is the one writer. Everything sync (`get_model`, the CLI,
eval scripts) still reads this file and nothing else; the durable user choice
lives in the shared DB (`semantic/tier_store.py`) and is pushed here by
`reconcile_tier()` on every warm, pipeline embed pass, and backfill, because
the file is per-checkout while the vectors it produces are per-user.

Integrity is ours, not the mirror's: every file is pinned by commit sha in the
URL *and* re-hashed against our own sha256 (`manifest.py`) after download and
on first use — a mirror can serve the wrong bytes at the right length, and ORT
will happily load a corrupt graph. Downloads resume via HTTP Range, land in a
`.part` file, and are renamed only after the hash matches, so a killed process
never leaves a plausible-looking corrupt artifact.

Never on a request path: `ensure_artifacts` is called from the `warm_model`
startup task and `deploy/install.sh` pre-warm. While weights are absent the
board stays fully usable (lexical search + first_seen order); failure here
backs off and retries next startup — never an error dialog.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tracker.platform.memory import SMALL_BELOW
from tracker.platform.memory import total_memory_bytes as detect_total_ram_bytes
from tracker.platform.paths import DATA_DIR
from tracker.semantic.manifest import TIER_FP32, TIER_INT8, ArtifactSpec, ModelSpec

logger = logging.getLogger(__name__)

#: >= 16 GiB total physical RAM takes the exact artifact; below takes the small one.
TIER_RAM_THRESHOLD = SMALL_BELOW

#: The only tiers a caller may name. Anything else is refused, never coerced —
#: an unknown tier would fall through to a KeyError deep inside `spec.tiers`.
TIERS: tuple[str, ...] = (TIER_FP32, TIER_INT8)

_DECISION_FILE = "provision.json"

#: Ordered mirrors; first success wins. Own release CDN belongs FIRST when it
#: exists — HF's anonymous limit is per-IP and pools corporate NAT users with
#: every other `transformers` user, so first-run must not depend on it alone.
_MIRRORS: tuple[str, ...] = ("https://huggingface.co/{repo}/resolve/{revision}/{path}",)


class ModelNotReady(RuntimeError):
    """Weights absent, partial, or failing verification. Callers degrade
    (API: lexical only) or fail honestly (pipeline embed pass: fatal)."""

    def __init__(self, message: str, *, reason: str = "download_failed") -> None:
        super().__init__(message)
        self.reason = reason


def models_dir() -> Path:
    return DATA_DIR / "models"


def model_dir(spec: ModelSpec) -> Path:
    return models_dir() / spec.name


def tier_for_ram(ram_bytes: int | None) -> str:
    if ram_bytes is None:
        return TIER_INT8
    return TIER_FP32 if ram_bytes >= TIER_RAM_THRESHOLD else TIER_INT8


def _decision_path() -> Path:
    return models_dir() / _DECISION_FILE


def read_decision() -> dict | None:
    """The persisted decision, or None when absent/unusable.

    A record without `chosen_by` is an auto decision by construction, so it
    reads as `"auto"` rather than as corrupt: a user who never touched this
    must not have their tier re-decided by an upgrade.
    """
    path = _decision_path()
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("unreadable %s; re-deciding tier", path)
        return None
    if not isinstance(record, dict) or record.get("tier") not in TIERS:
        return None
    record.setdefault("chosen_by", "auto")
    record.setdefault("detected_ram_bytes", None)
    return record


def set_tier(choice: str | None) -> str:
    """Write the active tier through to the per-checkout decision file.

    `choice` is a tier slug the user picked, or None for "follow detected RAM".
    The ONLY writer: every sync reader (`get_model`, the provision CLI, eval
    scripts) trusts this file, so a user choice that never lands here would be
    a choice the encoder ignores.
    """
    if choice is not None and choice not in TIERS:
        raise ValueError(f"unknown embedding tier {choice!r}; expected one of {TIERS}")
    ram = detect_total_ram_bytes()
    tier = choice or tier_for_ram(ram)
    record = {"tier": tier, "detected_ram_bytes": ram, "chosen_by": "user" if choice else "auto"}
    path = _decision_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1) + "\n")
    logger.info(
        "embedding tier set: %s (%s; detected RAM %s bytes)", tier, record["chosen_by"], ram
    )
    return tier


def would_resolve(choice: str | None) -> str:
    """The tier `set_tier(choice)` would land on, WITHOUT writing anything.

    Lets a caller decide whether a switch actually moves the tier before it
    commits to anything — the endpoint needs that to invalidate the corpus in
    the same transaction as the choice, rather than after the file has already
    changed.
    """
    if choice is not None and choice not in TIERS:
        raise ValueError(f"unknown embedding tier {choice!r}; expected one of {TIERS}")
    return choice or tier_for_ram(detect_total_ram_bytes())


def resolve_tier() -> str:
    """The persisted decision; decide from RAM and persist on first call.

    Deliberately takes no override argument. A caller that cannot see the DB
    (the CLI, an eval script) must NOT be able to silently reset a user's
    choice by passing None — that is what `set_tier` and `reconcile_tier` are
    for, and both are reached only from a session-holding caller.
    """
    record = read_decision()
    if record is not None:
        return record["tier"]
    return set_tier(None)


@dataclass(frozen=True)
class ProvisionState:
    status: str            # ready | downloading | missing
    tier: str
    downloaded_bytes: int
    total_bytes: int


def _artifacts(spec: ModelSpec, tier: str) -> list[ArtifactSpec]:
    return [spec.tiers[tier], spec.tokenizer]


def is_present(spec: ModelSpec, tier: str) -> bool:
    """On disk at the pinned size — an existence check, NOT a verification.

    Deliberately not `is_ready`: that one falls through to a full sha256 when
    the `.sha256.ok` marker is missing, which for the fp32 graph means reading
    hundreds of MB. `tier_options` runs on every `GET /api/intelligence` inside
    an async handler, and the Settings screen polls it: a hash there blocks the
    event loop for every other request. "Already on this Mac" only needs to know
    whether a download is owed; the sha256 pin still decides before the graph is
    ever loaded (`require_ready`), which is where trust actually matters.
    """
    return all(
        (path := artifact_path(spec, a)).exists() and path.stat().st_size == a.size
        for a in _artifacts(spec, tier)
    )


def tier_options(spec: ModelSpec) -> list[dict]:
    """What the user may pick between, priced in bytes actually downloaded.

    `total_bytes` includes the tokenizer because that is what the download
    costs; `installed` says whether this tier is already on disk, which is the
    difference between "switch" and "switch and wait". Order is fp32 first:
    the exact artifact is the better one wherever it fits, so the list reads
    best-to-smallest rather than by any RAM ordering.

    Nothing is `recommended` when RAM detection failed. `tier_for_ram(None)`
    returns int8 as a **fail-safe**, which is not the same claim as "this suits
    your machine": presenting it as one would tell a user with undetectable
    memory that int8 "suits 0 GB of RAM".
    """
    ram = detect_total_ram_bytes()
    return [
        {
            "tier": tier,
            "total_bytes": spec.tiers[tier].size + spec.tokenizer.size,
            "recommended": ram is not None and tier == tier_for_ram(ram),
            "installed": is_present(spec, tier),
        }
        for tier in TIERS
        if tier in spec.tiers
    ]


def artifact_path(spec: ModelSpec, artifact: ArtifactSpec) -> Path:
    return model_dir(spec) / artifact.local_name


def _marker(path: Path) -> Path:
    return path.with_name(path.name + ".sha256.ok")


def _verified(spec: ModelSpec, artifact: ArtifactSpec) -> bool:
    """True iff the file exists, has the pinned size, and its hash was checked.

    The full hash runs once; the marker (containing the verified sha) lets
    later launches trust size+marker instead of re-hashing the graph every start.
    """
    path = artifact_path(spec, artifact)
    if not path.exists() or path.stat().st_size != artifact.size:
        return False
    marker = _marker(path)
    if marker.exists() and marker.read_text().strip() == artifact.sha256:
        return True
    digest = _sha256(path)
    if digest != artifact.sha256:
        logger.warning("artifact %s failed sha256 verification; discarding", path)
        path.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
        return False
    marker.write_text(artifact.sha256 + "\n")
    return True


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_ready(spec: ModelSpec, tier: str) -> bool:
    return all(_verified(spec, a) for a in _artifacts(spec, tier))


def require_ready(spec: ModelSpec, tier: str) -> None:
    """Refuse to load an unprovisioned model, stating only what is true here.

    The consequence belongs to the CALLER: `embed_query` catches this and
    degrades search, while the pipeline's embed pass is fatal by design, so a
    promise of lexical fallback here would be false in a scrape that just
    aborted on it. A caller that degrades says so where it degrades.
    """
    if not is_ready(spec, tier):
        raise ModelNotReady(
            f"embedding model {spec.name} ({tier}) is not provisioned yet "
            f"(expected under {model_dir(spec)})"
        )


def provision_state(spec: ModelSpec, tier: str) -> ProvisionState:
    total = sum(a.size for a in _artifacts(spec, tier))
    done = 0
    partial = False
    for a in _artifacts(spec, tier):
        path = artifact_path(spec, a)
        if _verified(spec, a):
            done += a.size
        else:
            part = path.with_name(path.name + ".part")
            if part.exists():
                partial = True
                done += min(part.stat().st_size, a.size)
    if done >= total:
        return ProvisionState("ready", tier, total, total)
    return ProvisionState("downloading" if partial else "missing", tier, done, total)


def progress_state(spec: ModelSpec, tier: str) -> ProvisionState:
    """Read byte counts and verified markers without hashing files."""
    total = sum(a.size for a in _artifacts(spec, tier))
    done = 0
    complete = True
    for artifact in _artifacts(spec, tier):
        path = artifact_path(spec, artifact)
        try:
            verified = path.stat().st_size == artifact.size and _marker(path).read_text().strip() == artifact.sha256
        except OSError:
            verified = False
        if verified:
            done += artifact.size
        else:
            complete = False
            part = path.with_name(path.name + ".part")
            if part.exists():
                done += min(part.stat().st_size, artifact.size)
    return ProvisionState("ready" if complete else "downloading", tier, done, total)


def ensure_artifacts(spec: ModelSpec, tier: str, *, attempts: int = 3,
                     progress: Callable[[ProvisionState], None] | None = None) -> None:
    """Download and verify anything missing. Blocking; background callers only."""
    def report() -> None:
        if progress is not None:
            progress(progress_state(spec, tier))

    report()
    for artifact in _artifacts(spec, tier):
        if _verified(spec, artifact):
            report()
            continue
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                if progress is None:
                    _download(spec, artifact)
                else:
                    _download(spec, artifact, progress=report)
                if _verified(spec, artifact):
                    report()
                    break
                last_error = ModelNotReady(f"{artifact.local_name} failed verification after download")
            except Exception as exc:  # noqa: BLE001 — network path; retry then surface
                last_error = exc
                time.sleep(min(2**attempt * 2, 30))
        else:
            raise ModelNotReady(
                f"could not provision {spec.name}/{artifact.local_name}: {last_error}",
                reason=getattr(last_error, "reason", "download_failed"),
            ) from last_error
    report()
    logger.info("embedding model %s (%s) provisioned", spec.name, tier)


def _download(spec: ModelSpec, artifact: ArtifactSpec, *, progress: Callable[[], None] | None = None) -> None:
    import httpx

    dest = artifact_path(spec, artifact)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    offset = part.stat().st_size if part.exists() else 0
    if offset == artifact.size and _sha256(part) == artifact.sha256:
        part.replace(dest)
        _marker(dest).write_text(artifact.sha256 + "\n")
        if progress is not None:
            progress()
        return
    if offset > artifact.size:
        part.unlink()
        offset = 0

    errors: list[str] = []
    reason = "download_failed"
    for mirror in _MIRRORS:
        url = mirror.format(repo=spec.repo, revision=spec.revision, path=artifact.repo_path)
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        try:
            with httpx.stream(
                "GET", url, headers=headers, follow_redirects=True, timeout=httpx.Timeout(30, read=120)
            ) as response:
                if offset and response.status_code != 206:
                    # Mirror ignored Range: start over rather than corrupt.
                    part.unlink(missing_ok=True)
                    offset = 0
                    if response.status_code != 200:
                        response.raise_for_status()
                elif not offset:
                    response.raise_for_status()
                if offset and not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                    raise ModelNotReady("download resumed at an unexpected offset", reason="verification_failed")
                mode = "ab" if offset else "wb"
                received = offset
                with open(part, mode) as f:
                    for chunk in response.iter_bytes(1 << 20):
                        received += len(chunk)
                        if received > artifact.size:
                            raise ModelNotReady("download exceeded its pinned size", reason="verification_failed")
                        f.write(chunk)
                        f.flush()
                        if progress is not None:
                            progress()
            if part.stat().st_size < artifact.size:
                raise ModelNotReady("download is incomplete", reason="offline")
            digest = _sha256(part)
            if digest != artifact.sha256:
                part.unlink(missing_ok=True)
                raise ModelNotReady(
                    f"{artifact.local_name}: sha256 mismatch from {mirror.split('/')[2]} "
                    f"(got {digest[:12]}…, pinned {artifact.sha256[:12]}…)", reason="verification_failed",
                )
            part.replace(dest)
            _marker(dest).write_text(artifact.sha256 + "\n")
            logger.info("downloaded %s (%d bytes)", dest, artifact.size)
            return
        except ModelNotReady:
            raise
        except Exception as exc:  # noqa: BLE001 — try next mirror
            reason = "offline" if isinstance(exc, httpx.TransportError) else "download_failed"
            errors.append(f"{mirror.split('/')[2]}: {exc}")
            offset = part.stat().st_size if part.exists() else 0
    raise ModelNotReady(f"all mirrors failed for {artifact.local_name}: {'; '.join(errors)}", reason=reason)


def sideload(spec: ModelSpec, tier: str, source_dir: Path) -> None:
    """Operator path: copy pre-fetched artifacts in, then verify like any other.

    A side-loaded file gets no trust the downloader wouldn't get — the sha256
    pin decides, so a wrong or tampered copy is discarded, not loaded.
    """
    import shutil

    dest = model_dir(spec)
    dest.mkdir(parents=True, exist_ok=True)
    for artifact in _artifacts(spec, tier):
        src = source_dir / artifact.local_name
        if not src.exists():
            src = source_dir / Path(artifact.repo_path).name
        if src.exists():
            shutil.copyfile(src, artifact_path(spec, artifact))
    require_ready(spec, tier)


def main() -> None:
    """Pre-warm entry for deploy/install.sh: provision the configured model now.

        python -m tracker.semantic.provision                # download + verify
        python -m tracker.semantic.provision --offline DIR  # side-load a copy
        python -m tracker.semantic.provision --model all-MiniLM-L6-v2 --tier fp32

    `--model`/`--tier` provision a named model instead of the configured one;
    CI uses them for the golden-vector test's reference model.
    """
    import argparse

    from tracker.config import get_settings
    from tracker.semantic.manifest import spec_for

    parser = argparse.ArgumentParser(description="Provision the embedding model artifacts.")
    parser.add_argument("--offline", type=Path, default=None,
                        help="side-load verified artifacts from this directory instead of downloading")
    parser.add_argument("--model", default=None, help="a model in the manifest; default: the configured one")
    parser.add_argument("--tier", default=None, choices=TIERS,
                        help="default: the tier this machine resolves")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    spec = spec_for(args.model or get_settings().embedding_model)
    tier = args.tier or resolve_tier()
    if args.offline:
        sideload(spec, tier, args.offline)
    else:
        ensure_artifacts(spec, tier)
    state = provision_state(spec, tier)
    print(f"{spec.name} ({tier}): {state.status} — {state.downloaded_bytes}/{state.total_bytes} bytes")


def provenance_record(spec: ModelSpec, tier: str) -> dict:
    """What actually got provisioned — mirrored to app_settings by warm_model."""
    return {
        "model": spec.name,
        "repo": spec.repo,
        "revision": spec.revision,
        "tier": tier,
        "detected_ram_bytes": detect_total_ram_bytes(),
        "artifact_sha256": spec.tiers[tier].sha256,
        "tokenizer_sha256": spec.tokenizer.sha256,
        "dim": spec.dim,
        "max_tokens": spec.max_tokens,
    }


if __name__ == "__main__":
    main()
