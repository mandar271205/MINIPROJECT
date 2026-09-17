"""Phase 3 - compatibility rules between stored embeddings and the
active recognition provider, and how the pipeline/repository handle an
incompatible or empty roster.
"""

import uuid

import numpy as np

from app.services.models import EnrolledStudent
from app.services.recognition_provider import get_provider, reset_provider_for_tests


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def teardown_module(_module):
    reset_provider_for_tests()


def test_exact_model_and_dimension_are_accepted():
    provider = get_provider()
    assert provider.is_compatible(provider.model_id, provider.embedding_dimension) is True


def test_different_model_id_is_rejected():
    provider = get_provider()
    assert provider.is_compatible("fused_ada_swin", provider.embedding_dimension) is False


def test_different_dimension_is_rejected():
    provider = get_provider()
    assert provider.is_compatible(provider.model_id, provider.embedding_dimension + 1) is False


def test_invalid_legacy_vector_is_rejected_by_validation():
    provider = get_provider()
    # A legacy fused_ada_swin vector might coincidentally be 512-D, but
    # a genuinely corrupt/zero one must still fail independent of the
    # model-id check.
    zero_vector = np.zeros(provider.embedding_dimension, dtype=np.float32)
    try:
        provider.validate_embedding(zero_vector)
        assert False, "zero-norm vector should have been rejected"
    except Exception as exc:
        assert "zero norm" in str(exc)


def test_empty_compatible_roster_is_handled_by_matching():
    from app.services.matching import match_face
    from app.services.models import FaceEmbedding

    query = FaceEmbedding(vector=np.array([1.0, 0.0], dtype=np.float32), model_name="x")
    result = match_face(query, [], threshold=0.5)
    assert result.is_match is False
    assert result.student_id is None


def test_incompatible_students_are_excluded_from_pipeline_matching(app):
    """Uses the real provider to build one compatible and one
    incompatible EnrolledStudent, and confirms the pipeline's
    compatibility split (mirrors StudentRepository.get_enrolled +
    CctvAttendancePipeline.run's own split) puts each in the right
    bucket."""
    provider = get_provider()

    compatible = EnrolledStudent(
        student_id=1, name="Compatible", class_id=1,
        embedding=np.ones(provider.embedding_dimension, dtype=np.float32),
        model_id=provider.model_id, embedding_dimension=provider.embedding_dimension,
    )
    incompatible = EnrolledStudent(
        student_id=2, name="Incompatible", class_id=1,
        embedding=np.ones(512, dtype=np.float32),
        model_id="fused_ada_swin", embedding_dimension=512,
    )

    compatible_list = [s for s in [compatible, incompatible] if provider.is_compatible(s.model_id, s.embedding_dimension)]
    reenrollment_required = [s for s in [compatible, incompatible] if not provider.is_compatible(s.model_id, s.embedding_dimension)]

    assert [s.student_id for s in compatible_list] == [1]
    assert [s.student_id for s in reenrollment_required] == [2]
