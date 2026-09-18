"""Phase 4 - temporary face tracks and recognition observations.

These tables record *evidence*, not final identity decisions. A track
is a temporary visual association of face detections across sampled
frames within one session; it becomes a confirmed student identity
only after app/services/identity_voting.py accumulates enough
consistent evidence. See recognition_provider.py / matching.py for how
each observation's top-1/top-2 candidates are produced, and
observation_tracker.py for how detections are associated into tracks.

Deliberately excluded from these tables (Phase 4 privacy rules):
raw face crops, raw query embeddings, passwords/tokens, private
filesystem paths.
"""

from datetime import datetime, timezone

from ..extensions import db

TRACK_STATE_UNCONFIRMED = "UNCONFIRMED"
TRACK_STATE_CONFIRMED = "CONFIRMED"
TRACK_STATE_UNKNOWN = "UNKNOWN"
TRACK_STATE_AMBIGUOUS = "AMBIGUOUS"
TRACK_STATE_CLOSED = "CLOSED"

TRACK_STATES = (
    TRACK_STATE_UNCONFIRMED,
    TRACK_STATE_CONFIRMED,
    TRACK_STATE_UNKNOWN,
    TRACK_STATE_AMBIGUOUS,
    TRACK_STATE_CLOSED,
)

EVIDENCE_STATE_MATCH_CANDIDATE = "MATCH_CANDIDATE"
EVIDENCE_STATE_BELOW_THRESHOLD = "BELOW_THRESHOLD"
EVIDENCE_STATE_AMBIGUOUS = "AMBIGUOUS"
EVIDENCE_STATE_UNKNOWN = "UNKNOWN"
EVIDENCE_STATE_CONFIRMED_SUPPORT = "CONFIRMED_SUPPORT"
EVIDENCE_STATE_CONFLICTING = "CONFLICTING"

EVIDENCE_STATES = (
    EVIDENCE_STATE_MATCH_CANDIDATE,
    EVIDENCE_STATE_BELOW_THRESHOLD,
    EVIDENCE_STATE_AMBIGUOUS,
    EVIDENCE_STATE_UNKNOWN,
    EVIDENCE_STATE_CONFIRMED_SUPPORT,
    EVIDENCE_STATE_CONFLICTING,
)


def _utcnow():
    return datetime.now(timezone.utc)


class FaceTrack(db.Model):
    __tablename__ = "face_tracks"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("attendance_sessions.id"), nullable=False)
    track_key = db.Column(db.String(64), nullable=False)
    first_seen_seconds = db.Column(db.Float, nullable=False)
    last_seen_seconds = db.Column(db.Float, nullable=False)
    observation_count = db.Column(db.Integer, nullable=False, default=0)
    track_state = db.Column(db.String(20), nullable=False, default=TRACK_STATE_UNCONFIRMED)
    # No ondelete cascade from students -> face_tracks: deleting/deactivating
    # a student must never cascade-delete track evidence, and deleting a
    # track must never touch the student row.
    confirmed_student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=True)
    confirmed_at_seconds = db.Column(db.Float, nullable=True)
    mean_confidence = db.Column(db.Float, nullable=True)
    max_confidence = db.Column(db.Float, nullable=True)
    identity_conflict = db.Column(db.Boolean, nullable=False, default=False)
    conflict_reason = db.Column(db.String(255), nullable=True)
    closed_at_seconds = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    session = db.relationship("AttendanceSession", backref=db.backref("face_tracks", cascade="all, delete-orphan"))
    confirmed_student = db.relationship("Student")
    observations = db.relationship(
        "RecognitionObservation", back_populates="track", cascade="all, delete-orphan", order_by="RecognitionObservation.timestamp_seconds"
    )

    __table_args__ = (
        db.UniqueConstraint("session_id", "track_key", name="uq_face_track_session_key"),
        db.CheckConstraint("observation_count >= 0", name="ck_face_track_observation_count_nonnegative"),
        db.CheckConstraint(
            "(mean_confidence IS NULL) OR (mean_confidence >= 0 AND mean_confidence <= 1)",
            name="ck_face_track_mean_confidence_range",
        ),
        db.CheckConstraint(
            "(max_confidence IS NULL) OR (max_confidence >= 0 AND max_confidence <= 1)",
            name="ck_face_track_max_confidence_range",
        ),
        db.Index("ix_face_tracks_session_state", "session_id", "track_state"),
        db.Index("ix_face_tracks_session_confirmed_student", "session_id", "confirmed_student_id"),
    )

    def to_diagnostic_dict(self) -> dict:
        return {
            "track_id": self.id,
            "track_key": self.track_key,
            "state": self.track_state,
            "confirmed_student_id": self.confirmed_student_id,
            "first_seen_seconds": self.first_seen_seconds,
            "last_seen_seconds": self.last_seen_seconds,
            "observation_count": self.observation_count,
            "mean_confidence": self.mean_confidence,
            "identity_conflict": self.identity_conflict,
        }


class RecognitionObservation(db.Model):
    __tablename__ = "recognition_observations"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("attendance_sessions.id"), nullable=False)
    track_id = db.Column(db.Integer, db.ForeignKey("face_tracks.id"), nullable=False)
    frame_index = db.Column(db.Integer, nullable=True)
    # Disambiguates multiple faces detected within the same
    # (session, frame_index) so the same physical detection is never
    # inserted twice on retry, even before track assignment.
    detection_index = db.Column(db.Integer, nullable=False, default=0)
    timestamp_seconds = db.Column(db.Float, nullable=False)
    bbox_x1 = db.Column(db.Float, nullable=True)
    bbox_y1 = db.Column(db.Float, nullable=True)
    bbox_x2 = db.Column(db.Float, nullable=True)
    bbox_y2 = db.Column(db.Float, nullable=True)
    detection_confidence = db.Column(db.Float, nullable=True)
    top1_student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=True)
    top1_similarity = db.Column(db.Float, nullable=True)
    top2_student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=True)
    top2_similarity = db.Column(db.Float, nullable=True)
    similarity_margin = db.Column(db.Float, nullable=True)
    evidence_state = db.Column(db.String(30), nullable=False, default=EVIDENCE_STATE_UNKNOWN)
    provider_model_id = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    session = db.relationship("AttendanceSession", backref=db.backref("recognition_observations", cascade="all, delete-orphan"))
    track = db.relationship("FaceTrack", back_populates="observations")
    top1_student = db.relationship("Student", foreign_keys=[top1_student_id])
    top2_student = db.relationship("Student", foreign_keys=[top2_student_id])

    __table_args__ = (
        db.UniqueConstraint(
            "session_id", "track_id", "frame_index", "detection_index",
            name="uq_observation_identity",
        ),
        db.CheckConstraint("timestamp_seconds >= 0", name="ck_observation_timestamp_nonnegative"),
        db.CheckConstraint(
            "(top1_student_id IS NULL) OR (top2_student_id IS NULL) OR (top1_student_id != top2_student_id)",
            name="ck_observation_top1_top2_distinct",
        ),
        db.CheckConstraint(
            "(top1_similarity IS NULL) OR (top1_similarity >= -1 AND top1_similarity <= 1)",
            name="ck_observation_top1_similarity_range",
        ),
        db.CheckConstraint(
            "(top2_similarity IS NULL) OR (top2_similarity >= -1 AND top2_similarity <= 1)",
            name="ck_observation_top2_similarity_range",
        ),
        db.Index("ix_observations_session_timestamp", "session_id", "timestamp_seconds"),
        db.Index("ix_observations_track_timestamp", "track_id", "timestamp_seconds"),
        db.Index("ix_observations_top1_student", "top1_student_id"),
    )

    def to_safe_dict(self) -> dict:
        """Never includes raw embeddings, images, or filesystem paths -
        only the metadata needed for audit/reconstruction."""
        return {
            "id": self.id,
            "track_id": self.track_id,
            "frame_index": self.frame_index,
            "timestamp_seconds": self.timestamp_seconds,
            "bbox": [self.bbox_x1, self.bbox_y1, self.bbox_x2, self.bbox_y2],
            "detection_confidence": self.detection_confidence,
            "top1_student_id": self.top1_student_id,
            "top1_similarity": self.top1_similarity,
            "top2_student_id": self.top2_student_id,
            "top2_similarity": self.top2_similarity,
            "similarity_margin": self.similarity_margin,
            "evidence_state": self.evidence_state,
        }
