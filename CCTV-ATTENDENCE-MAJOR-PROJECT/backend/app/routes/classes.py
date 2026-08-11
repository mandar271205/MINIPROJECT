from uuid import uuid4

from flask import Blueprint, current_app, g, jsonify, request

from ..extensions import db
from ..models.classroom import Classroom
from ..models.student import Student
from ..services.enrollment_service import enroll_students_from_zip
from ..utils.files import save_upload
from ..utils.security import require_roles

bp = Blueprint("classes", __name__)


def _get_classroom(class_id: int, user):
    classroom = Classroom.query.get(class_id)
    if not classroom:
        return None, (jsonify({"error": "Class not found"}), 404)
    if user.role != "hod" and classroom.created_by != user.id:
        return None, (jsonify({"error": "Forbidden"}), 403)
    return classroom, None


@bp.get("/")
@require_roles("faculty", "hod")
def list_classes():
    user = g.current_user
    query = Classroom.query

    if not (user.role == "hod" and current_app.config.get("HOD_SEES_ALL")):
        query = query.filter_by(created_by=user.id)

    classes = query.order_by(Classroom.created_at.desc()).all()
    payload = []
    for classroom in classes:
        payload.append(
            {
                "id": classroom.id,
                "name": classroom.name,
                "subject": classroom.subject,
                "grace_period_minutes": classroom.grace_period_minutes,
                "student_count": len(classroom.students),
            }
        )

    return jsonify({"classes": payload})


@bp.post("/")
@require_roles("faculty", "hod")
def create_class():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    subject = (payload.get("subject") or "").strip()
    grace = payload.get("grace_period_minutes", 10)
    try:
        grace_value = int(grace)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid grace period"}), 400

    if not name or not subject:
        return jsonify({"error": "Name and subject are required"}), 400

    classroom = Classroom(
        name=name,
        subject=subject,
        grace_period_minutes=grace_value,
        created_by=g.current_user.id,
    )
    db.session.add(classroom)
    db.session.commit()

    return jsonify({"class": classroom.to_dict()}), 201


@bp.get("/<int:class_id>")
@require_roles("faculty", "hod")
def get_class(class_id: int):
    classroom, error = _get_classroom(class_id, g.current_user)
    if error:
        return error
    return jsonify({"class": classroom.to_dict()})


@bp.put("/<int:class_id>")
@require_roles("faculty", "hod")
def update_class(class_id: int):
    classroom, error = _get_classroom(class_id, g.current_user)
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    grace = payload.get("grace_period_minutes")
    if grace is None:
        return jsonify({"error": "grace_period_minutes is required"}), 400

    try:
        grace_value = int(grace)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid grace period"}), 400

    classroom.grace_period_minutes = grace_value
    db.session.commit()
    return jsonify({"class": classroom.to_dict()})


@bp.delete("/<int:class_id>")
@require_roles("faculty", "hod")
def delete_class(class_id: int):
    classroom, error = _get_classroom(class_id, g.current_user)
    if error:
        return error

    db.session.delete(classroom)
    db.session.commit()
    return jsonify({"message": "Class deleted"})


@bp.get("/<int:class_id>/students")
@require_roles("faculty", "hod")
def list_students(class_id: int):
    classroom, error = _get_classroom(class_id, g.current_user)
    if error:
        return error

    students = [student.to_dict() for student in classroom.students]
    return jsonify({"students": students})


@bp.post("/<int:class_id>/enroll-zip")
@require_roles("faculty", "hod")
def enroll_zip(class_id: int):
    classroom, error = _get_classroom(class_id, g.current_user)
    if error:
        return error

    if "file" not in request.files:
        return jsonify({"error": "Missing ZIP file"}), 400

    zip_file = request.files["file"]
    if not zip_file.filename or not zip_file.filename.lower().endswith(".zip"):
        return jsonify({"error": "Invalid ZIP file"}), 400

    temp_dir = current_app.config["TEMP_DIR"]
    zip_path = save_upload(zip_file, temp_dir, prefix=f"class_{class_id}_{uuid4().hex}")
    try:
        results = enroll_students_from_zip(classroom, zip_path)
    except Exception as exc:
        zip_path.unlink(missing_ok=True)
        return jsonify({"error": str(exc)}), 400

    zip_path.unlink(missing_ok=True)

    return jsonify({"results": results})


@bp.delete("/<int:class_id>/students/<int:student_id>")
@require_roles("faculty", "hod")
def delete_student(class_id: int, student_id: int):
    classroom, error = _get_classroom(class_id, g.current_user)
    if error:
        return error

    student = Student.query.filter_by(id=student_id, class_id=classroom.id).first()
    if not student:
        return jsonify({"error": "Student not found"}), 404

    db.session.delete(student)
    db.session.commit()
    return jsonify({"message": "Student removed"})
