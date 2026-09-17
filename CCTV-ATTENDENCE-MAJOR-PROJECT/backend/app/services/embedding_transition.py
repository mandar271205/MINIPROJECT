"""Phase 3 - controlled transition of existing student embeddings to
the verified InsightFaceArcFaceProvider.

Invoked via the Flask CLI command registered in app/__init__.py:

    flask transition-embeddings

Never runs automatically on app startup - it is an explicit, one-shot,
re-runnable operation an HOD/operator triggers deliberately.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import cv2

from ..extensions import db
from ..models.student import (
    EMBEDDING_STATUS_ACTIVE,
    EMBEDDING_STATUS_FAILED,
    EMBEDDING_STATUS_REENROLL_REQUIRED,
    Student,
)
from .face_detection import RetinaFaceDetector
from .recognition_provider import EmbeddingValidationError, get_provider

log = logging.getLogger(__name__)


def transition_all_students() -> list[dict]:
    """Attempts to regenerate every student's embedding with the active
    provider. Returns a transition report (one dict per student) with
    no raw embedding values or private image data - only ids, model
    ids, and safe result/reason strings.

    Per-student rules (see Phase 3 spec section F):

      1. The old embedding/model metadata is only ever overwritten
         after a *new* embedding has been generated and validated -
         never before, and never partially.
      2. Missing reference image -> old vector preserved,
         REENROLL_REQUIRED, reason recorded.
      3. Zero or multiple faces detected -> old vector preserved,
         REENROLL_REQUIRED, reason recorded.
      4. Any other failure -> rolled back, old vector preserved,
         FAILED, reason recorded; processing continues with the next
         student.
    """
    provider = get_provider()
    detector = RetinaFaceDetector()

    report: list[dict] = []

    students = Student.query.order_by(Student.id).all()
    for student in students:
        entry = {
            "student_id": student.id,
            "previous_model_id": student.face_model,
            "new_model_id": None,
            "result": None,
            "reenrollment_required": False,
            "failure_reason": None,
        }

        image_path = student.reference_image_path
        if not image_path or not Path(image_path).is_file():
            entry["result"] = "skipped"
            entry["reenrollment_required"] = True
            entry["failure_reason"] = "reference image is missing"
            _mark_reenroll_required(student, entry["failure_reason"])
            report.append(entry)
            continue

        try:
            frame = cv2.imread(str(image_path))
            if frame is None:
                raise ValueError("reference image could not be read")

            detections = detector.detect_raw(frame)
            if len(detections) == 0:
                entry["result"] = "skipped"
                entry["reenrollment_required"] = True
                entry["failure_reason"] = "no face detected in reference image"
                _mark_reenroll_required(student, entry["failure_reason"])
                report.append(entry)
                continue
            if len(detections) > 1:
                entry["result"] = "skipped"
                entry["reenrollment_required"] = True
                entry["failure_reason"] = "multiple faces detected in reference image"
                _mark_reenroll_required(student, entry["failure_reason"])
                report.append(entry)
                continue

            raw_embedding = provider.extract_embedding(detections[0].aligned_face)
            validated = provider.validate_embedding(raw_embedding)

            # Atomic replace: only touch the row once every step above
            # has already succeeded.
            student.face_embedding = validated.tolist()
            student.face_model = provider.model_id
            student.embedding_dimension = provider.embedding_dimension
            student.embedding_status = EMBEDDING_STATUS_ACTIVE
            student.embedding_updated_at = datetime.now(timezone.utc)
            student.embedding_error = None
            db.session.commit()

            entry["result"] = "regenerated"
            entry["new_model_id"] = provider.model_id
        except EmbeddingValidationError as exc:
            db.session.rollback()
            entry["result"] = "failed"
            entry["failure_reason"] = f"embedding validation failed: {exc}"
            _mark_failed(student, entry["failure_reason"])
            log.warning("Embedding transition failed for student %d: %s", student.id, exc)
        except Exception as exc:
            db.session.rollback()
            entry["result"] = "failed"
            entry["failure_reason"] = str(exc)
            _mark_failed(student, entry["failure_reason"])
            log.warning("Embedding transition failed for student %d: %s", student.id, exc)

        report.append(entry)

    log.info("Embedding transition complete: %d students processed", len(report))
    return report


def _mark_reenroll_required(student: Student, reason: str) -> None:
    """Preserves the existing embedding vector and model id; only the
    status/diagnostic fields change."""
    student.embedding_status = EMBEDDING_STATUS_REENROLL_REQUIRED
    student.embedding_error = reason
    student.embedding_updated_at = datetime.now(timezone.utc)
    db.session.commit()


def _mark_failed(student: Student, reason: str) -> None:
    """Preserves the existing embedding vector and model id; only the
    status/diagnostic fields change. Called after db.session.rollback()
    has already discarded any partial embedding change."""
    student.embedding_status = EMBEDDING_STATUS_FAILED
    student.embedding_error = reason
    student.embedding_updated_at = datetime.now(timezone.utc)
    db.session.commit()
