"""Phase 6 - transactional, idempotent persistence of AI attendance
recommendations and their independent flags.

Same policy as presence_persistence.py (Phase 5): every new row is
validated before any old row is deleted, and the whole
delete-old + insert-new + session-status-update happens in a single
transaction, so a failure leaves the previous successful set of
recommendations completely untouched. Only the target session's own
AI-generated (source="AI_RULE") rows are ever replaced - a future
faculty-created flag (source="FACULTY") would never be touched by
this function, and unrelated sessions are never queried at all.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from ..extensions import db
from ..models.attendance import AttendanceSession
from ..models.attendance_recommendation import (
    RECOMMENDATION_STATUS_COMPLETED,
    RECOMMENDATION_STATUS_FAILED,
    RECOMMENDATION_STATUS_PROCESSING,
    AttendanceFlag,
    AttendanceRecommendation,
)
from ..services.attendance_decision_engine import ALL_FLAG_TYPES, ALL_MAIN_STATUSES, FLAG_SOURCE_AI_RULE


class RecommendationValidationError(ValueError):
    pass


def _validate_recommendation_row(row: dict) -> None:
    if row["suggested_status"] not in ALL_MAIN_STATUSES:
        raise RecommendationValidationError(f"Invalid suggested_status: {row['suggested_status']!r}")
    if not row.get("reason_code"):
        raise RecommendationValidationError("reason_code is required")
    if not row.get("reason_text"):
        raise RecommendationValidationError("reason_text is required")
    if not row.get("decision_version"):
        raise RecommendationValidationError("decision_version is required")
    confidence = row.get("decision_confidence")
    if confidence is not None and not (0.0 <= confidence <= 1.0):
        raise RecommendationValidationError(f"decision_confidence must be between 0 and 1, got {confidence!r}")
    percentage = row.get("presence_percentage_snapshot")
    if percentage is not None:
        if not math.isfinite(percentage) or not (0.0 <= percentage <= 100.0):
            raise RecommendationValidationError(f"presence_percentage_snapshot out of range: {percentage!r}")
    for flag_type in row.get("flags", []):
        if flag_type not in ALL_FLAG_TYPES:
            raise RecommendationValidationError(f"Invalid flag_type: {flag_type!r}")


def replace_session_recommendations(
    session: AttendanceSession,
    *,
    recommendation_rows: list[dict],
    status: str = RECOMMENDATION_STATUS_COMPLETED,
    error_message: str | None = None,
    db_session=None,
) -> list[AttendanceRecommendation]:
    """Validates every row, then upserts this session's AI-generated
    recommendations + flags in one transaction, keyed by student_id.

    Deliberately an upsert-in-place rather than delete-all-then-
    reinsert: an existing recommendation row for a student is updated
    in place (same primary key), and only its AI_RULE-sourced flags
    are replaced. This matters because SQLite reuses a freed integer
    primary key for the very next insert on a non-AUTOINCREMENT table
    - a delete-then-reinsert approach could let a brand-new
    recommendation row silently inherit the recycled id of a deleted
    one, reattaching any surviving non-AI_RULE flag (e.g. a future
    faculty-created flag) to the wrong recommendation. Upserting in
    place never frees the id in the first place, so that failure mode
    cannot happen. `recommendation_rows` entries carry a `flags` list
    of flag-type strings, expanded into AttendanceFlag rows here."""
    sa_session = db_session or db.session

    for row in recommendation_rows:
        _validate_recommendation_row(row)

    try:
        existing_by_student = {
            r.student_id: r
            for r in AttendanceRecommendation.query.filter_by(session_id=session.id).all()
        }

        upserted: list[AttendanceRecommendation] = []
        for row in recommendation_rows:
            flag_types = row.pop("flags", [])
            recommendation = existing_by_student.get(row["student_id"])
            if recommendation is None:
                recommendation = AttendanceRecommendation(session_id=session.id, student_id=row["student_id"])
                sa_session.add(recommendation)

            recommendation.attendance_record_id = row.get("attendance_record_id")
            recommendation.suggested_status = row["suggested_status"]
            recommendation.suggested_status_source = FLAG_SOURCE_AI_RULE
            recommendation.reason_code = row["reason_code"]
            recommendation.reason_text = row["reason_text"]
            recommendation.explanation_json = row.get("explanation_json")
            recommendation.policy_id = row.get("policy_id")
            recommendation.policy_snapshot_json = row.get("policy_snapshot_json")
            recommendation.decision_version = row["decision_version"]
            recommendation.decision_confidence = row.get("decision_confidence")
            recommendation.decision_is_evaluable = row.get("decision_is_evaluable", False)
            recommendation.presence_percentage_snapshot = row.get("presence_percentage_snapshot")
            recommendation.presence_duration_seconds_snapshot = row.get("presence_duration_seconds_snapshot")
            recommendation.valid_session_seconds_snapshot = row.get("valid_session_seconds_snapshot")
            sa_session.flush()  # ensure recommendation.id exists before touching its flags

            # Only this recommendation's own AI_RULE flags are ever
            # replaced - any other source (e.g. a future faculty
            # override) attached to the same recommendation id survives.
            AttendanceFlag.query.filter_by(
                recommendation_id=recommendation.id, source=FLAG_SOURCE_AI_RULE
            ).delete(synchronize_session=False)
            for flag_type in flag_types:
                sa_session.add(
                    AttendanceFlag(
                        recommendation_id=recommendation.id, session_id=session.id, student_id=row["student_id"],
                        flag_type=flag_type, source=FLAG_SOURCE_AI_RULE, reason_code=row["reason_code"],
                    )
                )
            upserted.append(recommendation)

        session.recommendation_generation_status = status
        session.recommendation_generation_error = error_message
        session.recommendation_generated_at = datetime.now(timezone.utc)

        sa_session.commit()
        return upserted
    except Exception:
        sa_session.rollback()
        raise


def mark_generation_processing(session: AttendanceSession, db_session=None) -> None:
    sa_session = db_session or db.session
    session.recommendation_generation_status = RECOMMENDATION_STATUS_PROCESSING
    session.recommendation_generation_error = None
    sa_session.commit()


def mark_generation_failed(session: AttendanceSession, error_message: str, db_session=None) -> None:
    sa_session = db_session or db.session
    session.recommendation_generation_status = RECOMMENDATION_STATUS_FAILED
    session.recommendation_generation_error = error_message
    sa_session.commit()
