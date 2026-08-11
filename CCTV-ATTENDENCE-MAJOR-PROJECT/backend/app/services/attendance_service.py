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

        try:
            pipeline = CctvAttendancePipeline(
                student_repo=StudentRepository(db.session),
                attendance_repo=AttendanceRepository(db.session),
                frame_interval=float(app.config.get("FRAME_SAMPLE_EVERY", 2.0)),
                match_threshold=float(app.config.get("MATCH_THRESHOLD", 0.55)),
                grace_period_minutes=session.classroom.grace_period_minutes,
            )

            results = pipeline.run(
                video_path=session.video_path,
                class_id=session.class_id,
                session_id=session.id,
                class_start_time=session.class_start_time.isoformat() if session.class_start_time else None
            )

            if "error" in results and results["error"]:
                session.processing_status = "error"
                session.error_message = results["error"]
                db.session.commit()
                return

            session.processing_status = "done"
            session.progress_pct = 100
            if not session.class_start_time:
                session.class_start_time = session.created_at or utc_now()
            if not session.session_date:
                session.session_date = (session.class_start_time or utc_now()).date()
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            session.processing_status = "error"
            session.error_message = str(exc)
            db.session.commit()
