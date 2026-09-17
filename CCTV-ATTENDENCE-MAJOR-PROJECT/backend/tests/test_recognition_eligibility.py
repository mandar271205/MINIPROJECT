"""Phase 3 correction - ineligible students (LEGACY_INCOMPATIBLE,
REENROLL_REQUIRED, FAILED, missing embedding, wrong model id, wrong
dimension, invalid vector) must never receive a fabricated ABSENT (or
any other) attendance record. Uses fake detector/provider so these
tests are fast, deterministic, and don't depend on the real
InsightFace model.
"""

import os
import tempfile

import cv2
import numpy as np
import pytest

from app.services.models import EnrolledStudent, FaceDetection
from app.services.pipeline import CctvAttendancePipeline
from app.services.recognition_eligibility import classify_enrolled_students

FAKE_MODEL_ID = "test_fake_provider_v1"
FAKE_DIMENSION = 4


class _FakeProvider:
    model_id = FAKE_MODEL_ID
    embedding_dimension = FAKE_DIMENSION
    execution_provider = "FakeExecutionProvider"

    def extract_embedding(self, aligned_face):
        return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    def is_compatible(self, stored_model_id, stored_dimension):
        return stored_model_id == self.model_id and stored_dimension == self.embedding_dimension

    def validate_embedding(self, vector):
        arr = np.asarray(vector, dtype=np.float32).flatten()
        if arr.size == 0:
            raise ValueError("empty")
        if arr.size != self.embedding_dimension:
            raise ValueError("wrong dimension")
        if not np.all(np.isfinite(arr)):
            raise ValueError("non-finite")
        if float(np.linalg.norm(arr)) < 1e-8:
            raise ValueError("zero norm")
        return arr


class _AlwaysDetectsFakeFace:
    def detect(self, sample):
        return [
            FaceDetection(
                bbox=(0, 0, 10, 10),
                landmarks=np.zeros((5, 2), dtype=np.float32),
                confidence=0.99,
                aligned_face=np.zeros((112, 112, 3), dtype=np.uint8),
            )
        ]


class _RecordingAttendanceRepo:
    def __init__(self):
        self.saved = None

    def save_decisions(self, session_id, decisions):
        self.saved = (session_id, decisions)


class _StudentRepoStub:
    def __init__(self, students):
        self._students = students

    def get_enrolled(self, class_id):
        return self._students


def _eligible_student(student_id, name="Eligible") -> EnrolledStudent:
    return EnrolledStudent(
        student_id=student_id, name=name, class_id=1,
        embedding=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
        model_id=FAKE_MODEL_ID, embedding_dimension=FAKE_DIMENSION,
        embedding_status="ACTIVE",
    )


def _make_synthetic_video(path: str, num_frames: int = 20, fps: float = 10.0) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, (64, 64))
    for i in range(num_frames):
        frame = np.full((64, 64, 3), fill_value=(i * 5) % 256, dtype=np.uint8)
        writer.write(frame)
    writer.release()


@pytest.fixture()
def synthetic_video():
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    _make_synthetic_video(path)
    yield path
    if os.path.exists(path):
        os.remove(path)


# --------------------------------------------------------------------------
# classify_enrolled_students() - unit level
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "status,expected_reason",
    [
        ("LEGACY_INCOMPATIBLE", "LEGACY_INCOMPATIBLE"),
        ("REENROLL_REQUIRED", "REENROLL_REQUIRED"),
        ("FAILED", "FAILED"),
    ],
)
def test_status_based_reasons_are_ineligible(status, expected_reason):
    student = EnrolledStudent(
        student_id=1, name="S", class_id=1,
        embedding=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
        model_id=FAKE_MODEL_ID, embedding_dimension=FAKE_DIMENSION,
        embedding_status=status,
    )
    eligible, diagnostics = classify_enrolled_students([student], _FakeProvider())
    assert eligible == []
    assert diagnostics[0]["reason_code"] == expected_reason
    assert diagnostics[0]["eligible_for_recognition"] is False
    assert diagnostics[0]["attendance_generated"] is False
    assert diagnostics[0]["requires_reenrollment"] is True


def test_wrong_model_id_is_ineligible_not_treated_as_absent():
    student = EnrolledStudent(
        student_id=1, name="S", class_id=1,
        embedding=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
        model_id="some_other_model", embedding_dimension=FAKE_DIMENSION,
        embedding_status="ACTIVE",
    )
    eligible, diagnostics = classify_enrolled_students([student], _FakeProvider())
    assert eligible == []
    assert diagnostics[0]["reason_code"] == "EMBEDDING_MODEL_INCOMPATIBLE"


def test_wrong_dimension_is_ineligible_not_treated_as_absent():
    student = EnrolledStudent(
        student_id=1, name="S", class_id=1,
        embedding=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
        model_id=FAKE_MODEL_ID, embedding_dimension=999,
        embedding_status="ACTIVE",
    )
    eligible, diagnostics = classify_enrolled_students([student], _FakeProvider())
    assert eligible == []
    assert diagnostics[0]["reason_code"] == "EMBEDDING_DIMENSION_MISMATCH"


def test_invalid_vector_is_ineligible_not_treated_as_absent():
    student = EnrolledStudent(
        student_id=1, name="S", class_id=1,
        embedding=np.array([0.0, 0.0, 0.0, 0.0], dtype=np.float32),  # zero norm
        model_id=FAKE_MODEL_ID, embedding_dimension=FAKE_DIMENSION,
        embedding_status="ACTIVE",
    )
    eligible, diagnostics = classify_enrolled_students([student], _FakeProvider())
    assert eligible == []
    assert diagnostics[0]["reason_code"] == "EMBEDDING_INVALID"


def test_active_matching_student_is_eligible():
    eligible, diagnostics = classify_enrolled_students([_eligible_student(1)], _FakeProvider())
    assert len(eligible) == 1
    assert diagnostics == []


# --------------------------------------------------------------------------
# Full pipeline behaviour
# --------------------------------------------------------------------------

def test_mixed_roster_generates_attendance_only_for_eligible(synthetic_video):
    ineligible_student = EnrolledStudent(
        student_id=99, name="Ineligible", class_id=1,
        embedding=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
        model_id="fused_ada_swin", embedding_dimension=FAKE_DIMENSION,
        embedding_status="LEGACY_INCOMPATIBLE",
    )
    roster = [_eligible_student(1), ineligible_student]

    repo = _RecordingAttendanceRepo()
    pipeline = CctvAttendancePipeline(
        detector=_AlwaysDetectsFakeFace(),
        provider=_FakeProvider(),
        student_repo=_StudentRepoStub(roster),
        attendance_repo=repo,
        frame_interval=0.5,
        match_threshold=0.5,
    )

    results = pipeline.run(video_path=synthetic_video, class_id=1, session_id=1)

    assert "error" not in results
    assert results["attendance_generation_status"] == "PARTIAL_ROSTER"
    assert results["recognition_eligible_count"] == 1
    assert results["recognition_ineligible_count"] == 1
    assert results["students_requiring_reenrollment"] == 1
    assert results["attendance_not_generated_count"] == 1

    attendance_ids = {row["student_id"] for row in results["attendance"]}
    assert attendance_ids == {1}  # only the eligible student got a decision
    assert 99 not in attendance_ids

    ineligible_ids = {d["student_id"] for d in results["ineligible_students"]}
    assert ineligible_ids == {99}

    # save_decisions was called, but only with the eligible student's row.
    assert repo.saved is not None
    _session_id, saved_decisions = repo.saved
    assert {d.student_id for d in saved_decisions} == {1}


def test_zero_eligible_roster_generates_zero_attendance_records(synthetic_video):
    ineligible_student = EnrolledStudent(
        student_id=42, name="Ineligible Only", class_id=1,
        embedding=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
        model_id="fused_ada_swin", embedding_dimension=FAKE_DIMENSION,
        embedding_status="REENROLL_REQUIRED",
    )

    repo = _RecordingAttendanceRepo()
    pipeline = CctvAttendancePipeline(
        detector=_AlwaysDetectsFakeFace(),
        provider=_FakeProvider(),
        student_repo=_StudentRepoStub([ineligible_student]),
        attendance_repo=repo,
        frame_interval=0.5,
        match_threshold=0.5,
    )

    results = pipeline.run(video_path=synthetic_video, class_id=1, session_id=1)

    assert "error" not in results
    assert results["attendance_generation_status"] == "NOT_GENERATED"
    assert results["recognition_eligible_count"] == 0
    assert results["attendance"] == []
    assert "message" in results and "no compatible" in results["message"].lower() or "no student" in results["message"].lower()

    # The video must still have been read to EOF for the full-video
    # diagnostic, even though no attendance was generated.
    assert results["diagnostics"]["eof_reached"] is True
    assert results["diagnostics"]["frames_sampled"] > 0

    # No attendance record was ever persisted.
    assert repo.saved is None


def test_zero_eligible_roster_still_reaches_eof(synthetic_video):
    pipeline = CctvAttendancePipeline(
        detector=_AlwaysDetectsFakeFace(),
        provider=_FakeProvider(),
        student_repo=_StudentRepoStub([]),
        attendance_repo=_RecordingAttendanceRepo(),
        frame_interval=0.5,
        match_threshold=0.5,
    )
    results = pipeline.run(video_path=synthetic_video, class_id=1, session_id=1)
    assert results["diagnostics"]["eof_reached"] is True
    assert results["attendance_generation_status"] == "NOT_GENERATED"


def test_all_eligible_roster_reports_generated_status(synthetic_video):
    repo = _RecordingAttendanceRepo()
    pipeline = CctvAttendancePipeline(
        detector=_AlwaysDetectsFakeFace(),
        provider=_FakeProvider(),
        student_repo=_StudentRepoStub([_eligible_student(1), _eligible_student(2)]),
        attendance_repo=repo,
        frame_interval=0.5,
        match_threshold=0.5,
    )
    results = pipeline.run(video_path=synthetic_video, class_id=1, session_id=1)
    assert results["attendance_generation_status"] == "GENERATED"
    assert results["recognition_ineligible_count"] == 0
    assert repo.saved is not None
    assert {d.student_id for d in repo.saved[1]} == {1, 2}


def test_save_decisions_does_not_touch_other_sessions_records(app):
    """AttendanceRepository.save_decisions only ever deletes/replaces
    records for the given session_id - a previously saved valid record
    belonging to a different session is never touched, and reprocessing
    the same session replaces cleanly rather than duplicating."""
    import uuid

    from app.extensions import db
    from app.models.attendance import AttendanceRecord, AttendanceSession
    from app.models.classroom import Classroom
    from app.models.student import Student
    from app.models.user import User
    from app.services.models import AttendanceDecision
    from app.services.repositories import AttendanceRepository

    def _uniq(prefix):
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

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

        student = Student(
            class_id=classroom.id, roll_number=_uniq("roll"), name="S",
            face_embedding=[0.1, 0.2], face_model="x",
        )
        db.session.add(student)
        db.session.commit()

        other_session = AttendanceSession(
            class_id=classroom.id, uploaded_by=hod.id, session_date=__import__("datetime").date.today(),
            video_path="x.mp4", processing_status="done",
        )
        target_session = AttendanceSession(
            class_id=classroom.id, uploaded_by=hod.id, session_date=__import__("datetime").date.today(),
            video_path="y.mp4", processing_status="done",
        )
        db.session.add_all([other_session, target_session])
        db.session.commit()

        other_record = AttendanceRecord(
            session_id=other_session.id, student_id=student.id, status="present", flagged=False
        )
        db.session.add(other_record)
        db.session.commit()
        other_record_id = other_record.id

        repo = AttendanceRepository(db.session)
        decisions = [
            AttendanceDecision(
                student_id=student.id, student_name=student.name, status="present",
                first_seen_sec=1.0, confidence=0.9,
            )
        ]
        repo.save_decisions(target_session.id, decisions)

        # The other session's pre-existing record is untouched.
        assert AttendanceRecord.query.get(other_record_id) is not None

        # Reprocessing the same session replaces cleanly, no duplicates.
        repo.save_decisions(target_session.id, decisions)
        target_records = AttendanceRecord.query.filter_by(session_id=target_session.id).all()
        assert len(target_records) == 1


def test_api_exposes_reenrollment_warning_for_ineligible_students(app, client, hod_headers):
    """Integration-level proof that the session status/detail API
    surfaces the re-enrolment warning fields the frontend displays."""
    import uuid

    from app.extensions import db
    from app.models.attendance import AttendanceSession
    from app.models.classroom import Classroom
    from app.models.student import Student
    from app.models.user import User

    def _uniq(prefix):
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        classroom = Classroom(name=_uniq("class"), subject="test", created_by=hod.id)
        db.session.add(classroom)
        db.session.commit()

        student = Student(
            class_id=classroom.id, roll_number=_uniq("roll"), name="Needs Reenroll",
            face_embedding=[0.1, 0.2], face_model="fused_ada_swin",
            embedding_status="LEGACY_INCOMPATIBLE",
        )
        db.session.add(student)

        session = AttendanceSession(
            class_id=classroom.id, uploaded_by=hod.id, session_date=__import__("datetime").date.today(),
            video_path="z.mp4", processing_status="done", progress_pct=100,
        )
        db.session.add(session)
        db.session.commit()
        session_id = session.id

    resp = client.get(f"/api/attendance/sessions/{session_id}/status", headers=hod_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["students_requiring_reenrollment"] >= 1
    assert body["recognition_ineligible_count"] >= 1
    assert any(d["reason_code"] == "LEGACY_INCOMPATIBLE" for d in body["ineligible_students"])


def test_reprocessing_does_not_touch_existing_records_when_zero_eligible(synthetic_video):
    """A previous run may have left valid records for other students in
    the same session; a re-run that finds zero eligible students must
    not call save_decisions at all, so those records are untouched."""

    class _RepoThatWouldExplodeIfCalled:
        def save_decisions(self, session_id, decisions):
            raise AssertionError("save_decisions must not be called when there are no eligible students")

    ineligible_student = EnrolledStudent(
        student_id=7, name="Ineligible", class_id=1,
        embedding=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
        model_id="fused_ada_swin", embedding_dimension=FAKE_DIMENSION,
        embedding_status="FAILED",
    )

    pipeline = CctvAttendancePipeline(
        detector=_AlwaysDetectsFakeFace(),
        provider=_FakeProvider(),
        student_repo=_StudentRepoStub([ineligible_student]),
        attendance_repo=_RepoThatWouldExplodeIfCalled(),
        frame_interval=0.5,
        match_threshold=0.5,
    )

    results = pipeline.run(video_path=synthetic_video, class_id=1, session_id=1)
    assert results["attendance_generation_status"] == "NOT_GENERATED"
