from .attendance import bp as attendance_bp
from .auth import bp as auth_bp
from .classes import bp as classes_bp
from .reports import bp as reports_bp

__all__ = ["attendance_bp", "auth_bp", "classes_bp", "reports_bp"]
