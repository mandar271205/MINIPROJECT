"""Phase 7 - Attendance Finalisation and Faculty Override Service.

Provides:
  - Transaction-safe atomic attendance finalisation (no partial updates).
  - Faculty override capabilities with mandatory reason logging.
  - Comprehensive audit trail recording.
  - Safe rollback guarantees under error conditions.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..extensions import db
from ..models.attendance import AttendanceRecord, AttendanceSession
from ..models.attendance_audit import AttendanceAuditLog
from ..models.attendance_recommendation import (
    AttendanceFlag,
    AttendanceRecommendation,
    RECOMMENDATION_STATUS_COMPLETED,
)

VALID_OVERRIDE_STATUSES = {"PRESENT", "ABSENT", "PARTIAL"}
FLAG_FACULTY_OVERRIDE = "FACULTY_OVERRIDE"
FLAG_SOURCE_FACULTY = "FACULTY"


class FinalisationError(Exception):
    """Base class for finalisation and override domain errors."""
    pass


class FinalisationNotAllowed(FinalisationError):
    """Raised when the session is not in an evaluable/reconstructed state."""
    pass


class OverrideNotAllowed(FinalisationError):
    """Raised when an invalid override request is rejected."""
    pass


class UnresolvedReviewRequiredError(FinalisationError):
    """Raised when finalisation is attempted with unresolved REVIEW_REQUIRED statuses."""

    def __init__(self, message: str, unresolved_student_ids: List[int]):
        super().__init__(message)
        self.unresolved_student_ids = unresolved_student_ids


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def override_student_attendance(
    session_id: int,
    student_id: int,
    status: str,
    reason: str,
    user_id: int,
    db_session=None,
) -> AttendanceRecommendation:
    """Override a single student's attendance recommendation.

    Validates the status and mandatory reason, updates the recommendation,
    attaches a FACULTY_OVERRIDE flag, synchronizes official attendance records
    if the session is already finalised, and logs an audit trail entry.
    All operations are committed atomically.
    """
    sa_session = db_session or db.session

    if not status or not isinstance(status, str):
        raise OverrideNotAllowed("Override status is required")

    norm_status = status.strip().upper()
    if norm_status not in VALID_OVERRIDE_STATUSES:
        raise OverrideNotAllowed(
            f"Invalid override status '{status}'. Must be one of: {', '.join(sorted(VALID_OVERRIDE_STATUSES))}"
        )

    if not reason or not isinstance(reason, str) or not reason.strip():
        raise OverrideNotAllowed("A non-empty reason is required for manual override logging")

    clean_reason = reason.strip()

    session = sa_session.query(AttendanceSession).get(session_id)
    if not session:
        raise FinalisationError(f"Attendance session {session_id} not found")

    rec = sa_session.query(AttendanceRecommendation).filter_by(
        session_id=session_id, student_id=student_id
    ).first()
    if not rec:
        raise FinalisationError(
            f"No attendance recommendation found for student {student_id} in session {session_id}"
        )

    previous_status = rec.final_status if (rec.is_overridden and rec.final_status) else rec.suggested_status

    try:
        rec.final_status = norm_status
        rec.is_overridden = True
        rec.override_reason = clean_reason
        rec.overridden_by = user_id
        rec.overridden_at = _utcnow()

        # Update or add FACULTY_OVERRIDE flag
        existing_flag = sa_session.query(AttendanceFlag).filter_by(
            recommendation_id=rec.id, flag_type=FLAG_FACULTY_OVERRIDE
        ).first()

        if existing_flag:
            existing_flag.source = FLAG_SOURCE_FACULTY
            existing_flag.reason_text = clean_reason
            existing_flag.created_at = _utcnow()
        else:
            new_flag = AttendanceFlag(
                recommendation_id=rec.id,
                session_id=session_id,
                student_id=student_id,
                flag_type=FLAG_FACULTY_OVERRIDE,
                source=FLAG_SOURCE_FACULTY,
                reason_text=clean_reason,
            )
            sa_session.add(new_flag)

        # If session is already finalised, keep the official AttendanceRecord in sync
        if session.is_finalised:
            record = sa_session.query(AttendanceRecord).filter_by(
                session_id=session_id, student_id=student_id
            ).first()
            if record:
                record.status = norm_status
                record.flagged = True
            else:
                record = AttendanceRecord(
                    session_id=session_id,
                    student_id=student_id,
                    status=norm_status,
                    flagged=True,
                )
                sa_session.add(record)
            sa_session.flush()
            rec.attendance_record_id = record.id

        # Log audit trail
        audit = AttendanceAuditLog(
            session_id=session_id,
            student_id=student_id,
            user_id=user_id,
            action="OVERRIDE_STATUS",
            previous_status=previous_status,
            new_status=norm_status,
            reason=clean_reason,
            details_json={
                "original_suggested_status": rec.suggested_status,
                "session_is_finalised": session.is_finalised,
            },
        )
        sa_session.add(audit)
        sa_session.commit()
        return rec
    except Exception:
        sa_session.rollback()
        raise


def reset_student_override(
    session_id: int,
    student_id: int,
    user_id: int,
    db_session=None,
) -> AttendanceRecommendation:
    """Reset a manual override back to the original AI recommendation."""
    sa_session = db_session or db.session

    session = sa_session.query(AttendanceSession).get(session_id)
    if not session:
        raise FinalisationError(f"Attendance session {session_id} not found")

    rec = sa_session.query(AttendanceRecommendation).filter_by(
        session_id=session_id, student_id=student_id
    ).first()
    if not rec:
        raise FinalisationError(
            f"No attendance recommendation found for student {student_id} in session {session_id}"
        )

    if not rec.is_overridden:
        return rec

    previous_status = rec.final_status or rec.suggested_status

    try:
        rec.is_overridden = False
        rec.override_reason = None
        rec.overridden_by = None
        rec.overridden_at = None
        rec.final_status = rec.suggested_status if session.is_finalised else None

        # Remove FACULTY_OVERRIDE flag
        sa_session.query(AttendanceFlag).filter_by(
            recommendation_id=rec.id, flag_type=FLAG_FACULTY_OVERRIDE
        ).delete(synchronize_session=False)

        # If session is finalised, revert official record to suggested_status
        if session.is_finalised:
            record = sa_session.query(AttendanceRecord).filter_by(
                session_id=session_id, student_id=student_id
            ).first()
            if record:
                record.status = rec.suggested_status
                # Determine if other flags remain
                remaining_flags = sa_session.query(AttendanceFlag).filter_by(
                    recommendation_id=rec.id
                ).count()
                record.flagged = remaining_flags > 0

        # Log audit trail
        audit = AttendanceAuditLog(
            session_id=session_id,
            student_id=student_id,
            user_id=user_id,
            action="RESET_OVERRIDE",
            previous_status=previous_status,
            new_status=rec.suggested_status,
            reason="Manual override reset to AI recommendation",
            details_json={"original_suggested_status": rec.suggested_status},
        )
        sa_session.add(audit)
        sa_session.commit()
        return rec
    except Exception:
        sa_session.rollback()
        raise


def finalize_session_attendance(
    session_id: int,
    user_id: int,
    notes: Optional[str] = None,
    batch_overrides: Optional[List[Dict[str, Any]]] = None,
    allow_unresolved: bool = False,
    db_session=None,
) -> AttendanceSession:
    """Finalise attendance for an entire session with atomic transaction safety.

    Guarantees:
      - Validates recommendation completion.
      - Applies any batch overrides requested atomically.
      - Guards against unresolved REVIEW_REQUIRED statuses unless explicitly allowed.
      - Synchronizes all student records in attendance_records atomically.
      - Sets session.is_finalised = True with timestamp and user metadata.
      - Records comprehensive audit trail.
      - Full rollback on any failure — never leaves partial attendance records.
    """
    sa_session = db_session or db.session

    session = sa_session.query(AttendanceSession).get(session_id)
    if not session:
        raise FinalisationError(f"Attendance session {session_id} not found")

    if session.recommendation_generation_status != RECOMMENDATION_STATUS_COMPLETED:
        raise FinalisationNotAllowed(
            f"Cannot finalise session: recommendation generation status is "
            f"'{session.recommendation_generation_status}', expected '{RECOMMENDATION_STATUS_COMPLETED}'"
        )

    recommendations = (
        sa_session.query(AttendanceRecommendation)
        .filter_by(session_id=session_id)
        .all()
    )
    if not recommendations:
        raise FinalisationNotAllowed(
            f"Cannot finalise session: no attendance recommendations exist for session {session_id}"
        )

    # Process any optional batch overrides before finalising
    if batch_overrides:
        rec_by_student = {r.student_id: r for r in recommendations}
        for item in batch_overrides:
            s_id = item.get("student_id")
            s_status = item.get("status")
            s_reason = item.get("reason", "Batch override during finalisation")
            if s_id in rec_by_student and s_status:
                norm_status = s_status.strip().upper()
                if norm_status not in VALID_OVERRIDE_STATUSES:
                    raise OverrideNotAllowed(f"Invalid status '{s_status}' in batch overrides")
                r = rec_by_student[s_id]
                prev = r.final_status if (r.is_overridden and r.final_status) else r.suggested_status
                r.final_status = norm_status
                r.is_overridden = True
                r.override_reason = s_reason.strip()
                r.overridden_by = user_id
                r.overridden_at = _utcnow()

                # Flag update
                flag = sa_session.query(AttendanceFlag).filter_by(
                    recommendation_id=r.id, flag_type=FLAG_FACULTY_OVERRIDE
                ).first()
                if flag:
                    flag.reason_text = s_reason.strip()
                else:
                    sa_session.add(
                        AttendanceFlag(
                            recommendation_id=r.id,
                            session_id=session_id,
                            student_id=s_id,
                            flag_type=FLAG_FACULTY_OVERRIDE,
                            source=FLAG_SOURCE_FACULTY,
                            reason_text=s_reason.strip(),
                        )
                    )
                # Audit log for override
                sa_session.add(
                    AttendanceAuditLog(
                        session_id=session_id,
                        student_id=s_id,
                        user_id=user_id,
                        action="OVERRIDE_STATUS",
                        previous_status=prev,
                        new_status=norm_status,
                        reason=s_reason.strip(),
                    )
                )

    # Check unresolved REVIEW_REQUIRED statuses
    unresolved = [
        r for r in recommendations
        if r.suggested_status == "REVIEW_REQUIRED" and not r.is_overridden
    ]
    if unresolved and not allow_unresolved:
        unresolved_ids = [r.student_id for r in unresolved]
        raise UnresolvedReviewRequiredError(
            f"Cannot finalise session with {len(unresolved)} unresolved REVIEW_REQUIRED "
            f"recommendation(s) (student IDs: {unresolved_ids}). Please provide manual overrides first "
            f"or set allow_unresolved=True.",
            unresolved_student_ids=unresolved_ids,
        )

    try:
        # Atomic synchronization of official AttendanceRecord rows
        for r in recommendations:
            status_to_commit = r.final_status if r.is_overridden else r.suggested_status
            r.final_status = status_to_commit

            record = sa_session.query(AttendanceRecord).filter_by(
                session_id=session_id, student_id=r.student_id
            ).first()

            has_flags = len(r.flags) > 0 if r.flags else False
            if record:
                record.status = status_to_commit
                record.flagged = has_flags
            else:
                record = AttendanceRecord(
                    session_id=session_id,
                    student_id=r.student_id,
                    status=status_to_commit,
                    flagged=has_flags,
                )
                sa_session.add(record)

            sa_session.flush()
            r.attendance_record_id = record.id

        session.is_finalised = True
        session.finalised_at = _utcnow()
        session.finalised_by = user_id
        session.finalisation_notes = notes.strip() if notes else None

        # Finalisation audit trail
        audit = AttendanceAuditLog(
            session_id=session_id,
            student_id=None,
            user_id=user_id,
            action="FINALIZE_SESSION",
            previous_status="PENDING_REVIEW",
            new_status="FINALISED",
            reason=notes.strip() if notes else "Session attendance finalised by faculty",
            details_json={
                "total_students": len(recommendations),
                "overridden_count": sum(1 for r in recommendations if r.is_overridden),
            },
        )
        sa_session.add(audit)
        sa_session.commit()
        return session
    except Exception:
        sa_session.rollback()
        raise


def get_session_audit_logs(session_id: int, db_session=None) -> List[Dict[str, Any]]:
    """Retrieve full audit history for a session in descending chronological order."""
    sa_session = db_session or db.session
    logs = (
        sa_session.query(AttendanceAuditLog)
        .filter_by(session_id=session_id)
        .order_by(AttendanceAuditLog.created_at.desc(), AttendanceAuditLog.id.desc())
        .all()
    )
    return [log.to_dict() for log in logs]
