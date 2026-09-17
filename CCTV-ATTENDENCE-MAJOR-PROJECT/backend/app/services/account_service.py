"""HOD-only account management: faculty accounts, and linking a student
user account to an existing Student profile row.

Every function here is only ever reachable through routes/admin.py,
which is gated with @require_hod on every endpoint - nothing in this
module is a self-service path.
"""

from __future__ import annotations

from ..extensions import db
from ..models.student import Student
from ..models.user import User
from ..utils.errors import DomainError
from ..utils.roles import ROLE_FACULTY, ROLE_STUDENT


def _normalize_email(email) -> str:
    return (email or "").strip().lower()


# --------------------------------------------------------------------------
# Faculty accounts
# --------------------------------------------------------------------------

def list_faculty_accounts():
    return User.query.filter_by(role=ROLE_FACULTY).order_by(User.name).all()


def get_faculty_account_or_404(user_id: int) -> User:
    user = User.query.filter_by(id=user_id, role=ROLE_FACULTY).first()
    if not user:
        raise DomainError("NOT_FOUND", "Faculty account not found", 404)
    return user


def create_faculty_account(payload: dict) -> User:
    name = (payload.get("name") or "").strip()
    email = _normalize_email(payload.get("email"))
    password = payload.get("password") or ""
    if not name or not email or not password:
        raise DomainError("VALIDATION_ERROR", "name, email and password are required", 400)

    if User.query.filter_by(email=email).first():
        raise DomainError("DUPLICATE_RESOURCE", "Email already registered", 409)

    user = User(name=name, email=email, role=ROLE_FACULTY, is_active=True)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def update_faculty_account(user_id: int, payload: dict) -> User:
    user = get_faculty_account_or_404(user_id)

    if "name" in payload:
        name = (payload.get("name") or "").strip()
        if not name:
            raise DomainError("VALIDATION_ERROR", "name cannot be empty", 400)
        user.name = name

    if "email" in payload:
        email = _normalize_email(payload.get("email"))
        if not email:
            raise DomainError("VALIDATION_ERROR", "email cannot be empty", 400)
        clash = User.query.filter(User.email == email, User.id != user.id).first()
        if clash:
            raise DomainError("DUPLICATE_RESOURCE", "Email already registered", 409)
        user.email = email

    if payload.get("password"):
        user.set_password(payload["password"])

    db.session.commit()
    return user


def set_faculty_account_status(user_id: int, is_active: bool) -> User:
    user = get_faculty_account_or_404(user_id)
    user.is_active = bool(is_active)
    db.session.commit()
    return user


# --------------------------------------------------------------------------
# Student account linking
# --------------------------------------------------------------------------

def get_student_or_404(student_id: int) -> Student:
    student = Student.query.get(student_id)
    if not student:
        raise DomainError("NOT_FOUND", "Student not found", 404)
    return student


def _resolve_student_role_user(user_id) -> User:
    if not user_id:
        raise DomainError("VALIDATION_ERROR", "user_id is required", 400)
    user = User.query.get(user_id)
    if not user:
        raise DomainError("VALIDATION_ERROR", "user_id does not reference an existing user", 400)
    if user.role != ROLE_STUDENT:
        raise DomainError("VALIDATION_ERROR", "The selected user does not have the student role", 400)
    return user


def link_student_account(student_id: int, payload: dict) -> Student:
    student = get_student_or_404(student_id)

    if student.user_id is not None:
        raise DomainError("DUPLICATE_RESOURCE", "This student is already linked to an account", 409)

    user = _resolve_student_role_user(payload.get("user_id"))

    if Student.query.filter_by(user_id=user.id).first() is not None:
        raise DomainError("DUPLICATE_RESOURCE", "This user is already linked to a different student", 409)

    student.user_id = user.id
    db.session.commit()
    return student


def relink_student_account(student_id: int, payload: dict) -> Student:
    """Changes which user a student profile is linked to. Runs the same
    role/duplicate checks as link_student_account, just excluding this
    student's own current link from the duplicate check."""
    student = get_student_or_404(student_id)
    user = _resolve_student_role_user(payload.get("user_id"))

    clash = Student.query.filter(Student.user_id == user.id, Student.id != student.id).first()
    if clash is not None:
        raise DomainError("DUPLICATE_RESOURCE", "This user is already linked to a different student", 409)

    student.user_id = user.id
    db.session.commit()
    return student


def set_student_account_status(student_id: int, is_active: bool) -> tuple[Student, User]:
    student = get_student_or_404(student_id)
    if student.user_id is None:
        raise DomainError(
            "VALIDATION_ERROR", "This student has no linked account to activate or deactivate", 400
        )
    linked_user = User.query.get(student.user_id)
    linked_user.is_active = bool(is_active)
    db.session.commit()
    return student, linked_user
