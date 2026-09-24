"""Phase 6 - AI-suggested attendance recommendations and independent
flags.

Deliberate compatibility decision (see Phase 6 PRD section O): the
existing `attendance_records.status` column is NOT NULL and is read by
legacy dashboards/exports, and Phase 3 deliberately avoids creating a
record at all for a student with no compatible face template. Rather
than loosen that NOT NULL constraint or fabricate a misleading legacy
status just to attach Phase 6 fields to `attendance_records`, Phase 6
introduces this separate `attendance_recommendations` table:

  - Exactly one row per rostered student per session (enforced by a
    unique constraint), independent of whether a legacy
    attendance_records row exists for that student.
  - `attendance_record_id` is a nullable link back to the legacy row
    when one exists, purely for convenience/traceability - never
    required, and Phase 6 never creates, edits, or deletes legacy
    attendance_records rows.
  - `attendance_flags` links to a recommendation (not to
    attendance_records) for the same reason, plus session_id/
    student_id directly for the indexes the PRD asks for.

This keeps the legacy `status` column and all legacy behaviour
completely untouched, while still guaranteeing "no ineligible student
is silently omitted" from Phase 6's output.
"""

from datetime import datetime, timezone

from ..extensions import db

RECOMMENDATION_STATUS_NOT_STARTED = "NOT_STARTED"
RECOMMENDATION_STATUS_PROCESSING = "PROCESSING"
RECOMMENDATION_STATUS_COMPLETED = "COMPLETED"
RECOMMENDATION_STATUS_FAILED = "FAILED"

RECOMMENDATION_GENERATION_STATUSES = (
    RECOMMENDATION_STATUS_NOT_STARTED,
    RECOMMENDATION_STATUS_PROCESSING,
    RECOMMENDATION_STATUS_COMPLETED,
    RECOMMENDATION_STATUS_FAILED,
)


def _utcnow():
    return datetime.now(timezone.utc)


class AttendanceRecommendation(db.Model):
    __tablename__ = "attendance_recommendations"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("attendance_sessions.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    # Nullable on purpose - many ineligible students never get a
    # legacy attendance_records row (Phase 3 correction); this link is
    # populated only when one already exists.
    attendance_record_id = db.Column(db.Integer, db.ForeignKey("attendance_records.id"), nullable=True)

    suggested_status = db.Column(db.String(30), nullable=False)
    suggested_status_source = db.Column(db.String(20), nullable=False, default="AI_RULE")
    reason_code = db.Column(db.String(60), nullable=False)
    reason_text = db.Column(db.Text, nullable=False)
    explanation_json = db.Column(db.JSON, nullable=True)

    # Nullable: a session whose policy could not be resolved still gets
    # a REVIEW_REQUIRED recommendation, with no policy attached.
    policy_id = db.Column(db.Integer, db.ForeignKey("attendance_policies.id"), nullable=True)
    policy_snapshot_json = db.Column(db.JSON, nullable=True)
    decision_version = db.Column(db.String(50), nullable=False)
    decision_computed_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    decision_confidence = db.Column(db.Float, nullable=True)
    decision_is_evaluable = db.Column(db.Boolean, nullable=False, default=False)

    presence_percentage_snapshot = db.Column(db.Float, nullable=True)
    presence_duration_seconds_snapshot = db.Column(db.Float, nullable=True)
    valid_session_seconds_snapshot = db.Column(db.Float, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Phase 7 additions - faculty manual overrides & finalisation
    final_status = db.Column(db.String(30), nullable=True)
    is_overridden = db.Column(db.Boolean, nullable=False, default=False)
    override_reason = db.Column(db.Text, nullable=True)
    overridden_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    overridden_at = db.Column(db.DateTime(timezone=True), nullable=True)

    session = db.relationship(
        "AttendanceSession", backref=db.backref("recommendations", cascade="all, delete-orphan")
    )
    student = db.relationship("Student")
    attendance_record = db.relationship("AttendanceRecord")
    policy = db.relationship("AttendancePolicy")
    overrider = db.relationship("User", foreign_keys=[overridden_by])
    flags = db.relationship(
        "AttendanceFlag", back_populates="recommendation", cascade="all, delete-orphan",
        order_by="AttendanceFlag.flag_type",
    )

    __table_args__ = (
        db.UniqueConstraint("session_id", "student_id", name="uq_recommendation_session_student"),
        db.CheckConstraint(
            "decision_confidence IS NULL OR (decision_confidence >= 0 AND decision_confidence <= 1)",
            name="ck_recommendation_confidence_range",
        ),
        db.CheckConstraint(
            "presence_percentage_snapshot IS NULL OR "
            "(presence_percentage_snapshot >= 0 AND presence_percentage_snapshot <= 100)",
            name="ck_recommendation_percentage_range",
        ),
        db.Index("ix_recommendation_session_student", "session_id", "student_id"),
    )

    def to_dict(self, *, include_flags: bool = True) -> dict:
        is_final = bool(self.session.is_finalised if self.session else False)
        effective_status = self.final_status if (self.is_overridden or is_final) else self.suggested_status
        data = {
            "student_id": self.student_id,
            "suggested_status": self.suggested_status,
            "final_status": self.final_status,
            "effective_status": effective_status,
            "is_final": is_final,
            "is_overridden": self.is_overridden,
            "override_reason": self.override_reason,
            "overridden_by": self.overridden_by,
            "overridden_at": self.overridden_at.isoformat() if self.overridden_at else None,
            "decision_is_evaluable": self.decision_is_evaluable,
            "presence_percentage": self.presence_percentage_snapshot,
            "reason_code": self.reason_code,
            "reason_text": self.reason_text,
            "policy": (
                {"id": self.policy_id, "name": (self.policy_snapshot_json or {}).get("policy_name")}
                if self.policy_id is not None
                else None
            ),
            "decision_version": self.decision_version,
            "decision_computed_at": self.decision_computed_at.isoformat() if self.decision_computed_at else None,
            "explanation": self.explanation_json,
        }
        if include_flags:
            data["flags"] = [f.flag_type for f in self.flags]
        return data


class AttendanceFlag(db.Model):
    __tablename__ = "attendance_flags"

    id = db.Column(db.Integer, primary_key=True)
    recommendation_id = db.Column(db.Integer, db.ForeignKey("attendance_recommendations.id"), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey("attendance_sessions.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)

    flag_type = db.Column(db.String(30), nullable=False)
    source = db.Column(db.String(20), nullable=False, default="AI_RULE")
    reason_code = db.Column(db.String(60), nullable=True)
    reason_text = db.Column(db.String(255), nullable=True)
    evidence_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    recommendation = db.relationship("AttendanceRecommendation", back_populates="flags")
    session = db.relationship("AttendanceSession")
    student = db.relationship("Student")

    __table_args__ = (
        db.UniqueConstraint("recommendation_id", "flag_type", "source", name="uq_flag_recommendation_type_source"),
        db.Index("ix_flag_session_student", "session_id", "student_id"),
        db.Index("ix_flag_recommendation_type", "recommendation_id", "flag_type"),
        db.Index("ix_flag_type_session", "flag_type", "session_id"),
    )

    def to_dict(self) -> dict:
        return {
            "flag_type": self.flag_type,
            "source": self.source,
            "reason_code": self.reason_code,
            "reason_text": self.reason_text,
        }
