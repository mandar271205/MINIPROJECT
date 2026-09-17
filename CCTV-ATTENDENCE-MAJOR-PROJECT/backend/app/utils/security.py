from functools import wraps

from flask import g, jsonify
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from ..models.academic import FacultyAssignment
from ..models.user import User
from .roles import ROLE_FACULTY, ROLE_HOD, ROLE_STUDENT


def get_current_user():
    verify_jwt_in_request()
    user_id = get_jwt_identity()
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    user = User.query.get(user_id)
    if not user or not user.is_active:
        return None
    g.current_user = user
    return user


def require_roles(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            user_id = get_jwt_identity()
            try:
                user_id = int(user_id)
            except (TypeError, ValueError):
                return jsonify({"error": "Invalid user"}), 401
            user = User.query.get(user_id)
            if not user:
                return jsonify({"error": "Invalid user"}), 401
            # Re-checked on every request (not just at login) so an HOD
            # deactivating a faculty or student-linked account takes
            # effect immediately, even against an already-issued JWT
            # that has not expired yet.
            if not user.is_active:
                return jsonify({"error": "Invalid user"}), 401
            if roles and user.role not in roles:
                return jsonify({"error": "Forbidden"}), 403
            g.current_user = user
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# --- Phase 2 role-scoped decorators -----------------------------------
# Thin, readable aliases over require_roles() so route files declare
# intent explicitly instead of repeating role-name literals.

def require_hod(fn):
    return require_roles(ROLE_HOD)(fn)


def require_faculty(fn):
    return require_roles(ROLE_FACULTY)(fn)


def require_student(fn):
    return require_roles(ROLE_STUDENT)(fn)


def require_hod_or_faculty(fn):
    return require_roles(ROLE_HOD, ROLE_FACULTY)(fn)


# --- Phase 2 assignment / ownership checks ------------------------------

def faculty_has_assignment(faculty_id: int, *, subject_id: int | None = None, division_id: int | None = None) -> bool:
    """True if the given faculty user has an active assignment matching
    the given subject and/or division filters."""
    query = FacultyAssignment.query.filter_by(faculty_id=faculty_id, is_active=True)
    if subject_id is not None:
        query = query.filter_by(subject_id=subject_id)
    if division_id is not None:
        query = query.filter_by(division_id=division_id)
    return query.first() is not None


def require_hod_or_assigned_faculty(*, subject_id=None, division_id=None):
    """Allow HOD unconditionally, or a faculty member who holds an active
    assignment for the referenced subject/division. Returns a Flask
    response tuple on failure, or None when access is permitted. Must be
    called after the caller has already resolved g.current_user (e.g. via
    a require_roles(...) decorator on the route)."""
    user = g.current_user
    if user.role == ROLE_HOD:
        return None
    if user.role == ROLE_FACULTY and faculty_has_assignment(
        user.id, subject_id=subject_id, division_id=division_id
    ):
        return None
    return jsonify({"error": "Forbidden"}), 403
