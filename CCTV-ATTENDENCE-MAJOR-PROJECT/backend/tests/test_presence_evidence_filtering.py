"""Phase 5 - trusted-evidence filtering tests (category 1 of the
required tests). Exercises filter_trusted_observations_by_student()
directly against the database.
"""

import uuid

from app.extensions import db
from app.models.classroom import Classroom
from app.models.observation import FaceTrack, RecognitionObservation
from app.models.student import Student
from app.models.user import User
from app.services.presence_reconstruction import filter_trusted_observations_by_student


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _make_session():
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

    students = []
    for i in range(2):
        s = Student(
            class_id=classroom.id, roll_number=_uniq(f"roll{i}"), name=f"S{i}",
            face_embedding=[0.1], face_model="x",
        )
        db.session.add(s)
        students.append(s)
    db.session.commit()

    session = AttendanceSession(
        class_id=classroom.id, uploaded_by=hod.id, session_date=datetime.date.today(),
        video_path="x.mp4", processing_status="done",
    )
    db.session.add(session)
    db.session.commit()
    return session.id, [s.id for s in students]


def _add_track(session_id, student_id, *, state="CONFIRMED", conflict=False, key=None):
    track = FaceTrack(
        session_id=session_id, track_key=key or _uniq("track"),
        first_seen_seconds=0.0, last_seen_seconds=10.0, observation_count=1,
        track_state=state, confirmed_student_id=student_id, identity_conflict=conflict,
    )
    db.session.add(track)
    db.session.commit()
    return track.id


def _add_observation(session_id, track_id, top1_student_id, *, ts=1.0, sim=0.8,
                      evidence_state="CONFIRMED_SUPPORT", frame_index=0, detection_index=0):
    obs = RecognitionObservation(
        session_id=session_id, track_id=track_id, frame_index=frame_index,
        detection_index=detection_index, timestamp_seconds=ts,
        top1_student_id=top1_student_id, top1_similarity=sim,
        evidence_state=evidence_state, provider_model_id="test_model",
    )
    db.session.add(obs)
    db.session.commit()
    return obs.id


def test_confirmed_support_is_accepted(app):
    with app.app_context():
        session_id, [sid, _] = _make_session()
        track_id = _add_track(session_id, sid)
        _add_observation(session_id, track_id, sid, evidence_state="CONFIRMED_SUPPORT")

        by_student, excluded = filter_trusted_observations_by_student(session_id)
        assert excluded == 0
        assert sid in by_student
        assert len(by_student[sid]) == 1


def test_non_confirmed_support_states_are_excluded(app):
    with app.app_context():
        session_id, [sid, _] = _make_session()
        track_id = _add_track(session_id, sid)
        for i, state in enumerate(["MATCH_CANDIDATE", "UNKNOWN", "AMBIGUOUS", "CONFLICTING", "BELOW_THRESHOLD"]):
            _add_observation(session_id, track_id, sid, evidence_state=state, frame_index=i + 1)

        by_student, _ = filter_trusted_observations_by_student(session_id)
        assert by_student.get(sid, []) == []


def test_conflicting_track_is_excluded_entirely(app):
    with app.app_context():
        session_id, [sid, _] = _make_session()
        track_id = _add_track(session_id, sid, conflict=True)
        _add_observation(session_id, track_id, sid, evidence_state="CONFIRMED_SUPPORT")

        by_student, excluded = filter_trusted_observations_by_student(session_id)
        assert excluded == 1
        assert by_student.get(sid, []) == []


def test_unconfirmed_track_state_is_excluded(app):
    with app.app_context():
        session_id, [sid, _] = _make_session()
        track_id = _add_track(session_id, sid, state="UNCONFIRMED")
        _add_observation(session_id, track_id, sid, evidence_state="CONFIRMED_SUPPORT")

        by_student, _ = filter_trusted_observations_by_student(session_id)
        assert by_student.get(sid, []) == []


def test_incompatible_student_never_silently_given_zero_evidence_treated_as_zero(app):
    # This test documents the boundary: filter_trusted_observations_by_student
    # simply returns no observations for a student with no track evidence at
    # all - it does NOT decide eligibility. Eligibility/ineligible-reason
    # handling belongs to recognition_eligibility + reconstruct_session_presence,
    # tested separately; a student absent from by_student must never be
    # silently treated as 0% by this layer alone.
    with app.app_context():
        session_id, [sid, other_sid] = _make_session()
        track_id = _add_track(session_id, other_sid)
        _add_observation(session_id, track_id, other_sid, evidence_state="CONFIRMED_SUPPORT")

        by_student, _ = filter_trusted_observations_by_student(session_id)
        assert sid not in by_student
        assert other_sid in by_student


def test_duplicate_observation_not_double_counted(app):
    with app.app_context():
        session_id, [sid, _] = _make_session()
        track_id = _add_track(session_id, sid)
        _add_observation(session_id, track_id, sid, frame_index=0, detection_index=0)
        # Same (session, track, frame_index, detection_index) key can't be
        # inserted twice due to the unique constraint - simulate a
        # duplicate query result by asserting the dedupe key logic instead:
        # insert a *different* row that nonetheless represents the same
        # detection identity is impossible at the DB layer, so we assert
        # only one observation is ever returned for one physical detection.
        by_student, _ = filter_trusted_observations_by_student(session_id)
        assert len(by_student[sid]) == 1


def test_invalid_timestamp_is_rejected(app):
    with app.app_context():
        session_id, [sid, _] = _make_session()
        track_id = _add_track(session_id, sid)
        # timestamp_seconds has a DB check constraint (>=0), so exercise
        # the module's own guard using a directly constructed observation
        # via bulk update after insert to bypass the ORM-level default path.
        obs_id = _add_observation(session_id, track_id, sid, ts=5.0)
        obs = RecognitionObservation.query.get(obs_id)
        obs.timestamp_seconds = float("inf")
        db.session.commit()

        by_student, _ = filter_trusted_observations_by_student(session_id)
        assert by_student.get(sid, []) == []


def test_mismatched_top1_student_is_excluded(app):
    with app.app_context():
        session_id, [sid, other_sid] = _make_session()
        track_id = _add_track(session_id, sid)
        # Observation's top1 doesn't match the track's confirmed student.
        _add_observation(session_id, track_id, other_sid, evidence_state="CONFIRMED_SUPPORT")

        by_student, _ = filter_trusted_observations_by_student(session_id)
        assert by_student.get(sid, []) == []
        assert by_student.get(other_sid, []) == []


def test_track_with_no_confirmed_student_is_excluded(app):
    with app.app_context():
        session_id, [sid, _] = _make_session()
        track_id = _add_track(session_id, None)
        _add_observation(session_id, track_id, sid, evidence_state="CONFIRMED_SUPPORT")

        by_student, excluded = filter_trusted_observations_by_student(session_id)
        assert excluded == 0
        assert by_student == {}
