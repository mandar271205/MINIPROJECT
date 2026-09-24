"""Phase 6 - pipeline/orchestration integration tests (category 8 of
the required tests): generate_session_recommendations()'s gating
rules and end-to-end wiring, with get_provider/classify_enrolled_students
monkeypatched for determinism (same pattern as
test_pipeline_phase5_integration.py's percentage tests)."""

import datetime
import uuid

import pytest

from app.extensions import db
from app.models.attendance import (
    AttendanceSession,
    RECOMMENDATION_GENERATION_COMPLETED,
    RECOMMENDATION_GENERATION_FAILED,
    RECOMMENDATION_GENERATION_PROCESSING,
)
from app.models.attendance_policy import AttendancePolicy
from app.models.attendance_recommendation import AttendanceRecommendation
from app.models.classroom import Classroom
from app.models.observation import FaceTrack
from app.models.presence import PresenceWindow
from app.models.student import Student
from app.models.user import User
from app.services import attendance_recommendation_service as svc
from app.services.attendance_decision_engine import STATUS_PRESENT, STATUS_REVIEW_REQUIRED
from app.services.models import EnrolledStudent


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _no_leftover_active_default(app):
    with app.app_context():
        for leftover in AttendancePolicy.query.filter_by(is_default=True, is_active=True).all():
            leftover.is_active = False
        db.session.commit()
    yield


def _make_default_policy(hod_id):
    policy = AttendancePolicy(
        name=_uniq("Default"), is_default=True, is_active=True,
        present_threshold_percentage=75.0, late_grace_seconds=600.0, early_exit_tolerance_seconds=600.0,
        reentry_min_gap_seconds=300.0, low_confidence_flag_threshold=0.55, minimum_decision_confidence=0.45,
        minimum_valid_session_ratio=1.0, created_by=hod_id,
    )
    db.session.add(policy)
    db.session.commit()
    return policy


def _make_session(processing_status="done", presence_status="COMPLETED", valid_seconds=3600.0, eof_reached=True):
    hod = User.query.filter_by(role="hod").first()
    if not hod:
        hod = User(name="Seed HOD", email=_uniq("hod") + "@example.com", role="hod")
        hod.set_password("x")
        db.session.add(hod)
        db.session.commit()

    classroom = Classroom(name=_uniq("class"), subject="test", created_by=hod.id)
    db.session.add(classroom)
    db.session.commit()

    student = Student(class_id=classroom.id, roll_number=_uniq("roll"), name="S", face_embedding=[0.1], face_model="x")
    db.session.add(student)
    db.session.commit()

    session = AttendanceSession(
        class_id=classroom.id, uploaded_by=hod.id, session_date=datetime.date.today(),
        video_path="x.mp4", processing_status=processing_status,
    )
    session.presence_reconstruction_status = presence_status
    session.valid_duration_seconds = valid_seconds
    session.actual_duration_seconds = valid_seconds
    session.eof_reached = eof_reached
    db.session.add(session)
    db.session.commit()
    return session, hod.id, student.id


def _fake_eligible(student_id):
    return EnrolledStudent(
        student_id=student_id, name="S", class_id=1,
        embedding=None, model_id="fake", embedding_dimension=2, embedding_status="ACTIVE",
    )


def _patch(monkeypatch, *, eligible_ids=(), ineligible=()):
    monkeypatch.setattr(svc, "get_provider", lambda: object())
    monkeypatch.setattr(
        svc, "classify_enrolled_students",
        lambda students, provider: ([_fake_eligible(sid) for sid in eligible_ids], list(ineligible)),
    )


def test_generation_refused_when_presence_not_reconstructed(app):
    with app.app_context():
        session, hod_id, sid = _make_session(presence_status="NOT_STARTED")
        _make_default_policy(hod_id)

        with pytest.raises(svc.RecommendationGenerationNotAllowed):
            svc.generate_session_recommendations(session.id)
        assert AttendanceRecommendation.query.filter_by(session_id=session.id).count() == 0


def test_generation_refused_when_already_processing(app, monkeypatch):
    with app.app_context():
        session, hod_id, sid = _make_session()
        _make_default_policy(hod_id)
        session.recommendation_generation_status = RECOMMENDATION_GENERATION_PROCESSING
        db.session.commit()
        _patch(monkeypatch, eligible_ids=[sid])

        with pytest.raises(svc.RecommendationGenerationNotAllowed):
            svc.generate_session_recommendations(session.id)


def test_successful_generation_creates_one_recommendation_per_student(app, monkeypatch):
    with app.app_context():
        session, hod_id, sid = _make_session()
        _make_default_policy(hod_id)

        track = FaceTrack(
            session_id=session.id, track_key="t1", first_seen_seconds=0.0, last_seen_seconds=5.0,
            observation_count=1, track_state="CONFIRMED", confirmed_student_id=sid, identity_conflict=False,
        )
        db.session.add(track)
        db.session.commit()
        window = PresenceWindow(
            session_id=session.id, student_id=sid, window_index=0, start_seconds=0.0, end_seconds=3240.0,
            observed_duration_seconds=3240.0, inferred_gap_seconds=0.0, total_duration_seconds=3240.0,
            observation_count=5, contributing_track_count=1, mean_confidence=0.9,
            algorithm_version="presence_v1",
        )
        db.session.add(window)
        db.session.commit()

        _patch(monkeypatch, eligible_ids=[sid])
        result = svc.generate_session_recommendations(session.id)

        assert result["status"] == RECOMMENDATION_GENERATION_COMPLETED
        recs = AttendanceRecommendation.query.filter_by(session_id=session.id).all()
        assert len(recs) == 1
        assert recs[0].suggested_status == STATUS_PRESENT
        assert session.recommendation_generation_status == RECOMMENDATION_GENERATION_COMPLETED


def test_ineligible_student_gets_review_required_not_omitted(app, monkeypatch):
    with app.app_context():
        session, hod_id, sid = _make_session()
        _make_default_policy(hod_id)
        ineligible_entry = {
            "student_id": sid, "eligible_for_recognition": False, "attendance_generated": False,
            "requires_reenrollment": True, "reason_code": "LEGACY_INCOMPATIBLE", "message": "x",
        }
        _patch(monkeypatch, eligible_ids=[], ineligible=[ineligible_entry])

        svc.generate_session_recommendations(session.id)
        rec = AttendanceRecommendation.query.filter_by(session_id=session.id, student_id=sid).first()
        assert rec is not None
        assert rec.suggested_status == STATUS_REVIEW_REQUIRED
        assert rec.decision_is_evaluable is False


def test_no_applicable_policy_yields_review_required_for_every_student(app, monkeypatch):
    with app.app_context():
        session, hod_id, sid = _make_session()
        # Deliberately no active policy at all.
        _patch(monkeypatch, eligible_ids=[sid])

        result = svc.generate_session_recommendations(session.id)
        assert result["status"] == RECOMMENDATION_GENERATION_COMPLETED
        rec = AttendanceRecommendation.query.filter_by(session_id=session.id, student_id=sid).first()
        assert rec.suggested_status == STATUS_REVIEW_REQUIRED
        assert rec.reason_code == "POLICY_UNRESOLVED"
        assert rec.policy_id is None


def test_generation_failure_does_not_corrupt_presence_windows(app, monkeypatch):
    with app.app_context():
        session, hod_id, sid = _make_session()
        _make_default_policy(hod_id)
        window = PresenceWindow(
            session_id=session.id, student_id=sid, window_index=0, start_seconds=0.0, end_seconds=100.0,
            observed_duration_seconds=100.0, inferred_gap_seconds=0.0, total_duration_seconds=100.0,
            observation_count=2, contributing_track_count=1, mean_confidence=0.9,
            algorithm_version="presence_v1",
        )
        db.session.add(window)
        db.session.commit()
        window_count_before = PresenceWindow.query.filter_by(session_id=session.id).count()

        def _boom():
            raise RuntimeError("boom")

        monkeypatch.setattr(svc, "get_provider", _boom)

        with pytest.raises(RuntimeError):
            svc.generate_session_recommendations(session.id)

        assert session.recommendation_generation_status == RECOMMENDATION_GENERATION_FAILED
        assert session.presence_reconstruction_status == "COMPLETED"  # untouched
        assert PresenceWindow.query.filter_by(session_id=session.id).count() == window_count_before


def test_recalculation_uses_newly_edited_policy(app, monkeypatch):
    with app.app_context():
        session, hod_id, sid = _make_session()
        policy = _make_default_policy(hod_id)
        window = PresenceWindow(
            session_id=session.id, student_id=sid, window_index=0, start_seconds=0.0, end_seconds=1800.0,
            observed_duration_seconds=1800.0, inferred_gap_seconds=0.0, total_duration_seconds=1800.0,
            observation_count=3, contributing_track_count=1, mean_confidence=0.9,
            algorithm_version="presence_v1",
        )
        db.session.add(window)
        db.session.commit()
        _patch(monkeypatch, eligible_ids=[sid])

        svc.generate_session_recommendations(session.id)  # 1800/3600 = 50% < 75% -> PARTIAL
        first = AttendanceRecommendation.query.filter_by(session_id=session.id, student_id=sid).first()
        assert first.suggested_status == "PARTIAL"

        policy.present_threshold_percentage = 40.0  # now 50% clears the new threshold
        db.session.commit()

        svc.generate_session_recommendations(session.id)
        second = AttendanceRecommendation.query.filter_by(session_id=session.id, student_id=sid).first()
        assert second.suggested_status == STATUS_PRESENT
        assert second.id == first.id  # upserted in place, not duplicated
