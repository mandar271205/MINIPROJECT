"""Phase 8 - API Integration tests for At-Risk & Shortage Prediction Engine."""

import datetime
import uuid

import pytest

from app.extensions import db
from app.models.academic import AcademicYear, Division, FacultyAssignment, Semester, Subject
from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.classroom import Classroom
from app.models.student import Student
from app.models.user import User


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _scaffold_test_environment(app, faculty_user_id: int):
    """Sets up academic hierarchy, classroom, sessions, and 3 test students with distinct risk profiles."""
    with app.app_context():
        today = datetime.date.today()

        # Academic hierarchy
        year = AcademicYear(
            name=_uniq("AY"),
            start_date=today - datetime.timedelta(days=180),
            end_date=today + datetime.timedelta(days=180),
            is_current=True,
        )
        db.session.add(year)
        db.session.commit()

        sem = Semester(academic_year_id=year.id, number=1, name="Semester 1")
        db.session.add(sem)
        db.session.commit()

        division = Division(semester_id=sem.id, name="DivA", program="CS", batch_year=2026)
        subject = Subject(semester_id=sem.id, code=_uniq("SUB"), name="Computer Science", credits=4)
        db.session.add_all([division, subject])
        db.session.commit()

        assignment = FacultyAssignment(
            faculty_id=faculty_user_id,
            subject_id=subject.id,
            division_id=division.id,
            is_active=True,
        )
        db.session.add(assignment)
        db.session.commit()

        # Classroom
        classroom = Classroom(
            name=_uniq("Class_AI"),
            subject="Computer Science",
            subject_id=subject.id,
            division_id=division.id,
            legacy_mode=False,
            created_by=faculty_user_id,
        )
        db.session.add(classroom)
        db.session.commit()

        # 3 Students:
        # St1: High Risk (critically low attendance + consecutive absences)
        # St2: Medium Risk (moderate attendance ~66% or 2 consecutive absences)
        # St3: Low Risk (100% attendance, on track)
        st_high = Student(
            class_id=classroom.id,
            division_id=division.id,
            roll_number="01",
            name="High Risk Student",
            face_embedding=[0.1],
            face_model="buffalo_l",
        )
        st_med = Student(
            class_id=classroom.id,
            division_id=division.id,
            roll_number="02",
            name="Medium Risk Student",
            face_embedding=[0.2],
            face_model="buffalo_l",
        )
        st_low = Student(
            class_id=classroom.id,
            division_id=division.id,
            roll_number="03",
            name="Low Risk Student",
            face_embedding=[0.3],
            face_model="buffalo_l",
        )
        db.session.add_all([st_high, st_med, st_low])
        db.session.commit()

        # 6 Sessions across 3 consecutive weeks (2 sessions per week)
        sessions = []
        base_date = today - datetime.timedelta(days=21)
        day_offsets = [0, 2, 7, 9, 14, 16]
        for i in range(6):
            sess_date = base_date + datetime.timedelta(days=day_offsets[i])
            s = AttendanceSession(
                class_id=classroom.id,
                uploaded_by=faculty_user_id,
                session_date=sess_date,
                video_path=f"sess_{i}.mp4",
                processing_status="done",
                is_finalised=(i < 5),  # session 0..4 finalised, session 5 unfinalised
            )
            db.session.add(s)
            sessions.append(s)
        db.session.commit()

        # Attendance Records:
        # St_high: attended sessions 0, 1 (PRESENT); absent in 2, 3, 4, 5 (4 consecutive absences, 2/6 = 33.3% -> HIGH)
        # St_med: attended sessions 0, 2, 4, 5 (PRESENT); absent in 1, 3 (4/6 = 66.7%, stable/positive velocity -> MEDIUM)
        # St_low: attended all sessions 0..5 (PRESENT -> 100% -> LOW)
        for s_idx, sess in enumerate(sessions):
            # St_high
            st1_status = "PRESENT" if s_idx < 2 else "ABSENT"
            db.session.add(AttendanceRecord(session_id=sess.id, student_id=st_high.id, status=st1_status))

            # St_med: sessions 0, 2, 4, 5 present (4/6 = 66.67%, no consecutive absence streak >= 2, non-declining velocity)
            st2_status = "PRESENT" if s_idx in (0, 2, 4, 5) else "ABSENT"
            db.session.add(AttendanceRecord(session_id=sess.id, student_id=st_med.id, status=st2_status))

            # St_low
            db.session.add(AttendanceRecord(session_id=sess.id, student_id=st_low.id, status="PRESENT"))

        db.session.commit()


        classroom_id = classroom.id
        subject_id = subject.id
        division_id = division.id
        st_high_id = st_high.id
        st_med_id = st_med.id
        st_low_id = st_low.id

    return {
        "classroom_id": classroom_id,
        "subject_id": subject_id,
        "division_id": division_id,
        "student_ids": {"high": st_high_id, "med": st_med_id, "low": st_low_id},
    }



# ===========================================================================
# 1. Class At-Risk Endpoint Tests
# ===========================================================================

def test_faculty_can_fetch_class_at_risk(app, client, faculty_identity, faculty_headers):
    """Faculty fetches at-risk students for their owned classroom."""
    faculty_id = faculty_identity[0]
    data = _scaffold_test_environment(app, faculty_id)
    class_id = data["classroom_id"]

    res = client.get(f"/api/attendance/classes/{class_id}/at-risk", headers=faculty_headers)
    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True

    payload = body["data"]
    assert payload["class_id"] == class_id
    assert payload["total_students"] == 3
    assert payload["total_sessions"] == 6

    # Verify summary counts
    summary = payload["summary"]
    assert summary["high_risk_count"] == 1
    assert summary["medium_risk_count"] == 1
    assert summary["low_risk_count"] == 1
    assert summary["at_risk_total"] == 2

    # Check students list
    students = payload["students"]
    assert len(students) == 3

    # Sorted by risk score descending: highest risk first
    assert students[0]["risk_level"] == "HIGH"
    assert students[0]["roll_number"] == "01"
    assert students[0]["attendance_percentage"] == 33.33
    assert students[0]["consecutive_absences"] >= 3

    assert students[1]["risk_level"] == "MEDIUM"
    assert students[1]["roll_number"] == "02"
    assert students[1]["attendance_percentage"] == 66.67

    assert students[2]["risk_level"] == "LOW"
    assert students[2]["roll_number"] == "03"
    assert students[2]["attendance_percentage"] == 100.0


def test_unauthorized_faculty_forbidden_from_class_at_risk(
    app, client, faculty_identity, second_faculty_identity
):
    """A faculty member cannot access at-risk data for another faculty member's class."""
    faculty_id = faculty_identity[0]
    data = _scaffold_test_environment(app, faculty_id)
    class_id = data["classroom_id"]
    second_headers = second_faculty_identity[1]

    res = client.get(f"/api/attendance/classes/{class_id}/at-risk", headers=second_headers)
    assert res.status_code == 403


def test_hod_can_fetch_any_class_at_risk(app, client, faculty_identity, hod_headers):
    """HOD can access at-risk data for any class."""
    faculty_id = faculty_identity[0]
    data = _scaffold_test_environment(app, faculty_id)
    class_id = data["classroom_id"]

    res = client.get(f"/api/attendance/classes/{class_id}/at-risk", headers=hod_headers)
    assert res.status_code == 200
    body = res.get_json()
    assert body["data"]["class_id"] == class_id


def test_class_at_risk_filtering_by_risk_level(app, client, faculty_identity, faculty_headers):
    """Filtering by risk_level=HIGH or risk_level=AT_RISK."""
    faculty_id = faculty_identity[0]
    data = _scaffold_test_environment(app, faculty_id)
    class_id = data["classroom_id"]

    # Filter HIGH
    res_high = client.get(
        f"/api/attendance/classes/{class_id}/at-risk?risk_level=HIGH",
        headers=faculty_headers,
    )
    assert res_high.status_code == 200
    st_high_list = res_high.get_json()["data"]["students"]
    assert len(st_high_list) == 1
    assert st_high_list[0]["risk_level"] == "HIGH"

    # Filter AT_RISK (HIGH + MEDIUM)
    res_at_risk = client.get(
        f"/api/attendance/classes/{class_id}/at-risk?risk_level=AT_RISK",
        headers=faculty_headers,
    )
    assert res_at_risk.status_code == 200
    st_at_risk_list = res_at_risk.get_json()["data"]["students"]
    assert len(st_at_risk_list) == 2
    assert {s["risk_level"] for s in st_at_risk_list} == {"HIGH", "MEDIUM"}


def test_class_at_risk_only_finalised_filter(app, client, faculty_identity, faculty_headers):
    """When only_finalised=true, unfinalised sessions are excluded."""
    faculty_id = faculty_identity[0]
    data = _scaffold_test_environment(app, faculty_id)
    class_id = data["classroom_id"]

    res = client.get(
        f"/api/attendance/classes/{class_id}/at-risk?only_finalised=true",
        headers=faculty_headers,
    )
    assert res.status_code == 200
    payload = res.get_json()["data"]
    # 5 finalised sessions out of 6 total
    assert payload["total_sessions"] == 5


# ===========================================================================
# 2. Subject At-Risk Endpoint Tests
# ===========================================================================

def test_subject_at_risk_assigned_faculty_and_hod(
    app, client, faculty_identity, second_faculty_identity, hod_headers, faculty_headers
):
    """Assigned faculty and HOD can access subject at-risk; unassigned faculty receives 404."""
    faculty_id = faculty_identity[0]
    data = _scaffold_test_environment(app, faculty_id)
    subject_id = data["subject_id"]
    second_headers = second_faculty_identity[1]

    # Assigned faculty -> 200
    res_assigned = client.get(
        f"/api/attendance/subjects/{subject_id}/at-risk", headers=faculty_headers
    )
    assert res_assigned.status_code == 200
    body_assigned = res_assigned.get_json()["data"]
    assert body_assigned["subject_id"] == subject_id
    assert body_assigned["total_students"] == 3

    # HOD -> 200
    res_hod = client.get(f"/api/attendance/subjects/{subject_id}/at-risk", headers=hod_headers)
    assert res_hod.status_code == 200

    # Unassigned second faculty -> 404 non-disclosing
    res_unassigned = client.get(
        f"/api/attendance/subjects/{subject_id}/at-risk", headers=second_headers
    )
    assert res_unassigned.status_code == 404



# ===========================================================================
# 3. Student Risk Profile Tests
# ===========================================================================

def test_student_risk_profile_timeline_and_recovery(app, client, faculty_identity, faculty_headers):
    """Faculty can retrieve student risk profile with timeline and recovery forecast."""
    faculty_id = faculty_identity[0]
    data = _scaffold_test_environment(app, faculty_id)
    st_high_id = data["student_ids"]["high"]

    res = client.get(
        f"/api/attendance/students/{st_high_id}/risk-profile", headers=faculty_headers
    )
    assert res.status_code == 200
    payload = res.get_json()["data"]

    assert payload["student_id"] == st_high_id
    assert payload["student_name"] == "High Risk Student"
    assert payload["risk_level"] == "HIGH"
    assert payload["attendance_percentage"] == 33.33
    assert payload["sessions_needed_to_recover"] > 0
    assert len(payload["timeline"]) == 6
    assert len(payload["recommendations"]) > 0


def test_student_self_profile_and_isolation(app, client, faculty_identity):
    """Enrolled student can view their own profile via /me/risk-profile, but cannot view other students."""
    faculty_id = faculty_identity[0]
    data = _scaffold_test_environment(app, faculty_id)
    st_med_id = data["student_ids"]["med"]
    st_high_id = data["student_ids"]["high"]

    # Create a user account and link to st_med
    from flask_jwt_extended import create_access_token

    with app.app_context():
        user = User(name="Med Student User", email=_uniq("student") + "@example.com", role="student")
        user.set_password("Pass1234!")
        db.session.add(user)
        db.session.commit()
        st_med_row = Student.query.get(st_med_id)
        st_med_row.user_id = user.id
        db.session.commit()
        token = create_access_token(identity=str(user.id), additional_claims={"role": "student"})
        student_headers = {"Authorization": f"Bearer {token}"}

    # 1. Access own risk profile via /api/student/me/risk-profile
    res_me = client.get("/api/student/me/risk-profile", headers=student_headers)
    assert res_me.status_code == 200
    payload_me = res_me.get_json()["data"]
    assert payload_me["student_id"] == st_med_id
    assert payload_me["student_name"] == "Medium Risk Student"

    # 2. Access own risk profile via /api/attendance/students/<id>/risk-profile
    res_own = client.get(f"/api/attendance/students/{st_med_id}/risk-profile", headers=student_headers)
    assert res_own.status_code == 200

    # 3. Access another student's profile -> 403 Forbidden
    res_other = client.get(f"/api/attendance/students/{st_high_id}/risk-profile", headers=student_headers)
    assert res_other.status_code == 403


# ===========================================================================
# 4. At-Risk Dashboard Overview Tests
# ===========================================================================

def test_at_risk_overview_faculty_and_hod(app, client, faculty_identity, faculty_headers, hod_headers):
    """Faculty and HOD can fetch aggregated at-risk overview."""
    faculty_id = faculty_identity[0]
    _scaffold_test_environment(app, faculty_id)

    # Faculty overview
    res_faculty = client.get("/api/attendance/at-risk/overview", headers=faculty_headers)
    assert res_faculty.status_code == 200
    fac_overview = res_faculty.get_json()["data"]
    assert fac_overview["total_classes_monitored"] >= 1
    assert fac_overview["total_students_monitored"] >= 3
    assert fac_overview["high_risk_count"] >= 1
    assert fac_overview["medium_risk_count"] >= 1
    assert len(fac_overview["top_at_risk_students"]) >= 1

    # HOD overview
    res_hod = client.get("/api/attendance/at-risk/overview", headers=hod_headers)
    assert res_hod.status_code == 200
    hod_overview = res_hod.get_json()["data"]
    assert hod_overview["total_classes_monitored"] >= 1
    assert hod_overview["total_students_monitored"] >= 3

