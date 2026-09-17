"""Phase 3 - single verified recognition provider.

Replaces the dual AdaFace + Swin Transformer + arithmetic-fusion path
(recognition_adaptive.py / recognition_transformer.py / fusion.py, all
now unused and deprecated - see their module docstrings) with one
provider backed by InsightFace's bundled ArcFace recognition model.

Runtime identity, inspected directly against the loaded ONNX session
(see the Phase 3 completion report for the full trace): the "buffalo_l"
model pack's recognition model is an ``ArcFaceONNX`` wrapper around
``w600k_r50.onnx`` (a ResNet50 backbone trained on WebFace600K) - NOT
"ArcFace R100". This module never claims otherwise; ``model_id`` is
derived from the exact file that was actually loaded.
"""

from __future__ import annotations

import logging
import math
import threading

import numpy as np

log = logging.getLogger(__name__)

EXPECTED_EMBEDDING_DIMENSION = 512


class EmbeddingValidationError(ValueError):
    """Raised by validate_embedding()/normalize_embedding() for any
    vector that must never be stored or matched against: wrong
    dimension, non-finite values, or a zero/empty vector."""


class ProviderLoadError(RuntimeError):
    """Raised when the recognition model fails to load. There is no
    silent fallback to a different model - callers must treat this as a
    hard failure."""


def validate_embedding(vector, expected_dimension: int = EXPECTED_EMBEDDING_DIMENSION) -> np.ndarray:
    """Validates a candidate embedding vector, raising
    EmbeddingValidationError on the first violation found. Returns the
    vector as a flattened float32 array on success."""
    arr = np.asarray(vector, dtype=np.float32).flatten()
    if arr.size == 0:
        raise EmbeddingValidationError("embedding is empty")
    if arr.size != expected_dimension:
        raise EmbeddingValidationError(
            f"embedding has dimension {arr.size}, expected {expected_dimension}"
        )
    if not np.all(np.isfinite(arr)):
        raise EmbeddingValidationError("embedding contains NaN or infinite values")
    norm = float(np.linalg.norm(arr))
    if norm < 1e-8 or math.isclose(norm, 0.0, abs_tol=1e-8):
        raise EmbeddingValidationError("embedding has zero norm")
    return arr


def normalize_embedding(vector, expected_dimension: int = EXPECTED_EMBEDDING_DIMENSION) -> np.ndarray:
    """Validates then L2-normalizes a vector. Raises
    EmbeddingValidationError rather than silently returning a zero or
    garbage vector."""
    arr = validate_embedding(vector, expected_dimension=expected_dimension)
    norm = float(np.linalg.norm(arr))
    return (arr / norm).astype(np.float32)


class InsightFaceArcFaceProvider:
    """Loads the InsightFace ``buffalo_l`` recognition model exactly
    once and exposes it through a small, stable interface. There is no
    automatic fallback to AdaFace, Swin, or any other model - if the
    model fails to load, ProviderLoadError is raised and the caller must
    handle it explicitly (e.g. fail the processing job).
    """

    def __init__(self, *, providers: list[str] | None = None) -> None:
        try:
            from insightface.app import FaceAnalysis
        except Exception as exc:  # pragma: no cover - import failure path
            raise ProviderLoadError(f"insightface package is not available: {exc}") from exc

        exec_providers = providers or ["CUDAExecutionProvider", "CPUExecutionProvider"]
        try:
            self._app = FaceAnalysis(name="buffalo_l", providers=exec_providers)
            self._app.prepare(ctx_id=0, det_size=(640, 640))
        except Exception as exc:
            raise ProviderLoadError(f"failed to load InsightFace buffalo_l model pack: {exc}") from exc

        recognition_model = self._app.models.get("recognition")
        if recognition_model is None:
            raise ProviderLoadError("InsightFace buffalo_l pack has no 'recognition' model")
        self._recognition_model = recognition_model

        session = getattr(recognition_model, "session", None)
        self._execution_provider = (
            session.get_providers()[0] if session is not None and session.get_providers() else "unknown"
        )

        model_file = getattr(recognition_model, "model_file", "") or ""
        # Stable model id derived from the actual weights file that
        # loaded, e.g. "insightface_arcface_w600k_r50" - never a fixed
        # literal, so it can never silently drift from what is really
        # running.
        stem = model_file.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0] or "unknown"
        self._model_id = f"insightface_arcface_{stem}"
        self._model_file = model_file
        self._embedding_dimension = EXPECTED_EMBEDDING_DIMENSION

        log.info(
            "Loaded recognition provider model_id=%s model_file=%s execution_provider=%s embedding_dimension=%d",
            self._model_id, self._model_file, self._execution_provider, self._embedding_dimension,
        )

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def embedding_dimension(self) -> int:
        return self._embedding_dimension

    @property
    def execution_provider(self) -> str:
        return self._execution_provider

    def extract_embedding(self, aligned_face: np.ndarray) -> np.ndarray:
        """Runs the loaded ArcFace model on a single aligned 112x112
        BGR face crop and returns a validated, L2-normalized 512-D
        embedding. Raises EmbeddingValidationError if the model's raw
        output is not usable."""
        raw = self._recognition_model.get_feat(aligned_face)
        return self.normalize_embedding(raw)

    def normalize_embedding(self, vector) -> np.ndarray:
        return normalize_embedding(vector, expected_dimension=self._embedding_dimension)

    def validate_embedding(self, vector) -> np.ndarray:
        return validate_embedding(vector, expected_dimension=self._embedding_dimension)

    def is_compatible(self, stored_model_id: str | None, stored_dimension: int | None) -> bool:
        """True only on an exact model-id and dimension match. There is
        no partial or fuzzy compatibility - a different model id (e.g.
        the legacy "fused_ada_swin") is never treated as usable, even if
        its dimension happens to also be 512."""
        return stored_model_id == self._model_id and stored_dimension == self._embedding_dimension


_provider_lock = threading.Lock()
_provider_instance: InsightFaceArcFaceProvider | None = None


def get_provider() -> InsightFaceArcFaceProvider:
    """Returns the process-wide provider instance, loading the model on
    first use only. Safe to call from multiple threads (the attendance
    pipeline runs in a background thread per session)."""
    global _provider_instance
    if _provider_instance is None:
        with _provider_lock:
            if _provider_instance is None:
                _provider_instance = InsightFaceArcFaceProvider()
    return _provider_instance


def reset_provider_for_tests() -> None:
    """Test-only hook to force a fresh provider on next get_provider()
    call. Never used by application code."""
    global _provider_instance
    with _provider_lock:
        _provider_instance = None
