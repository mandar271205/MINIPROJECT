"""Phase 6 - deterministic attendance-policy resolution.

Scope priority (most specific wins):
  1. Subject + division
  2. Subject only
  3. Division only
  4. Global default (subject_id and division_id both null, is_default=True)

Only `is_active=True` policies within their effective date range are
considered. If two policies at the *same* specificity level both
match, resolution refuses to choose arbitrarily and raises
PolicyAmbiguousError - the caller (attendance_recommendation_service)
turns that into a REVIEW_REQUIRED recommendation, never a silent
guess.
"""

from __future__ import annotations

import datetime

from ..extensions import db


class PolicyResolutionError(RuntimeError):
    pass


class PolicyNotFoundError(PolicyResolutionError):
    pass


class PolicyAmbiguousError(PolicyResolutionError):
    pass


def _within_effective_range(policy, reference_date: datetime.date) -> bool:
    if policy.effective_from is not None and reference_date < policy.effective_from:
        return False
    if policy.effective_until is not None and reference_date > policy.effective_until:
        return False
    return True


def _specificity_level(policy, subject_id: int | None, division_id: int | None) -> int | None:
    if subject_id is not None and division_id is not None and policy.subject_id == subject_id and policy.division_id == division_id:
        return 1
    if subject_id is not None and policy.subject_id == subject_id and policy.division_id is None:
        return 2
    if division_id is not None and policy.division_id == division_id and policy.subject_id is None:
        return 3
    if policy.subject_id is None and policy.division_id is None and policy.is_default:
        return 4
    return None


def resolve_policy(
    *, subject_id: int | None, division_id: int | None, reference_date: datetime.date, db_session=None
):
    """Returns the single applicable AttendancePolicy row, or raises
    PolicyNotFoundError / PolicyAmbiguousError. Never returns None and
    never guesses between equally-specific candidates."""
    from ..models.attendance_policy import AttendancePolicy

    sa_session = db_session or db.session
    active_policies = sa_session.query(AttendancePolicy).filter_by(is_active=True).all()

    matched: list[tuple[int, "AttendancePolicy"]] = []
    for policy in active_policies:
        if not _within_effective_range(policy, reference_date):
            continue
        level = _specificity_level(policy, subject_id, division_id)
        if level is not None:
            matched.append((level, policy))

    if not matched:
        raise PolicyNotFoundError("No applicable attendance policy could be resolved for this scope/date")

    best_level = min(level for level, _ in matched)
    best_candidates = [policy for level, policy in matched if level == best_level]
    if len(best_candidates) > 1:
        raise PolicyAmbiguousError(
            f"{len(best_candidates)} equally-specific active policies match (specificity level {best_level})"
        )
    return best_candidates[0]


def to_decision_policy(policy):
    """Maps a persisted AttendancePolicy row to the pure
    attendance_decision_engine.DecisionPolicy dataclass."""
    from .attendance_decision_engine import DecisionPolicy

    return DecisionPolicy(
        policy_id=policy.id,
        policy_name=policy.name,
        present_threshold_percentage=policy.present_threshold_percentage,
        late_grace_seconds=policy.late_grace_seconds,
        early_exit_tolerance_seconds=policy.early_exit_tolerance_seconds,
        reentry_min_gap_seconds=policy.reentry_min_gap_seconds,
        low_confidence_flag_threshold=policy.low_confidence_flag_threshold,
        minimum_decision_confidence=policy.minimum_decision_confidence,
        minimum_valid_session_ratio=policy.minimum_valid_session_ratio,
    )
