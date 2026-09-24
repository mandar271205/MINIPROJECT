"""Phase 6 - configurable attendance policy.

A policy holds the thresholds attendance_decision_engine.py uses to
turn reconstructed presence evidence into a suggested status. Policies
are versioned by scope (subject+division, subject, division, or a
single global default) and by effective date range; resolution is
handled by policy_resolution.py, never hard-coded in the engine.
"""

from datetime import datetime, timezone

from ..extensions import db


def _utcnow():
    return datetime.now(timezone.utc)


class AttendancePolicy(db.Model):
    __tablename__ = "attendance_policies"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=True)
    division_id = db.Column(db.Integer, db.ForeignKey("divisions.id"), nullable=True)
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    effective_from = db.Column(db.Date, nullable=True)
    effective_until = db.Column(db.Date, nullable=True)

    present_threshold_percentage = db.Column(db.Float, nullable=False)
    late_grace_seconds = db.Column(db.Float, nullable=False)
    early_exit_tolerance_seconds = db.Column(db.Float, nullable=False)
    reentry_min_gap_seconds = db.Column(db.Float, nullable=False)
    # Phase 6 section I.4 requires two distinct confidence values rather
    # than the single `low_confidence_threshold` shorthand in section F:
    # a "flag" band (still evaluable) and a stricter "decision minimum"
    # (below which automatic classification is unsafe).
    low_confidence_flag_threshold = db.Column(db.Float, nullable=False)
    minimum_decision_confidence = db.Column(db.Float, nullable=False)
    minimum_valid_session_ratio = db.Column(db.Float, nullable=False, default=1.0)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    subject = db.relationship("Subject")
    division = db.relationship("Division")
    creator = db.relationship("User")

    __table_args__ = (
        db.CheckConstraint(
            "present_threshold_percentage > 0 AND present_threshold_percentage <= 100",
            name="ck_policy_present_threshold_range",
        ),
        db.CheckConstraint("late_grace_seconds >= 0", name="ck_policy_late_grace_nonnegative"),
        db.CheckConstraint("early_exit_tolerance_seconds >= 0", name="ck_policy_early_exit_nonnegative"),
        db.CheckConstraint("reentry_min_gap_seconds > 0", name="ck_policy_reentry_gap_positive"),
        db.CheckConstraint(
            "low_confidence_flag_threshold >= 0 AND low_confidence_flag_threshold <= 1",
            name="ck_policy_low_confidence_flag_range",
        ),
        db.CheckConstraint(
            "minimum_decision_confidence >= 0 AND minimum_decision_confidence <= 1",
            name="ck_policy_minimum_decision_confidence_range",
        ),
        db.CheckConstraint(
            "minimum_decision_confidence <= low_confidence_flag_threshold",
            name="ck_policy_confidence_ordering",
        ),
        db.CheckConstraint(
            "minimum_valid_session_ratio >= 0 AND minimum_valid_session_ratio <= 1",
            name="ck_policy_valid_session_ratio_range",
        ),
        db.CheckConstraint(
            "(effective_from IS NULL) OR (effective_until IS NULL) OR (effective_until > effective_from)",
            name="ck_policy_effective_range_order",
        ),
        # Only one active default policy may exist at a time - a
        # partial unique index (SQLite supports WHERE on indexes).
        db.Index(
            "uq_policy_single_active_default", "is_default",
            unique=True, sqlite_where=db.text("is_default = 1 AND is_active = 1"),
        ),
        db.Index("ix_policy_subject_division", "subject_id", "division_id"),
        db.Index("ix_policy_active", "is_active"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "subject_id": self.subject_id,
            "division_id": self.division_id,
            "is_default": self.is_default,
            "is_active": self.is_active,
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "effective_until": self.effective_until.isoformat() if self.effective_until else None,
            "present_threshold_percentage": self.present_threshold_percentage,
            "late_grace_seconds": self.late_grace_seconds,
            "early_exit_tolerance_seconds": self.early_exit_tolerance_seconds,
            "reentry_min_gap_seconds": self.reentry_min_gap_seconds,
            "low_confidence_flag_threshold": self.low_confidence_flag_threshold,
            "minimum_decision_confidence": self.minimum_decision_confidence,
            "minimum_valid_session_ratio": self.minimum_valid_session_ratio,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
