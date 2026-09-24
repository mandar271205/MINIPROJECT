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

# Phase 6 - recommendation-GENERATION workflow states (NOT_STARTED /
# PROCESSING / COMPLETED / FAILED). These describe whether the AI
# decision engine has run for this session, never an attendance
# status itself - see attendance_decision_engine.py for the actual
# PRESENT/PARTIAL/ABSENT/REVIEW_REQUIRED domain.
RECOMMENDATION_GENERATION_NOT_STARTED = "NOT_STARTED"
RECOMMENDATION_GENERATION_PROCESSING = "PROCESSING"
RECOMMENDATION_GENERATION_COMPLETED = "COMPLETED"
RECOMMENDATION_GENERATION_FAILED = "FAILED"

RECOMMENDATION_GENERATION_STATUSES = (
    RECOMMENDATION_GENERATION_NOT_STARTED,
    RECOMMENDATION_GENERATION_PROCESSING,
    RECOMMENDATION_GENERATION_COMPLETED,
    RECOMMENDATION_GENERATION_FAILED,
)

# Phase 6 reliability correction - the current full-video pipeline
# version string persisted alongside verified completion evidence.
# Bumped whenever the processing pipeline's EOF/completion semantics
# change, so a session can always be traced back to which pipeline
# version actually verified it.
FULL_VIDEO_PIPELINE_VERSION = "full_video_arcface_v1"


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

    # Phase 6 additions - all nullable/defaulted so existing sessions
    # keep working unchanged until/unless recommendations are generated.
    recommendation_generation_status = db.Column(
        db.String(20), nullable=False, default=RECOMMENDATION_GENERATION_NOT_STARTED
    )
    recommendation_generation_error = db.Column(db.Text, nullable=True)
    recommendation_generated_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Phase 6 reliability correction - persisted, verifiable full-video
    # completion evidence. `eof_reached` is intentionally nullable and
    # three-valued: True (verified complete), False (verified
    # incomplete/early-stop), NULL (no proof either way - e.g. a
    # session processed before this evidence existed). NULL must never
    # be treated as True anywhere downstream - see
    # attendance_decision_engine.py's REASON_FULL_VIDEO_COMPLETION_UNVERIFIED.
    eof_reached = db.Column(db.Boolean, nullable=True)
    processing_pipeline_version = db.Column(db.String(50), nullable=True)
    processed_video_duration_seconds = db.Column(db.Float, nullable=True)
    final_processed_timestamp_seconds = db.Column(db.Float, nullable=True)
    processing_completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Phase 7 additions - transaction-safe attendance finalisation metadata.
    # Default is_finalised to False so all pre-existing sessions continue
    # in unfinalised review state until explicitly finalised by faculty/HOD.
    is_finalised = db.Column(db.Boolean, nullable=False, default=False)
    finalised_at = db.Column(db.DateTime(timezone=True), nullable=True)
    finalised_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    finalisation_notes = db.Column(db.Text, nullable=True)

    classroom = db.relationship("Classroom", back_populates="sessions")
    finaliser = db.relationship("User", foreign_keys=[finalised_by])
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
            "is_finalised": self.is_finalised,
            "finalised_at": self.finalised_at.isoformat() if self.finalised_at else None,
            "finalised_by": self.finalised_by,
            "finalisation_notes": self.finalisation_notes,
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
