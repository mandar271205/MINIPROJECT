from datetime import datetime, timezone

from ..extensions import db

# Phase 5 - processing states for presence reconstruction. These are
# job/processing states, never attendance statuses.
PRESENCE_STATUS_NOT_STARTED = "NOT_STARTED"
PRESENCE_STATUS_PROCESSING = "PROCESSING"
PRESENCE_STATUS_COMPLETED = "COMPLETED"
PRESENCE_STATUS_FAILED = "FAILED"
PRESENCE_STATUS_PARTIAL_EVIDENCE = "PARTIAL_EVIDENCE"

PRESENCE_RECONSTRUCTION_STATUSES = (
    PRESENCE_STATUS_NOT_STARTED,
    PRESENCE_STATUS_PROCESSING,
    PRESENCE_STATUS_COMPLETED,
    PRESENCE_STATUS_FAILED,
    PRESENCE_STATUS_PARTIAL_EVIDENCE,
)


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

    # Phase 5 additions - all nullable so existing sessions (created
    # before Phase 5) keep working unchanged until/unless reconstructed.
    actual_duration_seconds = db.Column(db.Float, nullable=True)
    valid_duration_seconds = db.Column(db.Float, nullable=True)
    presence_reconstructed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    presence_algorithm_version = db.Column(db.String(50), nullable=True)
    presence_reconstruction_status = db.Column(
        db.String(20), nullable=False, default=PRESENCE_STATUS_NOT_STARTED
    )
    presence_reconstruction_error = db.Column(db.Text, nullable=True)

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
