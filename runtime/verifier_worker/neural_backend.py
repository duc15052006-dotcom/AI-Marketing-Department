"""Worker-only neural inference backend (PROD-VERIFIER-02B).

THIS MODULE IS EXECUTED ONLY INSIDE THE ISOLATED VERIFIER WORKER PROCESS.
It must never be imported by the main Python 3.14 runtime; the import
firewall test (tests/test_prod_verifier_02_sidecar_boundary.py) enforces
that torch/transformers never enter main-process sys.modules.

Model identity is preserved exactly from the certified baseline:
    MoritzLaurer/mDeBERTa-v3-base-mnli-xnli
    revision 8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c
    trust_remote_code=False

The worker performs raw NLI scoring only. Threshold application and all
scope/provenance/policy authority remain in the main process.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("verifier_worker.neural_backend")


class NeuralBackend:
    """Lazy-loading mDeBERTa NLI backend owned by the worker process."""

    def __init__(
        self,
        model_id: str,
        model_revision: str,
        device: str = "auto",
        max_length: int = 512,
        network_mode: str = "LOCAL_ONLY",
        local_snapshot_dir: Optional[str] = None,
    ) -> None:
        self.model_id = model_id
        self.model_revision = model_revision
        self._requested_device = device
        self.max_length = max_length
        self.network_mode = network_mode
        self.local_snapshot_dir = local_snapshot_dir
        self.local_files_only = network_mode == "LOCAL_ONLY"
        self._active_device: Optional[str] = None
        self._tokenizer = None
        self._model = None
        self._label_map: Dict[str, int] = {}
        self._is_loaded = False
        self.loaded_commit_hash: Optional[str] = None

    # ------------------------------------------------------------------

    def dependencies_available(self) -> bool:
        """Import probe without loading weights."""
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
            return True
        except Exception:
            return False

    def load_model(self) -> Tuple[bool, Optional[str]]:
        """Load tokenizer/model with strict pinning. Returns (ok, error_category)."""
        if self._is_loaded and self._model is not None:
            return True, None
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            if self._requested_device == "auto":
                self._active_device = "cuda" if torch.cuda.is_available() else "cpu"
            else:
                self._active_device = self._requested_device

            logger.info(
                "Loading NLI verifier: %s (rev: %s) on %s (network_mode=%s)",
                self.model_id, self.model_revision, self._active_device, self.network_mode,
            )

            load_source = self.local_snapshot_dir or self.model_id
            # LOCAL_ONLY: resolve strictly from the verified local snapshot;
            # never contact the hub, never silently fall back to online.
            # SAFETENSORS-ONLY (PROD-VERIFIER-02F): pickle weights are never
            # loaded. use_safetensors=True makes transformers FAIL when only
            # pytorch_model.bin exists — no unsafe deserialization fallback.
            self._tokenizer = AutoTokenizer.from_pretrained(
                load_source,
                revision=self.model_revision if not self.local_snapshot_dir else None,
                use_fast=True,
                trust_remote_code=False,
                local_files_only=self.local_files_only,
            )
            try:
                self._model = AutoModelForSequenceClassification.from_pretrained(
                    load_source,
                    revision=self.model_revision if not self.local_snapshot_dir else None,
                    trust_remote_code=False,
                    local_files_only=self.local_files_only,
                    use_safetensors=True,
                )
            except Exception as e:
                # Missing/corrupt safetensors must NEVER fall back to
                # pytorch_model.bin / pickle deserialization.
                logger.error("Safetensors-only load failed (pickle fallback forbidden): %s", e)
                return False, "MODEL_SAFE_WEIGHTS_UNAVAILABLE"
            self._model.to(self._active_device)
            self._model.eval()

            # Loaded-config commit attestation: when transformers exposes the
            # resolved commit hash it MUST equal the pinned commit.
            config_commit = getattr(self._model.config, "_commit_hash", None)
            self.loaded_commit_hash = config_commit
            if config_commit is not None and config_commit != self.model_revision:
                logger.error("Loaded config commit %s != pinned revision %s",
                             config_commit, self.model_revision)
                self._is_loaded = False
                return False, "MODEL_IDENTITY_MISMATCH"

            config = self._model.config
            raw_label2id = {k.lower(): int(v) for k, v in config.label2id.items()} if hasattr(config, "label2id") else {}
            raw_id2label = {int(k): v.lower() for k, v in config.id2label.items()} if hasattr(config, "id2label") else {}

            ent_idx = raw_label2id.get("entailment")
            neu_idx = raw_label2id.get("neutral")
            con_idx = raw_label2id.get("contradiction")
            if ent_idx is None or neu_idx is None or con_idx is None:
                for idx, name in raw_id2label.items():
                    name_l = name.lower()
                    if "entail" in name_l:
                        ent_idx = idx
                    elif "contra" in name_l:
                        con_idx = idx
                    elif "neut" in name_l:
                        neu_idx = idx
            if ent_idx is None or neu_idx is None or con_idx is None:
                logger.error("Cannot resolve 3-way NLI labels from model config.")
                self._is_loaded = False
                return False, "MODEL_LOAD_FAILED"

            self._label_map = {"entailment": ent_idx, "neutral": neu_idx, "contradiction": con_idx}
            self._is_loaded = True
            logger.info("NLI verifier loaded. Label map: %s", self._label_map)
            return True, None

        except ImportError:
            logger.error("Verifier dependencies missing (torch/transformers).", exc_info=True)
            return False, "DEPENDENCY_MISSING"
        except VerifierBackendError:
            raise
        except Exception as e:
            logger.error("Failed to load NLI verifier: %s", e, exc_info=True)
            self._model = None
            self._tokenizer = None
            self._is_loaded = False
            return False, "MODEL_LOAD_FAILED"

    def score(self, evidence_text: str, claim_text: str) -> Dict[str, Any]:
        """Run NLI scoring for (premise=evidence, hypothesis=claim).

        Token-length preflight (PROD-VERIFIER-02C) runs FIRST using only the
        tokenizer (no torch import required for this step): the pair is
        tokenized WITHOUT truncation. If the encoded pair exceeds the
        supported context, INPUT_TOO_LARGE is raised — the model NEVER sees
        silently truncated input, so an oversized pair can never produce
        SUPPORTED.

        Returns dict with p_entailment / p_neutral / p_contradiction /
        argmax_label / backend / latency_ms.

        Raises VerifierBackendError on load/inference failure so the worker
        loop can translate it into a protocol ERROR frame.
        """
        ok, err_category = self.load_model()
        if not ok:
            raise VerifierBackendError(err_category or "MODEL_LOAD_FAILED")

        # --- Explicit token-length preflight: tokenizer only, NO truncation ---
        preflight = self._tokenizer(
            evidence_text,
            claim_text,
            truncation=False,
            return_tensors=None,
        )
        encoded_len = len(preflight["input_ids"])
        model_limit = getattr(self._model.config, "max_position_embeddings", None)
        effective_limit = min(
            self.max_length,
            int(model_limit) if model_limit else self.max_length,
        )
        if encoded_len > effective_limit:
            raise VerifierBackendError(
                "INPUT_TOO_LARGE",
                f"tokenized pair length {encoded_len} exceeds supported context "
                f"{effective_limit}",
            )

        try:
            import numpy as np  # noqa: F401
            import torch

            # --- Real inference: pair known to fit; truncation is a no-op ---
            t0 = time.perf_counter()
            inputs = self._tokenizer(
                evidence_text,
                claim_text,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            inputs = {k: v.to(self._active_device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = self._model(**inputs)
                logits = outputs.logits[0]
                probs = torch.softmax(logits, dim=-1).cpu().numpy()

            latency_ms = (time.perf_counter() - t0) * 1000.0

            p_ent = float(probs[self._label_map["entailment"]])
            p_neu = float(probs[self._label_map["neutral"]])
            p_con = float(probs[self._label_map["contradiction"]])
            scores = {"ENTAILMENT": p_ent, "NEUTRAL": p_neu, "CONTRADICTION": p_con}

            return {
                "p_entailment": round(p_ent, 6),
                "p_neutral": round(p_neu, 6),
                "p_contradiction": round(p_con, 6),
                "argmax_label": max(scores, key=scores.get),
                "backend": f"pytorch_{self._active_device}",
                "latency_ms": round(latency_ms, 2),
            }
        except VerifierBackendError:
            raise
        except Exception as e:
            logger.error("Inference exception: %s", e, exc_info=True)
            raise VerifierBackendError("INFERENCE_EXCEPTION") from e


class VerifierBackendError(Exception):
    """Worker-side backend failure carrying a stable error category."""

    def __init__(self, category: str, message: str = "") -> None:
        super().__init__(message or category)
        self.category = category
