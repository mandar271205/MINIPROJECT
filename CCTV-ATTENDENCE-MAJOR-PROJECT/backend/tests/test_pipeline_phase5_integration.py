"""Phase 5 - pipeline integration tests (category 8 of the required
tests): presence reconstruction's gating rules and its wiring into the
existing video-processing pipeline outcome, without depending on the
real InsightFace provider (get_provider/classify_enrolled_students are
monkeypatched for determinism, matching the pattern already used for
filter_trusted_observations_by_student in the percentage tests)."""

import datetime
import os
import tempfile
import uuid

import cv2
import numpy as np
import pytest

from app.extensions import db
from app.models.attendance import (
    AttendanceSession,
    PRESENCE_STATUS_COMPLETED,
    PRESENCE_STATUS_FAILED,
    PRESENCE_STATUS_PARTIAL_EVIDENCE,
    PRESENCE_STATUS_PROCESSING,
)
from app.models.classroom import Classroom
from app.models.observation import FaceTrack, RecognitionObservation
from app.models.presence import PresenceWindow
from app.models.student import Student
from app.models.user import User
from app.services import presence_service
from app.services.models import EnrolledStudent


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _make_synthetic_video(path: str, num_frames: int = 100, fps: float = 10.0) -> None:
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
    _make_synthetic_video(path, num_frames=100, fps=10.0)  # 10 seconds @ 10fps
    yield path
    if os.path.exists(path):
        os.remove(path)


def _make_session(video_path, processing_status="done"):
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
        video_path=video_path, processing_status=processing_status,
    )
    db.session.add(session)
    db.session.commit()
    return session, student.id


def _fake_eligible(student_id):
    return EnrolledStudent(
        student_id=student_id, name="S", class_id=1,
        embedding=np.array([1.0, 0.0], dtype=np.float32),
        model_id="fake", embedding_dimension=2, embedding_status="ACTIVE",
    )


def _patch_provider_and_classifier(monkeypatch, *, eligible_ids=(), ineligible=()):
    monkeypatch.setattr(presence_service, "get_provider", lambda: object())
    monkeypatch.setattr(
        presence_service, "classify_enrolled_students",
        lambda students, provider: ([_fake_eligible(sid) for sid in eligible_ids], list(ineligible)),
    )


def test_reconstruction_refused_when_processing_not_done(app, synthetic_video):
    with app.app_context():
        session, _sid = _make_session(synthetic_video, processing_status="processing")
        with pytest.raises(presence_service.PresenceReconstructionNotAllowed):
            presence_service.run_presence_reconstruction(session.id)
        assert PresenceWindow.query.filter_by(session_id=session.id).count() == 0


def test_reconstruction_refused_when_processing_errored(app, synthetic_video):
    with app.app_context():
        session, _sid = _make_session(synthetic_video, processing_status="error")
        with pytest.raises(presence_service.PresenceReconstructionNotAllowed):
            presence_service.run_presence_reconstruction(session.id)


def test_reconstruction_refused_when_eof_not_reached(app, synthetic_video):
    with app.app_context():
        session, _sid = _make_session(synthetic_video, processing_status="done")
        with pytest.raises(presence_service.PresenceReconstructionNotAllowed):
            presence_service.run_presence_reconstruction(session.id, eof_reached=False)
        assert session.presence_reconstruction_status != PRESENCE_STATUS_COMPLETED


def test_reconstruction_refused_when_already_processing(app, synthetic_video, monkeypatch):
    with app.app_context():
        session, sid = _make_session(synthetic_video, processing_status="done")
        session.presence_reconstruction_status = PRESENCE_STATUS_PROCESSING
        db.session.commit()
        _patch_provider_and_classifier(monkeypatch, eligible_ids=[sid])

        with pytest.raises(presence_service.PresenceReconstructionNotAllowed):
            presence_service.run_presence_reconstruction(session.id, eof_reached=True)


def test_successful_reconstruction_persists_windows_for_eligible_student_with_evidence(app, synthetic_video, monkeypatch):
    with app.app_context():
        session, sid = _make_session(synthetic_video, processing_status="done")
        track = FaceTrack(
            session_id=session.id, track_key="t1", first_seen_seconds=0.0, last_seen_seconds=5.0,
            observation_count=1, track_state="CONFIRMED", confirmed_student_id=sid, identity_conflict=False,
        )
        db.session.add(track)
        db.session.commit()
        obs = RecognitionObservation(
            session_id=session.id, track_id=track.id, frame_index=0, detection_index=0,
            timestamp_seconds=2.0, top1_student_id=sid, top1_similarity=0.9,
            evidence_state="CONFIRMED_SUPPORT", provider_model_id="test",
        )
        db.session.add(obs)
        db.session.commit()

        _patch_provider_and_classifier(monkeypatch, eligible_ids=[sid])
        result = presence_service.run_presence_reconstruction(session.id, eof_reached=True)

        assert result["status"] == PRESENCE_STATUS_COMPLETED
        windows = PresenceWindow.query.filter_by(session_id=session.id, student_id=sid).all()
        assert len(windows) == 1
        assert session.presence_reconstruction_status == PRESENCE_STATUS_COMPLETED


def test_eligible_student_with_zero_evidence_yields_partial_evidence_status(app, synthetic_video, monkeypatch):
    with app.app_context():
        session, sid = _make_session(synthetic_video, processing_status="done")
        _patch_provider_and_classifier(monkeypatch, eligible_ids=[sid])

        result = presence_service.run_presence_reconstruction(session.id, eof_reached=True)
        assert result["status"] == PRESENCE_STATUS_PARTIAL_EVIDENCE
        assert PresenceWindow.query.filter_by(session_id=session.id).count() == 0


def test_ineligible_student_reported_without_fabricated_zero(app, synthetic_video, monkeypatch):
    with app.app_context():
        session, sid = _make_session(synthetic_video, processing_status="done")
        ineligible_entry = {
            "student_id": sid, "eligible_for_recognition": False, "attendance_generated": False,
            "requires_reenrollment": True, "reason_code": "LEGACY_INCOMPATIBLE", "message": "x",
        }
        _patch_provider_and_classifier(monkeypatch, eligible_ids=[], ineligible=[ineligible_entry])

        result = presence_service.run_presence_reconstruction(session.id, eof_reached=True)
        assert result["status"] == PRESENCE_STATUS_COMPLETED  # no eligible students -> not PARTIAL_EVIDENCE
        summary = next(s for s in result["summaries"] if s["student_id"] == sid)
        assert summary["eligible_for_reconstruction"] is False
        assert summary["reason_code"] == "LEGACY_INCOMPATIBLE"


def test_reconstruction_failure_does_not_flip_processing_status(app, synthetic_video, monkeypatch):
    with app.app_context():
        session, sid = _make_session(synthetic_video, processing_status="done")

        def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(presence_service, "get_provider", _boom)
        with pytest.raises(RuntimeError):
            presence_service.run_presence_reconstruction(session.id, eof_reached=True)

        assert session.processing_status == "done"  # legacy status untouched
        assert session.presence_reconstruction_status == PRESENCE_STATUS_FAILED
        assert PresenceWindow.query.filter_by(session_id=session.id).count() == 0


def test_reconstruction_never_mutates_face_tracks_or_observations(app, synthetic_video, monkeypatch):
    with app.app_context():
        session, sid = _make_session(synthetic_video, processing_status="done")
        track = FaceTrack(
            session_id=session.id, track_key="t1", first_seen_seconds=0.0, last_seen_seconds=5.0,
            observation_count=1, track_state="CONFIRMED", confirmed_student_id=sid, identity_conflict=False,
        )
        db.session.add(track)
        db.session.commit()
        obs = RecognitionObservation(
            session_id=session.id, track_id=track.id, frame_index=0, detection_index=0,
            timestamp_seconds=2.0, top1_student_id=sid, top1_similarity=0.9,
            evidence_state="CONFIRMED_SUPPORT", provider_model_id="test",
        )
        db.session.add(obs)
        db.session.commit()
        track_count_before = FaceTrack.query.filter_by(session_id=session.id).count()
        obs_count_before = RecognitionObservation.query.filter_by(session_id=session.id).count()

        _patch_provider_and_classifier(monkeypatch, eligible_ids=[sid])
        presence_service.run_presence_reconstruction(session.id, eof_reached=True)

        assert FaceTrack.query.filter_by(session_id=session.id).count() == track_count_before
        assert RecognitionObservation.query.filter_by(session_id=session.id).count() == obs_count_before
