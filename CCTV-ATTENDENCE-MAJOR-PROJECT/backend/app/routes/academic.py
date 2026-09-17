from flask import Blueprint, g, request

from ..services import academic_service as svc
from ..utils.errors import DomainError
from ..utils.responses import success
from ..utils.security import faculty_has_assignment, require_hod, require_hod_or_faculty

bp = Blueprint("academic", __name__)


# --------------------------------------------------------------------------
# Academic Years
# --------------------------------------------------------------------------

@bp.get("/years")
@require_hod_or_faculty
def list_years():
    years = svc.list_academic_years()
    return success([y.to_dict() for y in years])


@bp.post("/years")
@require_hod
def create_year():
    payload = request.get_json(silent=True) or {}
    year = svc.create_academic_year(payload)
    return success(year.to_dict(), "Academic year created", 201)


@bp.get("/years/<int:year_id>")
@require_hod_or_faculty
def get_year(year_id: int):
    year = svc.get_academic_year_or_404(year_id)
    return success(year.to_dict())


@bp.put("/years/<int:year_id>")
@require_hod
def update_year(year_id: int):
    payload = request.get_json(silent=True) or {}
    year = svc.update_academic_year(year_id, payload)
    return success(year.to_dict(), "Academic year updated")


@bp.delete("/years/<int:year_id>")
@require_hod
def delete_year(year_id: int):
    year, deactivated = svc.deactivate_or_delete_academic_year(year_id)
    if deactivated:
        return success(year.to_dict(), "Academic year has dependants; deactivated instead of deleted")
    return success(None, "Academic year deleted")


# --------------------------------------------------------------------------
# Semesters
# --------------------------------------------------------------------------

@bp.get("/semesters")
@require_hod_or_faculty
def list_semesters():
    academic_year_id = request.args.get("academic_year_id", type=int)
    semesters = svc.list_semesters(academic_year_id=academic_year_id)
    return success([s.to_dict() for s in semesters])


@bp.post("/semesters")
@require_hod
def create_semester():
    payload = request.get_json(silent=True) or {}
    semester = svc.create_semester(payload)
    return success(semester.to_dict(), "Semester created", 201)


@bp.get("/semesters/<int:semester_id>")
@require_hod_or_faculty
def get_semester(semester_id: int):
    semester = svc.get_semester_or_404(semester_id)
    return success(semester.to_dict())


@bp.put("/semesters/<int:semester_id>")
@require_hod
def update_semester(semester_id: int):
    payload = request.get_json(silent=True) or {}
    semester = svc.update_semester(semester_id, payload)
    return success(semester.to_dict(), "Semester updated")


@bp.delete("/semesters/<int:semester_id>")
@require_hod
def delete_semester(semester_id: int):
    semester, deactivated = svc.deactivate_or_delete_semester(semester_id)
    if deactivated:
        return success(semester.to_dict(), "Semester has dependants; deactivated instead of deleted")
    return success(None, "Semester deleted")


# --------------------------------------------------------------------------
# Divisions
# --------------------------------------------------------------------------

@bp.get("/divisions")
@require_hod_or_faculty
def list_divisions():
    semester_id = request.args.get("semester_id", type=int)
    program = request.args.get("program")
    if g.current_user.role == "hod":
        divisions = svc.list_divisions(semester_id=semester_id, program=program)
    else:
        # Faculty only ever see divisions they hold an active assignment
        # for - never the full division table.
        divisions = svc.list_divisions_for_faculty(
            g.current_user.id, semester_id=semester_id, program=program
        )
    return success([d.to_dict() for d in divisions])


@bp.post("/divisions")
@require_hod
def create_division():
    payload = request.get_json(silent=True) or {}
    division = svc.create_division(payload)
    return success(division.to_dict(), "Division created", 201)


@bp.get("/divisions/<int:division_id>")
@require_hod_or_faculty
def get_division(division_id: int):
    division = svc.get_division_or_404(division_id)
    if g.current_user.role != "hod" and not faculty_has_assignment(
        g.current_user.id, division_id=division.id
    ):
        # Non-disclosing 404: a faculty member manually incrementing an
        # id cannot tell "doesn't exist" apart from "not mine".
        raise DomainError("NOT_FOUND", "Division not found", 404)
    return success(division.to_dict())


@bp.put("/divisions/<int:division_id>")
@require_hod
def update_division(division_id: int):
    payload = request.get_json(silent=True) or {}
    division = svc.update_division(division_id, payload)
    return success(division.to_dict(), "Division updated")


@bp.delete("/divisions/<int:division_id>")
@require_hod
def delete_division(division_id: int):
    division, deactivated = svc.deactivate_or_delete_division(division_id)
    if deactivated:
        return success(division.to_dict(), "Division has dependants; deactivated instead of deleted")
    return success(None, "Division deleted")


# --------------------------------------------------------------------------
# Subjects
# --------------------------------------------------------------------------

@bp.get("/subjects")
@require_hod_or_faculty
def list_subjects():
    semester_id = request.args.get("semester_id", type=int)
    if g.current_user.role == "hod":
        subjects = svc.list_subjects(semester_id=semester_id)
    else:
        # Faculty only ever see subjects they hold an active assignment
        # for - never the full subject table.
        subjects = svc.list_subjects_for_faculty(g.current_user.id, semester_id=semester_id)
    return success([s.to_dict() for s in subjects])


@bp.post("/subjects")
@require_hod
def create_subject():
    payload = request.get_json(silent=True) or {}
    subject = svc.create_subject(payload)
    return success(subject.to_dict(), "Subject created", 201)


@bp.get("/subjects/<int:subject_id>")
@require_hod_or_faculty
def get_subject(subject_id: int):
    subject = svc.get_subject_or_404(subject_id)
    if g.current_user.role != "hod" and not faculty_has_assignment(
        g.current_user.id, subject_id=subject.id
    ):
        # Non-disclosing 404 - see get_division() above for why.
        raise DomainError("NOT_FOUND", "Subject not found", 404)
    return success(subject.to_dict())


@bp.put("/subjects/<int:subject_id>")
@require_hod
def update_subject(subject_id: int):
    payload = request.get_json(silent=True) or {}
    subject = svc.update_subject(subject_id, payload)
    return success(subject.to_dict(), "Subject updated")


@bp.delete("/subjects/<int:subject_id>")
@require_hod
def delete_subject(subject_id: int):
    subject, deactivated = svc.deactivate_or_delete_subject(subject_id)
    if deactivated:
        return success(subject.to_dict(), "Subject has dependants; deactivated instead of deleted")
    return success(None, "Subject deleted")


# --------------------------------------------------------------------------
# Faculty Assignments
# --------------------------------------------------------------------------

@bp.get("/faculty-assignments")
@require_hod_or_faculty
def list_faculty_assignments():
    faculty_id = request.args.get("faculty_id", type=int)
    division_id = request.args.get("division_id", type=int)
    # A faculty user may only ever list their own assignments through
    # this endpoint; only HOD may query arbitrary faculty_id values.
    if g.current_user.role != "hod":
        faculty_id = g.current_user.id
    assignments = svc.list_faculty_assignments(faculty_id=faculty_id, division_id=division_id)
    return success([a.to_dict() for a in assignments])


@bp.post("/faculty-assignments")
@require_hod
def create_faculty_assignment():
    payload = request.get_json(silent=True) or {}
    assignment = svc.create_faculty_assignment(payload)
    return success(assignment.to_dict(), "Faculty assignment created", 201)


@bp.put("/faculty-assignments/<int:assignment_id>")
@require_hod
def update_faculty_assignment(assignment_id: int):
    payload = request.get_json(silent=True) or {}
    assignment = svc.update_faculty_assignment(assignment_id, payload)
    return success(assignment.to_dict(), "Faculty assignment updated")


@bp.delete("/faculty-assignments/<int:assignment_id>")
@require_hod
def delete_faculty_assignment(assignment_id: int):
    assignment, _ = svc.deactivate_or_delete_faculty_assignment(assignment_id)
    return success(assignment.to_dict(), "Faculty assignment deactivated")
