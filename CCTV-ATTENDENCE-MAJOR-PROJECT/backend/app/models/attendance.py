from datetime import datetime, timezone

from ..extensions import db


class AttendanceSession(db.Model):
    __tablename__ = "attendance_sessions"

    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey("classrooms.id"), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    session_date = db.Column(db.Date, nullable=False)
    class_start_time = db.Column(db.DateTime(timezone=True), nullable=True)
    video_path = db.Column(db.String(500), nullable=False)
    processing_status = db.Column(db.String(20), nullable=False, default="pending")
    progress_pct = db.Column(db.Integer, nullable=False, default=0)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    classroom = db.relationship("Classroom", back_populates="sessions")
    records = db.relationship(
        "AttendanceRecord",
        back_populates="session",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "class_id": self.class_id,
            "session_date": self.session_date.isoformat(),
            "class_start_time": self.class_start_time.isoformat() if self.class_start_time else None,
            "processing_status": self.processing_status,
            "progress_pct": self.progress_pct,
            "error_message": self.error_message,
        }


class AttendanceRecord(db.Model):
    __tablename__ = "attendance_records"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("attendance_sessions.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    detected_at_seconds = db.Column(db.Float, nullable=True)
    flagged = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    session = db.relationship("AttendanceSession", back_populates="records")
    student = db.relationship("Student")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "student_id": self.student_id,
            "status": self.status,
            "flagged": self.flagged,
            "detected_at_seconds": self.detected_at_seconds,
        }
