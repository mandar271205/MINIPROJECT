from flask import Blueprint, g

from ..services import academic_service as svc
from ..utils.responses import success
from ..utils.security import require_faculty

bp = Blueprint("faculty", __name__)


@bp.get("/me/assignments")
@require_faculty
def my_assignments():
    assignments = svc.list_faculty_assignments(faculty_id=g.current_user.id)
    payload = []
    for assignment in assignments:
        item = assignment.to_dict()
        item["subject"] = assignment.subject.to_dict()
        item["division"] = assignment.division.to_dict()
        payload.append(item)
    return success(payload)
