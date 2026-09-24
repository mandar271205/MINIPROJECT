"""Phase 7 - Attendance Audit Log model.

Tracks all faculty/HOD manual overrides, finalisation events, and
status transitions with explicit reason logging and timestamps for
compliance and explainability.
"""

from datetime import datetime, timezone

from ..extensions import db


def _utcnow():
    return datetime.now(timezone.utc)


class AttendanceAuditLog(db.Model):
    __tablename__ = "attendance_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer,
        db.ForeignKey("attendance_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id = db.Column(
        db.Integer,
        db.ForeignKey("students.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
        index=True,
    )
    action = db.Column(db.String(50), nullable=False, index=True)
    previous_status = db.Column(db.String(30), nullable=True)
    new_status = db.Column(db.String(30), nullable=True)
    reason = db.Column(db.Text, nullable=False)
    details_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)

    session = db.relationship("AttendanceSession", backref=db.backref("audit_logs", cascade="all, delete-orphan", lazy="dynamic"))
    student = db.relationship("Student")
    user = db.relationship("User")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "student_id": self.student_id,
            "student_roll_number": self.student.roll_number if self.student else None,
            "student_name": self.student.name if self.student else None,
            "user_id": self.user_id,
            "user_name": self.user.name if self.user else None,
            "user_role": self.user.role if self.user else None,
            "action": self.action,
            "previous_status": self.previous_status,
            "new_status": self.new_status,
            "reason": self.reason,
            "details": self.details_json,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
