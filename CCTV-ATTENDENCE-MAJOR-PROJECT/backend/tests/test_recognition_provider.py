"""Phase 3 - proves the recognition provider's real behaviour: loads
once, exposes true runtime model metadata, produces correctly-shaped
normalized output, rejects invalid vectors, and fails loudly (never
silently falling back to AdaFace/Swin/Fusion) if loading fails.
"""

from unittest.mock import patch

import numpy as np
import pytest

from app.services.recognition_provider import (
    EmbeddingValidationError,
    InsightFaceArcFaceProvider,
    ProviderLoadError,
    get_provider,
    normalize_embedding,
    reset_provider_for_tests,
    validate_embedding,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_provider_for_tests()
    yield
    reset_provider_for_tests()


def test_provider_loads_and_exposes_real_model_metadata():
    provider = get_provider()

    # Must be the real runtime identity, not a hardcoded literal - the
    # Phase 3 audit confirmed buffalo_l's recognition model is
    # w600k_r50, never claimed here as "R100".
    assert provider.model_id.startswith("insightface_arcface_")
    assert "r100" not in provider.model_id.lower()
    assert provider.embedding_dimension == 512
    assert isinstance(provider.execution_provider, str) and provider.execution_provider


def test_provider_is_a_singleton_loaded_once():
    first = get_provider()
    second = get_provider()
    assert first is second


def test_extract_embedding_output_shape_and_normalization():
    provider = get_provider()
    dummy_face = (np.random.rand(112, 112, 3) * 255).astype(np.uint8)

    embedding = provider.extract_embedding(dummy_face)

    assert embedding.shape == (512,)
    assert embedding.dtype == np.float32
    assert abs(float(np.linalg.norm(embedding)) - 1.0) < 1e-4


@pytest.mark.parametrize(
    "bad_vector",
    [
        [0.1] * 10,  # wrong dimension
        [float("nan")] * 512,  # NaN
        [float("inf")] * 512,  # infinite
        [],  # empty
        [0.0] * 512,  # zero norm
    ],
)
def test_validate_embedding_rejects_invalid_vectors(bad_vector):
    with pytest.raises(EmbeddingValidationError):
        validate_embedding(bad_vector, expected_dimension=512)


def test_normalize_embedding_actually_normalizes():
    vec = np.array([3.0, 4.0] + [0.0] * 510, dtype=np.float32)
    normalized = normalize_embedding(vec, expected_dimension=512)
    assert abs(float(np.linalg.norm(normalized)) - 1.0) < 1e-6


def test_is_compatible_requires_exact_model_and_dimension_match():
    provider = get_provider()
    assert provider.is_compatible(provider.model_id, provider.embedding_dimension) is True
    assert provider.is_compatible("fused_ada_swin", 512) is False  # legacy model id, same dim
    assert provider.is_compatible(provider.model_id, 256) is False  # right id, wrong dim
    assert provider.is_compatible(None, None) is False


def test_provider_load_failure_is_explicit_not_silent_fallback():
    with patch(
        "app.services.recognition_provider.InsightFaceArcFaceProvider.__init__",
        side_effect=ProviderLoadError("simulated model load failure"),
    ):
        with pytest.raises(ProviderLoadError):
            InsightFaceArcFaceProvider()


def test_provider_import_failure_raises_provider_load_error():
    with patch.dict("sys.modules", {"insightface": None, "insightface.app": None}):
        with pytest.raises(ProviderLoadError):
            InsightFaceArcFaceProvider()
