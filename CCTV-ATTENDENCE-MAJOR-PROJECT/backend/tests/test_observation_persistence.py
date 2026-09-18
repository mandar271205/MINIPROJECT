"""Phase 4 - observation/track persistence tests."""

import uuid

import pytest

from app.extensions import db
from app.models.classroom import Classroom
from app.models.observation import FaceTrack, RecognitionObservation
from app.models.student import Student
from app.models.user import User
from app.services.observation_persistence import ObservationPersistence


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _make_session(app):
    from app.models.attendance import AttendanceSession
    import datetime

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
        face_embedding=[0.1], face_model="x",
    )
    db.session.add(student)
    db.session.commit()

    session = AttendanceSession(
        class_id=classroom.id, uploaded_by=hod.id, session_date=datetime.date.today(),
        video_path="x.mp4", processing_status="done",
    )
    db.session.add(session)
    db.session.commit()
    return session.id, student.id


def _sample_track(key="track-0001"):
    return {
        "track_key": key, "first_seen_seconds": 0.0, "last_seen_seconds": 5.0,
        "observation_count": 2, "track_state": "CONFIRMED", "confirmed_student_id": None,
        "confirmed_at_seconds": 0.0, "mean_confidence": 0.8, "max_confidence": 0.85,
        "identity_conflict": False, "conflict_reason": None, "closed_at_seconds": 5.0,
    }


def _sample_observations(key="track-0001", provider_model_id="test_model"):
    return [
        {
            "track_key": key, "frame_index": 0, "detection_index": 0, "timestamp_seconds": 0.0,
            "bbox_x1": 0.0, "bbox_y1": 0.0, "bbox_x2": 10.0, "bbox_y2": 10.0,
            "detection_confidence": 0.9, "top1_student_id": None, "top1_similarity": 0.7,
            "top2_student_id": None, "top2_similarity": None, "similarity_margin": None,
            "evidence_state": "MATCH_CANDIDATE", "provider_model_id": provider_model_id,
        },
        {
            "track_key": key, "frame_index": 1, "detection_index": 0, "timestamp_seconds": 1.0,
            "bbox_x1": 1.0, "bbox_y1": 1.0, "bbox_x2": 11.0, "bbox_y2": 11.0,
            "detection_confidence": 0.9, "top1_student_id": None, "top1_similarity": 0.75,
            "top2_student_id": None, "top2_similarity": None, "similarity_margin": None,
            "evidence_state": "MATCH_CANDIDATE", "provider_model_id": provider_model_id,
        },
    ]


def test_tracks_and_observations_persist_correctly(app):
    with app.app_context():
        session_id, _student_id = _make_session(app)
        persistence = ObservationPersistence(db.session)
        persistence.replace_session_evidence(session_id, [_sample_track()], _sample_observations())

        tracks = FaceTrack.query.filter_by(session_id=session_id).all()
        assert len(tracks) == 1
        assert tracks[0].track_key == "track-0001"

        observations = RecognitionObservation.query.filter_by(session_id=session_id).order_by(
            RecognitionObservation.timestamp_seconds
        ).all()
        assert len(observations) == 2
        assert [o.timestamp_seconds for o in observations] == [0.0, 1.0]
        assert observations[0].track_id == tracks[0].id


def test_reprocessing_does_not_duplicate_observations(app):
    with app.app_context():
        session_id, _ = _make_session(app)
        persistence = ObservationPersistence(db.session)
        persistence.replace_session_evidence(session_id, [_sample_track()], _sample_observations())
        persistence.replace_session_evidence(session_id, [_sample_track()], _sample_observations())

        assert FaceTrack.query.filter_by(session_id=session_id).count() == 1
        assert RecognitionObservation.query.filter_by(session_id=session_id).count() == 2


def test_failure_rolls_back_partial_replacement(app):
    with app.app_context():
        session_id, _ = _make_session(app)
        persistence = ObservationPersistence(db.session)
        persistence.replace_session_evidence(session_id, [_sample_track()], _sample_observations())
        before_tracks = FaceTrack.query.filter_by(session_id=session_id).count()
        before_obs = RecognitionObservation.query.filter_by(session_id=session_id).count()

        # An observation referencing a track_key that doesn't exist in
        # the tracks list -> KeyError during the replace, must roll
        # back to the pre-replace state entirely.
        bad_observations = _sample_observations()
        bad_observations[0]["track_key"] = "nonexistent-track"

        with pytest.raises(KeyError):
            persistence.replace_session_evidence(session_id, [_sample_track(key="track-9999")], bad_observations)

        db.session.rollback()
        assert FaceTrack.query.filter_by(session_id=session_id).count() == before_tracks
        assert RecognitionObservation.query.filter_by(session_id=session_id).count() == before_obs


def test_deleting_test_session_cleans_only_its_tracks_and_observations(app):
    with app.app_context():
        session_a_id, _ = _make_session(app)
        session_b_id, _ = _make_session(app)
        persistence = ObservationPersistence(db.session)
        persistence.replace_session_evidence(session_a_id, [_sample_track("a-track")], _sample_observations("a-track"))
        persistence.replace_session_evidence(session_b_id, [_sample_track("b-track")], _sample_observations("b-track"))

        from app.models.attendance import AttendanceSession

        session_a = AttendanceSession.query.get(session_a_id)
        db.session.delete(session_a)
        db.session.commit()

        assert FaceTrack.query.filter_by(session_id=session_a_id).count() == 0
        assert RecognitionObservation.query.filter_by(session_id=session_a_id).count() == 0
        # Session B's evidence is completely unaffected.
        assert FaceTrack.query.filter_by(session_id=session_b_id).count() == 1
        assert RecognitionObservation.query.filter_by(session_id=session_b_id).count() == 2


def test_student_rows_are_never_cascade_deleted(app):
    with app.app_context():
        session_id, student_id = _make_session(app)
        persistence = ObservationPersistence(db.session)
        track = _sample_track()
        track["confirmed_student_id"] = student_id
        persistence.replace_session_evidence(session_id, [track], _sample_observations())

        from app.models.attendance import AttendanceSession

        session = AttendanceSession.query.get(session_id)
        db.session.delete(session)
        db.session.commit()

        # The student row itself must survive deleting the session/track
        # that referenced it.
        assert Student.query.get(student_id) is not None
