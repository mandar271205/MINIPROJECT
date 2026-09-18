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
    }


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
            **_recognition_eligibility_summary(session.class_id),
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
            **_recognition_eligibility_summary(session.class_id),
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

    return jsonify({"session": session.to_dict()})
