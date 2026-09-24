"""Phase 6 - policy and recommendation API / RBAC tests (category 11
of the required tests)."""

import datetime
import uuid

from app.extensions import db
from app.models.attendance import AttendanceSession, RECOMMENDATION_GENERATION_PROCESSING
from app.models.attendance_policy import AttendancePolicy
from app.models.classroom import Classroom
from app.models.presence import PresenceWindow
from app.models.student import Student
from app.models.user import User

import pytest


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _no_leftover_active_global_policy(app):
    """The `app` fixture shares one database across this whole test
    module, and most tests here create a policy with no subject/
    division scope (subject_id=None, division_id=None). Leaving one
    of those active would collide with the next test's own creation
    attempt via check_no_conflicting_active_policy's scope-overlap
    rule - every test starts with a clean slate for that scope."""
    with app.app_context():
        for leftover in AttendancePolicy.query.filter_by(subject_id=None, division_id=None, is_active=True).all():
            leftover.is_active = False
        db.session.commit()
    yield


def _valid_policy_payload(**overrides):
    payload = dict(
        name=_uniq("Policy"), present_threshold_percentage=75.0, late_grace_seconds=600.0,
        early_exit_tolerance_seconds=600.0, reentry_min_gap_seconds=300.0, low_confidence_flag_threshold=0.55,
        minimum_decision_confidence=0.45, minimum_valid_session_ratio=1.0,
    )
    payload.update(overrides)
    return payload


def _make_session_owned_by(owner_user_id, *, with_windows=True):
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
    session.presence_reconstruction_status = "COMPLETED"
    session.valid_duration_seconds = 3600.0
    db.session.add(session)
    db.session.commit()

    if with_windows:
        window = PresenceWindow(
            session_id=session.id, student_id=student.id, window_index=0, start_seconds=0.0, end_seconds=100.0,
            observed_duration_seconds=100.0, inferred_gap_seconds=0.0, total_duration_seconds=100.0,
            observation_count=2, contributing_track_count=1, mean_confidence=0.9, algorithm_version="presence_v1",
        )
        db.session.add(window)
        db.session.commit()
    return session.id, student.id


# --------------------------------------------------------------------------
# Policy CRUD - HOD only
# --------------------------------------------------------------------------

def test_hod_can_create_list_and_view_policy(app, client, hod_headers):
    resp = client.post("/api/attendance/policies", headers=hod_headers, json=_valid_policy_payload())
    assert resp.status_code == 200
    policy_id = resp.get_json()["data"]["id"]

    resp = client.get("/api/attendance/policies", headers=hod_headers)
    assert resp.status_code == 200
    assert any(p["id"] == policy_id for p in resp.get_json()["data"]["policies"])

    resp = client.get(f"/api/attendance/policies/{policy_id}", headers=hod_headers)
    assert resp.status_code == 200


def test_hod_can_update_and_toggle_policy_status(app, client, hod_headers):
    resp = client.post("/api/attendance/policies", headers=hod_headers, json=_valid_policy_payload())
    policy_id = resp.get_json()["data"]["id"]

    resp = client.put(f"/api/attendance/policies/{policy_id}", headers=hod_headers, json={"present_threshold_percentage": 80.0})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["present_threshold_percentage"] == 80.0

    resp = client.put(f"/api/attendance/policies/{policy_id}/status", headers=hod_headers, json={"is_active": False})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["is_active"] is False


def test_faculty_cannot_create_or_modify_policy(app, client, faculty_headers):
    resp = client.post("/api/attendance/policies", headers=faculty_headers, json=_valid_policy_payload())
    assert resp.status_code == 403

    resp = client.get("/api/attendance/policies", headers=faculty_headers)
    assert resp.status_code == 403


def test_student_cannot_access_policy_endpoints(app, client, student_headers):
    resp = client.get("/api/attendance/policies", headers=student_headers)
    assert resp.status_code == 403
    resp = client.post("/api/attendance/policies", headers=student_headers, json=_valid_policy_payload())
    assert resp.status_code == 403


def test_invalid_policy_payload_rejected(app, client, hod_headers):
    resp = client.post(
        "/api/attendance/policies", headers=hod_headers,
        json=_valid_policy_payload(present_threshold_percentage=0.0),
    )
    assert resp.status_code == 400


def test_no_jwt_returns_401_for_policies(client):
    resp = client.get("/api/attendance/policies")
    assert resp.status_code == 401


# --------------------------------------------------------------------------
# Effective policy - HOD + assigned faculty
# --------------------------------------------------------------------------

def test_assigned_faculty_can_view_effective_policy(app, client, faculty_identity):
    faculty_id, faculty_headers = faculty_identity
    with app.app_context():
        client.post("/api/attendance/policies", headers=faculty_headers, json=_valid_policy_payload())  # should 403, ignored

    resp = client.post("/api/attendance/policies", headers=faculty_headers, json=_valid_policy_payload())
    assert resp.status_code == 403  # confirms faculty truly cannot create

    with app.app_context():
        hod = User.query.filter_by(role="hod").first() or User(name="H", email=_uniq("hod") + "@x.com", role="hod")
        if not hod.id:
            hod.set_password("x")
            db.session.add(hod)
            db.session.commit()
        default_policy = AttendancePolicy(
            name=_uniq("Default"), is_default=True, is_active=True, **{k: v for k, v in _valid_policy_payload().items() if k != "name"},
            created_by=hod.id,
        )
        db.session.add(default_policy)
        db.session.commit()
        session_id, _student_id = _make_session_owned_by(faculty_id)

    resp = client.get(f"/api/attendance/sessions/{session_id}/effective-policy", headers=faculty_headers)
    assert resp.status_code == 200
    assert resp.get_json()["data"]["policy"]["is_default"] is True


def test_unassigned_faculty_denied_effective_policy(app, client, hod_headers, faculty_identity):
    _faculty_id, faculty_headers = faculty_identity
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session_id, _student_id = _make_session_owned_by(hod.id)

    resp = client.get(f"/api/attendance/sessions/{session_id}/effective-policy", headers=faculty_headers)
    assert resp.status_code == 403


def test_student_denied_effective_policy(app, client, hod_headers, student_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session_id, _student_id = _make_session_owned_by(hod.id)

    resp = client.get(f"/api/attendance/sessions/{session_id}/effective-policy", headers=student_headers)
    assert resp.status_code == 403


# --------------------------------------------------------------------------
# Recommendation APIs
# --------------------------------------------------------------------------

def test_hod_can_generate_and_view_recommendations(app, client, hod_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        default_policy = AttendancePolicy(
            name=_uniq("Default"), is_default=True, is_active=True,
            **{k: v for k, v in _valid_policy_payload().items() if k != "name"}, created_by=hod.id,
        )
        db.session.add(default_policy)
        db.session.commit()
        session_id, student_id = _make_session_owned_by(hod.id)

    resp = client.post(f"/api/attendance/sessions/{session_id}/generate-recommendations", headers=hod_headers)
    assert resp.status_code == 200

    resp = client.get(f"/api/attendance/sessions/{session_id}/recommendations", headers=hod_headers)
    assert resp.status_code == 200
    recs = resp.get_json()["data"]["recommendations"]
    assert any(r["student_id"] == student_id for r in recs)
    assert all(r["is_final"] is False for r in recs)

    resp = client.get(f"/api/attendance/sessions/{session_id}/students/{student_id}/recommendation", headers=hod_headers)
    assert resp.status_code == 200


def test_unassigned_faculty_denied_recommendations(app, client, hod_headers, faculty_identity):
    _faculty_id, faculty_headers = faculty_identity
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session_id, _student_id = _make_session_owned_by(hod.id)

    resp = client.get(f"/api/attendance/sessions/{session_id}/recommendations", headers=faculty_headers)
    assert resp.status_code == 403
    resp = client.post(f"/api/attendance/sessions/{session_id}/generate-recommendations", headers=faculty_headers)
    assert resp.status_code == 403


def test_student_denied_recommendations(app, client, hod_headers, student_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session_id, _student_id = _make_session_owned_by(hod.id)

    resp = client.get(f"/api/attendance/sessions/{session_id}/recommendations", headers=student_headers)
    assert resp.status_code == 403
    resp = client.post(f"/api/attendance/sessions/{session_id}/generate-recommendations", headers=student_headers)
    assert resp.status_code == 403


def test_no_jwt_returns_401_for_recommendations(client):
    resp = client.get("/api/attendance/sessions/1/recommendations")
    assert resp.status_code == 401


def test_simultaneous_generation_returns_409(app, client, hod_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session_id, _student_id = _make_session_owned_by(hod.id, with_windows=False)
        session = AttendanceSession.query.get(session_id)
        session.recommendation_generation_status = RECOMMENDATION_GENERATION_PROCESSING
        db.session.commit()

    resp = client.post(f"/api/attendance/sessions/{session_id}/generate-recommendations", headers=hod_headers)
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "GENERATION_NOT_ALLOWED"


def test_unknown_student_recommendation_returns_404(app, client, hod_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        default_policy = AttendancePolicy(
            name=_uniq("Default"), is_default=True, is_active=True,
            **{k: v for k, v in _valid_policy_payload().items() if k != "name"}, created_by=hod.id,
        )
        db.session.add(default_policy)
        db.session.commit()
        session_id, _student_id = _make_session_owned_by(hod.id)

    client.post(f"/api/attendance/sessions/{session_id}/generate-recommendations", headers=hod_headers)
    resp = client.get(f"/api/attendance/sessions/{session_id}/students/999999/recommendation", headers=hod_headers)
    assert resp.status_code == 404


def test_recommendation_response_never_contains_raw_embedding_or_path_fields(app, client, hod_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        default_policy = AttendancePolicy(
            name=_uniq("Default"), is_default=True, is_active=True,
            **{k: v for k, v in _valid_policy_payload().items() if k != "name"}, created_by=hod.id,
        )
        db.session.add(default_policy)
        db.session.commit()
        session_id, _student_id = _make_session_owned_by(hod.id)

    client.post(f"/api/attendance/sessions/{session_id}/generate-recommendations", headers=hod_headers)
    resp = client.get(f"/api/attendance/sessions/{session_id}/recommendations", headers=hod_headers)
    raw = resp.get_data(as_text=True)
    assert "embedding" not in raw.lower()
    assert "video_path" not in raw
    assert "face_model" not in raw
