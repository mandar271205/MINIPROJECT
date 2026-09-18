"""Phase 4 - recognition-evidence API / RBAC tests."""

import datetime
import uuid

from app.extensions import db
from app.models.attendance import AttendanceSession
from app.models.classroom import Classroom
from app.models.user import User
from app.services.observation_persistence import ObservationPersistence


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _make_session_owned_by(app, owner_user_id):
    classroom = Classroom(name=_uniq("class"), subject="test", created_by=owner_user_id)
    db.session.add(classroom)
    db.session.commit()

    session = AttendanceSession(
        class_id=classroom.id, uploaded_by=owner_user_id, session_date=datetime.date.today(),
        video_path="x.mp4", processing_status="done",
    )
    db.session.add(session)
    db.session.commit()

    ObservationPersistence(db.session).replace_session_evidence(
        session.id,
        [
            {
                "track_key": "track-0001", "first_seen_seconds": 0.0, "last_seen_seconds": 5.0,
                "observation_count": 1, "track_state": "CONFIRMED", "confirmed_student_id": None,
                "confirmed_at_seconds": 0.0, "mean_confidence": 0.8, "max_confidence": 0.8,
                "identity_conflict": False, "conflict_reason": None, "closed_at_seconds": 5.0,
            }
        ],
        [
            {
                "track_key": "track-0001", "frame_index": 0, "detection_index": 0, "timestamp_seconds": 0.0,
                "bbox_x1": 0.0, "bbox_y1": 0.0, "bbox_x2": 10.0, "bbox_y2": 10.0,
                "detection_confidence": 0.9, "top1_student_id": None, "top1_similarity": 0.8,
                "top2_student_id": None, "top2_similarity": None, "similarity_margin": None,
                "evidence_state": "MATCH_CANDIDATE", "provider_model_id": "test_model",
            }
        ],
    )
    return session.id


def test_hod_can_view_evidence(app, client, hod_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session_id = _make_session_owned_by(app, hod.id)

    resp = client.get(f"/api/attendance/sessions/{session_id}/recognition-evidence", headers=hod_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["data"]["summary"]["total_tracks"] == 1
    assert body["data"]["tracks"][0]["track_key"] == "track-0001"


def test_assigned_faculty_can_view_own_session_evidence(app, client, faculty_identity):
    faculty_id, faculty_headers = faculty_identity
    with app.app_context():
        session_id = _make_session_owned_by(app, faculty_id)

    resp = client.get(f"/api/attendance/sessions/{session_id}/recognition-evidence", headers=faculty_headers)
    assert resp.status_code == 200


def test_unassigned_faculty_cannot_view_evidence(app, client, hod_headers, faculty_identity):
    _faculty_id, faculty_headers = faculty_identity
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session_id = _make_session_owned_by(app, hod.id)

    resp = client.get(f"/api/attendance/sessions/{session_id}/recognition-evidence", headers=faculty_headers)
    assert resp.status_code == 403


def test_student_cannot_view_evidence(app, client, hod_headers, student_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session_id = _make_session_owned_by(app, hod.id)

    resp = client.get(f"/api/attendance/sessions/{session_id}/recognition-evidence", headers=student_headers)
    assert resp.status_code == 403


def test_missing_jwt_returns_401(client):
    resp = client.get("/api/attendance/sessions/1/recognition-evidence")
    assert resp.status_code == 401


def test_pagination_limit_is_enforced(app, client, hod_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session_id = _make_session_owned_by(app, hod.id)
        from app.models.observation import FaceTrack

        track = FaceTrack.query.filter_by(session_id=session_id).first()
        track_id = track.id

    resp = client.get(
        f"/api/attendance/sessions/{session_id}/tracks/{track_id}/observations?per_page=99999",
        headers=hod_headers,
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["per_page"] <= 200


def test_evidence_response_never_contains_raw_embedding_fields(app, client, hod_headers):
    with app.app_context():
        hod = User.query.filter_by(role="hod").first()
        session_id = _make_session_owned_by(app, hod.id)
        from app.models.observation import FaceTrack

        track_id = FaceTrack.query.filter_by(session_id=session_id).first().id

    resp = client.get(f"/api/attendance/sessions/{session_id}/recognition-evidence", headers=hod_headers)
    raw = resp.get_data(as_text=True)
    assert "embedding" not in raw.lower()

    resp2 = client.get(
        f"/api/attendance/sessions/{session_id}/tracks/{track_id}/observations", headers=hod_headers
    )
    raw2 = resp2.get_data(as_text=True)
    assert "embedding" not in raw2.lower()
    assert "reference_image_path" not in raw2
