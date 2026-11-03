"""Pinned embedding-model artifacts — the provenance record provisioning trusts.

Same discipline as `tracker/vendored.py`: an artifact nobody can re-check is
indistinguishable from a current one. Every model the app may download is
declared here with an **immutable 40-char commit sha** (never a branch) and
**our own sha256 per file** — `hf_hub_download` verifies byte length only, and
ONNX Runtime will happily load a corrupt graph, so both pins are load-bearing,
not ceremony.

Runtime shape (pooling, window, prefixes) lives on the spec too: pooling comes
from the model's own config, never from habit — mean-pooling a CLS model
produces plausible-looking wrong vectors and nothing raises.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

#: Tier slugs, chosen once per machine by detected total RAM (provision.py).
TIER_FP32 = "fp32"
TIER_INT8 = "int8"


@dataclass(frozen=True)
class ArtifactSpec:
    repo_path: str    # path inside the upstream repo at `revision`
    local_name: str   # filename inside the model's local artifact dir
    sha256: str       # our own pin, verified after download and before load
    size: int         # bytes; a fast pre-check and the progress denominator


@dataclass(frozen=True)
class ModelSpec:
    name: str                 # the `embedding_model` settings value this serves
    repo: str                 # upstream HF repo id, fetched through `provision._MIRRORS`
    revision: str             # immutable 40-char commit sha
    dim: int
    max_tokens: int           # OUR window; never the wrapper's max_seq_length default
    pooling: str              # "cls" | "mean" — from the model's own config
    tokenizer: ArtifactSpec
    tiers: Mapping[str, ArtifactSpec]
    query_prefix: str = ""
    document_prefix: str = ""


_MINILM_FP32 = ArtifactSpec(
    repo_path="onnx/model.onnx",
    local_name="model.fp32.onnx",
    sha256="6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452",
    size=90405214,
)

MODEL_SPECS: Mapping[str, ModelSpec] = MappingProxyType(
    {
        # The shipped model. ModernBERT-family encoder, 149M params, CLS
        # pooling per its own 1_Pooling config, prompts "query: "/"document: "
        # from config_sentence_transformers.json (trailing spaces are part of
        # the string). Window is 4096 FLAT on every machine: 8192 gives
        # practically the same vectors while 2048 shifts ranks, so 4096, not
        # tiered, not configurable. Its sentence_bert_config.json says 512; that is
        # the wrapper caller default, not a capability (8192), and we drive
        # raw ONNX. fp32 is exact AND faster on ARM; int8 is a size choice
        # for <16 GiB machines, never a speed one.
        "lightonai/DenseOn": ModelSpec(
            name="lightonai/DenseOn",
            repo="onnx-community/DenseOn-ONNX",
            revision="8606070c911ab26c582ce23db387abd3885541f2",
            dim=768,
            max_tokens=4096,
            pooling="cls",
            query_prefix="query: ",
            document_prefix="document: ",
            tokenizer=ArtifactSpec(
                repo_path="tokenizer.json",
                local_name="tokenizer.json",
                sha256="3703d011b3ee259e00b59b60772f8fd54998d79e8fa5a1388d507eff28f8f09e",
                size=3583485,
            ),
            tiers=MappingProxyType(
                {
                    TIER_FP32: ArtifactSpec(
                        repo_path="onnx/model.onnx",
                        local_name="model.fp32.onnx",
                        sha256="6cad6d4f0162f53397fd11cba99d28ce876bbe6b4675dda223af83862ae08ac6",
                        size=596570031,
                    ),
                    TIER_INT8: ArtifactSpec(
                        repo_path="onnx/model_int8.onnx",
                        local_name="model.int8.onnx",
                        sha256="73920e2aa82fcc9b1b1020dfe0a39e2df69e14b7a8c7d7a8c4dbb1949acd1364",
                        size=149906833,
                    ),
                }
            ),
        ),
        # The golden-vector parity reference: `tests/test_embedding_golden.py`
        # pins the ONNX runtime against a torch-recorded fixture of this model,
        # independent of the configured model. The small fp32 graph serves
        # both tiers: int8 exists to shrink large artifacts, not this one.
        "all-MiniLM-L6-v2": ModelSpec(
            name="all-MiniLM-L6-v2",
            repo="sentence-transformers/all-MiniLM-L6-v2",
            revision="1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
            dim=384,
            max_tokens=256,
            pooling="mean",
            tokenizer=ArtifactSpec(
                repo_path="tokenizer.json",
                local_name="tokenizer.json",
                sha256="be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037",
                size=466247,
            ),
            tiers=MappingProxyType({TIER_FP32: _MINILM_FP32, TIER_INT8: _MINILM_FP32}),
        ),
    }
)


def spec_for(name: str) -> ModelSpec:
    """Fail closed: an unpinned model name must never reach the downloader."""
    try:
        return MODEL_SPECS[name]
    except KeyError:
        raise ValueError(f"embedding model {name!r} has no pinned artifact manifest") from None
