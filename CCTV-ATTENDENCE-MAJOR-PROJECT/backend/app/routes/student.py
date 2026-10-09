from flask import Blueprint, g

from ..models.student import Student
from ..utils.errors import DomainError
from ..utils.responses import success
from ..utils.security import require_student

bp = Blueprint("student", __name__)


@bp.get("/me/profile")
@require_student
def my_profile():
    # Resolved strictly through students.user_id == the authenticated
    # user's id. There is no way to request another student's profile
    # through this endpoint — no student id is ever accepted as input.
    profile = Student.query.filter_by(user_id=g.current_user.id).first()
    if not profile:
        raise DomainError("NOT_FOUND", "No student profile is linked to this account", 404)
    return success(profile.to_profile_dict())


@bp.get("/me/risk-profile")
@require_student
def my_risk_profile():
    profile = Student.query.filter_by(user_id=g.current_user.id).first()
    if not profile:
        raise DomainError("NOT_FOUND", "No student profile is linked to this account", 404)

    from ..services.risk_scoring_service import calculate_student_risk_profile

    data = calculate_student_risk_profile(profile.id)
    return success(data)

