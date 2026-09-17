from .academic import bp as academic_bp
from .admin import bp as admin_bp
from .attendance import bp as attendance_bp
from .auth import bp as auth_bp
from .classes import bp as classes_bp
from .faculty import bp as faculty_bp
from .reports import bp as reports_bp
from .student import bp as student_bp

__all__ = [
    "academic_bp",
    "admin_bp",
    "attendance_bp",
    "auth_bp",
    "classes_bp",
    "faculty_bp",
    "reports_bp",
    "student_bp",
]
