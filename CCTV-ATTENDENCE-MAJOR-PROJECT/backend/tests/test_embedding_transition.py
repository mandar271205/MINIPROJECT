"""Phase 3 - the controlled embedding transition service. Uses fake
detector/provider (patched in) so these tests are fast and
deterministic, and don't depend on real face images or the real
InsightFace model.
"""

import uuid
from unittest.mock import patch

import numpy as np
import pytest

from app.services.models import FaceDetection

FAKE_MODEL_ID = "test_fake_provider_v1"
FAKE_DIMENSION = 4


class _FakeProvider:
    model_id = FAKE_MODEL_ID
    embedding_dimension = FAKE_DIMENSION

    def extract_embedding(self, aligned_face):
        return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    def validate_embedding(self, vector):
        arr = np.asarray(vector, dtype=np.float32).flatten()
        if arr.size != FAKE_DIMENSION:
            raise ValueError("bad dimension")
        return arr


class _FakeFailingProvider(_FakeProvider):
    def extract_embedding(self, aligned_face):
        raise RuntimeError("simulated extraction failure")


class _ConfigurableFakeDetector:
    """Returns a fixed number of fake detections regardless of input,
    so tests can force zero/one/many "faces"."""

    def __init__(self, face_count: int):
        self._face_count = face_count

    def detect_raw(self, frame_bgr):
        return [
            FaceDetection(
                bbox=(0, 0, 10, 10),
                landmarks=np.zeros((5, 2), dtype=np.float32),
                confidence=0.9,
                aligned_face=np.zeros((112, 112, 3), dtype=np.uint8),
            )
            for _ in range(self._face_count)
        ]


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _make_student(app, *, with_image: bool, image_readable: bool = True):
    import cv2

    from app.extensions import db
    from app.models.classroom import Classroom
    from app.models.student import Student
    from app.models.user import User

    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        if not hod:
            hod = User(name="Seed HOD", email=_uniq("hod") + "@example.com", role="hod")
            hod.set_password("x")
            db.session.add(hod)
            db.session.commit()

        classroom = Classroom(name=_uniq("class"), subject="test", created_by=hod.id)
        db.session.add(classroom)
        db.session.commit()

        image_path = None
        if with_image:
            fd_dir = app.config["TEMP_DIR"]
            fd_dir.mkdir(parents=True, exist_ok=True)
            image_path = str(fd_dir / f"{_uniq('ref')}.png")
            if image_readable:
                img = np.full((112, 112, 3), 128, dtype=np.uint8)
                cv2.imwrite(image_path, img)
            # else: leave path pointing at a nonexistent/unreadable file

        student = Student(
            class_id=classroom.id,
            roll_number=_uniq("roll"),
            name="Transition Test Student",
            face_embedding=[0.1, 0.2, 0.3, 0.4],
            face_model="fused_ada_swin",
            embedding_status="LEGACY_INCOMPATIBLE",
            reference_image_path=image_path,
        )
        db.session.add(student)
        db.session.commit()
        return student.id


def _patched_transition(app, *, provider, detector):
    from app.services import embedding_transition as mod

    with patch.object(mod, "get_provider", return_value=provider), patch.object(
        mod, "RetinaFaceDetector", return_value=detector
    ):
        with app.app_context():
            return mod.transition_all_students()


def test_valid_reference_image_regenerates_successfully(app):
    student_id = _make_student(app, with_image=True)
    report = _patched_transition(app, provider=_FakeProvider(), detector=_ConfigurableFakeDetector(1))

    entry = next(e for e in report if e["student_id"] == student_id)
    assert entry["result"] == "regenerated"
    assert entry["new_model_id"] == FAKE_MODEL_ID
    assert entry["reenrollment_required"] is False

    with app.app_context():
        from app.models.student import Student

        student = Student.query.get(student_id)
        assert student.face_model == FAKE_MODEL_ID
        assert student.embedding_status == "ACTIVE"
        assert student.embedding_dimension == FAKE_DIMENSION
        assert student.face_embedding == [1.0, 0.0, 0.0, 0.0]


def test_missing_image_preserves_old_vector(app):
    student_id = _make_student(app, with_image=False)
    report = _patched_transition(app, provider=_FakeProvider(), detector=_ConfigurableFakeDetector(1))

    entry = next(e for e in report if e["student_id"] == student_id)
    assert entry["result"] == "skipped"
    assert entry["reenrollment_required"] is True

    with app.app_context():
        from app.models.student import Student

        student = Student.query.get(student_id)
        assert student.face_model == "fused_ada_swin"  # unchanged
        assert student.face_embedding == [0.1, 0.2, 0.3, 0.4]  # unchanged
        assert student.embedding_status == "REENROLL_REQUIRED"


def test_zero_face_image_preserves_old_vector(app):
    student_id = _make_student(app, with_image=True)
    report = _patched_transition(app, provider=_FakeProvider(), detector=_ConfigurableFakeDetector(0))

    entry = next(e for e in report if e["student_id"] == student_id)
    assert entry["result"] == "skipped"
    assert entry["reenrollment_required"] is True
    assert "no face" in entry["failure_reason"]

    with app.app_context():
        from app.models.student import Student

        student = Student.query.get(student_id)
        assert student.face_embedding == [0.1, 0.2, 0.3, 0.4]
        assert student.embedding_status == "REENROLL_REQUIRED"


def test_multi_face_image_preserves_old_vector(app):
    student_id = _make_student(app, with_image=True)
    report = _patched_transition(app, provider=_FakeProvider(), detector=_ConfigurableFakeDetector(2))

    entry = next(e for e in report if e["student_id"] == student_id)
    assert entry["result"] == "skipped"
    assert entry["reenrollment_required"] is True
    assert "multiple faces" in entry["failure_reason"]

    with app.app_context():
        from app.models.student import Student

        student = Student.query.get(student_id)
        assert student.face_embedding == [0.1, 0.2, 0.3, 0.4]
        assert student.embedding_status == "REENROLL_REQUIRED"


def test_extraction_failure_does_not_partially_update_and_preserves_old_vector(app):
    student_id = _make_student(app, with_image=True)
    report = _patched_transition(app, provider=_FakeFailingProvider(), detector=_ConfigurableFakeDetector(1))

    entry = next(e for e in report if e["student_id"] == student_id)
    assert entry["result"] == "failed"
    assert entry["new_model_id"] is None

    with app.app_context():
        from app.models.student import Student

        student = Student.query.get(student_id)
        # Old vector and model id must be completely untouched.
        assert student.face_model == "fused_ada_swin"
        assert student.face_embedding == [0.1, 0.2, 0.3, 0.4]
        assert student.embedding_status == "FAILED"
        assert student.embedding_error


def test_transition_continues_with_remaining_students_after_one_failure(app):
    # transition_all_students() processes every student in the shared
    # test database (other test modules leave rows behind), and every
    # student with an existing reference image will reach
    # extract_embedding (this test's fake detector always reports
    # exactly one face). Target the failure at "the first of this
    # test's own two students" by counting how many prior calls will
    # actually happen, rather than assuming call #1 overall - that
    # keeps this test deterministic regardless of execution order.
    with app.app_context():
        from app.models.student import Student

        existing_calls_before = Student.query.filter(
            Student.reference_image_path.isnot(None)
        ).count()

    failing_id = _make_student(app, with_image=True)
    ok_id = _make_student(app, with_image=True)

    real_provider = _FakeProvider()
    calls = {"count": 0}
    target_call = existing_calls_before + 1

    class _FlakyProvider(_FakeProvider):
        def extract_embedding(self, aligned_face):
            calls["count"] += 1
            if calls["count"] == target_call:
                raise RuntimeError("targeted student fails")
            return real_provider.extract_embedding(aligned_face)

    report = _patched_transition(app, provider=_FlakyProvider(), detector=_ConfigurableFakeDetector(1))

    results_by_id = {e["student_id"]: e for e in report}
    assert results_by_id[failing_id]["result"] == "failed"
    assert results_by_id[ok_id]["result"] == "regenerated"
