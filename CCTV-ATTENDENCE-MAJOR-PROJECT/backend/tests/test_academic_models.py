import uuid

import pytest

from app.extensions import db
from app.models.user import User
from app.services import academic_service as svc
from app.utils.errors import DomainError


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def test_academic_year_requires_end_after_start(app):
    with app.app_context():
        with pytest.raises(DomainError) as excinfo:
            svc.create_academic_year(
                {"name": _uniq("AY"), "start_date": "2026-08-01", "end_date": "2026-01-01"}
            )
        assert excinfo.value.code == "VALIDATION_ERROR"


def test_academic_year_name_must_be_unique(app):
    with app.app_context():
        name = _uniq("AY")
        svc.create_academic_year({"name": name, "start_date": "2026-01-01", "end_date": "2026-12-31"})
        with pytest.raises(DomainError) as excinfo:
            svc.create_academic_year({"name": name, "start_date": "2027-01-01", "end_date": "2027-12-31"})
        assert excinfo.value.code == "DUPLICATE_RESOURCE"


def test_only_one_academic_year_can_be_current(app):
    with app.app_context():
        first = svc.create_academic_year(
            {"name": _uniq("AY"), "start_date": "2026-01-01", "end_date": "2026-12-31", "is_current": True}
        )
        second = svc.create_academic_year(
            {"name": _uniq("AY"), "start_date": "2027-01-01", "end_date": "2027-12-31", "is_current": True}
        )
        db.session.refresh(first)
        assert first.is_current is False
        assert second.is_current is True


def _create_year(app):
    return svc.create_academic_year(
        {"name": _uniq("AY"), "start_date": "2026-01-01", "end_date": "2026-12-31"}
    )


def test_semester_unique_per_year_number(app):
    with app.app_context():
        year = _create_year(app)
        svc.create_semester({"academic_year_id": year.id, "number": 1, "name": "Sem 1"})
        with pytest.raises(DomainError) as excinfo:
            svc.create_semester({"academic_year_id": year.id, "number": 1, "name": "Sem 1 dup"})
        assert excinfo.value.code == "DUPLICATE_RESOURCE"


def test_semester_number_out_of_range_rejected(app):
    with app.app_context():
        year = _create_year(app)
        with pytest.raises(DomainError) as excinfo:
            svc.create_semester({"academic_year_id": year.id, "number": 9, "name": "Bad"})
        assert excinfo.value.code == "VALIDATION_ERROR"


def _create_semester(app):
    year = _create_year(app)
    return svc.create_semester({"academic_year_id": year.id, "number": 1, "name": "Sem 1"})


def test_division_unique_per_semester_program_name(app):
    with app.app_context():
        semester = _create_semester(app)
        svc.create_division(
            {"semester_id": semester.id, "name": "A", "program": "CSE", "batch_year": 2026}
        )
        with pytest.raises(DomainError) as excinfo:
            svc.create_division(
                {"semester_id": semester.id, "name": "A", "program": "CSE", "batch_year": 2026}
            )
        assert excinfo.value.code == "DUPLICATE_RESOURCE"


def test_subject_code_unique_per_semester(app):
    with app.app_context():
        semester = _create_semester(app)
        svc.create_subject({"semester_id": semester.id, "code": "CS101", "name": "Intro", "credits": 4})
        with pytest.raises(DomainError) as excinfo:
            svc.create_subject({"semester_id": semester.id, "code": "CS101", "name": "Intro dup", "credits": 4})
        assert excinfo.value.code == "DUPLICATE_RESOURCE"


def test_faculty_assignment_unique(app):
    with app.app_context():
        semester = _create_semester(app)
        division = svc.create_division(
            {"semester_id": semester.id, "name": "A", "program": "CSE", "batch_year": 2026}
        )
        subject = svc.create_subject({"semester_id": semester.id, "code": "CS101", "name": "Intro", "credits": 4})
        faculty = User(name="F", email=_uniq("f") + "@example.com", role="faculty")
        faculty.set_password("x")
        db.session.add(faculty)
        db.session.commit()

        svc.create_faculty_assignment(
            {"faculty_id": faculty.id, "subject_id": subject.id, "division_id": division.id}
        )
        with pytest.raises(DomainError) as excinfo:
            svc.create_faculty_assignment(
                {"faculty_id": faculty.id, "subject_id": subject.id, "division_id": division.id}
            )
        assert excinfo.value.code == "DUPLICATE_RESOURCE"


def test_faculty_assignment_rejects_non_faculty_user(app):
    with app.app_context():
        semester = _create_semester(app)
        division = svc.create_division(
            {"semester_id": semester.id, "name": "A", "program": "CSE", "batch_year": 2026}
        )
        subject = svc.create_subject({"semester_id": semester.id, "code": "CS101", "name": "Intro", "credits": 4})
        non_faculty = User(name="H", email=_uniq("h") + "@example.com", role="hod")
        non_faculty.set_password("x")
        db.session.add(non_faculty)
        db.session.commit()

        with pytest.raises(DomainError) as excinfo:
            svc.create_faculty_assignment(
                {"faculty_id": non_faculty.id, "subject_id": subject.id, "division_id": division.id}
            )
        assert excinfo.value.code == "ACADEMIC_RELATIONSHIP_INVALID"


def test_faculty_assignment_rejects_incompatible_subject_and_division(app):
    with app.app_context():
        year = _create_year(app)
        semester_a = svc.create_semester({"academic_year_id": year.id, "number": 1, "name": "Sem 1"})
        semester_b = svc.create_semester({"academic_year_id": year.id, "number": 2, "name": "Sem 2"})
        division = svc.create_division(
            {"semester_id": semester_a.id, "name": "A", "program": "CSE", "batch_year": 2026}
        )
        subject = svc.create_subject({"semester_id": semester_b.id, "code": "CS201", "name": "Other", "credits": 4})
        faculty = User(name="F2", email=_uniq("f2") + "@example.com", role="faculty")
        faculty.set_password("x")
        db.session.add(faculty)
        db.session.commit()

        with pytest.raises(DomainError) as excinfo:
            svc.create_faculty_assignment(
                {"faculty_id": faculty.id, "subject_id": subject.id, "division_id": division.id}
            )
        assert excinfo.value.code == "ACADEMIC_RELATIONSHIP_INVALID"


def test_student_user_id_must_be_unique(app):
    with app.app_context():
        from app.models.classroom import Classroom
        from app.models.student import Student

        hod = User.query.filter_by(role="hod").first() or User(
            name="HOD", email=_uniq("hod") + "@example.com", role="hod"
        )
        if not hod.id:
            hod.set_password("x")
            db.session.add(hod)
            db.session.commit()

        classroom = Classroom(name=_uniq("class"), subject="test", created_by=hod.id)
        db.session.add(classroom)
        db.session.commit()

        student_user = User(name="S", email=_uniq("s") + "@example.com", role="student")
        student_user.set_password("x")
        db.session.add(student_user)
        db.session.commit()

        s1 = Student(
            class_id=classroom.id,
            roll_number=_uniq("r"),
            name="Student One",
            face_embedding=[0.0],
            face_model="test",
            user_id=student_user.id,
        )
        db.session.add(s1)
        db.session.commit()

        s2 = Student(
            class_id=classroom.id,
            roll_number=_uniq("r"),
            name="Student Two",
            face_embedding=[0.0],
            face_model="test",
            user_id=student_user.id,
        )
        db.session.add(s2)
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()
