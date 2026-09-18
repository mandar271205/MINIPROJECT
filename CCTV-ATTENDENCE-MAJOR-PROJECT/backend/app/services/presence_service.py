"""Phase 5 - orchestrates presence reconstruction for one session:
resolves the video-duration denominator, loads eligible/ineligible
students (reusing the exact Phase 3 classifier - never re-derived with
different logic), runs reconstruction, and persists the result.

Called from two places only:
  1. attendance_service.py, automatically, right after a video-
     processing job completes successfully and reaches EOF.
  2. routes/attendance.py's POST .../reconstruct-presence, a manual
     re-run trigger, gated by the same completed+EOF requirement.
"""

from __future__ import annotations

import cv2
from flask import current_app

from ..extensions import db
from ..models.attendance import (
    PRESENCE_STATUS_COMPLETED,
    PRESENCE_STATUS_PARTIAL_EVIDENCE,
    PRESENCE_STATUS_PROCESSING,
    AttendanceSession,
)
from .presence_persistence import mark_reconstruction_failed, mark_reconstruction_processing, replace_session_presence
from .presence_reconstruction import reconstruct_session_presence
from .recognition_eligibility import classify_enrolled_students
from .recognition_provider import get_provider
from .repositories import StudentRepository


class PresenceReconstructionNotAllowed(RuntimeError):
    """Raised when reconstruction is requested in a state where it
    must not run (job not done, EOF not reached, already running)."""


def _resolve_video_duration_seconds(video_path: str) -> float | None:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        cap.release()
        return None
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    cap.release()
    if total_frames <= 0:
        return None
    return total_frames / fps


def run_presence_reconstruction(
    session_id: int, *, eof_reached: bool | None = None, video_duration_seconds: float | None = None
) -> dict:
    """Runs Phase 5 presence reconstruction for one session.

    Raises PresenceReconstructionNotAllowed (never runs anything) when:
      - the session doesn't exist
      - the video-processing job did not complete successfully
      - the caller reports EOF was not reached
      - a reconstruction is already in progress for this session

    Any failure once reconstruction has started is recorded on the
    session (status=FAILED, error message) and re-raised - the
    previous successful set of presence_windows rows, if any, is left
    completely untouched (see presence_persistence.replace_session_presence,
    which validates every new row before deleting anything old).
    """
    session = AttendanceSession.query.get(session_id)
    if not session:
        raise PresenceReconstructionNotAllowed("Session not found")

    if session.processing_status != "done":
        raise PresenceReconstructionNotAllowed(
            "Presence reconstruction requires the video processing job to have completed successfully"
        )

    if eof_reached is False:
        raise PresenceReconstructionNotAllowed(
            "Presence reconstruction requires the full video to have reached EOF"
        )

    if session.presence_reconstruction_status == PRESENCE_STATUS_PROCESSING:
        raise PresenceReconstructionNotAllowed("Presence reconstruction is already running for this session")

    mark_reconstruction_processing(session)

    try:
        duration = video_duration_seconds
        if duration is None:
            duration = session.actual_duration_seconds
        if duration is None:
            duration = _resolve_video_duration_seconds(session.video_path)

        if duration is None or duration <= 0:
            mark_reconstruction_failed(
                session,
                "Video duration is unavailable or zero; presence percentage cannot be computed safely.",
            )
            return {"status": session.presence_reconstruction_status, "error": session.presence_reconstruction_error}

        cfg = current_app.config
        half_width = float(cfg["PRESENCE_EVIDENCE_HALF_WIDTH_SECONDS"])
        max_bridge_gap = float(cfg["PRESENCE_MAX_BRIDGE_GAP_SECONDS"])
        algorithm_version = str(cfg["PRESENCE_ALGORITHM_VERSION"])

        provider = get_provider()
        enrolled = StudentRepository(db.session).get_enrolled(session.class_id)
        eligible, ineligible = classify_enrolled_students(enrolled, provider)

        result = reconstruct_session_presence(
            session_id=session.id,
            eligible_students=eligible,
            ineligible_diagnostics=ineligible,
            session_start=0.0,
            session_end=duration,
            half_width=half_width,
            max_bridge_gap=max_bridge_gap,
            algorithm_version=algorithm_version,
        )

        window_rows: list[dict] = []
        for student_id, windows in result["windows_by_student"].items():
            for w in windows:
                window_rows.append(
                    {
                        "student_id": student_id,
                        "window_index": w.window_index,
                        "start_seconds": w.start_seconds,
                        "end_seconds": w.end_seconds,
                        "observed_duration_seconds": w.observed_duration_seconds,
                        "inferred_gap_seconds": w.inferred_gap_seconds,
                        "total_duration_seconds": w.total_duration_seconds,
                        "observation_count": w.observation_count,
                        "contributing_track_count": w.contributing_track_count,
                        "mean_confidence": w.mean_confidence,
                        "minimum_confidence": w.minimum_confidence,
                        "maximum_confidence": w.maximum_confidence,
                        "algorithm_version": algorithm_version,
                        "reconstruction_metadata": {
                            "evidence_half_width_seconds": half_width,
                            "max_bridge_gap_seconds": max_bridge_gap,
                            "excluded_conflicting_tracks": result["excluded_conflicting_tracks"],
                            "algorithm_version": algorithm_version,
                        },
                    }
                )

        has_eligible_without_evidence = any(
            s["eligible_for_reconstruction"] and s["window_count"] == 0 for s in result["summaries"]
        )
        status = PRESENCE_STATUS_PARTIAL_EVIDENCE if (eligible and has_eligible_without_evidence) else PRESENCE_STATUS_COMPLETED

        replace_session_presence(
            session,
            window_rows=window_rows,
            actual_duration_seconds=duration,
            valid_duration_seconds=duration,
            algorithm_version=algorithm_version,
            status=status,
        )

        return {"status": status, "summaries": result["summaries"]}
    except Exception as exc:
        db.session.rollback()
        mark_reconstruction_failed(session, str(exc))
        raise
