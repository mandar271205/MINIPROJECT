from __future__ import annotations

import threading

from flask import current_app

from ..extensions import db



def start_processing(session_id: int) -> None:
    app = current_app._get_current_object()
    thread = threading.Thread(target=_process_session, args=(app, session_id), daemon=True)
    thread.start()


def _process_session(app, session_id: int) -> None:
    from .pipeline import CctvAttendancePipeline
    from .repositories import StudentRepository, AttendanceRepository
    from ..utils.time import utc_now
    from ..models.attendance import AttendanceSession
    from ..extensions import db

    with app.app_context():
        session = AttendanceSession.query.get(session_id)
        if not session:
            return

        session.processing_status = "processing"
        session.progress_pct = 0
        session.error_message = None
        db.session.commit()

        # --- Live progress callback: update DB every few % ---
        _last_reported = [0]

        def _progress(pct: int) -> None:
            if pct - _last_reported[0] >= 5:          # update every 5%
                _last_reported[0] = pct
                try:
                    s = db.session.get(AttendanceSession, session_id)
                    if s:
                        s.progress_pct = pct
                        db.session.commit()
                except Exception:
                    db.session.rollback()

        try:
            from .observation_persistence import ObservationPersistence

            pipeline = CctvAttendancePipeline(
                student_repo=StudentRepository(db.session),
                attendance_repo=AttendanceRepository(db.session),
                observation_persistence=ObservationPersistence(db.session),
                frame_interval=float(app.config["FRAME_SAMPLE_INTERVAL_SECONDS"]),
                match_threshold=float(app.config["FACE_MATCH_THRESHOLD"]),
                grace_period_minutes=session.classroom.grace_period_minutes,
                track_max_gap_seconds=float(app.config["TRACK_MAX_GAP_SECONDS"]),
                track_min_iou=float(app.config["TRACK_MIN_IOU"]),
                track_max_centroid_distance=float(app.config["TRACK_MAX_CENTROID_DISTANCE"]),
                track_close_after_seconds=float(app.config["TRACK_CLOSE_AFTER_SECONDS"]),
                identity_vote_window_size=int(app.config["IDENTITY_VOTE_WINDOW_SIZE"]),
                identity_min_support=int(app.config["IDENTITY_MIN_SUPPORT"]),
                identity_min_support_ratio=float(app.config["IDENTITY_MIN_SUPPORT_RATIO"]),
                identity_min_mean_confidence=float(app.config["IDENTITY_MIN_MEAN_CONFIDENCE"]),
                identity_min_margin=float(app.config["IDENTITY_MIN_MARGIN"]),
                identity_conflict_support=int(app.config["IDENTITY_CONFLICT_SUPPORT"]),
            )

            results = pipeline.run(
                video_path=session.video_path,
                class_id=session.class_id,
                session_id=session.id,
                class_start_time=session.class_start_time.isoformat() if session.class_start_time else None,
                progress_callback=_progress,
            )

            if "error" in results and results["error"]:
                # Never reports "done"/100% on failure - the pipeline
                # itself does not persist any decisions in this branch.
                session.processing_status = "error"
                session.error_message = results["error"]
                db.session.commit()
                return

            # Progress only reaches 100 here, after save_decisions()
            # already ran inside pipeline.run() and the video's actual
            # EOF was reached (diagnostics["eof_reached"] is True).
            session.processing_status = "done"
            session.progress_pct = 100
            if not session.class_start_time:
                session.class_start_time = session.created_at or utc_now()
            if not session.session_date:
                session.session_date = (session.class_start_time or utc_now()).date()
            db.session.commit()

            # Phase 5: presence reconstruction only ever runs after the
            # legacy job above has already committed as "done" and the
            # pipeline's own diagnostics confirm EOF was reached. A
            # reconstruction failure is recorded on the session by
            # presence_service itself and must never flip the
            # already-successful video-processing status back to
            # "error" - the two are independent processing states.
            diagnostics = results.get("diagnostics") or {}
            try:
                from .presence_service import run_presence_reconstruction

                run_presence_reconstruction(
                    session.id,
                    eof_reached=diagnostics.get("eof_reached"),
                    video_duration_seconds=diagnostics.get("video_duration_sec"),
                )
            except Exception:
                current_app.logger.exception(
                    "Presence reconstruction failed for session %d (video processing itself succeeded)",
                    session.id,
                )
        except Exception as exc:
            db.session.rollback()
            session.processing_status = "error"
            session.error_message = str(exc)
            db.session.commit()

