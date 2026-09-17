from flask import Blueprint, g, jsonify, request
from flask_jwt_extended import create_access_token

from ..extensions import db
from ..models.user import User
from ..utils.roles import SELF_REGISTERABLE_ROLES
from ..utils.security import get_current_user, require_roles

bp = Blueprint("auth", __name__)


@bp.post("/login")
def login():
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    role = (payload.get("role") or "").strip().lower()

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid credentials"}), 401

    if role and user.role != role:
        return jsonify({"error": "Invalid role"}), 403

    if not user.is_active:
        return jsonify({"error": "This account has been deactivated"}), 403

    token = create_access_token(identity=str(user.id), additional_claims={"role": user.role})
    return jsonify({"token": token, "user": user.to_dict()})


@bp.post("/register")
def register():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    # Public self-service registration can only ever create a "student"
    # user - it is the only role in SELF_REGISTERABLE_ROLES. There is no
    # faculty default any more: "hod" and "faculty" accounts can only be
    # created through HOD-controlled paths (seeding, or
    # /api/admin/faculty). A caller that explicitly asks for any other
    # role is rejected outright, it is never silently downgraded.
    requested_role = (payload.get("role") or SELF_REGISTERABLE_ROLES[0]).strip().lower()

    if not name or not email or not password:
        return jsonify({"error": "Name, email, and password are required"}), 400

    if requested_role not in SELF_REGISTERABLE_ROLES:
        return jsonify({"error": "Invalid role"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 409

    # This creates only the User account. It deliberately never links the
    # new user to any students row - linking an account to an existing
    # student profile is an HOD-only action (see routes/admin.py), never
    # something a self-registering caller can trigger for themselves.
    user = User(name=name, email=email, role=requested_role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return jsonify({"message": "Registration successful"}), 201


@bp.get("/me")
@require_roles("faculty", "hod")
def me():
    user = getattr(g, "current_user", None) or get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"user": user.to_dict()})
