"""Phase 2 correction tests: secure account creation, faculty isolation,
and HOD-controlled student-profile linking.
"""

import uuid


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _register(client, role=None, **overrides):
    payload = {
        "name": "New Person",
        "email": _uniq("reg") + "@example.com",
        "password": "TestPass!234",
    }
    if role is not None:
        payload["role"] = role
    payload.update(overrides)
    return client.post("/api/auth/register", json=payload)


# --------------------------------------------------------------------------
# Secure account creation
# --------------------------------------------------------------------------

def test_public_registration_cannot_create_hod(client):
    resp = _register(client, role="hod")
    assert resp.status_code == 400


def test_public_registration_cannot_create_faculty(client):
    resp = _register(client, role="faculty")
    assert resp.status_code == 400


def test_public_registration_default_is_student_not_faculty(client):
    email = _uniq("reg") + "@example.com"
    resp = client.post(
        "/api/auth/register",
        json={"name": "Someone", "email": email, "password": "TestPass!234"},
    )
    assert resp.status_code == 201

    login_resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass!234"})
    assert login_resp.status_code == 200
    assert login_resp.get_json()["user"]["role"] == "student"


def test_hod_can_create_and_deactivate_faculty(client, hod_headers):
    email = _uniq("newfaculty") + "@example.com"
    create_resp = client.post(
        "/api/admin/faculty",
        json={"name": "New Faculty", "email": email, "password": "TestPass!234"},
        headers=hod_headers,
    )
    assert create_resp.status_code == 201
    body = create_resp.get_json()
    assert body["success"] is True
    assert body["data"]["role"] == "faculty"
    assert "password" not in body["data"]
    assert "password_hash" not in body["data"]
    faculty_id = body["data"]["id"]

    listing = client.get("/api/admin/faculty", headers=hod_headers)
    assert listing.status_code == 200
    assert any(f["id"] == faculty_id for f in listing.get_json()["data"])

    deactivate = client.put(
        f"/api/admin/faculty/{faculty_id}/status", json={"is_active": False}, headers=hod_headers
    )
    assert deactivate.status_code == 200
    assert deactivate.get_json()["data"]["is_active"] is False

    # Deactivated faculty can no longer log in.
    login_resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass!234"})
    assert login_resp.status_code == 403


def test_hod_create_faculty_rejects_duplicate_email(client, hod_headers):
    email = _uniq("dupfaculty") + "@example.com"
    first = client.post(
        "/api/admin/faculty",
        json={"name": "First", "email": email, "password": "TestPass!234"},
        headers=hod_headers,
    )
    assert first.status_code == 201
    second = client.post(
        "/api/admin/faculty",
        json={"name": "Second", "email": email, "password": "TestPass!234"},
        headers=hod_headers,
    )
    assert second.status_code == 409
    assert second.get_json()["error"]["code"] == "DUPLICATE_RESOURCE"


def test_faculty_cannot_create_another_faculty_account(client, faculty_headers):
    resp = client.post(
        "/api/admin/faculty",
        json={"name": "Sneaky", "email": _uniq("sneaky") + "@example.com", "password": "TestPass!234"},
        headers=faculty_headers,
    )
    assert resp.status_code == 403


def test_student_cannot_access_admin_faculty_endpoints(client, student_headers):
    resp = client.get("/api/admin/faculty", headers=student_headers)
    assert resp.status_code == 403


# --------------------------------------------------------------------------
# Faculty academic-visibility isolation
# --------------------------------------------------------------------------

def _build_hierarchy(client, hod_headers, suffix):
    year = client.post(
        "/api/academic/years",
        json={"name": _uniq(f"AY{suffix}"), "start_date": "2026-01-01", "end_date": "2026-12-31"},
        headers=hod_headers,
    ).get_json()["data"]
    semester = client.post(
        "/api/academic/semesters",
        json={"academic_year_id": year["id"], "number": 1, "name": f"Sem {suffix}"},
        headers=hod_headers,
    ).get_json()["data"]
    division = client.post(
        "/api/academic/divisions",
        json={"semester_id": semester["id"], "name": suffix, "program": "CSE", "batch_year": 2026},
        headers=hod_headers,
    ).get_json()["data"]
    subject = client.post(
        "/api/academic/subjects",
        json={"semester_id": semester["id"], "code": _uniq(f"CS{suffix}"), "name": f"Subject {suffix}", "credits": 4},
        headers=hod_headers,
    ).get_json()["data"]
    return year, semester, division, subject


def test_faculty_a_cannot_access_faculty_b_subject_or_division(
    client, hod_headers, faculty_identity, second_faculty_identity
):
    faculty_a_id, faculty_a_headers = faculty_identity
    faculty_b_id, faculty_b_headers = second_faculty_identity

    _, _, division_a, subject_a = _build_hierarchy(client, hod_headers, "A")
    _, _, division_b, subject_b = _build_hierarchy(client, hod_headers, "B")

    assert client.post(
        "/api/academic/faculty-assignments",
        json={"faculty_id": faculty_a_id, "subject_id": subject_a["id"], "division_id": division_a["id"]},
        headers=hod_headers,
    ).status_code == 201
    assert client.post(
        "/api/academic/faculty-assignments",
        json={"faculty_id": faculty_b_id, "subject_id": subject_b["id"], "division_id": division_b["id"]},
        headers=hod_headers,
    ).status_code == 201

    # Faculty A's own list only contains A's subject/division.
    subjects_a = client.get("/api/academic/subjects", headers=faculty_a_headers).get_json()["data"]
    divisions_a = client.get("/api/academic/divisions", headers=faculty_a_headers).get_json()["data"]
    assert {s["id"] for s in subjects_a} == {subject_a["id"]}
    assert {d["id"] for d in divisions_a} == {division_a["id"]}

    # Faculty A manually incrementing/guessing B's subject/division id is
    # rejected with a non-disclosing 404, not the real record.
    resp_subject = client.get(f"/api/academic/subjects/{subject_b['id']}", headers=faculty_a_headers)
    assert resp_subject.status_code == 404
    resp_division = client.get(f"/api/academic/divisions/{division_b['id']}", headers=faculty_a_headers)
    assert resp_division.status_code == 404

    # But faculty A can still fetch their own subject/division by id.
    assert client.get(f"/api/academic/subjects/{subject_a['id']}", headers=faculty_a_headers).status_code == 200
    assert client.get(f"/api/academic/divisions/{division_a['id']}", headers=faculty_a_headers).status_code == 200

    # /api/faculty/me/assignments never mixes the two faculty members.
    mine_a = client.get("/api/faculty/me/assignments", headers=faculty_a_headers).get_json()["data"]
    mine_b = client.get("/api/faculty/me/assignments", headers=faculty_b_headers).get_json()["data"]
    assert {a["subject_id"] for a in mine_a} == {subject_a["id"]}
    assert {a["subject_id"] for a in mine_b} == {subject_b["id"]}


# --------------------------------------------------------------------------
# Student-profile linking
# --------------------------------------------------------------------------

def _create_bare_student(app):
    """Creates a Student row with no linked user, mirroring a legacy
    ZIP-enrolled student, directly via the ORM (there is no HTTP route
    for this in these tests - enroll-zip needs real face images)."""
    with app.app_context():
        from app.extensions import db
        from app.models.classroom import Classroom
        from app.models.student import Student
        from app.models.user import User

        hod = User.query.filter_by(role="hod").first()
        if not hod:
            hod = User(name="Seed HOD", email=_uniq("seedhod") + "@example.com", role="hod")
            hod.set_password("x")
            db.session.add(hod)
            db.session.commit()

        classroom = Classroom(name=_uniq("class"), subject="test", created_by=hod.id)
        db.session.add(classroom)
        db.session.commit()

        student = Student(
            class_id=classroom.id,
            roll_number=_uniq("roll"),
            name="Unlinked Student",
            face_embedding=[0.0],
            face_model="test",
        )
        db.session.add(student)
        db.session.commit()
        return student.id


def test_hod_can_link_a_student_account(app, client, hod_headers, student_identity):
    student_user_id, student_headers = student_identity
    student_id = _create_bare_student(app)

    resp = client.post(
        f"/api/admin/students/{student_id}/account",
        json={"user_id": student_user_id},
        headers=hod_headers,
    )
    assert resp.status_code == 201
    assert resp.get_json()["data"]["id"] == student_id

    profile_resp = client.get("/api/student/me/profile", headers=student_headers)
    assert profile_resp.status_code == 200
    assert profile_resp.get_json()["data"]["id"] == student_id


def test_duplicate_student_user_link_is_rejected(app, client, hod_headers, student_identity):
    student_user_id, _headers = student_identity
    student_one_id = _create_bare_student(app)
    student_two_id = _create_bare_student(app)

    first = client.post(
        f"/api/admin/students/{student_one_id}/account",
        json={"user_id": student_user_id},
        headers=hod_headers,
    )
    assert first.status_code == 201

    # Same user linked to a second student must be rejected.
    second = client.post(
        f"/api/admin/students/{student_two_id}/account",
        json={"user_id": student_user_id},
        headers=hod_headers,
    )
    assert second.status_code == 409
    assert second.get_json()["error"]["code"] == "DUPLICATE_RESOURCE"

    # Linking a second, different user to the already-linked first
    # student must also be rejected.
    from tests.conftest import _make_user_and_headers  # local import to avoid cycles at module load

    other_user_id, _ = _make_user_and_headers(app, "student")
    third = client.post(
        f"/api/admin/students/{student_one_id}/account",
        json={"user_id": other_user_id},
        headers=hod_headers,
    )
    assert third.status_code == 409


def test_student_cannot_self_link_arbitrary_profile(client, student_headers):
    # There is no endpoint at all through which a student can request a
    # link for themselves - only /api/admin/students/... exists, and
    # that requires the HOD role. Confirm the admin path itself rejects
    # a student caller outright.
    resp = client.post(
        "/api/admin/students/1/account", json={"user_id": 1}, headers=student_headers
    )
    assert resp.status_code == 403


def test_student_a_cannot_access_student_b_profile(app, client, student_identity):
    student_a_user_id, headers_a = student_identity
    student_a_id = _create_bare_student(app)

    with app.app_context():
        from app.extensions import db
        from app.models.student import Student

        student_a = Student.query.get(student_a_id)
        student_a.user_id = student_a_user_id
        db.session.commit()

    # student A can see only their own profile - there is no id
    # parameter on this endpoint at all, so "requesting" student B's
    # profile is not even expressible; confirm A gets exactly A's data.
    resp = client.get("/api/student/me/profile", headers=headers_a)
    assert resp.status_code == 200
    assert resp.get_json()["data"]["id"] == student_a_id
    assert resp.get_json()["data"]["name"] == "Unlinked Student"
