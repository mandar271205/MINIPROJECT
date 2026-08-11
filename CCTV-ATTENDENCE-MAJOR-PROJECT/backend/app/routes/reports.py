from flask import Blueprint, g, send_file

from ..models.attendance import AttendanceSession
from ..services.reporting import generate_pdf, generate_xlsx
from ..utils.security import require_roles
from .attendance import _get_session_or_error

bp = Blueprint("reports", __name__)


def _records_payload(session: AttendanceSession) -> list[dict]:
    records = []
    for record in session.records:
        records.append(
            {
                "roll_number": record.student.roll_number,
                "name": record.student.name,
                "status": record.status,
            }
        )
    return records


@bp.get("/<int:session_id>/xlsx")
@require_roles("faculty", "hod")
def download_xlsx(session_id: int):
    session, error = _get_session_or_error(session_id, g.current_user)
    if error:
        return error

    records = _records_payload(session)
    output = generate_xlsx(records)
    filename = f"attendance_session_{session.id}.xlsx"

    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.get("/<int:session_id>/pdf")
@require_roles("faculty", "hod")
def download_pdf(session_id: int):
    session, error = _get_session_or_error(session_id, g.current_user)
    if error:
        return error

    records = _records_payload(session)
    title = f"Attendance Report - Session {session.id}"
    output = generate_pdf(records, title)
    filename = f"attendance_session_{session.id}.pdf"

    return send_file(output, as_attachment=True, download_name=filename, mimetype="application/pdf")
