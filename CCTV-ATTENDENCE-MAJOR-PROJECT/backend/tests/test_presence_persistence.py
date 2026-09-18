"""Phase 5 - presence persistence idempotency/transaction tests
(category 6 of the required tests)."""

import uuid

import pytest

from app.extensions import db
from app.models.attendance import PRESENCE_STATUS_COMPLETED, PRESENCE_STATUS_FAILED
from app.models.classroom import Classroom
from app.models.presence import PresenceWindow
from app.models.student import Student
from app.models.user import User
from app.services.presence_persistence import (
    PresenceValidationError,
    mark_reconstruction_failed,
    mark_reconstruction_processing,
    replace_session_presence,
)


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _make_session_with_student():
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

    student = Student(class_id=classroom.id, roll_number=_uniq("roll"), name="S", face_embedding=[0.1], face_model="x")
    db.session.add(student)
    db.session.commit()

    session = AttendanceSession(
        class_id=classroom.id, uploaded_by=hod.id, session_date=datetime.date.today(),
        video_path="x.mp4", processing_status="done",
    )
    db.session.add(session)
    db.session.commit()
    return session, student.id


def _valid_row(student_id, window_index=0, start=0.0, end=10.0):
    return dict(
        student_id=student_id, window_index=window_index, start_seconds=start, end_seconds=end,
        observed_duration_seconds=end - start, inferred_gap_seconds=0.0,
        total_duration_seconds=end - start, observation_count=2, contributing_track_count=1,
        mean_confidence=0.8, minimum_confidence=0.7, maximum_confidence=0.9,
        algorithm_version="presence_v1", reconstruction_metadata={"note": "test"},
    )


def test_repeated_reconstruction_produces_identical_windows(app):
    with app.app_context():
        session, sid = _make_session_with_student()
        rows = [_valid_row(sid)]
        replace_session_presence(
            session, window_rows=rows, actual_duration_seconds=100.0, valid_duration_seconds=100.0,
            algorithm_version="presence_v1", status=PRESENCE_STATUS_COMPLETED,
        )
        first = [w.to_dict() if hasattr(w, "to_dict") else w.id for w in PresenceWindow.query.filter_by(session_id=session.id).all()]

        replace_session_presence(
            session, window_rows=rows, actual_duration_seconds=100.0, valid_duration_seconds=100.0,
            algorithm_version="presence_v1", status=PRESENCE_STATUS_COMPLETED,
        )
        second_windows = PresenceWindow.query.filter_by(session_id=session.id).all()
        assert len(second_windows) == 1
        assert second_windows[0].start_seconds == 0.0
        assert second_windows[0].end_seconds == 10.0


def test_no_duplicate_windows_across_repeated_runs(app):
    with app.app_context():
        session, sid = _make_session_with_student()
        rows = [_valid_row(sid, window_index=0), _valid_row(sid, window_index=1, start=20.0, end=30.0)]
        for _ in range(3):
            replace_session_presence(
                session, window_rows=rows, actual_duration_seconds=100.0, valid_duration_seconds=100.0,
                algorithm_version="presence_v1", status=PRESENCE_STATUS_COMPLETED,
            )
        assert PresenceWindow.query.filter_by(session_id=session.id).count() == 2


def test_failure_preserves_previous_windows(app):
    with app.app_context():
        session, sid = _make_session_with_student()
        good_rows = [_valid_row(sid)]
        replace_session_presence(
            session, window_rows=good_rows, actual_duration_seconds=100.0, valid_duration_seconds=100.0,
            algorithm_version="presence_v1", status=PRESENCE_STATUS_COMPLETED,
        )
        before = PresenceWindow.query.filter_by(session_id=session.id).all()
        before_count = len(before)
        before_start = before[0].start_seconds

        bad_row = _valid_row(sid)
        bad_row["end_seconds"] = -5.0  # invalid: end < start
        with pytest.raises(PresenceValidationError):
            replace_session_presence(
                session, window_rows=[bad_row], actual_duration_seconds=100.0, valid_duration_seconds=100.0,
                algorithm_version="presence_v1", status=PRESENCE_STATUS_COMPLETED,
            )

        after = PresenceWindow.query.filter_by(session_id=session.id).all()
        assert len(after) == before_count
        assert after[0].start_seconds == before_start


def test_validation_rejects_mismatched_total_duration(app):
    with app.app_context():
        session, sid = _make_session_with_student()
        row = _valid_row(sid)
        row["total_duration_seconds"] = 999.0  # doesn't equal observed+inferred
        with pytest.raises(PresenceValidationError):
            replace_session_presence(
                session, window_rows=[row], actual_duration_seconds=100.0, valid_duration_seconds=100.0,
                algorithm_version="presence_v1", status=PRESENCE_STATUS_COMPLETED,
            )
        assert PresenceWindow.query.filter_by(session_id=session.id).count() == 0


def test_only_target_session_windows_are_replaced(app):
    with app.app_context():
        session_a, sid_a = _make_session_with_student()
        session_b, sid_b = _make_session_with_student()

        replace_session_presence(
            session_a, window_rows=[_valid_row(sid_a)], actual_duration_seconds=100.0, valid_duration_seconds=100.0,
            algorithm_version="presence_v1", status=PRESENCE_STATUS_COMPLETED,
        )
        replace_session_presence(
            session_b, window_rows=[_valid_row(sid_b)], actual_duration_seconds=100.0, valid_duration_seconds=100.0,
            algorithm_version="presence_v1", status=PRESENCE_STATUS_COMPLETED,
        )

        # Re-run only session A.
        replace_session_presence(
            session_a, window_rows=[_valid_row(sid_a, start=5.0, end=15.0)], actual_duration_seconds=100.0,
            valid_duration_seconds=100.0, algorithm_version="presence_v1", status=PRESENCE_STATUS_COMPLETED,
        )

        b_windows = PresenceWindow.query.filter_by(session_id=session_b.id).all()
        assert len(b_windows) == 1
        assert b_windows[0].start_seconds == 0.0  # untouched by session A's re-run


def test_unrelated_students_and_records_unchanged_by_reconstruction(app):
    with app.app_context():
        from app.models.attendance import AttendanceRecord

        session, sid = _make_session_with_student()
        other_student = Student(class_id=session.class_id, roll_number=_uniq("roll"), name="Other", face_embedding=[0.2], face_model="x")
        db.session.add(other_student)
        db.session.commit()

        record = AttendanceRecord(session_id=session.id, student_id=other_student.id, status="PRESENT")
        db.session.add(record)
        db.session.commit()
        record_id = record.id

        replace_session_presence(
            session, window_rows=[_valid_row(sid)], actual_duration_seconds=100.0, valid_duration_seconds=100.0,
            algorithm_version="presence_v1", status=PRESENCE_STATUS_COMPLETED,
        )

        assert Student.query.get(other_student.id) is not None
        assert AttendanceRecord.query.get(record_id).status == "PRESENT"


def test_mark_processing_and_failed_update_status_only(app):
    with app.app_context():
        session, _sid = _make_session_with_student()
        mark_reconstruction_processing(session)
        assert session.presence_reconstruction_status == "PROCESSING"

        mark_reconstruction_failed(session, "boom")
        assert session.presence_reconstruction_status == PRESENCE_STATUS_FAILED
        assert session.presence_reconstruction_error == "boom"
