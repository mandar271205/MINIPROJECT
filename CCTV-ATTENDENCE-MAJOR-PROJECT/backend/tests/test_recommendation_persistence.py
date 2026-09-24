"""Phase 6 - recommendation/flag persistence idempotency and
transaction-safety tests (category 10 of the required tests)."""

import uuid

import pytest

from app.extensions import db
from app.models.attendance_recommendation import AttendanceFlag, AttendanceRecommendation
from app.models.classroom import Classroom
from app.models.student import Student
from app.models.user import User
from app.services.attendance_decision_engine import FLAG_LATE, FLAG_LOW_CONFIDENCE, STATUS_PARTIAL, STATUS_PRESENT
from app.services.recommendation_persistence import (
    RecommendationValidationError,
    replace_session_recommendations,
)


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _make_session_with_students(n=2):
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
    for i in range(n):
        s = Student(class_id=classroom.id, roll_number=_uniq(f"roll{i}"), name=f"S{i}", face_embedding=[0.1], face_model="x")
        db.session.add(s)
        students.append(s)
    db.session.commit()

    session = AttendanceSession(
        class_id=classroom.id, uploaded_by=hod.id, session_date=datetime.date.today(),
        video_path="x.mp4", processing_status="done",
    )
    db.session.add(session)
    db.session.commit()
    return session, [s.id for s in students]


def _row(student_id, status=STATUS_PRESENT, flags=None, reason_code="PRESENCE_MEETS_THRESHOLD"):
    return dict(
        student_id=student_id, attendance_record_id=None, suggested_status=status, reason_code=reason_code,
        reason_text="test reason", explanation_json={"suggested_status": status}, policy_id=None,
        policy_snapshot_json=None, decision_version="attendance_rules_v1", decision_confidence=0.9,
        decision_is_evaluable=True, presence_percentage_snapshot=80.0, presence_duration_seconds_snapshot=2880.0,
        valid_session_seconds_snapshot=3600.0, flags=list(flags or []),
    )


def test_repeated_generation_produces_no_duplicates(app):
    with app.app_context():
        session, [sid] = _make_session_with_students(1)
        rows = [_row(sid, flags=[FLAG_LATE])]
        replace_session_recommendations(session, recommendation_rows=[dict(rows[0])])
        replace_session_recommendations(session, recommendation_rows=[dict(rows[0])])

        assert AttendanceRecommendation.query.filter_by(session_id=session.id).count() == 1
        rec = AttendanceRecommendation.query.filter_by(session_id=session.id).first()
        assert AttendanceFlag.query.filter_by(recommendation_id=rec.id).count() == 1


def test_failed_calculation_preserves_previous_recommendation(app):
    with app.app_context():
        session, [sid] = _make_session_with_students(1)
        good_row = _row(sid, status=STATUS_PRESENT)
        replace_session_recommendations(session, recommendation_rows=[dict(good_row)])
        before = AttendanceRecommendation.query.filter_by(session_id=session.id).first()
        before_status = before.suggested_status

        bad_row = _row(sid, status="NOT_A_REAL_STATUS")
        with pytest.raises(RecommendationValidationError):
            replace_session_recommendations(session, recommendation_rows=[dict(bad_row)])

        after = AttendanceRecommendation.query.filter_by(session_id=session.id).first()
        assert after.suggested_status == before_status


def test_unrelated_sessions_unaffected(app):
    with app.app_context():
        session_a, [sid_a] = _make_session_with_students(1)
        session_b, [sid_b] = _make_session_with_students(1)

        replace_session_recommendations(session_a, recommendation_rows=[dict(_row(sid_a))])
        replace_session_recommendations(session_b, recommendation_rows=[dict(_row(sid_b, status=STATUS_PARTIAL))])

        replace_session_recommendations(session_a, recommendation_rows=[dict(_row(sid_a, status=STATUS_PARTIAL))])

        rec_b = AttendanceRecommendation.query.filter_by(session_id=session_b.id).first()
        assert rec_b.suggested_status == STATUS_PARTIAL  # untouched by session A's re-run


def test_legacy_attendance_record_status_untouched(app):
    with app.app_context():
        from app.models.attendance import AttendanceRecord

        session, [sid] = _make_session_with_students(1)
        record = AttendanceRecord(session_id=session.id, student_id=sid, status="present")
        db.session.add(record)
        db.session.commit()
        record_id = record.id

        replace_session_recommendations(
            session, recommendation_rows=[dict(_row(sid, status=STATUS_PARTIAL))]
        )

        assert AttendanceRecord.query.get(record_id).status == "present"  # legacy field never rewritten


def test_manual_future_source_flags_are_not_deleted(app):
    with app.app_context():
        session, [sid] = _make_session_with_students(1)
        replace_session_recommendations(session, recommendation_rows=[dict(_row(sid, flags=[FLAG_LATE]))])
        rec = AttendanceRecommendation.query.filter_by(session_id=session.id).first()

        manual_flag = AttendanceFlag(
            recommendation_id=rec.id, session_id=session.id, student_id=sid,
            flag_type="FACULTY_OVERRIDE", source="FACULTY", reason_code="MANUAL_TEST",
        )
        db.session.add(manual_flag)
        db.session.commit()
        manual_flag_id = manual_flag.id

        replace_session_recommendations(session, recommendation_rows=[dict(_row(sid, flags=[FLAG_LOW_CONFIDENCE]))])

        # The recommendation row is upserted IN PLACE (same primary
        # key) specifically so a manual/future-source flag attached to
        # it survives recalculation untouched, while its own AI_RULE
        # flags are replaced.
        new_rec = AttendanceRecommendation.query.filter_by(session_id=session.id).first()
        assert new_rec.id == rec.id
        assert AttendanceFlag.query.get(manual_flag_id) is not None
        surviving_flag = AttendanceFlag.query.get(manual_flag_id)
        assert surviving_flag.flag_type == "FACULTY_OVERRIDE"
        assert surviving_flag.source == "FACULTY"

        ai_flags = AttendanceFlag.query.filter_by(recommendation_id=rec.id, source="AI_RULE").all()
        assert [f.flag_type for f in ai_flags] == [FLAG_LOW_CONFIDENCE]  # old AI flag (LATE) was replaced


def test_whole_session_update_is_transactional(app):
    with app.app_context():
        session, [sid1, sid2] = _make_session_with_students(2)
        bad_rows = [dict(_row(sid1)), dict(_row(sid2, status="INVALID"))]

        with pytest.raises(RecommendationValidationError):
            replace_session_recommendations(session, recommendation_rows=bad_rows)

        # Neither row was written - partial-roster updates are forbidden.
        assert AttendanceRecommendation.query.filter_by(session_id=session.id).count() == 0


def test_every_rostered_student_receives_a_row_including_ineligible(app):
    with app.app_context():
        session, [sid1, sid2] = _make_session_with_students(2)
        rows = [dict(_row(sid1, status=STATUS_PRESENT)), dict(_row(sid2, status="REVIEW_REQUIRED", reason_code="FACE_TEMPLATE_UNAVAILABLE"))]
        rows[1]["decision_is_evaluable"] = False
        rows[1]["presence_percentage_snapshot"] = None
        rows[1]["decision_confidence"] = None

        created = replace_session_recommendations(session, recommendation_rows=rows)
        assert len(created) == 2
        assert {r.student_id for r in created} == {sid1, sid2}
