"""Standardized JSON response envelope for Phase 2 APIs.

Existing Phase 1 routes keep their original ad-hoc jsonify() shape
unchanged (touching them was out of scope); only new Phase 2 endpoints
under /api/academic, /api/student and /api/faculty use this helper.
"""

from flask import jsonify


def success(data=None, message: str = "Operation completed", status: int = 200):
    return jsonify({"success": True, "data": data if data is not None else {}, "message": message}), status


def error(code: str, message: str, status: int = 400):
    return jsonify({"success": False, "error": {"code": code, "message": message}}), status
