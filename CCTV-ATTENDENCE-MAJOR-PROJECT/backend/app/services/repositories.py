"""Data-access helpers used by the architecture pipeline.

Provides functions to read enrolled student embeddings from the database
and persist attendance results. Uses SQLAlchemy models from the main app.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from .models import AttendanceDecision, EnrolledStudent, FirstAppearance


class StudentRepository:
    """
    Read enrolled students and their embeddings from the database.
    """

    def __init__(self, db_session) -> None:
        self._session = db_session

    def get_enrolled(self, class_id: int) -> list[EnrolledStudent]:
        """
        Return all students for *class_id* that have a stored embedding,
        tagged with the exact model id/dimension it was generated with.
        Compatibility filtering happens downstream (see
        recognition_provider.InsightFaceArcFaceProvider.is_compatible());
        this method never decides compatibility itself.
        """
        from ..models.student import Student  # deferred to avoid circular imports

        students = (
            self._session.query(Student)
            .filter_by(class_id=class_id)
            .all()
        )

        enrolled: list[EnrolledStudent] = []
        for s in students:
            raw = getattr(s, "face_embedding", None)
            if raw is None:
                continue
            enrolled.append(
                EnrolledStudent(
                    student_id=s.id,
                    name=s.name,
                    class_id=class_id,
                    embedding=np.array(raw, dtype=np.float32),
                    model_id=s.face_model,
                    embedding_dimension=s.embedding_dimension,
                    embedding_status=s.embedding_status,
                )
            )
        return enrolled


class AttendanceRepository:
    """
    Persist attendance session results to the database.
    """

    def __init__(self, db_session) -> None:
        self._session = db_session

    def save_first_appearances(
        self,
        session_id: int,
        appearances: list[FirstAppearance],
    ) -> None:
        """
        Write first-appearance records to the attendance_records table.
        """
        from ..models.attendance import AttendanceRecord  # deferred import

        for a in appearances:
            record = AttendanceRecord(
                session_id=session_id,
                student_id=a.student_id,
                status="detected",
                detected_at_seconds=a.first_seen_sec,
                flagged=False,
            )
            self._session.add(record)
        self._session.commit()

    def save_decisions(
        self,
        session_id: int,
        decisions: list[AttendanceDecision],
    ) -> None:
        """
        Write final attendance decisions, replacing any existing records
        for the session.
        """
        from ..models.attendance import AttendanceRecord, AttendanceSession

        # Clear existing records for this session
        self._session.query(AttendanceRecord).filter_by(
            session_id=session_id
        ).delete()

        for d in decisions:
            record = AttendanceRecord(
                session_id=session_id,
                student_id=d.student_id,
                status=d.status,
                detected_at_seconds=d.first_seen_sec,
                flagged=False,
            )
            self._session.add(record)

        # Update session status
        session = self._session.query(AttendanceSession).get(session_id)
        if session:
            session.processing_status = "done"

        self._session.commit()

    def mark_session_error(
        self,
        session_id: int,
        error_message: str,
    ) -> None:
        """Mark a session as failed."""
        from ..models.attendance import AttendanceSession

        session = self._session.query(AttendanceSession).get(session_id)
        if session:
            session.processing_status = "error"
            session.error_message = error_message
        self._session.commit()
