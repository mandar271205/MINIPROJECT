"""Phase 6 reliability correction - full-video completion evidence
tests. Proves eof_reached is persisted honestly (never fabricated as
True), that NULL/legacy sessions are treated conservatively
everywhere downstream, and that policy edits/recalculation semantics
from Phase 6 are unaffected.
"""

import datetime
import os
import tempfile
import uuid

import cv2
import numpy as np
import pytest

from app.extensions import db
from app.models.attendance import AttendanceSession, FULL_VIDEO_PIPELINE_VERSION
from app.models.attendance_policy import AttendancePolicy
from app.models.attendance_recommendation import AttendanceRecommendation
from app.models.classroom import Classroom
from app.models.presence import PresenceWindow
from app.models.student import Student
from app.models.user import User
from app.services import attendance_recommendation_service as rec_svc
from app.services.attendance_decision_engine import (
    REASON_FULL_VIDEO_COMPLETION_UNVERIFIED,
    REASON_VIDEO_EOF_NOT_REACHED,
    STATUS_PRESENT,
    STATUS_REVIEW_REQUIRED,
    SessionEvidenceContext,
    StudentEvidence,
    evaluate_student,
)
from app.services.attendance_service import _process_session
from app.services.models import EnrolledStudent


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _policy(**overrides):
    from app.services.attendance_decision_engine import DecisionPolicy

    defaults = dict(
        policy_id=1, policy_name="Development Default", present_threshold_percentage=75.0,
        late_grace_seconds=600.0, early_exit_tolerance_seconds=600.0, reentry_min_gap_seconds=300.0,
        low_confidence_flag_threshold=0.55, minimum_decision_confidence=0.45, minimum_valid_session_ratio=1.0,
    )
    defaults.update(overrides)
    return DecisionPolicy(**defaults)


# --------------------------------------------------------------------------
# Decision-engine level: True / False / None
# --------------------------------------------------------------------------

def test_explicit_true_permits_normal_evaluation():
    student = StudentEvidence(
        student_id=1, eligible_for_recognition=True, presence_percentage=80.0, presence_duration_seconds=2880.0,
        window_count=1, mean_confidence=0.9,
    )
    session = SessionEvidenceContext(eof_reached=True, presence_reconstruction_status="COMPLETED", valid_session_seconds=3600.0)
    result = evaluate_student(student, _policy(), session)
    assert result.suggested_status == STATUS_PRESENT


def test_explicit_false_produces_review_required():
    student = StudentEvidence(student_id=1, eligible_for_recognition=True, presence_percentage=0.0, presence_duration_seconds=0.0)
    session = SessionEvidenceContext(eof_reached=False, presence_reconstruction_status="COMPLETED", valid_session_seconds=3600.0)
    result = evaluate_student(student, _policy(), session)
    assert result.suggested_status == STATUS_REVIEW_REQUIRED
    assert result.reason_code == REASON_VIDEO_EOF_NOT_REACHED


def test_null_eof_produces_review_required_with_unverified_reason():
    student = StudentEvidence(student_id=1, eligible_for_recognition=True, presence_percentage=90.0, presence_duration_seconds=3240.0, mean_confidence=0.9)
    session = SessionEvidenceContext(eof_reached=None, presence_reconstruction_status="COMPLETED", valid_session_seconds=3600.0)
    result = evaluate_student(student, _policy(), session)
    assert result.suggested_status == STATUS_REVIEW_REQUIRED
    assert result.reason_code == REASON_FULL_VIDEO_COMPLETION_UNVERIFIED


def test_null_is_never_silently_treated_as_true():
    # Same high-quality evidence, only eof_reached differs - True and
    # None must never produce the same PRESENT outcome.
    student = StudentEvidence(
        student_id=1, eligible_for_recognition=True, presence_percentage=90.0, presence_duration_seconds=3240.0,
        window_count=1, mean_confidence=0.9,
    )
    true_session = SessionEvidenceContext(eof_reached=True, presence_reconstruction_status="COMPLETED", valid_session_seconds=3600.0)
    null_session = SessionEvidenceContext(eof_reached=None, presence_reconstruction_status="COMPLETED", valid_session_seconds=3600.0)

    assert evaluate_student(student, _policy(), true_session).suggested_status == STATUS_PRESENT
    assert evaluate_student(student, _policy(), null_session).suggested_status == STATUS_REVIEW_REQUIRED


# --------------------------------------------------------------------------
# Pipeline write-location tests (attendance_service._process_session)
# --------------------------------------------------------------------------

def _make_synthetic_video(path: str, num_frames: int = 40, fps: float = 10.0) -> None:
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
    _make_synthetic_video(path, num_frames=40, fps=10.0)
    yield path
    if os.path.exists(path):
        os.remove(path)


def _make_session_for_pipeline(app, video_path):
    hod = User.query.filter_by(role="hod").first()
    if not hod:
        hod = User(name="Seed HOD", email=_uniq("hod") + "@example.com", role="hod")
        hod.set_password("x")
        db.session.add(hod)
        db.session.commit()

    classroom = Classroom(name=_uniq("class"), subject="test", created_by=hod.id)
    db.session.add(classroom)
    db.session.commit()

    session = AttendanceSession(
        class_id=classroom.id, uploaded_by=hod.id, session_date=datetime.date.today(),
        video_path=video_path, processing_status="pending",
    )
    db.session.add(session)
    db.session.commit()
    return session.id


def test_successful_full_video_job_stores_eof_reached_true(app, synthetic_video):
    with app.app_context():
        session_id = _make_session_for_pipeline(app, synthetic_video)

    _process_session(app, session_id)

    with app.app_context():
        session = AttendanceSession.query.get(session_id)
        assert session.processing_status == "done"
        assert session.eof_reached is True
        assert session.processing_pipeline_version == FULL_VIDEO_PIPELINE_VERSION
        assert session.processed_video_duration_seconds is not None
        assert session.processing_completed_at is not None


def test_failed_job_never_stores_eof_reached_true(app):
    with app.app_context():
        session_id = _make_session_for_pipeline(app, "/nonexistent/path/does_not_exist.mp4")

    _process_session(app, session_id)

    with app.app_context():
        session = AttendanceSession.query.get(session_id)
        assert session.processing_status == "error"
        assert session.eof_reached is not True
        assert session.processing_completed_at is None


def test_stale_prior_true_is_cleared_on_reprocessing_attempt(app):
    """A session that previously succeeded (eof_reached=True) must not
    keep that stale value if a later reprocessing attempt fails -
    otherwise a failed retry could look falsely verified."""
    with app.app_context():
        session_id = _make_session_for_pipeline(app, "/nonexistent/path/does_not_exist.mp4")
        session = AttendanceSession.query.get(session_id)
        session.eof_reached = True  # simulate stale evidence from an earlier successful run
        session.processing_completed_at = datetime.datetime.now(datetime.timezone.utc)
        db.session.commit()

    _process_session(app, session_id)

    with app.app_context():
        session = AttendanceSession.query.get(session_id)
        assert session.processing_status == "error"
        assert session.eof_reached is not True


# --------------------------------------------------------------------------
# Recommendation-engine integration: legacy NULL sessions
# --------------------------------------------------------------------------

def _fake_eligible(student_id):
    return EnrolledStudent(student_id=student_id, name="S", class_id=1, embedding=None, model_id="fake", embedding_dimension=2, embedding_status="ACTIVE")


def _patch(monkeypatch, *, eligible_ids=()):
    monkeypatch.setattr(rec_svc, "get_provider", lambda: object())
    monkeypatch.setattr(
        rec_svc, "classify_enrolled_students",
        lambda students, provider: ([_fake_eligible(sid) for sid in eligible_ids], []),
    )


def _make_recommendation_session(eof_reached, monkeypatch):
    hod = User.query.filter_by(role="hod").first()
    if not hod:
        hod = User(name="Seed HOD", email=_uniq("hod") + "@example.com", role="hod")
        hod.set_password("x")
        db.session.add(hod)
        db.session.commit()

    for leftover in AttendancePolicy.query.filter_by(is_default=True, is_active=True).all():
        leftover.is_active = False
    policy = AttendancePolicy(
        name=_uniq("Default"), is_default=True, is_active=True, present_threshold_percentage=75.0,
        late_grace_seconds=600.0, early_exit_tolerance_seconds=600.0, reentry_min_gap_seconds=300.0,
        low_confidence_flag_threshold=0.55, minimum_decision_confidence=0.45, minimum_valid_session_ratio=1.0,
        created_by=hod.id,
    )
    db.session.add(policy)
    db.session.commit()

    classroom = Classroom(name=_uniq("class"), subject="test", created_by=hod.id)
    db.session.add(classroom)
    db.session.commit()

    student = Student(class_id=classroom.id, roll_number=_uniq("roll"), name="S", face_embedding=[0.1], face_model="x")
    db.session.add(student)
    db.session.commit()

    session = AttendanceSession(
        class_id=classroom.id, uploaded_by=hod.id, session_date=datetime.date.today(),
        video_path="legacy.mp4", processing_status="done",
    )
    session.presence_reconstruction_status = "COMPLETED"
    session.valid_duration_seconds = 3600.0
    session.eof_reached = eof_reached
    db.session.add(session)
    db.session.commit()

    window = PresenceWindow(
        session_id=session.id, student_id=student.id, window_index=0, start_seconds=0.0, end_seconds=3240.0,
        observed_duration_seconds=3240.0, inferred_gap_seconds=0.0, total_duration_seconds=3240.0,
        observation_count=5, contributing_track_count=1, mean_confidence=0.9, algorithm_version="presence_v1",
    )
    db.session.add(window)
    db.session.commit()

    _patch(monkeypatch, eligible_ids=[student.id])
    return session, student.id


def test_legacy_null_eof_session_produces_review_required(app, monkeypatch):
    with app.app_context():
        session, sid = _make_recommendation_session(None, monkeypatch)
        rec_svc.generate_session_recommendations(session.id)

        rec = AttendanceRecommendation.query.filter_by(session_id=session.id, student_id=sid).first()
        assert rec.suggested_status == STATUS_REVIEW_REQUIRED
        assert rec.reason_code == REASON_FULL_VIDEO_COMPLETION_UNVERIFIED


def test_verified_true_session_permits_normal_status(app, monkeypatch):
    with app.app_context():
        session, sid = _make_recommendation_session(True, monkeypatch)
        rec_svc.generate_session_recommendations(session.id)

        rec = AttendanceRecommendation.query.filter_by(session_id=session.id, student_id=sid).first()
        assert rec.suggested_status == STATUS_PRESENT


def test_existing_recommendation_snapshot_unchanged_until_explicit_recalculation(app, monkeypatch):
    with app.app_context():
        session, sid = _make_recommendation_session(True, monkeypatch)
        rec_svc.generate_session_recommendations(session.id)
        before = AttendanceRecommendation.query.filter_by(session_id=session.id, student_id=sid).first()
        before_snapshot = dict(before.explanation_json)
        before_status = before.suggested_status

        # Simulate the correction being deployed and the session's
        # eof_reached later found to be unverifiable (e.g. corrected
        # from a bad value) - the EXISTING row must not silently
        # change; only an explicit recalculation call updates it.
        session.eof_reached = None
        db.session.commit()

        after = AttendanceRecommendation.query.filter_by(session_id=session.id, student_id=sid).first()
        assert after.suggested_status == before_status
        assert after.explanation_json == before_snapshot

        # Now explicitly recalculate - this is allowed to change it.
        rec_svc.generate_session_recommendations(session.id)
        recalculated = AttendanceRecommendation.query.filter_by(session_id=session.id, student_id=sid).first()
        assert recalculated.suggested_status == STATUS_REVIEW_REQUIRED


# --------------------------------------------------------------------------
# Manual reconstruction cannot bypass missing EOF proof (API level)
# --------------------------------------------------------------------------

def test_manual_reconstruct_presence_endpoint_refuses_null_eof_session(app, client, hod_headers):
    with app.app_context():
        from app.models.user import User as UserModel

        hod = UserModel.query.filter_by(role="hod").first()
        classroom = Classroom(name=_uniq("class"), subject="test", created_by=hod.id)
        db.session.add(classroom)
        db.session.commit()
        session = AttendanceSession(
            class_id=classroom.id, uploaded_by=hod.id, session_date=datetime.date.today(),
            video_path="legacy.mp4", processing_status="done",
        )
        session.eof_reached = None
        db.session.add(session)
        db.session.commit()
        session_id = session.id

    resp = client.post(f"/api/attendance/sessions/{session_id}/reconstruct-presence", headers=hod_headers)
    assert resp.status_code == 409
