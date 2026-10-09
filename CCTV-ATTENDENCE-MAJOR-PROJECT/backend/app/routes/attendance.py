from uuid import uuid4

from flask import Blueprint, current_app, g, jsonify, request

from ..extensions import db
from ..models.attendance import AttendanceSession
from ..models.classroom import Classroom
from ..services.attendance_service import start_processing
from ..utils.errors import DomainError
from ..utils.files import ALLOWED_VIDEO_EXTENSIONS, allowed_extension, save_upload
from ..utils.responses import success
from ..utils.security import require_roles
from ..utils.time import parse_datetime, utc_now

MAX_OBSERVATIONS_PER_PAGE = 200

bp = Blueprint("attendance", __name__)


def _allowed_classes(user):
    if user.role == "hod" and current_app.config.get("HOD_SEES_ALL"):
        return Classroom.query.all()
    return Classroom.query.filter_by(created_by=user.id).all()


def _get_session_or_error(session_id: int, user):
    session = AttendanceSession.query.get(session_id)
    if not session:
        return None, (jsonify({"error": "Session not found"}), 404)

    allowed = {cls.id for cls in _allowed_classes(user)}
    if session.class_id not in allowed:
        return None, (jsonify({"error": "Forbidden"}), 403)
    return session, None


@bp.post("/upload-video")
@require_roles("faculty", "hod")
def upload_video():
    if "video" not in request.files:
        return jsonify({"error": "Missing video file"}), 400

    class_id_raw = request.form.get("class_id")
    try:
        class_id = int(class_id_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid class_id"}), 400

    classroom = Classroom.query.get(class_id)
    if not classroom:
        return jsonify({"error": "Class not found"}), 404

    if g.current_user.role != "hod" and classroom.created_by != g.current_user.id:
        return jsonify({"error": "Forbidden"}), 403

    video_file = request.files["video"]
    if not video_file.filename or not allowed_extension(video_file.filename, ALLOWED_VIDEO_EXTENSIONS):
        return jsonify({"error": "Unsupported video format"}), 400

    video_path = save_upload(
        video_file,
        current_app.config["VIDEO_DIR"],
        prefix=f"class_{class_id}_{uuid4().hex}",
    )

    class_start_time = parse_datetime(request.form.get("class_start_time"))
    session_date = (class_start_time or utc_now()).date()

    session = AttendanceSession(
        class_id=class_id,
        uploaded_by=g.current_user.id,
        session_date=session_date,
        class_start_time=class_start_time,
        video_path=str(video_path),
        processing_status="pending",
        progress_pct=0,
    )
    db.session.add(session)
    db.session.commit()

    start_processing(session.id)

    return jsonify({"session_id": session.id}), 202


@bp.get("/sessions")
@require_roles("faculty", "hod")
def list_sessions():
    class_id = request.args.get("class_id", type=int)
    allowed_classes = _allowed_classes(g.current_user)
    allowed_ids = {cls.id for cls in allowed_classes}

    if class_id and class_id not in allowed_ids:
        return jsonify({"error": "Forbidden"}), 403

    query = AttendanceSession.query
    if class_id:
        query = query.filter_by(class_id=class_id)
    else:
        query = query.filter(AttendanceSession.class_id.in_(allowed_ids))

    sessions = query.order_by(AttendanceSession.created_at.desc()).all()
    return jsonify({"sessions": [session.to_dict() for session in sessions]})


def _recognition_eligibility_summary(class_id: int) -> dict:
    """Live eligibility summary for a class, using the exact same
    classifier the pipeline uses (recognition_eligibility.py) - so the
    API and the actual video-processing run never disagree about which
    students are eligible."""
    from ..services.recognition_eligibility import classify_enrolled_students
    from ..services.recognition_provider import get_provider
    from ..services.repositories import StudentRepository

    provider = get_provider()
    enrolled = StudentRepository(db.session).get_enrolled(class_id)
    eligible, ineligible = classify_enrolled_students(enrolled, provider)

    return {
        "recognition_eligible_count": len(eligible),
        "recognition_ineligible_count": len(ineligible),
        "students_requiring_reenrollment": sum(1 for d in ineligible if d["requires_reenrollment"]),
        "attendance_not_generated_count": len(ineligible),
        "ineligible_students": ineligible,
        "eligible_student_ids": [s.student_id for s in eligible],
    }


def _public_eligibility_fields(summary: dict) -> dict:
    """Strips internal-only keys (not meant for the plain
    get_session/get_session_status responses) before spreading into
    their JSON payload."""
    return {k: v for k, v in summary.items() if k != "eligible_student_ids"}


@bp.get("/sessions/<int:session_id>")
@require_roles("faculty", "hod")
def get_session(session_id: int):
    session, error = _get_session_or_error(session_id, g.current_user)
    if error:
        return error

    classroom = session.classroom
    records = []
    for record in session.records:
        records.append(
            {
                "id": record.id,
                "roll_number": record.student.roll_number,
                "name": record.student.name,
                "status": record.status,
                "flagged": record.flagged,
            }
        )

    return jsonify(
        {
            "session": session.to_dict(),
            "class": classroom.to_dict(),
            "records": records,
            **_public_eligibility_fields(_recognition_eligibility_summary(session.class_id)),
        }
    )


@bp.get("/sessions/<int:session_id>/status")
@require_roles("faculty", "hod")
def get_session_status(session_id: int):
    session, error = _get_session_or_error(session_id, g.current_user)
    if error:
        return error

    return jsonify(
        {
            "status": session.processing_status,
            "progress": session.progress_pct,
            "error": session.error_message,
            **_public_eligibility_fields(_recognition_eligibility_summary(session.class_id)),
        }
    )


@bp.get("/sessions/<int:session_id>/recognition-evidence")
@require_roles("faculty", "hod")
def get_recognition_evidence(session_id: int):
    """Phase 4 diagnostic view of face tracks and their voting
    outcomes for one session. Same RBAC as the rest of this blueprint:
    HOD sees any session, faculty only their own classes' sessions
    (_get_session_or_error already enforces this), students cannot
    reach this endpoint at all (not in @require_roles). Never exposes
    raw embeddings, images, or filesystem paths - see
    FaceTrack.to_diagnostic_dict()."""
    session, error = _get_session_or_error(session_id, g.current_user)
    if error:
        return error

    from ..services.observation_persistence import ObservationPersistence

    tracks = ObservationPersistence(db.session).get_tracks(session_id)

    summary = {
        "total_tracks": len(tracks),
        "confirmed_tracks": sum(1 for t in tracks if t.track_state == "CONFIRMED"),
        "unconfirmed_tracks": sum(1 for t in tracks if t.track_state in ("UNCONFIRMED", "CLOSED")),
        "unknown_tracks": sum(1 for t in tracks if t.track_state == "UNKNOWN"),
        "ambiguous_tracks": sum(1 for t in tracks if t.track_state == "AMBIGUOUS"),
        "identity_conflict_tracks": sum(1 for t in tracks if t.identity_conflict),
        "total_observations": sum(t.observation_count for t in tracks),
    }

    return success(
        {
            "session_id": session_id,
            "summary": summary,
            "tracks": [t.to_diagnostic_dict() for t in tracks],
        }
    )


@bp.get("/sessions/<int:session_id>/tracks/<int:track_id>/observations")
@require_roles("faculty", "hod")
def get_track_observations(session_id: int, track_id: int):
    """Paginated recognition observations for one track. Same
    authorization boundary as recognition-evidence above. Never
    exposes raw embeddings, images, or filesystem paths - see
    RecognitionObservation.to_safe_dict()."""
    session, error = _get_session_or_error(session_id, g.current_user)
    if error:
        return error

    from ..models.observation import FaceTrack

    track = FaceTrack.query.filter_by(id=track_id, session_id=session_id).first()
    if not track:
        raise DomainError("NOT_FOUND", "Track not found", 404)

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    if page < 1:
        raise DomainError("VALIDATION_ERROR", "page must be >= 1", 400)
    if per_page < 1:
        raise DomainError("VALIDATION_ERROR", "per_page must be >= 1", 400)
    per_page = min(per_page, MAX_OBSERVATIONS_PER_PAGE)

    from ..services.observation_persistence import ObservationPersistence

    items, total = ObservationPersistence(db.session).get_observations_page(session_id, track_id, page, per_page)

    return success(
        {
            "session_id": session_id,
            "track_id": track_id,
            "page": page,
            "per_page": per_page,
            "total": total,
            "observations": [o.to_safe_dict() for o in items],
        }
    )


def _presence_response(session: AttendanceSession) -> dict:
    """Builds the GET .../presence payload from persisted
    presence_windows rows plus the live eligibility summary - never
    re-running reconstruction itself (that only ever happens via the
    trigger endpoint or automatically post-EOF)."""
    from ..models.presence import PresenceWindow

    eligibility = _recognition_eligibility_summary(session.class_id)
    windows = (
        PresenceWindow.query.filter_by(session_id=session.id)
        .order_by(PresenceWindow.student_id, PresenceWindow.window_index)
        .all()
    )

    windows_by_student: dict[int, list] = {}
    for w in windows:
        windows_by_student.setdefault(w.student_id, []).append(w)

    student_summaries = []
    for student_id, student_windows in windows_by_student.items():
        total_presence = sum(w.total_duration_seconds for w in student_windows)
        valid_seconds = session.valid_duration_seconds
        percentage = None
        if valid_seconds and valid_seconds > 0:
            percentage = round(min(100.0, max(0.0, (total_presence / valid_seconds) * 100.0)), 4)
        confidences = [w.mean_confidence for w in student_windows if w.mean_confidence is not None]
        student_summaries.append(
            {
                "student_id": student_id,
                "eligible_for_reconstruction": True,
                "window_count": len(student_windows),
                "observation_count": sum(w.observation_count for w in student_windows),
                "observed_presence_seconds": sum(w.observed_duration_seconds for w in student_windows),
                "inferred_gap_seconds": sum(w.inferred_gap_seconds for w in student_windows),
                "total_presence_seconds": total_presence,
                "valid_session_seconds": valid_seconds,
                "presence_percentage": percentage,
                "first_confirmed_presence_seconds": student_windows[0].start_seconds,
                "last_confirmed_presence_seconds": student_windows[-1].end_seconds,
                "mean_confidence": (sum(confidences) / len(confidences)) if confidences else None,
                "algorithm_version": student_windows[0].algorithm_version,
                "windows": [w.to_dict() for w in student_windows],
            }
        )

    # Eligible students with zero windows (no trusted evidence at all)
    # still need an explicit zero-presence entry, not silent omission.
    covered_student_ids = set(windows_by_student.keys())
    for entry in eligibility.get("eligible_student_ids", []):
        if entry not in covered_student_ids:
            student_summaries.append(
                {
                    "student_id": entry,
                    "eligible_for_reconstruction": True,
                    "window_count": 0,
                    "observation_count": 0,
                    "observed_presence_seconds": 0.0,
                    "inferred_gap_seconds": 0.0,
                    "total_presence_seconds": 0.0,
                    "valid_session_seconds": session.valid_duration_seconds,
                    "presence_percentage": 0.0 if session.valid_duration_seconds else None,
                    "first_confirmed_presence_seconds": None,
                    "last_confirmed_presence_seconds": None,
                    "mean_confidence": None,
                    "algorithm_version": session.presence_algorithm_version,
                    "windows": [],
                }
            )

    return {
        "session_id": session.id,
        "reconstruction_status": session.presence_reconstruction_status,
        "reconstruction_error": session.presence_reconstruction_error,
        "actual_duration_seconds": session.actual_duration_seconds,
        "valid_duration_seconds": session.valid_duration_seconds,
        "algorithm_version": session.presence_algorithm_version,
        "reconstructed_at": (
            session.presence_reconstructed_at.isoformat() if session.presence_reconstructed_at else None
        ),
        # Reliability correction: any presence data reconstructed
        # before verified full-video completion evidence existed (or
        # for a session where that evidence is False/unavailable) may
        # still be shown here as historical/diagnostic evidence, but
        # is never sufficient on its own for an automatic attendance
        # recommendation - see attendance_decision_engine.py.
        "eof_reached": session.eof_reached,
        "insufficient_for_automatic_attendance": session.eof_reached is not True,
        "students": student_summaries,
        "ineligible_students": [
            {
                "student_id": d["student_id"],
                "eligible_for_reconstruction": False,
                "presence_calculated": False,
                "requires_reenrollment": d["requires_reenrollment"],
                "reason_code": d["reason_code"],
            }
            for d in eligibility["ineligible_students"]
        ],
    }


@bp.get("/sessions/<int:session_id>/presence")
@require_roles("faculty", "hod")
def get_session_presence(session_id: int):
    """Phase 5 explainable presence view. Same RBAC boundary as
    recognition-evidence: HOD any session, faculty only their own
    classes (_get_session_or_error enforces this), students never (not
    in @require_roles). Never exposes raw embeddings/images/paths -
    only aggregated durations, percentages, and window boundaries."""
    session, error = _get_session_or_error(session_id, g.current_user)
    if error:
        return error

    return success(_presence_response(session))


@bp.get("/sessions/<int:session_id>/students/<int:student_id>/presence")
@require_roles("faculty", "hod")
def get_student_session_presence(session_id: int, student_id: int):
    session, error = _get_session_or_error(session_id, g.current_user)
    if error:
        return error

    data = _presence_response(session)
    entry = next((s for s in data["students"] if s["student_id"] == student_id), None)
    if entry is None:
        entry = next((s for s in data["ineligible_students"] if s["student_id"] == student_id), None)
    if entry is None:
        raise DomainError("NOT_FOUND", "No presence data for this student in this session", 404)

    return success({"session_id": session_id, "student": entry})


@bp.post("/sessions/<int:session_id>/reconstruct-presence")
@require_roles("faculty", "hod")
def reconstruct_presence(session_id: int):
    """Manual re-run trigger. HOD or the owning faculty may trigger;
    the same _get_session_or_error boundary as every other endpoint in
    this blueprint denies anyone else (students are excluded entirely
    by @require_roles). Guarded against concurrent reconstruction of
    the same session by presence_service's own status check."""
    session, error = _get_session_or_error(session_id, g.current_user)
    if error:
        return error

    from ..services.presence_service import PresenceReconstructionNotAllowed, run_presence_reconstruction

    try:
        result = run_presence_reconstruction(session_id)
    except PresenceReconstructionNotAllowed as exc:
        raise DomainError("RECONSTRUCTION_NOT_ALLOWED", str(exc), 409)
    except Exception as exc:
        raise DomainError("RECONSTRUCTION_FAILED", "Presence reconstruction failed", 500) from exc

    return success(result, "Presence reconstruction complete")


@bp.post("/sessions/<int:session_id>/set-start-time")
@require_roles("faculty", "hod")
def set_start_time(session_id: int):
    session, error = _get_session_or_error(session_id, g.current_user)
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    class_start_time = parse_datetime(payload.get("class_start_time"))
    if not class_start_time:
        return jsonify({"error": "Invalid class_start_time"}), 400

    session.class_start_time = class_start_time
    session.session_date = class_start_time.date()
    db.session.commit()


# ===========================================================================
# Phase 6 - attendance policies, AI recommendations and independent flags
# ===========================================================================
#
# CRITICAL: every value returned by the routes below is an AI SUGGESTION,
# never a final/official attendance decision - see
# services/attendance_decision_engine.py's module docstring. Faculty
# review/finalisation does not exist yet (a later phase); nothing here
# writes to attendance_records.status or any "final_status" field.

import datetime as _dt


def _parse_date_only(value):
    if not value:
        return None
    try:
        return _dt.date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _policy_payload_from_request():
    payload = request.get_json(silent=True) or {}
    parsed = dict(payload)
    if "effective_from" in payload:
        parsed["effective_from"] = _parse_date_only(payload["effective_from"])
    if "effective_until" in payload:
        parsed["effective_until"] = _parse_date_only(payload["effective_until"])
    return parsed


@bp.get("/policies")
@require_roles("hod")
def list_policies():
    from ..models.attendance_policy import AttendancePolicy

    policies = AttendancePolicy.query.order_by(AttendancePolicy.id).all()
    return success({"policies": [p.to_dict() for p in policies]})


@bp.post("/policies")
@require_roles("hod")
def create_policy_route():
    from ..services.attendance_policy_service import create_policy

    payload = _policy_payload_from_request()
    policy = create_policy(payload, g.current_user.id)
    return success(policy.to_dict(), "Policy created")


@bp.get("/policies/<int:policy_id>")
@require_roles("hod")
def get_policy(policy_id: int):
    from ..models.attendance_policy import AttendancePolicy

    policy = AttendancePolicy.query.get(policy_id)
    if not policy:
        raise DomainError("NOT_FOUND", "Policy not found", 404)
    return success(policy.to_dict())


@bp.put("/policies/<int:policy_id>")
@require_roles("hod")
def update_policy_route(policy_id: int):
    from ..models.attendance_policy import AttendancePolicy
    from ..services.attendance_policy_service import update_policy

    policy = AttendancePolicy.query.get(policy_id)
    if not policy:
        raise DomainError("NOT_FOUND", "Policy not found", 404)

    payload = _policy_payload_from_request()
    policy = update_policy(policy, payload)
    return success(policy.to_dict(), "Policy updated")


@bp.put("/policies/<int:policy_id>/status")
@require_roles("hod")
def set_policy_status_route(policy_id: int):
    from ..models.attendance_policy import AttendancePolicy
    from ..services.attendance_policy_service import set_policy_active_status

    policy = AttendancePolicy.query.get(policy_id)
    if not policy:
        raise DomainError("NOT_FOUND", "Policy not found", 404)

    payload = request.get_json(silent=True) or {}
    if "is_active" not in payload:
        raise DomainError("VALIDATION_ERROR", "is_active is required", 400)

    policy = set_policy_active_status(policy, bool(payload["is_active"]))
    return success(policy.to_dict(), "Policy status updated")


@bp.get("/sessions/<int:session_id>/effective-policy")
@require_roles("faculty", "hod")
def get_effective_policy(session_id: int):
    """HOD or the owning faculty may view which policy would apply to
    this session right now - never a policy-editing capability for
    faculty (that stays HOD-only, enforced above by @require_roles on
    every /policies route)."""
    from ..services.policy_resolution import PolicyAmbiguousError, PolicyNotFoundError, resolve_policy

    session, error = _get_session_or_error(session_id, g.current_user)
    if error:
        return error

    classroom = session.classroom
    try:
        policy = resolve_policy(
            subject_id=classroom.subject_id, division_id=classroom.division_id,
            reference_date=session.session_date, db_session=db.session,
        )
    except PolicyNotFoundError:
        raise DomainError("POLICY_NOT_FOUND", "No applicable attendance policy could be resolved for this session", 404)
    except PolicyAmbiguousError as exc:
        raise DomainError("POLICY_AMBIGUOUS", str(exc), 409)

    return success({"session_id": session_id, "policy": policy.to_dict()})


@bp.post("/sessions/<int:session_id>/generate-recommendations")
@require_roles("faculty", "hod")
def generate_recommendations_route(session_id: int):
    """Manual (and, per attendance_service.py, automatic-after-EOF)
    trigger. Same RBAC boundary as every other endpoint in this
    blueprint; guarded against concurrent generation for the same
    session by attendance_recommendation_service's own status check."""
    session, error = _get_session_or_error(session_id, g.current_user)
    if error:
        return error

    from ..services.attendance_recommendation_service import (
        RecommendationGenerationNotAllowed,
        generate_session_recommendations,
    )

    try:
        result = generate_session_recommendations(session_id)
    except RecommendationGenerationNotAllowed as exc:
        raise DomainError("GENERATION_NOT_ALLOWED", str(exc), 409)
    except Exception as exc:
        raise DomainError("GENERATION_FAILED", "Recommendation generation failed", 500) from exc

    return success(result, "Recommendation generation complete")


def _recommendations_response(session):
    from ..models.attendance_recommendation import AttendanceRecommendation

    recommendations = (
        AttendanceRecommendation.query.filter_by(session_id=session.id)
        .order_by(AttendanceRecommendation.student_id)
        .all()
    )
    return {
        "session_id": session.id,
        "is_finalised": session.is_finalised,
        "finalised_at": session.finalised_at.isoformat() if session.finalised_at else None,
        "finalised_by": session.finalised_by,
        "finalisation_notes": session.finalisation_notes,
        "recommendation_generation_status": session.recommendation_generation_status,
        "recommendation_generation_error": session.recommendation_generation_error,
        "recommendation_generated_at": (
            session.recommendation_generated_at.isoformat() if session.recommendation_generated_at else None
        ),
        "recommendations": [r.to_dict() for r in recommendations],
    }


@bp.get("/sessions/<int:session_id>/recommendations")
@require_roles("faculty", "hod")
def get_recommendations(session_id: int):
    session, error = _get_session_or_error(session_id, g.current_user)
    if error:
        return error

    return success(_recommendations_response(session))


@bp.get("/sessions/<int:session_id>/students/<int:student_id>/recommendation")
@require_roles("faculty", "hod")
def get_student_recommendation(session_id: int, student_id: int):
    session, error = _get_session_or_error(session_id, g.current_user)
    if error:
        return error

    data = _recommendations_response(session)
    entry = next((r for r in data["recommendations"] if r["student_id"] == student_id), None)
    if entry is None:
        raise DomainError("NOT_FOUND", "No recommendation for this student in this session", 404)

    return success({"session_id": session_id, "recommendation": entry})


# ===========================================================================
# Phase 7 - faculty review, manual overrides, and transaction-safe finalisation
# ===========================================================================

@bp.post("/sessions/<int:session_id>/students/<int:student_id>/override")
@require_roles("faculty", "hod")
def override_student_route(session_id: int, student_id: int):
    """Faculty or HOD sets a manual attendance override with mandatory reason logging."""
    session, error = _get_session_or_error(session_id, g.current_user)
    if error:
        return error

    from ..services.attendance_finalisation_service import (
        FinalisationError,
        OverrideNotAllowed,
        override_student_attendance,
    )

    payload = request.get_json(silent=True) or {}
    status = payload.get("status")
    reason = payload.get("reason")

    try:
        rec = override_student_attendance(
            session_id=session.id,
            student_id=student_id,
            status=status,
            reason=reason,
            user_id=g.current_user.id,
        )
    except OverrideNotAllowed as exc:
        raise DomainError("VALIDATION_ERROR", str(exc), 400)
    except FinalisationError as exc:
        raise DomainError("OVERRIDE_FAILED", str(exc), 404)
    except Exception as exc:
        raise DomainError("OVERRIDE_ERROR", "Failed to apply manual override", 500) from exc

    return success(rec.to_dict(), "Manual override applied successfully")


@bp.delete("/sessions/<int:session_id>/students/<int:student_id>/override")
@require_roles("faculty", "hod")
def reset_student_override_route(session_id: int, student_id: int):
    """Faculty or HOD resets a manual attendance override back to AI recommendation."""
    session, error = _get_session_or_error(session_id, g.current_user)
    if error:
        return error

    from ..services.attendance_finalisation_service import (
        FinalisationError,
        reset_student_override,
    )

    try:
        rec = reset_student_override(
            session_id=session.id,
            student_id=student_id,
            user_id=g.current_user.id,
        )
    except FinalisationError as exc:
        raise DomainError("RESET_FAILED", str(exc), 404)
    except Exception as exc:
        raise DomainError("RESET_ERROR", "Failed to reset manual override", 500) from exc

    return success(rec.to_dict(), "Manual override reset successfully")


@bp.post("/sessions/<int:session_id>/finalize")
@bp.post("/sessions/<int:session_id>/finalise")
@require_roles("faculty", "hod")
def finalize_session_route(session_id: int):
    """Transaction-safe atomic finalisation of session attendance into official records."""
    session, error = _get_session_or_error(session_id, g.current_user)
    if error:
        return error

    from ..services.attendance_finalisation_service import (
        FinalisationError,
        FinalisationNotAllowed,
        OverrideNotAllowed,
        UnresolvedReviewRequiredError,
        finalize_session_attendance,
    )

    payload = request.get_json(silent=True) or {}
    notes = payload.get("notes")
    batch_overrides = payload.get("overrides")
    allow_unresolved = bool(payload.get("allow_unresolved", False))

    try:
        finalised_session = finalize_session_attendance(
            session_id=session.id,
            user_id=g.current_user.id,
            notes=notes,
            batch_overrides=batch_overrides,
            allow_unresolved=allow_unresolved,
        )
    except UnresolvedReviewRequiredError as exc:
        raise DomainError(
            "UNRESOLVED_REVIEW_REQUIRED",
            str(exc),
            400,
        )
    except FinalisationNotAllowed as exc:
        raise DomainError("FINALISATION_NOT_ALLOWED", str(exc), 409)
    except OverrideNotAllowed as exc:
        raise DomainError("VALIDATION_ERROR", str(exc), 400)
    except FinalisationError as exc:
        raise DomainError("FINALISATION_FAILED", str(exc), 400)
    except Exception as exc:
        raise DomainError("FINALISATION_ERROR", "Failed to finalise attendance session", 500) from exc

    return success(finalised_session.to_dict(), "Attendance finalised successfully")


@bp.get("/sessions/<int:session_id>/audit-logs")
@require_roles("faculty", "hod")
def get_session_audit_logs_route(session_id: int):
    """Retrieve full audit trail of overrides and finalisation actions for a session."""
    session, error = _get_session_or_error(session_id, g.current_user)
    if error:
        return error

    from ..services.attendance_finalisation_service import get_session_audit_logs

    logs = get_session_audit_logs(session.id)
    return success({"session_id": session.id, "audit_logs": logs})


# ===========================================================================
# Phase 8 - At-Risk & Shortage Prediction Engine Endpoints
# ===========================================================================

@bp.get("/classes/<int:class_id>/at-risk")
@require_roles("faculty", "hod")
def get_class_at_risk_route(class_id: int):
    """Retrieve at-risk and shortage predictions for all students in a classroom."""
    allowed_classes = _allowed_classes(g.current_user)
    allowed_ids = {cls.id for cls in allowed_classes}
    if class_id not in allowed_ids:
        return jsonify({"error": "Forbidden"}), 403

    from ..services.risk_scoring_service import calculate_class_at_risk_students

    threshold = request.args.get("threshold", type=float)
    risk_level = request.args.get("risk_level")
    only_finalised = request.args.get("only_finalised", "false").lower() in ("true", "1")

    try:
        result = calculate_class_at_risk_students(
            class_id=class_id,
            threshold=threshold,
            risk_level_filter=risk_level,
            only_finalised=only_finalised,
        )
    except ValueError as exc:
        raise DomainError("NOT_FOUND", str(exc), 404)
    except Exception as exc:
        raise DomainError("RISK_EVALUATION_ERROR", "Failed to compute at-risk attendance metrics", 500) from exc

    return success(result)


@bp.get("/subjects/<int:subject_id>/at-risk")
@require_roles("faculty", "hod")
def get_subject_at_risk_route(subject_id: int):
    """Retrieve at-risk and shortage predictions across all classes for an academic subject."""
    from ..utils.security import faculty_has_assignment

    if g.current_user.role != "hod" and not faculty_has_assignment(
        g.current_user.id, subject_id=subject_id
    ):
        raise DomainError("NOT_FOUND", "Subject not found", 404)

    from ..services.risk_scoring_service import calculate_subject_at_risk_students

    division_id = request.args.get("division_id", type=int)
    threshold = request.args.get("threshold", type=float)
    risk_level = request.args.get("risk_level")
    only_finalised = request.args.get("only_finalised", "false").lower() in ("true", "1")

    try:
        result = calculate_subject_at_risk_students(
            subject_id=subject_id,
            division_id=division_id,
            threshold=threshold,
            risk_level_filter=risk_level,
            only_finalised=only_finalised,
        )
    except ValueError as exc:
        raise DomainError("NOT_FOUND", str(exc), 404)
    except Exception as exc:
        raise DomainError("RISK_EVALUATION_ERROR", "Failed to compute at-risk subject metrics", 500) from exc

    return success(result)


@bp.get("/students/<int:student_id>/risk-profile")
@require_roles("faculty", "hod", "student")
def get_student_risk_profile_route(student_id: int):
    """Retrieve comprehensive risk profile, streak analytics, and session history for a student."""
    from ..models.student import Student
    from ..services.risk_scoring_service import calculate_student_risk_profile

    student = Student.query.get(student_id)
    if not student:
        raise DomainError("NOT_FOUND", "Student not found", 404)

    if g.current_user.role == "student":
        if student.user_id != g.current_user.id:
            return jsonify({"error": "Forbidden"}), 403
    elif g.current_user.role == "faculty":
        allowed_classes = _allowed_classes(g.current_user)
        allowed_ids = {cls.id for cls in allowed_classes}
        if student.class_id not in allowed_ids:
            return jsonify({"error": "Forbidden"}), 403

    class_id = request.args.get("class_id", type=int)
    threshold = request.args.get("threshold", type=float)
    only_finalised = request.args.get("only_finalised", "false").lower() in ("true", "1")

    try:
        profile = calculate_student_risk_profile(
            student_id=student.id,
            class_id=class_id,
            threshold=threshold,
            only_finalised=only_finalised,
        )
    except ValueError as exc:
        raise DomainError("NOT_FOUND", str(exc), 404)
    except Exception as exc:
        raise DomainError("RISK_EVALUATION_ERROR", "Failed to compute student risk profile", 500) from exc

    return success(profile)


@bp.get("/at-risk/overview")
@require_roles("faculty", "hod")
def get_at_risk_overview_route():
    """Retrieve aggregated at-risk dashboard summary across all accessible classrooms."""
    from ..services.risk_scoring_service import get_at_risk_dashboard_overview

    threshold = request.args.get("threshold", type=float)
    only_finalised = request.args.get("only_finalised", "false").lower() in ("true", "1")

    try:
        overview = get_at_risk_dashboard_overview(
            g.current_user,
            threshold=threshold,
            only_finalised=only_finalised,
        )
    except Exception as exc:
        raise DomainError("RISK_EVALUATION_ERROR", "Failed to generate at-risk overview", 500) from exc

    return success(overview)

