"""Provisioning + manifest contracts (pure logic; no network, no model load).

The download path itself is a network boundary and is not exercised here —
what pytest holds is everything a corrupt or half-provisioned state depends
on: tier choice, decision persistence, sha256 verification, and the pinned
manifest's integrity.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re

import pytest

from tracker.semantic import provision
from tracker.semantic.manifest import (
    MODEL_SPECS,
    TIER_FP32,
    TIER_INT8,
    ArtifactSpec,
    ModelSpec,
    spec_for,
)


@pytest.fixture
def tmp_models(tmp_path, monkeypatch):
    monkeypatch.setattr(provision, "DATA_DIR", tmp_path)
    return tmp_path / "models"


# --- tier choice -------------------------------------------------------------

def test_tier_for_ram_threshold():
    gib = 2**30
    assert provision.tier_for_ram(8 * gib) == TIER_INT8
    assert provision.tier_for_ram(16 * gib) == TIER_FP32
    assert provision.tier_for_ram(48 * gib) == TIER_FP32
    # Detection failure fails safe: the smaller artifact.
    assert provision.tier_for_ram(None) == TIER_INT8


def test_resolve_tier_persists_first_decision(tmp_models, monkeypatch):
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 32 * 2**30)
    assert provision.resolve_tier() == TIER_FP32
    # A later launch on (apparently) different hardware must NOT re-decide —
    # re-deciding means re-downloading and a stale vector space.
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    assert provision.resolve_tier() == TIER_FP32
    record = json.loads((tmp_models / "provision.json").read_text())
    assert record["tier"] == TIER_FP32
    assert record["detected_ram_bytes"] == 32 * 2**30


def test_resolve_tier_survives_corrupt_decision_file(tmp_models, monkeypatch):
    tmp_models.mkdir(parents=True)
    (tmp_models / "provision.json").write_text("{not json")
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: None)
    assert provision.resolve_tier() == TIER_INT8


# --- user override ------------------------------------------------

def test_set_tier_overrides_the_hardware_verdict(tmp_models, monkeypatch):
    """The case the override exists for: detection fails, so auto pins a large
    Mac to the small artifact permanently. A user choice must beat it AND be
    what every later sync reader sees, since the encoder reads only this file."""
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: None)
    assert provision.resolve_tier() == TIER_INT8  # auto, fail-safe

    assert provision.set_tier(TIER_FP32) == TIER_FP32
    assert provision.resolve_tier() == TIER_FP32
    record = provision.read_decision()
    assert record["tier"] == TIER_FP32
    assert record["chosen_by"] == "user"


def test_set_tier_none_restores_auto_detection(tmp_models, monkeypatch):
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    provision.set_tier(TIER_FP32)
    assert provision.resolve_tier() == TIER_FP32
    # Back to auto: the hardware verdict applies again, and is re-derived once.
    assert provision.set_tier(None) == TIER_INT8
    assert provision.read_decision()["chosen_by"] == "auto"


def test_set_tier_refuses_an_unpinned_tier(tmp_models):
    """Fail closed at the setter, not with a KeyError inside spec.tiers later."""
    with pytest.raises(ValueError, match="unknown embedding tier"):
        provision.set_tier("fp16")


def test_legacy_decision_file_reads_as_auto(tmp_models, monkeypatch):
    """A record written before `chosen_by` existed is an auto decision by
    construction. It must not read as corrupt — that would re-decide the tier
    on upgrade, which means a re-download and a stale corpus for every user."""
    tmp_models.mkdir(parents=True)
    (tmp_models / "provision.json").write_text(
        json.dumps({"tier": TIER_FP32, "detected_ram_bytes": 32 * 2**30})
    )
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    assert provision.resolve_tier() == TIER_FP32
    assert provision.read_decision()["chosen_by"] == "auto"


def test_tier_options_price_each_tier_with_its_tokenizer(tmp_models, monkeypatch):
    """The picker quotes what the download actually costs — the graph alone
    understates it, and `recommended` must track the hardware, not the choice."""
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    spec = spec_for("lightonai/DenseOn")
    options = {opt["tier"]: opt for opt in provision.tier_options(spec)}

    assert set(options) == {TIER_FP32, TIER_INT8}
    for tier, opt in options.items():
        assert opt["total_bytes"] == spec.tiers[tier].size + spec.tokenizer.size
        assert opt["installed"] is False  # tmp_models is empty
    assert options[TIER_INT8]["recommended"] is True
    assert options[TIER_FP32]["recommended"] is False

    # A user pinning fp32 does not make fp32 the *recommendation*: the two are
    # different claims, and conflating them would hide why a choice was made.
    provision.set_tier(TIER_FP32)
    assert provision.tier_options(spec)[1]["recommended"] is True  # int8 still


def test_nothing_is_recommended_when_ram_is_unknown(tmp_models, monkeypatch):
    """`tier_for_ram(None)` returns int8 as a FAIL-SAFE, which is not the claim
    "this suits your machine". Presented as one, the UI would tell a user with
    undetectable memory that int8 suits 0 GB of RAM."""
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: None)
    options = provision.tier_options(spec_for("lightonai/DenseOn"))
    assert [o["recommended"] for o in options] == [False, False]


def test_installed_is_an_existence_check_and_never_hashes(tmp_models, monkeypatch):
    """`tier_options` runs inside an async handler the Settings screen polls
    every 4s. `is_ready` falls through to a full sha256 when the marker is
    missing — 596 MB for the fp32 graph — which would block the event loop for
    every other request. "Already on this Mac" only needs to know whether a
    download is owed; the sha256 pin still gates the load itself."""
    spec = spec_for("lightonai/DenseOn")
    art = spec.tiers[TIER_INT8]
    path = provision.artifact_path(spec, art)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Right size, NO verification marker — the case that must not trigger a hash.
    path.write_bytes(b"\0" * art.size)
    tok = provision.artifact_path(spec, spec.tokenizer)
    tok.write_bytes(b"\0" * spec.tokenizer.size)

    def explode(_path):
        raise AssertionError("tier_options must not hash artifacts on a request path")

    real_sha256 = provision._sha256
    monkeypatch.setattr(provision, "_sha256", explode)
    options = {o["tier"]: o for o in provision.tier_options(spec)}
    assert options[TIER_INT8]["installed"] is True
    assert options[TIER_FP32]["installed"] is False
    assert provision.is_present(spec, TIER_INT8) is True

    # Trust is unchanged where it matters: the load path still verifies, and
    # these zero bytes are not the pinned artifact. Restore only the hash — a
    # blanket `monkeypatch.undo()` would also revert DATA_DIR and silently
    # re-point this at the machine's real, genuinely-valid artifacts.
    monkeypatch.setattr(provision, "_sha256", real_sha256)
    assert provision.is_ready(spec, TIER_INT8) is False


# --- verification ------------------------------------------------------------

def _tiny_spec(payload: bytes, tok: bytes) -> ModelSpec:
    art = ArtifactSpec("m.onnx", "m.onnx", hashlib.sha256(payload).hexdigest(), len(payload))
    return ModelSpec(
        name="tiny", repo="example/tiny", revision="0" * 40, dim=2, max_tokens=8,
        pooling="cls",
        tokenizer=ArtifactSpec("tokenizer.json", "tokenizer.json",
                               hashlib.sha256(tok).hexdigest(), len(tok)),
        tiers={TIER_FP32: art, TIER_INT8: art},
    )


def test_verification_accepts_pinned_bytes(tmp_models):
    spec = _tiny_spec(b"weights", b"tok")
    d = provision.model_dir(spec)
    d.mkdir(parents=True)
    (d / "m.onnx").write_bytes(b"weights")
    (d / "tokenizer.json").write_bytes(b"tok")
    assert provision.is_ready(spec, TIER_FP32)
    # Verified state is markered so 600 MB is not re-hashed every launch.
    assert (d / "m.onnx.sha256.ok").read_text().strip() == spec.tiers[TIER_FP32].sha256


def test_verification_discards_corrupt_artifact(tmp_models):
    spec = _tiny_spec(b"weights", b"tok")
    d = provision.model_dir(spec)
    d.mkdir(parents=True)
    (d / "m.onnx").write_bytes(b"wEights")  # right length, wrong bytes
    (d / "tokenizer.json").write_bytes(b"tok")
    assert not provision.is_ready(spec, TIER_FP32)
    assert not (d / "m.onnx").exists(), "a corrupt artifact must not survive to be loaded"
    with pytest.raises(provision.ModelNotReady):
        provision.require_ready(spec, TIER_FP32)


def test_stale_marker_does_not_bless_new_bytes(tmp_models):
    spec = _tiny_spec(b"weights", b"tok")
    d = provision.model_dir(spec)
    d.mkdir(parents=True)
    (d / "m.onnx").write_bytes(b"weights")
    (d / "tokenizer.json").write_bytes(b"tok")
    assert provision.is_ready(spec, TIER_FP32)
    # Same length, different content, marker left behind: must re-fail on hash…
    (d / "m.onnx").write_bytes(b"wEights")
    (d / "m.onnx.sha256.ok").write_text("bogus\n")
    assert not provision.is_ready(spec, TIER_FP32)


def test_provision_state_reports_progress(tmp_models):
    spec = _tiny_spec(b"weightsweights", b"tok")
    d = provision.model_dir(spec)
    d.mkdir(parents=True)
    state = provision.provision_state(spec, TIER_FP32)
    assert state.status == "missing"
    (d / "m.onnx.part").write_bytes(b"weights")
    state = provision.provision_state(spec, TIER_FP32)
    assert state.status == "downloading"
    assert 0 < state.downloaded_bytes < state.total_bytes


# --- manifest integrity ------------------------------------------------------

def test_every_spec_is_fully_pinned():
    for name, spec in MODEL_SPECS.items():
        assert name == spec.name
        assert re.fullmatch(r"[0-9a-f]{40}", spec.revision), "revision must be a commit sha, never a branch"
        for artifact in (spec.tokenizer, *spec.tiers.values()):
            assert re.fullmatch(r"[0-9a-f]{64}", artifact.sha256)
            assert artifact.size > 0
        assert set(spec.tiers) == {TIER_FP32, TIER_INT8}
        assert spec.pooling in ("cls", "mean")
        assert spec.dim > 0 and spec.max_tokens > 0


def test_spec_for_fails_closed():
    with pytest.raises(ValueError):
        spec_for("model-nobody-pinned")


# --- degradation contract ----------------------------------------------------

def test_embed_query_degrades_to_lexical_when_unprovisioned(monkeypatch):
    from tracker.semantic import embed

    def _not_ready():
        raise provision.ModelNotReady("weights pending")

    monkeypatch.setattr(embed, "get_model", _not_ready)
    assert asyncio.run(embed.embed_query("senior ai product leadership")) == []


def test_embed_texts_fails_honestly_when_unprovisioned(monkeypatch):
    from tracker.semantic import embed

    def _not_ready():
        raise provision.ModelNotReady("weights pending")

    monkeypatch.setattr(embed, "get_model", _not_ready)
    with pytest.raises(provision.ModelNotReady):
        embed.embed_texts(["a posting"])


def test_the_command_provisions_a_named_model_and_tier_instead_of_the_configured_one(tmp_models, monkeypatch):
    """CI provisions the golden test's reference model this way; without the
    flags the configured model at the machine's tier is what gets provisioned."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(provision, "ensure_artifacts", lambda spec, tier: calls.append((spec.name, tier)))
    monkeypatch.setattr(provision, "resolve_tier", lambda: TIER_INT8)
    monkeypatch.setattr("sys.argv", ["provision", "--model", "all-MiniLM-L6-v2", "--tier", TIER_FP32])
    provision.main()
    monkeypatch.setattr("sys.argv", ["provision"])
    provision.main()

    from tracker.config import get_settings

    assert calls == [("all-MiniLM-L6-v2", TIER_FP32), (get_settings().embedding_model, TIER_INT8)]
