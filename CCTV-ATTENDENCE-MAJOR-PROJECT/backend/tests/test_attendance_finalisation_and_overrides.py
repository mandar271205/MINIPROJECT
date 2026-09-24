"""Phase 7 - Faculty review, manual overrides, and transaction-safe finalisation tests."""

import datetime
from unittest.mock import patch
import uuid

import pytest

from app.extensions import db
from app.models.attendance import (
    AttendanceRecord,
    AttendanceSession,
    RECOMMENDATION_GENERATION_COMPLETED,
    RECOMMENDATION_GENERATION_NOT_STARTED,
)
from app.models.attendance_audit import AttendanceAuditLog
from app.models.attendance_policy import AttendancePolicy
from app.models.attendance_recommendation import (
    AttendanceFlag,
    AttendanceRecommendation,
)
from app.models.classroom import Classroom
from app.models.student import Student
from app.models.user import User
from app.services.attendance_finalisation_service import (
    FinalisationError,
    FinalisationNotAllowed,
    OverrideNotAllowed,
    UnresolvedReviewRequiredError,
    finalize_session_attendance,
    get_session_audit_logs,
    override_student_attendance,
    reset_student_override,
)


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _create_test_session_with_recs(owner_id=None, student_count=2, *, status="PRESENT", with_review_required=False):
    """Helper to scaffold a classroom, students, session, and recommendations."""
    if owner_id is None:
        user = User(name="Faculty User", email=_uniq("faculty") + "@test.com", role="faculty")
        user.set_password("Pass123!")
        db.session.add(user)
        db.session.commit()
        owner_id = user.id

    classroom = Classroom(name=_uniq("Class"), subject="Math", created_by=owner_id)
    db.session.add(classroom)
    db.session.commit()

    students = []
    for i in range(student_count):
        student = Student(
            class_id=classroom.id,
            roll_number=_uniq(f"R{i}"),
            name=f"Student {i}",
            face_embedding=[0.1 * (i + 1)],
            face_model="buffalo_l",
        )
        db.session.add(student)
        students.append(student)
    db.session.commit()

    session = AttendanceSession(
        class_id=classroom.id,
        uploaded_by=owner_id,
        session_date=datetime.date.today(),
        video_path="test.mp4",
        processing_status="done",
        recommendation_generation_status=RECOMMENDATION_GENERATION_COMPLETED,
        recommendation_generated_at=datetime.datetime.now(datetime.timezone.utc),
        eof_reached=True,
        is_finalised=False,
    )
    db.session.add(session)
    db.session.commit()

    recs = []
    for idx, student in enumerate(students):
        suggested = "REVIEW_REQUIRED" if (with_review_required and idx == 0) else status
        reason_code = "POLICY_ATTENDANCE_PRESENT" if suggested == "PRESENT" else "MANUAL_REVIEW_NEEDED"
        rec = AttendanceRecommendation(
            session_id=session.id,
            student_id=student.id,
            suggested_status=suggested,
            suggested_status_source="AI_RULE",
            reason_code=reason_code,
            reason_text=f"AI determined {suggested}",
            decision_version="v1",
            decision_is_evaluable=True,
            presence_percentage_snapshot=85.0 if suggested == "PRESENT" else 40.0,
        )
        db.session.add(rec)
        recs.append(rec)
    db.session.commit()

    return session, students, recs


# --------------------------------------------------------------------------
# Unit / Service tests: Manual Overrides
# --------------------------------------------------------------------------

def test_override_student_attendance_success(app):
    with app.app_context():
        session, students, recs = _create_test_session_with_recs(student_count=1, status="ABSENT")
        student = students[0]
        user_id = session.uploaded_by

        updated_rec = override_student_attendance(
            session_id=session.id,
            student_id=student.id,
            status="PRESENT",
            reason="Student was physically present and verified by faculty",
            user_id=user_id,
        )

        assert updated_rec.is_overridden is True
        assert updated_rec.final_status == "PRESENT"
        assert updated_rec.override_reason == "Student was physically present and verified by faculty"
        assert updated_rec.overridden_by == user_id
        assert updated_rec.overridden_at is not None

        # Check that FACULTY_OVERRIDE flag was added
        flag = AttendanceFlag.query.filter_by(
            recommendation_id=updated_rec.id, flag_type="FACULTY_OVERRIDE"
        ).first()
        assert flag is not None
        assert flag.source == "FACULTY"
        assert flag.reason_text == "Student was physically present and verified by faculty"

        # Check audit log
        logs = get_session_audit_logs(session.id)
        assert len(logs) == 1
        assert logs[0]["action"] == "OVERRIDE_STATUS"
        assert logs[0]["previous_status"] == "ABSENT"
        assert logs[0]["new_status"] == "PRESENT"
        assert logs[0]["reason"] == "Student was physically present and verified by faculty"
        assert logs[0]["user_id"] == user_id


def test_override_student_attendance_rejects_empty_reason(app):
    with app.app_context():
        session, students, _ = _create_test_session_with_recs(student_count=1)

        with pytest.raises(OverrideNotAllowed, match="non-empty reason is required"):
            override_student_attendance(
                session_id=session.id,
                student_id=students[0].id,
                status="PRESENT",
                reason="   ",
                user_id=session.uploaded_by,
            )


def test_override_student_attendance_rejects_invalid_status(app):
    with app.app_context():
        session, students, _ = _create_test_session_with_recs(student_count=1)

        with pytest.raises(OverrideNotAllowed, match="Invalid override status"):
            override_student_attendance(
                session_id=session.id,
                student_id=students[0].id,
                status="UNKNOWN_STATUS",
                reason="Some reason",
                user_id=session.uploaded_by,
            )


def test_reset_student_override(app):
    with app.app_context():
        session, students, _ = _create_test_session_with_recs(student_count=1, status="ABSENT")
        student = students[0]
        user_id = session.uploaded_by

        override_student_attendance(
            session_id=session.id,
            student_id=student.id,
            status="PRESENT",
            reason="Mistake correction",
            user_id=user_id,
        )

        reset_rec = reset_student_override(
            session_id=session.id,
            student_id=student.id,
            user_id=user_id,
        )

        assert reset_rec.is_overridden is False
        assert reset_rec.override_reason is None
        assert reset_rec.overridden_by is None
        assert reset_rec.final_status is None

        # Flag should be removed
        flag = AttendanceFlag.query.filter_by(
            recommendation_id=reset_rec.id, flag_type="FACULTY_OVERRIDE"
        ).first()
        assert flag is None

        # Audit log
        logs = get_session_audit_logs(session.id)
        assert len(logs) == 2
        assert logs[0]["action"] == "RESET_OVERRIDE"


# --------------------------------------------------------------------------
# Unit / Service tests: Finalisation & Atomic Rollback
# --------------------------------------------------------------------------

def test_finalize_session_attendance_success(app):
    with app.app_context():
        session, students, recs = _create_test_session_with_recs(student_count=2, status="PRESENT")
        user_id = session.uploaded_by

        finalised_session = finalize_session_attendance(
            session_id=session.id,
            user_id=user_id,
            notes="Session reviewed and approved",
        )

        assert finalised_session.is_finalised is True
        assert finalised_session.finalised_at is not None
        assert finalised_session.finalised_by == user_id
        assert finalised_session.finalisation_notes == "Session reviewed and approved"

        # Check that AttendanceRecord rows were created for both students
        records = AttendanceRecord.query.filter_by(session_id=session.id).all()
        assert len(records) == 2
        assert {r.student_id for r in records} == {s.id for s in students}
        assert all(r.status == "PRESENT" for r in records)

        # Check recommendation to_dict reflects is_final=True
        updated_recs = AttendanceRecommendation.query.filter_by(session_id=session.id).all()
        for r in updated_recs:
            d = r.to_dict()
            assert d["is_final"] is True
            assert d["final_status"] == "PRESENT"

        # Audit log entry for finalisation
        logs = get_session_audit_logs(session.id)
        assert any(l["action"] == "FINALIZE_SESSION" for l in logs)


def test_finalize_session_blocks_on_unresolved_review_required(app):
    with app.app_context():
        session, students, _ = _create_test_session_with_recs(
            student_count=2, status="PRESENT", with_review_required=True
        )
        user_id = session.uploaded_by

        with pytest.raises(UnresolvedReviewRequiredError) as exc_info:
            finalize_session_attendance(
                session_id=session.id,
                user_id=user_id,
            )
        assert students[0].id in exc_info.value.unresolved_student_ids

        # If allow_unresolved is True, finalisation is permitted
        finalised = finalize_session_attendance(
            session_id=session.id,
            user_id=user_id,
            allow_unresolved=True,
        )
        assert finalised.is_finalised is True


def test_finalize_session_refused_when_recommendations_not_completed(app):
    with app.app_context():
        session, _, _ = _create_test_session_with_recs(student_count=1)
        session.recommendation_generation_status = RECOMMENDATION_GENERATION_NOT_STARTED
        db.session.commit()

        with pytest.raises(FinalisationNotAllowed, match="recommendation generation status"):
            finalize_session_attendance(
                session_id=session.id,
                user_id=session.uploaded_by,
            )


def test_atomic_rollback_on_failure_prevents_partial_updates(app):
    with app.app_context():
        session, students, _ = _create_test_session_with_recs(student_count=3, status="PRESENT")
        user_id = session.uploaded_by

        # Simulate a crash during the attendance_records loop on student 2
        orig_flush = db.session.flush
        call_count = 0

        def faulty_flush(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise RuntimeError("Simulated mid-finalisation database failure")
            return orig_flush(*args, **kwargs)

        with patch.object(db.session, "flush", side_effect=faulty_flush):
            with pytest.raises(RuntimeError, match="Simulated mid-finalisation"):
                finalize_session_attendance(session_id=session.id, user_id=user_id)

        # Assert no partial updates were committed!
        db.session.expire_all()
        refreshed_session = AttendanceSession.query.get(session.id)
        assert refreshed_session.is_finalised is False
        assert refreshed_session.finalised_at is None

        records = AttendanceRecord.query.filter_by(session_id=session.id).all()
        assert len(records) == 0  # Atomic rollback cleaned up partial records!


# --------------------------------------------------------------------------
# API & RBAC Integration tests
# --------------------------------------------------------------------------

def test_api_override_and_reset_workflow(app, client, hod_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session, students, _ = _create_test_session_with_recs(hod.id, student_count=1, status="ABSENT")
        session_id = session.id
        student_id = students[0].id

    # 1. Apply override
    resp = client.post(
        f"/api/attendance/sessions/{session_id}/students/{student_id}/override",
        headers=hod_headers,
        json={"status": "PRESENT", "reason": "Verified on CCTV recording footage"},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["is_overridden"] is True
    assert data["final_status"] == "PRESENT"
    assert data["override_reason"] == "Verified on CCTV recording footage"
    assert "FACULTY_OVERRIDE" in data["flags"]

    # 2. Check audit logs endpoint
    resp = client.get(f"/api/attendance/sessions/{session_id}/audit-logs", headers=hod_headers)
    assert resp.status_code == 200
    logs = resp.get_json()["data"]["audit_logs"]
    assert len(logs) == 1
    assert logs[0]["action"] == "OVERRIDE_STATUS"
    assert logs[0]["student_id"] == student_id

    # 3. Reset override
    resp = client.delete(
        f"/api/attendance/sessions/{session_id}/students/{student_id}/override",
        headers=hod_headers,
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["is_overridden"] is False
    assert "FACULTY_OVERRIDE" not in data["flags"]


def test_api_finalize_session_workflow(app, client, hod_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session, students, _ = _create_test_session_with_recs(hod.id, student_count=2, status="PRESENT")
        session_id = session.id

    resp = client.post(
        f"/api/attendance/sessions/{session_id}/finalize",
        headers=hod_headers,
        json={"notes": "Finalised for lecture 12"},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["is_finalised"] is True
    assert data["finalisation_notes"] == "Finalised for lecture 12"

    # Verify recommendations response shows is_final=True
    resp = client.get(f"/api/attendance/sessions/{session_id}/recommendations", headers=hod_headers)
    assert resp.status_code == 200
    recs_data = resp.get_json()["data"]
    assert recs_data["is_finalised"] is True
    assert all(r["is_final"] is True for r in recs_data["recommendations"])

    # Verify reports endpoint downloads work with finalised records
    resp_xlsx = client.get(f"/api/reports/{session_id}/xlsx", headers=hod_headers)
    assert resp_xlsx.status_code == 200
    assert resp_xlsx.headers["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_unassigned_faculty_denied_override_and_finalize(app, client, faculty_identity):
    _faculty_id, faculty_headers = faculty_identity
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session, students, _ = _create_test_session_with_recs(hod.id, student_count=1)
        session_id = session.id
        student_id = students[0].id

    # Unassigned faculty cannot override
    resp = client.post(
        f"/api/attendance/sessions/{session_id}/students/{student_id}/override",
        headers=faculty_headers,
        json={"status": "PRESENT", "reason": "Attempted breach"},
    )
    assert resp.status_code == 403

    # Unassigned faculty cannot finalize
    resp = client.post(
        f"/api/attendance/sessions/{session_id}/finalize",
        headers=faculty_headers,
        json={"notes": "Attempted breach"},
    )
    assert resp.status_code == 403

    # Unassigned faculty cannot view audit logs
    resp = client.get(f"/api/attendance/sessions/{session_id}/audit-logs", headers=faculty_headers)
    assert resp.status_code == 403


def test_student_denied_override_and_finalize(app, client, student_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session, students, _ = _create_test_session_with_recs(hod.id, student_count=1)
        session_id = session.id
        student_id = students[0].id

    resp = client.post(
        f"/api/attendance/sessions/{session_id}/students/{student_id}/override",
        headers=student_headers,
        json={"status": "PRESENT", "reason": "Self attendance"},
    )
    assert resp.status_code == 403

    resp = client.post(
        f"/api/attendance/sessions/{session_id}/finalize",
        headers=student_headers,
    )
    assert resp.status_code == 403
