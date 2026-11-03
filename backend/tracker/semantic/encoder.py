"""ONNX embedding encoder — the whole inference runtime, no torch anywhere.

Drives the pinned graph with `onnxruntime` + `tokenizers` only. Every runtime
choice here was measured, not assumed:

- Padding is disabled explicitly: shipped tokenizer.json files enable it by
  default, which silently reports every document as max-length.
- Truncation is OUR window (spec.max_tokens), never the sentence-transformers
  `max_seq_length` wrapper default the model card mentions.
- Pooling comes from the spec (the model's own config). CLS models mean-pooled
  produce plausible-looking wrong vectors and nothing raises.
- BATCH SIZE IS 1 AND PINNED. At long sequences a single document already
  saturates the cores; batching buys a few percent of throughput for linear
  memory growth and runs an 8 GB machine out of memory. This is a memory cliff,
  not a slope: never expose batch size as a setting or a default someone can
  raise.
"""

from __future__ import annotations

import logging

import numpy as np

from tracker.semantic.manifest import ModelSpec

logger = logging.getLogger(__name__)

_INTRA_OP_THREADS = 8


class OnnxEncoder:
    def __init__(self, spec: ModelSpec, tier: str, model_path: str, tokenizer_path: str):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.spec = spec
        self.tier = tier
        self.dim = spec.dim

        self._tokenizer = Tokenizer.from_file(tokenizer_path)
        self._tokenizer.no_padding()
        self._tokenizer.enable_truncation(max_length=spec.max_tokens)

        options = ort.SessionOptions()
        options.intra_op_num_threads = _INTRA_OP_THREADS
        self._session = ort.InferenceSession(
            model_path, sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._input_names = {i.name for i in self._session.get_inputs()}
        logger.info(
            "loaded %s (%s): dim=%d window=%d pooling=%s",
            spec.name, tier, spec.dim, spec.max_tokens, spec.pooling,
        )

    def encode(self, texts: list[str], *, kind: str = "document") -> list[list[float]]:
        """Encode to L2-normalized vectors (cosine == dot product).

        `kind` selects the spec's prefix: "query" for search/intent sentences,
        "document" for postings. One model, one space, two entry points.
        """
        prefix = self.spec.query_prefix if kind == "query" else self.spec.document_prefix
        out: list[list[float]] = []
        for text in texts:  # batch size 1, pinned: see module docstring
            out.append(self._encode_one(prefix + text))
        return out

    def _encode_one(self, text: str) -> list[float]:
        encoding = self._tokenizer.encode(text)
        ids = np.asarray([encoding.ids], dtype=np.int64)
        mask = np.asarray([encoding.attention_mask], dtype=np.int64)
        feeds: dict[str, np.ndarray] = {}
        if "input_ids" in self._input_names:
            feeds["input_ids"] = ids
        if "attention_mask" in self._input_names:
            feeds["attention_mask"] = mask
        if "token_type_ids" in self._input_names:
            feeds["token_type_ids"] = np.zeros_like(ids)
        hidden = self._session.run(None, feeds)[0]  # [1, tokens, dim]

        if self.spec.pooling == "cls":
            vec = hidden[0, 0].astype(np.float64)
        elif self.spec.pooling == "mean":
            weights = mask[0].astype(np.float64)[:, None]
            vec = (hidden[0].astype(np.float64) * weights).sum(axis=0) / max(weights.sum(), 1.0)
        else:
            raise ValueError(f"unknown pooling {self.spec.pooling!r} for {self.spec.name}")

        norm = float(np.linalg.norm(vec))
        if norm > 0.0:
            vec = vec / norm
        return [float(x) for x in vec]
