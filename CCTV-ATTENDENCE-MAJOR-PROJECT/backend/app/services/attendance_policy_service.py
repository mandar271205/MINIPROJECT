"""Phase 6 - attendance-policy CRUD validation and safe seed logic.

Routes call this module so all validation, overlap-checking, and the
single-active-default rule live in one place instead of being
duplicated across route handlers.
"""

from __future__ import annotations

import datetime
import math

from ..extensions import db
from ..models.attendance_policy import AttendancePolicy
from ..utils.errors import DomainError

REQUIRED_NUMERIC_FIELDS = (
    "present_threshold_percentage", "late_grace_seconds", "early_exit_tolerance_seconds",
    "reentry_min_gap_seconds", "low_confidence_flag_threshold", "minimum_decision_confidence",
)


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_policy_payload(payload: dict) -> None:
    for field in REQUIRED_NUMERIC_FIELDS:
        if field not in payload or not _finite(payload[field]):
            raise DomainError("VALIDATION_ERROR", f"{field} must be a finite number", 400)

    present = payload["present_threshold_percentage"]
    if not (0.0 < present <= 100.0):
        raise DomainError("VALIDATION_ERROR", "present_threshold_percentage must be > 0 and <= 100", 400)
    if payload["late_grace_seconds"] < 0:
        raise DomainError("VALIDATION_ERROR", "late_grace_seconds must be >= 0", 400)
    if payload["early_exit_tolerance_seconds"] < 0:
        raise DomainError("VALIDATION_ERROR", "early_exit_tolerance_seconds must be >= 0", 400)
    if payload["reentry_min_gap_seconds"] <= 0:
        raise DomainError("VALIDATION_ERROR", "reentry_min_gap_seconds must be > 0", 400)

    low_flag = payload["low_confidence_flag_threshold"]
    min_decision = payload["minimum_decision_confidence"]
    if not (0.0 <= low_flag <= 1.0):
        raise DomainError("VALIDATION_ERROR", "low_confidence_flag_threshold must be between 0 and 1", 400)
    if not (0.0 <= min_decision <= 1.0):
        raise DomainError("VALIDATION_ERROR", "minimum_decision_confidence must be between 0 and 1", 400)
    if min_decision > low_flag:
        raise DomainError("VALIDATION_ERROR", "minimum_decision_confidence must be <= low_confidence_flag_threshold", 400)

    ratio = payload.get("minimum_valid_session_ratio", 1.0)
    if not _finite(ratio) or not (0.0 <= ratio <= 1.0):
        raise DomainError("VALIDATION_ERROR", "minimum_valid_session_ratio must be between 0 and 1", 400)

    effective_from = payload.get("effective_from")
    effective_until = payload.get("effective_until")
    if effective_from and effective_until and effective_until <= effective_from:
        raise DomainError("VALIDATION_ERROR", "effective_until must be after effective_from", 400)

    if not payload.get("name") or not str(payload["name"]).strip():
        raise DomainError("VALIDATION_ERROR", "name is required", 400)


def _ranges_overlap(a_from, a_until, b_from, b_until) -> bool:
    # None means unbounded on that side.
    if a_until is not None and b_from is not None and a_until < b_from:
        return False
    if b_until is not None and a_from is not None and b_until < a_from:
        return False
    return True


def check_no_conflicting_active_policy(
    *, subject_id, division_id, is_default, effective_from, effective_until, exclude_id=None
) -> None:
    """Prevents two active policies from covering the same scope and
    an overlapping effective period - the ambiguity policy_resolution
    would otherwise have to reject at evaluation time."""
    query = AttendancePolicy.query.filter_by(is_active=True, subject_id=subject_id, division_id=division_id)
    if exclude_id is not None:
        query = query.filter(AttendancePolicy.id != exclude_id)

    for existing in query.all():
        if _ranges_overlap(effective_from, effective_until, existing.effective_from, existing.effective_until):
            raise DomainError(
                "POLICY_CONFLICT",
                f"An active policy (id={existing.id}) already covers this scope for an overlapping effective period",
                409,
            )

    if is_default:
        default_query = AttendancePolicy.query.filter_by(is_active=True, is_default=True)
        if exclude_id is not None:
            default_query = default_query.filter(AttendancePolicy.id != exclude_id)
        if default_query.first() is not None:
            raise DomainError("POLICY_CONFLICT", "Only one active default policy may exist at a time", 409)


def create_policy(payload: dict, created_by: int) -> AttendancePolicy:
    validate_policy_payload(payload)
    is_default = bool(payload.get("is_default", False))
    check_no_conflicting_active_policy(
        subject_id=payload.get("subject_id"), division_id=payload.get("division_id"), is_default=is_default,
        effective_from=payload.get("effective_from"), effective_until=payload.get("effective_until"),
    )

    policy = AttendancePolicy(
        name=payload["name"].strip(),
        subject_id=payload.get("subject_id"),
        division_id=payload.get("division_id"),
        is_default=is_default,
        is_active=bool(payload.get("is_active", True)),
        effective_from=payload.get("effective_from"),
        effective_until=payload.get("effective_until"),
        present_threshold_percentage=payload["present_threshold_percentage"],
        late_grace_seconds=payload["late_grace_seconds"],
        early_exit_tolerance_seconds=payload["early_exit_tolerance_seconds"],
        reentry_min_gap_seconds=payload["reentry_min_gap_seconds"],
        low_confidence_flag_threshold=payload["low_confidence_flag_threshold"],
        minimum_decision_confidence=payload["minimum_decision_confidence"],
        minimum_valid_session_ratio=payload.get("minimum_valid_session_ratio", 1.0),
        created_by=created_by,
    )
    db.session.add(policy)
    db.session.commit()
    return policy


def update_policy(policy: AttendancePolicy, payload: dict) -> AttendancePolicy:
    merged = {
        "name": payload.get("name", policy.name),
        "subject_id": payload.get("subject_id", policy.subject_id),
        "division_id": payload.get("division_id", policy.division_id),
        "is_default": payload.get("is_default", policy.is_default),
        "is_active": payload.get("is_active", policy.is_active),
        "effective_from": payload.get("effective_from", policy.effective_from),
        "effective_until": payload.get("effective_until", policy.effective_until),
        "present_threshold_percentage": payload.get("present_threshold_percentage", policy.present_threshold_percentage),
        "late_grace_seconds": payload.get("late_grace_seconds", policy.late_grace_seconds),
        "early_exit_tolerance_seconds": payload.get("early_exit_tolerance_seconds", policy.early_exit_tolerance_seconds),
        "reentry_min_gap_seconds": payload.get("reentry_min_gap_seconds", policy.reentry_min_gap_seconds),
        "low_confidence_flag_threshold": payload.get("low_confidence_flag_threshold", policy.low_confidence_flag_threshold),
        "minimum_decision_confidence": payload.get("minimum_decision_confidence", policy.minimum_decision_confidence),
        "minimum_valid_session_ratio": payload.get("minimum_valid_session_ratio", policy.minimum_valid_session_ratio),
    }
    validate_policy_payload(merged)
    if merged["is_active"]:
        check_no_conflicting_active_policy(
            subject_id=merged["subject_id"], division_id=merged["division_id"], is_default=merged["is_default"],
            effective_from=merged["effective_from"], effective_until=merged["effective_until"], exclude_id=policy.id,
        )

    for key, value in merged.items():
        setattr(policy, key, value)
    db.session.commit()
    return policy


def set_policy_active_status(policy: AttendancePolicy, is_active: bool) -> AttendancePolicy:
    if is_active and not policy.is_active:
        check_no_conflicting_active_policy(
            subject_id=policy.subject_id, division_id=policy.division_id, is_default=policy.is_default,
            effective_from=policy.effective_from, effective_until=policy.effective_until, exclude_id=policy.id,
        )
    policy.is_active = is_active
    db.session.commit()
    return policy


DEVELOPMENT_DEFAULT_POLICY_NAME = "Development Default (uncalibrated)"


def ensure_development_default_policy(created_by: int) -> AttendancePolicy | None:
    """Idempotent seed: creates exactly one clearly-labelled
    development-default policy if, and only if, no active default
    policy exists yet. Never recreates a duplicate on repeated calls
    (e.g. app startup) - see Phase 6 PRD section G."""
    existing_default = AttendancePolicy.query.filter_by(is_default=True, is_active=True).first()
    if existing_default is not None:
        return None

    policy = AttendancePolicy(
        name=DEVELOPMENT_DEFAULT_POLICY_NAME,
        subject_id=None, division_id=None, is_default=True, is_active=True,
        effective_from=None, effective_until=None,
        present_threshold_percentage=75.0, late_grace_seconds=600.0, early_exit_tolerance_seconds=600.0,
        reentry_min_gap_seconds=300.0, low_confidence_flag_threshold=0.55, minimum_decision_confidence=0.45,
        minimum_valid_session_ratio=1.0, created_by=created_by,
    )
    db.session.add(policy)
    db.session.commit()
    return policy
