"""Validation and persistence logic for the Phase 2 academic hierarchy.

Route handlers stay thin: they parse the request, call a function here,
and let DomainError bubble up to the central error handler registered in
create_app (see app/__init__.py), which converts it into the
standardized {"success": false, "error": {...}} envelope. No SQL
statement or stack trace ever reaches a route response.
"""

from __future__ import annotations

from datetime import date

from ..extensions import db
from ..models.academic import (
    MAX_SEMESTER_NUMBER,
    MIN_SEMESTER_NUMBER,
    AcademicYear,
    Division,
    FacultyAssignment,
    Semester,
    Subject,
)
from ..models.user import User
from ..utils.errors import DomainError
from ..utils.roles import ROLE_FACULTY


def _require_str(payload: dict, field: str) -> str:
    value = (payload.get(field) or "").strip() if isinstance(payload.get(field), str) else payload.get(field)
    if not value:
        raise DomainError("VALIDATION_ERROR", f"{field} is required", 400)
    return value


def _parse_date(payload: dict, field: str) -> date:
    raw = payload.get(field)
    if not raw:
        raise DomainError("VALIDATION_ERROR", f"{field} is required", 400)
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        raise DomainError("VALIDATION_ERROR", f"{field} must be an ISO date (YYYY-MM-DD)", 400)


# --------------------------------------------------------------------------
# Academic Year
# --------------------------------------------------------------------------

def list_academic_years():
    return AcademicYear.query.order_by(AcademicYear.start_date.desc()).all()


def get_academic_year_or_404(year_id: int) -> AcademicYear:
    year = AcademicYear.query.get(year_id)
    if not year:
        raise DomainError("NOT_FOUND", "Academic year not found", 404)
    return year


def create_academic_year(payload: dict) -> AcademicYear:
    name = _require_str(payload, "name")
    start_date = _parse_date(payload, "start_date")
    end_date = _parse_date(payload, "end_date")
    if end_date <= start_date:
        raise DomainError("VALIDATION_ERROR", "end_date must be after start_date", 400)
    if AcademicYear.query.filter_by(name=name).first():
        raise DomainError("DUPLICATE_RESOURCE", "An academic year with this name already exists", 409)

    is_current = bool(payload.get("is_current", False))
    year = AcademicYear(
        name=name,
        start_date=start_date,
        end_date=end_date,
        is_current=is_current,
        is_active=True,
    )
    if is_current:
        AcademicYear.query.filter_by(is_current=True).update({"is_current": False})
    db.session.add(year)
    db.session.commit()
    return year


def update_academic_year(year_id: int, payload: dict) -> AcademicYear:
    year = get_academic_year_or_404(year_id)

    name = year.name
    if "name" in payload:
        name = _require_str(payload, "name")
        existing = AcademicYear.query.filter(AcademicYear.name == name, AcademicYear.id != year.id).first()
        if existing:
            raise DomainError("DUPLICATE_RESOURCE", "An academic year with this name already exists", 409)

    start_date = date.fromisoformat(payload["start_date"]) if payload.get("start_date") else year.start_date
    end_date = date.fromisoformat(payload["end_date"]) if payload.get("end_date") else year.end_date
    if end_date <= start_date:
        raise DomainError("VALIDATION_ERROR", "end_date must be after start_date", 400)

    year.name = name
    year.start_date = start_date
    year.end_date = end_date

    if "is_active" in payload:
        year.is_active = bool(payload["is_active"])

    if "is_current" in payload:
        if payload["is_current"]:
            AcademicYear.query.filter(AcademicYear.id != year.id).update({"is_current": False})
            year.is_current = True
        else:
            year.is_current = False

    db.session.commit()
    return year


def deactivate_or_delete_academic_year(year_id: int) -> tuple[AcademicYear | None, bool]:
    """Returns (year_or_none, was_soft_deactivated)."""
    year = get_academic_year_or_404(year_id)
    has_dependants = Semester.query.filter_by(academic_year_id=year.id).first() is not None
    if has_dependants:
        year.is_active = False
        year.is_current = False
        db.session.commit()
        return year, True
    db.session.delete(year)
    db.session.commit()
    return None, False


# --------------------------------------------------------------------------
# Semester
# --------------------------------------------------------------------------

def list_semesters(academic_year_id: int | None = None):
    query = Semester.query
    if academic_year_id is not None:
        query = query.filter_by(academic_year_id=academic_year_id)
    return query.order_by(Semester.academic_year_id, Semester.number).all()


def get_semester_or_404(semester_id: int) -> Semester:
    semester = Semester.query.get(semester_id)
    if not semester:
        raise DomainError("NOT_FOUND", "Semester not found", 404)
    return semester


def create_semester(payload: dict) -> Semester:
    academic_year_id = payload.get("academic_year_id")
    if not academic_year_id:
        raise DomainError("VALIDATION_ERROR", "academic_year_id is required", 400)
    year = AcademicYear.query.get(academic_year_id)
    if not year:
        raise DomainError("ACADEMIC_RELATIONSHIP_INVALID", "academic_year_id does not reference an existing academic year", 400)
    if not year.is_active:
        raise DomainError("ACADEMIC_RELATIONSHIP_INVALID", "Cannot add a semester to an inactive academic year", 400)

    try:
        number = int(payload.get("number"))
    except (TypeError, ValueError):
        raise DomainError("VALIDATION_ERROR", "number is required and must be an integer", 400)
    if not (MIN_SEMESTER_NUMBER <= number <= MAX_SEMESTER_NUMBER):
        raise DomainError(
            "VALIDATION_ERROR",
            f"number must be between {MIN_SEMESTER_NUMBER} and {MAX_SEMESTER_NUMBER}",
            400,
        )

    name = _require_str(payload, "name")

    if Semester.query.filter_by(academic_year_id=academic_year_id, number=number).first():
        raise DomainError("DUPLICATE_RESOURCE", "This semester number already exists for the academic year", 409)

    semester = Semester(academic_year_id=academic_year_id, number=number, name=name, is_active=True)
    db.session.add(semester)
    db.session.commit()
    return semester


def update_semester(semester_id: int, payload: dict) -> Semester:
    semester = get_semester_or_404(semester_id)

    number = semester.number
    if "number" in payload:
        try:
            number = int(payload["number"])
        except (TypeError, ValueError):
            raise DomainError("VALIDATION_ERROR", "number must be an integer", 400)
        if not (MIN_SEMESTER_NUMBER <= number <= MAX_SEMESTER_NUMBER):
            raise DomainError(
                "VALIDATION_ERROR",
                f"number must be between {MIN_SEMESTER_NUMBER} and {MAX_SEMESTER_NUMBER}",
                400,
            )
        clash = Semester.query.filter(
            Semester.academic_year_id == semester.academic_year_id,
            Semester.number == number,
            Semester.id != semester.id,
        ).first()
        if clash:
            raise DomainError("DUPLICATE_RESOURCE", "This semester number already exists for the academic year", 409)

    if "name" in payload:
        semester.name = _require_str(payload, "name")
    if "is_active" in payload:
        semester.is_active = bool(payload["is_active"])

    semester.number = number
    db.session.commit()
    return semester


def deactivate_or_delete_semester(semester_id: int) -> tuple[Semester | None, bool]:
    semester = get_semester_or_404(semester_id)
    has_dependants = (
        Division.query.filter_by(semester_id=semester.id).first() is not None
        or Subject.query.filter_by(semester_id=semester.id).first() is not None
    )
    if has_dependants:
        semester.is_active = False
        db.session.commit()
        return semester, True
    db.session.delete(semester)
    db.session.commit()
    return None, False


# --------------------------------------------------------------------------
# Division
# --------------------------------------------------------------------------

def list_divisions(semester_id: int | None = None, program: str | None = None):
    query = Division.query
    if semester_id is not None:
        query = query.filter_by(semester_id=semester_id)
    if program:
        query = query.filter_by(program=program)
    return query.order_by(Division.semester_id, Division.program, Division.name).all()


def list_divisions_for_faculty(faculty_id: int, semester_id: int | None = None, program: str | None = None):
    """Only the divisions a faculty member holds an active assignment
    for - never the full table, so a faculty account cannot enumerate
    divisions it has no relationship to."""
    division_ids = {
        a.division_id
        for a in FacultyAssignment.query.filter_by(faculty_id=faculty_id, is_active=True).all()
    }
    if not division_ids:
        return []
    query = Division.query.filter(Division.id.in_(division_ids))
    if semester_id is not None:
        query = query.filter_by(semester_id=semester_id)
    if program:
        query = query.filter_by(program=program)
    return query.order_by(Division.semester_id, Division.program, Division.name).all()


def get_division_or_404(division_id: int) -> Division:
    division = Division.query.get(division_id)
    if not division:
        raise DomainError("NOT_FOUND", "Division not found", 404)
    return division


def create_division(payload: dict) -> Division:
    semester_id = payload.get("semester_id")
    if not semester_id:
        raise DomainError("VALIDATION_ERROR", "semester_id is required", 400)
    semester = Semester.query.get(semester_id)
    if not semester:
        raise DomainError("ACADEMIC_RELATIONSHIP_INVALID", "semester_id does not reference an existing semester", 400)
    if not semester.is_active:
        raise DomainError("ACADEMIC_RELATIONSHIP_INVALID", "Cannot add a division to an inactive semester", 400)

    name = _require_str(payload, "name")
    program = _require_str(payload, "program")
    try:
        batch_year = int(payload.get("batch_year"))
    except (TypeError, ValueError):
        raise DomainError("VALIDATION_ERROR", "batch_year is required and must be an integer", 400)

    if Division.query.filter_by(semester_id=semester_id, program=program, name=name).first():
        raise DomainError("DUPLICATE_RESOURCE", "A division with this name already exists for the program/semester", 409)

    division = Division(
        semester_id=semester_id, name=name, program=program, batch_year=batch_year, is_active=True
    )
    db.session.add(division)
    db.session.commit()
    return division


def update_division(division_id: int, payload: dict) -> Division:
    division = get_division_or_404(division_id)

    name = payload.get("name", division.name)
    program = payload.get("program", division.program)
    if "name" in payload or "program" in payload:
        clash = Division.query.filter(
            Division.semester_id == division.semester_id,
            Division.program == program,
            Division.name == name,
            Division.id != division.id,
        ).first()
        if clash:
            raise DomainError("DUPLICATE_RESOURCE", "A division with this name already exists for the program/semester", 409)

    division.name = name
    division.program = program
    if "batch_year" in payload:
        try:
            division.batch_year = int(payload["batch_year"])
        except (TypeError, ValueError):
            raise DomainError("VALIDATION_ERROR", "batch_year must be an integer", 400)
    if "is_active" in payload:
        division.is_active = bool(payload["is_active"])

    db.session.commit()
    return division


def deactivate_or_delete_division(division_id: int) -> tuple[Division | None, bool]:
    division = get_division_or_404(division_id)
    has_dependants = (
        len(division.students) > 0
        or FacultyAssignment.query.filter_by(division_id=division.id).first() is not None
    )
    if has_dependants:
        division.is_active = False
        db.session.commit()
        return division, True
    db.session.delete(division)
    db.session.commit()
    return None, False


# --------------------------------------------------------------------------
# Subject
# --------------------------------------------------------------------------

def list_subjects(semester_id: int | None = None):
    query = Subject.query
    if semester_id is not None:
        query = query.filter_by(semester_id=semester_id)
    return query.order_by(Subject.semester_id, Subject.code).all()


def list_subjects_for_faculty(faculty_id: int, semester_id: int | None = None):
    """Only the subjects a faculty member holds an active assignment
    for - never the full table."""
    subject_ids = {
        a.subject_id
        for a in FacultyAssignment.query.filter_by(faculty_id=faculty_id, is_active=True).all()
    }
    if not subject_ids:
        return []
    query = Subject.query.filter(Subject.id.in_(subject_ids))
    if semester_id is not None:
        query = query.filter_by(semester_id=semester_id)
    return query.order_by(Subject.semester_id, Subject.code).all()


def get_subject_or_404(subject_id: int) -> Subject:
    subject = Subject.query.get(subject_id)
    if not subject:
        raise DomainError("NOT_FOUND", "Subject not found", 404)
    return subject


def create_subject(payload: dict) -> Subject:
    semester_id = payload.get("semester_id")
    if not semester_id:
        raise DomainError("VALIDATION_ERROR", "semester_id is required", 400)
    semester = Semester.query.get(semester_id)
    if not semester:
        raise DomainError("ACADEMIC_RELATIONSHIP_INVALID", "semester_id does not reference an existing semester", 400)
    if not semester.is_active:
        raise DomainError("ACADEMIC_RELATIONSHIP_INVALID", "Cannot add a subject to an inactive semester", 400)

    code = _require_str(payload, "code")
    name = _require_str(payload, "name")
    try:
        credits = int(payload.get("credits", 0))
    except (TypeError, ValueError):
        raise DomainError("VALIDATION_ERROR", "credits must be an integer", 400)

    if Subject.query.filter_by(semester_id=semester_id, code=code).first():
        raise DomainError("DUPLICATE_RESOURCE", "A subject with this code already exists for the semester", 409)

    subject = Subject(semester_id=semester_id, code=code, name=name, credits=credits, is_active=True)
    db.session.add(subject)
    db.session.commit()
    return subject


def update_subject(subject_id: int, payload: dict) -> Subject:
    subject = get_subject_or_404(subject_id)

    code = payload.get("code", subject.code)
    if "code" in payload:
        clash = Subject.query.filter(
            Subject.semester_id == subject.semester_id,
            Subject.code == code,
            Subject.id != subject.id,
        ).first()
        if clash:
            raise DomainError("DUPLICATE_RESOURCE", "A subject with this code already exists for the semester", 409)

    subject.code = code
    if "name" in payload:
        subject.name = _require_str(payload, "name")
    if "credits" in payload:
        try:
            subject.credits = int(payload["credits"])
        except (TypeError, ValueError):
            raise DomainError("VALIDATION_ERROR", "credits must be an integer", 400)
    if "is_active" in payload:
        subject.is_active = bool(payload["is_active"])

    db.session.commit()
    return subject


def deactivate_or_delete_subject(subject_id: int) -> tuple[Subject | None, bool]:
    subject = get_subject_or_404(subject_id)
    has_dependants = FacultyAssignment.query.filter_by(subject_id=subject.id).first() is not None
    if has_dependants:
        subject.is_active = False
        db.session.commit()
        return subject, True
    db.session.delete(subject)
    db.session.commit()
    return None, False


# --------------------------------------------------------------------------
# Faculty Assignment
# --------------------------------------------------------------------------

def list_faculty_assignments(faculty_id: int | None = None, division_id: int | None = None):
    query = FacultyAssignment.query
    if faculty_id is not None:
        query = query.filter_by(faculty_id=faculty_id)
    if division_id is not None:
        query = query.filter_by(division_id=division_id)
    return query.order_by(FacultyAssignment.id).all()


def get_faculty_assignment_or_404(assignment_id: int) -> FacultyAssignment:
    assignment = FacultyAssignment.query.get(assignment_id)
    if not assignment:
        raise DomainError("NOT_FOUND", "Faculty assignment not found", 404)
    return assignment


def create_faculty_assignment(payload: dict) -> FacultyAssignment:
    faculty_id = payload.get("faculty_id")
    subject_id = payload.get("subject_id")
    division_id = payload.get("division_id")
    if not faculty_id or not subject_id or not division_id:
        raise DomainError("VALIDATION_ERROR", "faculty_id, subject_id and division_id are required", 400)

    faculty = User.query.get(faculty_id)
    if not faculty:
        raise DomainError("ACADEMIC_RELATIONSHIP_INVALID", "faculty_id does not reference an existing user", 400)
    if faculty.role != ROLE_FACULTY:
        raise DomainError("ACADEMIC_RELATIONSHIP_INVALID", "Only a user with the faculty role can be assigned", 400)

    subject = Subject.query.get(subject_id)
    if not subject:
        raise DomainError("ACADEMIC_RELATIONSHIP_INVALID", "subject_id does not reference an existing subject", 400)
    if not subject.is_active:
        raise DomainError("ACADEMIC_RELATIONSHIP_INVALID", "Cannot assign an inactive subject", 400)

    division = Division.query.get(division_id)
    if not division:
        raise DomainError("ACADEMIC_RELATIONSHIP_INVALID", "division_id does not reference an existing division", 400)
    if not division.is_active:
        raise DomainError("ACADEMIC_RELATIONSHIP_INVALID", "Cannot assign an inactive division", 400)

    if subject.semester_id != division.semester_id:
        raise DomainError(
            "ACADEMIC_RELATIONSHIP_INVALID",
            "Subject and division must belong to the same semester",
            400,
        )

    if FacultyAssignment.query.filter_by(
        faculty_id=faculty_id, subject_id=subject_id, division_id=division_id
    ).first():
        raise DomainError("DUPLICATE_RESOURCE", "This faculty assignment already exists", 409)

    assignment = FacultyAssignment(
        faculty_id=faculty_id, subject_id=subject_id, division_id=division_id, is_active=True
    )
    db.session.add(assignment)
    db.session.commit()
    return assignment


def update_faculty_assignment(assignment_id: int, payload: dict) -> FacultyAssignment:
    assignment = get_faculty_assignment_or_404(assignment_id)
    if "is_active" in payload:
        assignment.is_active = bool(payload["is_active"])
    db.session.commit()
    return assignment


def deactivate_or_delete_faculty_assignment(assignment_id: int) -> tuple[FacultyAssignment | None, bool]:
    assignment = get_faculty_assignment_or_404(assignment_id)
    # Faculty assignments have no dependants of their own; always safe to
    # hard-delete, but soft-deactivate is preferred so assignment history
    # (and any future attendance linkage) is not silently lost.
    assignment.is_active = False
    db.session.commit()
    return assignment, True
