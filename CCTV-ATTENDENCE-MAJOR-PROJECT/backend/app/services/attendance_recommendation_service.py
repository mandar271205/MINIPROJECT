"""Phase 6 - orchestrates AI attendance-recommendation generation for
one session: resolves the applicable policy, loads eligibility and
reconstructed presence evidence (Phase 3/4/5 outputs - never
re-derived with different logic), evaluates every rostered student
through attendance_decision_engine.evaluate_student(), and persists
the result transactionally.

CRITICAL SEPARATION (see Phase 6 PRD section C): this produces an
AI-SUGGESTED status only. It never writes to the legacy
`attendance_records.status` column and there is no `final_status`
anywhere in this codebase yet - faculty review/finalisation is a
later phase. UI and API consumers must always present this output as
"AI recommendation - pending faculty review", never as official
attendance.

Called from two places only:
  1. routes/attendance.py's POST .../generate-recommendations (manual
     trigger, gated by presence reconstruction having produced a
     usable result).
  2. Optionally, automatically after presence reconstruction succeeds
     (see attendance_service.py) - a recommendation-generation
     failure is recorded on the session and must never corrupt the
     presence_windows rows it reads from.
"""

from __future__ import annotations

from ..extensions import db
from ..models.attendance import (
    AttendanceRecord,
    AttendanceSession,
    RECOMMENDATION_GENERATION_COMPLETED,
    RECOMMENDATION_GENERATION_PROCESSING,
)
from ..models.observation import FaceTrack
from ..models.presence import PresenceWindow
from .attendance_decision_engine import (
    DECISION_VERSION,
    REASON_POLICY_UNRESOLVED,
    STATUS_REVIEW_REQUIRED,
    SessionEvidenceContext,
    StudentEvidence,
    evaluate_student,
)
from .policy_resolution import PolicyResolutionError, resolve_policy, to_decision_policy
from .recognition_eligibility import classify_enrolled_students
from .recognition_provider import get_provider
from .recommendation_persistence import mark_generation_failed, mark_generation_processing, replace_session_recommendations
from .repositories import StudentRepository


class RecommendationGenerationNotAllowed(RuntimeError):
    """Raised when recommendation generation is requested in a state
    where it must not run (session missing, presence reconstruction
    not usable yet, already running)."""


_POLICY_UNRESOLVED_REASON_TEXT = "Attendance could not be evaluated automatically because no applicable attendance policy could be resolved for this session."


def _load_presence_summary_by_student(session_id: int) -> dict[int, dict]:
    windows = (
        PresenceWindow.query.filter_by(session_id=session_id)
        .order_by(PresenceWindow.student_id, PresenceWindow.window_index)
        .all()
    )
    by_student: dict[int, list[PresenceWindow]] = {}
    for w in windows:
        by_student.setdefault(w.student_id, []).append(w)

    summaries: dict[int, dict] = {}
    for student_id, student_windows in by_student.items():
        confidences = [w.mean_confidence for w in student_windows if w.mean_confidence is not None]
        summaries[student_id] = {
            "presence_duration_seconds": sum(w.total_duration_seconds for w in student_windows),
            "window_count": len(student_windows),
            "windows": [(w.start_seconds, w.end_seconds) for w in student_windows],
            "first_confirmed_presence_seconds": student_windows[0].start_seconds,
            "last_confirmed_presence_seconds": student_windows[-1].end_seconds,
            "mean_confidence": (sum(confidences) / len(confidences)) if confidences else None,
        }
    return summaries


def _load_identity_conflict_counts(session_id: int) -> dict[int, int]:
    conflicted = FaceTrack.query.filter_by(session_id=session_id, identity_conflict=True).all()
    counts: dict[int, int] = {}
    for track in conflicted:
        if track.confirmed_student_id is not None:
            counts[track.confirmed_student_id] = counts.get(track.confirmed_student_id, 0) + 1
    return counts


def _load_attendance_record_ids(session_id: int) -> dict[int, int]:
    records = AttendanceRecord.query.filter_by(session_id=session_id).all()
    return {r.student_id: r.id for r in records}


def generate_session_recommendations(session_id: int) -> dict:
    """Evaluates every rostered student for *session_id* and persists
    exactly one AttendanceRecommendation row per student. Raises
    RecommendationGenerationNotAllowed (never runs anything) when the
    session doesn't exist, presence reconstruction hasn't produced a
    usable result yet, or generation is already running for this
    session."""
    session = AttendanceSession.query.get(session_id)
    if not session:
        raise RecommendationGenerationNotAllowed("Session not found")

    if session.presence_reconstruction_status not in ("COMPLETED", "PARTIAL_EVIDENCE"):
        raise RecommendationGenerationNotAllowed(
            "Recommendation generation requires presence reconstruction to have completed"
        )

    if session.recommendation_generation_status == RECOMMENDATION_GENERATION_PROCESSING:
        raise RecommendationGenerationNotAllowed("Recommendation generation is already running for this session")

    mark_generation_processing(session)

    try:
        classroom = session.classroom
        provider = get_provider()
        enrolled = StudentRepository(db.session).get_enrolled(session.class_id)
        eligible, ineligible = classify_enrolled_students(enrolled, provider)

        presence_by_student = _load_presence_summary_by_student(session.id)
        conflict_counts = _load_identity_conflict_counts(session.id)
        record_ids = _load_attendance_record_ids(session.id)

        # Reliability correction: the session's own PERSISTED
        # eof_reached column is passed straight through, three-valued,
        # to the decision engine - True permits normal evaluation,
        # False and NULL (missing/legacy proof) both become
        # REVIEW_REQUIRED (see attendance_decision_engine.evaluate_student).
        # NULL is never treated as True.
        session_context = SessionEvidenceContext(
            eof_reached=session.eof_reached,
            presence_reconstruction_status=session.presence_reconstruction_status,
            valid_session_seconds=session.valid_duration_seconds,
        )

        try:
            policy_row = resolve_policy(
                subject_id=classroom.subject_id, division_id=classroom.division_id,
                reference_date=session.session_date, db_session=db.session,
            )
            decision_policy = to_decision_policy(policy_row)
            policy_snapshot = decision_policy.to_snapshot()
        except PolicyResolutionError:
            policy_row = None
            decision_policy = None
            policy_snapshot = None

        rows: list[dict] = []
        for student in eligible:
            presence = presence_by_student.get(student.student_id, {})
            evidence = StudentEvidence(
                student_id=student.student_id,
                eligible_for_recognition=True,
                presence_percentage=(
                    min(100.0, max(0.0, (presence["presence_duration_seconds"] / session.valid_duration_seconds) * 100.0))
                    if presence and session.valid_duration_seconds
                    else (0.0 if session.valid_duration_seconds else None)
                ),
                presence_duration_seconds=presence.get("presence_duration_seconds", 0.0),
                window_count=presence.get("window_count", 0),
                windows=presence.get("windows", []),
                first_confirmed_presence_seconds=presence.get("first_confirmed_presence_seconds"),
                last_confirmed_presence_seconds=presence.get("last_confirmed_presence_seconds"),
                mean_confidence=presence.get("mean_confidence"),
                identity_conflict_track_count=conflict_counts.get(student.student_id, 0),
            )

            if decision_policy is None:
                rows.append(
                    _policy_unresolved_row(student.student_id, record_ids.get(student.student_id))
                )
                continue

            result = evaluate_student(evidence, decision_policy, session_context)
            rows.append(_result_to_row(result, record_ids.get(student.student_id), policy_row, policy_snapshot))

        for diagnostic in ineligible:
            evidence = StudentEvidence(
                student_id=diagnostic["student_id"], eligible_for_recognition=False,
                ineligible_reason_code=diagnostic.get("reason_code"),
            )
            if decision_policy is None:
                rows.append(
                    _policy_unresolved_row(diagnostic["student_id"], record_ids.get(diagnostic["student_id"]))
                )
                continue
            result = evaluate_student(evidence, decision_policy, session_context)
            rows.append(_result_to_row(result, record_ids.get(diagnostic["student_id"]), policy_row, policy_snapshot))

        created = replace_session_recommendations(
            session, recommendation_rows=rows, status=RECOMMENDATION_GENERATION_COMPLETED,
        )
        return {
            "status": RECOMMENDATION_GENERATION_COMPLETED,
            "recommendations": [r.to_dict() for r in created],
        }
    except Exception as exc:
        db.session.rollback()
        mark_generation_failed(session, str(exc))
        raise


def _policy_unresolved_row(student_id: int, attendance_record_id: int | None) -> dict:
    return {
        "student_id": student_id,
        "attendance_record_id": attendance_record_id,
        "suggested_status": STATUS_REVIEW_REQUIRED,
        "reason_code": REASON_POLICY_UNRESOLVED,
        "reason_text": _POLICY_UNRESOLVED_REASON_TEXT,
        "explanation_json": {"suggested_status": STATUS_REVIEW_REQUIRED, "reason_code": REASON_POLICY_UNRESOLVED, "flags": []},
        "policy_id": None,
        "policy_snapshot_json": None,
        "decision_version": DECISION_VERSION,
        "decision_confidence": None,
        "decision_is_evaluable": False,
        "presence_percentage_snapshot": None,
        "presence_duration_seconds_snapshot": None,
        "valid_session_seconds_snapshot": None,
        "flags": [],
    }


def _result_to_row(result, attendance_record_id, policy_row, policy_snapshot) -> dict:
    return {
        "student_id": result.student_id,
        "attendance_record_id": attendance_record_id,
        "suggested_status": result.suggested_status,
        "reason_code": result.reason_code,
        "reason_text": result.reason_text,
        "explanation_json": result.explanation,
        "policy_id": policy_row.id if policy_row is not None else None,
        "policy_snapshot_json": policy_snapshot,
        "decision_version": DECISION_VERSION,
        "decision_confidence": result.confidence if result.confidence is not None and result.confidence == result.confidence else None,
        "decision_is_evaluable": result.is_evaluable,
        "presence_percentage_snapshot": result.explanation.get("presence_percentage"),
        "presence_duration_seconds_snapshot": result.explanation.get("presence_duration_seconds"),
        "valid_session_seconds_snapshot": result.explanation.get("valid_session_seconds"),
        "flags": result.flags,
    }
