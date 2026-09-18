"""Phase 5 - reconstructed presence windows.

A presence window is NOT an attendance status. It is an explainable,
evidence-based time interval during which trusted confirmed recognition
evidence (see presence_reconstruction.py) supports that a specific
student was present. Final AttendIQ attendance statuses are assigned in
a later phase, using this data as one input among others.
"""

from datetime import datetime, timezone

from ..extensions import db


def _utcnow():
    return datetime.now(timezone.utc)


class PresenceWindow(db.Model):
    __tablename__ = "presence_windows"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("attendance_sessions.id"), nullable=False)
    # No ondelete cascade toward students: deleting/deactivating a
    # student must never cascade-delete presence evidence, and
    # deleting a presence window must never touch the student row.
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    window_index = db.Column(db.Integer, nullable=False)
    start_seconds = db.Column(db.Float, nullable=False)
    end_seconds = db.Column(db.Float, nullable=False)
    observed_duration_seconds = db.Column(db.Float, nullable=False)
    inferred_gap_seconds = db.Column(db.Float, nullable=False)
    total_duration_seconds = db.Column(db.Float, nullable=False)
    observation_count = db.Column(db.Integer, nullable=False)
    contributing_track_count = db.Column(db.Integer, nullable=False)
    mean_confidence = db.Column(db.Float, nullable=True)
    minimum_confidence = db.Column(db.Float, nullable=True)
    maximum_confidence = db.Column(db.Float, nullable=True)
    algorithm_version = db.Column(db.String(50), nullable=False)
    # Compact explainability metadata only (config used, exclusion
    # counts) - never raw observation lists or embeddings. See
    # presence_reconstruction.py's module docstring.
    reconstruction_metadata = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    session = db.relationship(
        "AttendanceSession", backref=db.backref("presence_windows", cascade="all, delete-orphan")
    )
    student = db.relationship("Student")

    __table_args__ = (
        db.UniqueConstraint("session_id", "student_id", "window_index", name="uq_presence_window_index"),
        db.CheckConstraint("start_seconds >= 0", name="ck_presence_window_start_nonnegative"),
        db.CheckConstraint("end_seconds >= start_seconds", name="ck_presence_window_end_after_start"),
        db.CheckConstraint("observed_duration_seconds >= 0", name="ck_presence_window_observed_nonnegative"),
        db.CheckConstraint("inferred_gap_seconds >= 0", name="ck_presence_window_inferred_nonnegative"),
        db.CheckConstraint("total_duration_seconds >= 0", name="ck_presence_window_total_nonnegative"),
        db.CheckConstraint("observation_count > 0", name="ck_presence_window_observation_count_positive"),
        db.CheckConstraint("contributing_track_count > 0", name="ck_presence_window_track_count_positive"),
        db.CheckConstraint(
            "(mean_confidence IS NULL) OR (mean_confidence >= 0 AND mean_confidence <= 1)",
            name="ck_presence_window_mean_confidence_range",
        ),
        db.CheckConstraint(
            "(minimum_confidence IS NULL) OR (minimum_confidence >= 0 AND minimum_confidence <= 1)",
            name="ck_presence_window_min_confidence_range",
        ),
        db.CheckConstraint(
            "(maximum_confidence IS NULL) OR (maximum_confidence >= 0 AND maximum_confidence <= 1)",
            name="ck_presence_window_max_confidence_range",
        ),
        # total_duration ~= observed + inferred is enforced in
        # application code (presence_reconstruction.py) and tests, not
        # as an exact-equality DB constraint - SQLite floating-point
        # comparison in a CHECK constraint is not a reliable way to
        # enforce an approximate equality.
        db.Index("ix_presence_windows_session_student", "session_id", "student_id"),
        db.Index("ix_presence_windows_session_start", "session_id", "start_seconds"),
        db.Index("ix_presence_windows_student_session", "student_id", "session_id"),
    )

    def to_dict(self) -> dict:
        return {
            "window_index": self.window_index,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "observed_duration_seconds": self.observed_duration_seconds,
            "inferred_gap_seconds": self.inferred_gap_seconds,
            "total_duration_seconds": self.total_duration_seconds,
            "observation_count": self.observation_count,
            "contributing_track_count": self.contributing_track_count,
            "mean_confidence": self.mean_confidence,
        }
