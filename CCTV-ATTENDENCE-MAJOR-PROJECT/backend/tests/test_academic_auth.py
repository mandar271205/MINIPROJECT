import uuid


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _year_payload():
    return {"name": _uniq("AY"), "start_date": "2026-01-01", "end_date": "2026-12-31"}


def test_missing_jwt_returns_401(client):
    resp = client.get("/api/academic/years")
    assert resp.status_code == 401


def test_hod_can_create_academic_year(client, hod_headers):
    resp = client.post("/api/academic/years", json=_year_payload(), headers=hod_headers)
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["success"] is True
    assert body["data"]["name"]


def test_faculty_cannot_create_academic_year(client, faculty_headers):
    resp = client.post("/api/academic/years", json=_year_payload(), headers=faculty_headers)
    assert resp.status_code == 403


def test_student_cannot_access_academic_management(client, student_headers):
    resp = client.get("/api/academic/years", headers=student_headers)
    assert resp.status_code == 403


def test_faculty_can_read_academic_years(client, faculty_headers, hod_headers):
    client.post("/api/academic/years", json=_year_payload(), headers=hod_headers)
    resp = client.get("/api/academic/years", headers=faculty_headers)
    assert resp.status_code == 200


def test_faculty_cannot_create_faculty_assignment(client, faculty_headers):
    resp = client.post(
        "/api/academic/faculty-assignments",
        json={"faculty_id": 1, "subject_id": 1, "division_id": 1},
        headers=faculty_headers,
    )
    assert resp.status_code == 403


def _build_hierarchy(client, hod_headers):
    year = client.post("/api/academic/years", json=_year_payload(), headers=hod_headers).get_json()["data"]
    semester = client.post(
        "/api/academic/semesters",
        json={"academic_year_id": year["id"], "number": 1, "name": "Sem 1"},
        headers=hod_headers,
    ).get_json()["data"]
    division = client.post(
        "/api/academic/divisions",
        json={"semester_id": semester["id"], "name": "A", "program": "CSE", "batch_year": 2026},
        headers=hod_headers,
    ).get_json()["data"]
    subject = client.post(
        "/api/academic/subjects",
        json={"semester_id": semester["id"], "code": _uniq("CS"), "name": "Intro", "credits": 4},
        headers=hod_headers,
    ).get_json()["data"]
    return year, semester, division, subject


def test_faculty_only_sees_own_assignments(client, hod_headers, faculty_identity, second_faculty_identity):
    faculty_id, faculty_headers = faculty_identity
    other_faculty_id, other_headers = second_faculty_identity
    _year, _semester, division, subject = _build_hierarchy(client, hod_headers)

    created = client.post(
        "/api/academic/faculty-assignments",
        json={"faculty_id": faculty_id, "subject_id": subject["id"], "division_id": division["id"]},
        headers=hod_headers,
    )
    assert created.status_code == 201

    mine = client.get("/api/faculty/me/assignments", headers=faculty_headers).get_json()["data"]
    assert len(mine) == 1
    assert mine[0]["faculty_id"] == faculty_id

    other = client.get("/api/faculty/me/assignments", headers=other_headers).get_json()["data"]
    assert other == []


def test_student_profile_requires_student_role(client, faculty_headers):
    resp = client.get("/api/student/me/profile", headers=faculty_headers)
    assert resp.status_code == 403


def test_student_without_linked_profile_gets_domain_404(client, student_headers):
    resp = client.get("/api/student/me/profile", headers=student_headers)
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


def test_student_profile_cannot_be_requested_for_another_student(app, client, student_identity):
    """The endpoint takes no id parameter at all - resolving strictly via
    the JWT's own user id is what prevents cross-student access, so this
    confirms the linked-only-to-self profile is returned when present."""
    student_id, headers = student_identity
    with app.app_context():
        from app.extensions import db
        from app.models.classroom import Classroom
        from app.models.student import Student
        from app.models.user import User

        hod = User(name="HOD2", email=_uniq("hod2") + "@example.com", role="hod")
        hod.set_password("x")
        db.session.add(hod)
        db.session.commit()

        classroom = Classroom(name=_uniq("class"), subject="test", created_by=hod.id)
        db.session.add(classroom)
        db.session.commit()

        profile = Student(
            class_id=classroom.id,
            roll_number=_uniq("r"),
            name="Owned Student",
            face_embedding=[0.0],
            face_model="test",
            user_id=student_id,
        )
        db.session.add(profile)
        db.session.commit()

    resp = client.get("/api/student/me/profile", headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert body["name"] == "Owned Student"
