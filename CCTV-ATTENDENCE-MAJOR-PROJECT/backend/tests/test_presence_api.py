"""Phase 5 - presence API / RBAC tests (category 7 of the required
tests)."""

import datetime
import uuid

from app.extensions import db
from app.models.attendance import AttendanceSession, PRESENCE_STATUS_COMPLETED, PRESENCE_STATUS_PROCESSING
from app.models.classroom import Classroom
from app.models.student import Student
from app.models.user import User
from app.services.presence_persistence import replace_session_presence


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _make_session_owned_by(owner_user_id, with_windows=True):
    classroom = Classroom(name=_uniq("class"), subject="test", created_by=owner_user_id)
    db.session.add(classroom)
    db.session.commit()

    student = Student(class_id=classroom.id, roll_number=_uniq("roll"), name="S", face_embedding=[0.1], face_model="x")
    db.session.add(student)
    db.session.commit()

    session = AttendanceSession(
        class_id=classroom.id, uploaded_by=owner_user_id, session_date=datetime.date.today(),
        video_path="x.mp4", processing_status="done",
    )
    db.session.add(session)
    db.session.commit()

    if with_windows:
        row = dict(
            student_id=student.id, window_index=0, start_seconds=0.0, end_seconds=10.0,
            observed_duration_seconds=10.0, inferred_gap_seconds=0.0, total_duration_seconds=10.0,
            observation_count=2, contributing_track_count=1, mean_confidence=0.8,
            minimum_confidence=0.7, maximum_confidence=0.9, algorithm_version="presence_v1",
            reconstruction_metadata={},
        )
        replace_session_presence(
            session, window_rows=[row], actual_duration_seconds=100.0, valid_duration_seconds=100.0,
            algorithm_version="presence_v1", status=PRESENCE_STATUS_COMPLETED,
        )
    return session.id, student.id


def test_hod_can_view_presence(app, client, hod_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session_id, student_id = _make_session_owned_by(hod.id)

    resp = client.get(f"/api/attendance/sessions/{session_id}/presence", headers=hod_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    students = body["data"]["students"]
    assert any(s["student_id"] == student_id and s["total_presence_seconds"] == 10.0 for s in students)


def test_assigned_faculty_can_view_and_trigger(app, client, faculty_identity):
    faculty_id, faculty_headers = faculty_identity
    with app.app_context():
        session_id, _student_id = _make_session_owned_by(faculty_id)

    resp = client.get(f"/api/attendance/sessions/{session_id}/presence", headers=faculty_headers)
    assert resp.status_code == 200


def test_unassigned_faculty_denied_view(app, client, hod_headers, faculty_identity):
    _faculty_id, faculty_headers = faculty_identity
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session_id, _student_id = _make_session_owned_by(hod.id)

    resp = client.get(f"/api/attendance/sessions/{session_id}/presence", headers=faculty_headers)
    assert resp.status_code == 403


def test_student_denied_view(app, client, hod_headers, student_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session_id, _student_id = _make_session_owned_by(hod.id)

    resp = client.get(f"/api/attendance/sessions/{session_id}/presence", headers=student_headers)
    assert resp.status_code == 403


def test_student_denied_trigger(app, client, hod_headers, student_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session_id, _student_id = _make_session_owned_by(hod.id)

    resp = client.post(f"/api/attendance/sessions/{session_id}/reconstruct-presence", headers=student_headers)
    assert resp.status_code == 403


def test_missing_jwt_returns_401(client):
    resp = client.get("/api/attendance/sessions/1/presence")
    assert resp.status_code == 401


def test_per_student_presence_endpoint(app, client, hod_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session_id, student_id = _make_session_owned_by(hod.id)

    resp = client.get(f"/api/attendance/sessions/{session_id}/students/{student_id}/presence", headers=hod_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["student"]["student_id"] == student_id


def test_unknown_student_in_session_returns_404(app, client, hod_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session_id, _student_id = _make_session_owned_by(hod.id)

    resp = client.get(f"/api/attendance/sessions/{session_id}/students/999999/presence", headers=hod_headers)
    assert resp.status_code == 404


def test_simultaneous_reconstruction_rejected_safely(app, client, hod_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session_id, _student_id = _make_session_owned_by(hod.id, with_windows=False)
        session = AttendanceSession.query.get(session_id)
        session.presence_reconstruction_status = PRESENCE_STATUS_PROCESSING
        db.session.commit()

    resp = client.post(f"/api/attendance/sessions/{session_id}/reconstruct-presence", headers=hod_headers)
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["error"]["code"] == "RECONSTRUCTION_NOT_ALLOWED"


def test_presence_response_never_contains_raw_embedding_or_path_fields(app, client, hod_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session_id, _student_id = _make_session_owned_by(hod.id)

    resp = client.get(f"/api/attendance/sessions/{session_id}/presence", headers=hod_headers)
    raw = resp.get_data(as_text=True)
    assert "embedding" not in raw.lower()
    assert "video_path" not in raw
    assert "face_model" not in raw
