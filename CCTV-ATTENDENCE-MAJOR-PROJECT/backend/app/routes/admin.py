from flask import Blueprint, request

from ..services import account_service as svc
from ..utils.errors import DomainError
from ..utils.responses import success
from ..utils.security import require_hod

bp = Blueprint("admin", __name__)


def _require_is_active_field(payload: dict) -> bool:
    if "is_active" not in payload:
        raise DomainError("VALIDATION_ERROR", "is_active is required", 400)
    return bool(payload["is_active"])


# --------------------------------------------------------------------------
# Faculty account management (HOD-only)
# --------------------------------------------------------------------------

@bp.get("/faculty")
@require_hod
def list_faculty():
    users = svc.list_faculty_accounts()
    return success([u.to_dict() for u in users])


@bp.post("/faculty")
@require_hod
def create_faculty():
    payload = request.get_json(silent=True) or {}
    user = svc.create_faculty_account(payload)
    return success(user.to_dict(), "Faculty account created", 201)


@bp.put("/faculty/<int:user_id>")
@require_hod
def update_faculty(user_id: int):
    payload = request.get_json(silent=True) or {}
    user = svc.update_faculty_account(user_id, payload)
    return success(user.to_dict(), "Faculty account updated")


@bp.put("/faculty/<int:user_id>/status")
@require_hod
def update_faculty_status(user_id: int):
    payload = request.get_json(silent=True) or {}
    is_active = _require_is_active_field(payload)
    user = svc.set_faculty_account_status(user_id, is_active)
    return success(user.to_dict(), "Faculty account status updated")


# --------------------------------------------------------------------------
# Student account linking (HOD-only)
# --------------------------------------------------------------------------

@bp.post("/students/<int:student_id>/account")
@require_hod
def link_student_account(student_id: int):
    payload = request.get_json(silent=True) or {}
    student = svc.link_student_account(student_id, payload)
    return success(student.to_profile_dict(), "Student account linked", 201)


@bp.put("/students/<int:student_id>/account")
@require_hod
def relink_student_account(student_id: int):
    payload = request.get_json(silent=True) or {}
    student = svc.relink_student_account(student_id, payload)
    return success(student.to_profile_dict(), "Student account relinked")


@bp.put("/students/<int:student_id>/account/status")
@require_hod
def update_student_account_status(student_id: int):
    payload = request.get_json(silent=True) or {}
    is_active = _require_is_active_field(payload)
    student, linked_user = svc.set_student_account_status(student_id, is_active)
    return success(
        {"student": student.to_profile_dict(), "user": linked_user.to_dict()},
        "Student account status updated",
    )
