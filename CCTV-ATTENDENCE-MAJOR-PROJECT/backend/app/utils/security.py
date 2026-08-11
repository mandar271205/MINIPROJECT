from functools import wraps

from flask import g, jsonify
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from ..models.user import User


def get_current_user():
    verify_jwt_in_request()
    user_id = get_jwt_identity()
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    user = User.query.get(user_id)
    if not user:
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
            if roles and user.role not in roles:
                return jsonify({"error": "Forbidden"}), 403
            g.current_user = user
            return fn(*args, **kwargs)

        return wrapper

    return decorator
