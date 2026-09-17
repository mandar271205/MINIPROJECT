from __future__ import annotations

import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app

from ..extensions import db
from ..models.student import EMBEDDING_STATUS_ACTIVE, Student
from ..utils.files import ALLOWED_IMAGE_EXTENSIONS, allowed_extension, ensure_dir
from .face_detection import RetinaFaceDetector
from .recognition_provider import EmbeddingValidationError, get_provider


import re


def _parse_student_filename(filename: str) -> tuple[str | None, str | None]:
    stem = Path(filename).stem
    clean_stem = re.sub(r"\s*\(\d+\)$", "", stem).strip()

    if "_" in clean_stem:
        roll_number, name_part = clean_stem.split("_", 1)
        roll_number = roll_number.strip()
        name = name_part.replace("_", " ").strip()
        if roll_number and name:
            return roll_number, name

    if clean_stem:
        roll_number = clean_stem
        name = clean_stem.replace("-", " ").replace("_", " ").strip()
        if roll_number.isdigit() or len(roll_number) >= 5:
            name = f"Student {roll_number}"
        return roll_number, name

    return None, None


def enroll_students_from_zip(classroom, zip_path: Path) -> list[dict]:
    """Enrols/re-enrols every valid image in *zip_path* using the
    single verified InsightFaceArcFaceProvider.

    Sequence per file: read image -> detect faces -> require exactly
    one face -> align -> ArcFace embedding -> validate -> commit.
    Each student's database write is its own transaction (commit per
    student), so one student's failure never rolls back another
    student's already-successful enrolment within the same ZIP.
    """
    temp_dir = Path(current_app.config["TEMP_DIR"]) / zip_path.stem
    ensure_dir(temp_dir)

    results: list[dict] = []
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(temp_dir)

    class_dir = Path(current_app.config["ENROLL_DIR"]) / f"class_{classroom.id}"
    ensure_dir(class_dir)

    provider = get_provider()
    detector = RetinaFaceDetector()

    for file_path in temp_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if not allowed_extension(file_path.name, ALLOWED_IMAGE_EXTENSIONS):
            results.append({"file": file_path.name, "success": False, "reason": "Unsupported file"})
            continue

        roll_number, name = _parse_student_filename(file_path.name)
        if not roll_number or not name:
            results.append({"file": file_path.name, "success": False, "reason": "Bad filename"})
            continue

        try:
            import cv2

            frame = cv2.imread(str(file_path))
            if frame is None:
                raise ValueError("Could not read image file")

            detections = detector.detect_raw(frame)
            if len(detections) == 0:
                raise ValueError("No face detected in image")
            if len(detections) > 1:
                raise ValueError(f"Expected exactly one face, found {len(detections)}")

            embedding_vec = provider.extract_embedding(detections[0].aligned_face)
            validated = provider.validate_embedding(embedding_vec)
            embedding_list = validated.tolist()
        except Exception as exc:
            results.append({"file": file_path.name, "success": False, "reason": str(exc)})
            continue

        dest_path = class_dir / file_path.name
        shutil.copy(file_path, dest_path)

        existing = Student.query.filter_by(class_id=classroom.id, roll_number=roll_number).first()
        try:
            if existing:
                existing.name = name
                existing.face_embedding = embedding_list
                existing.face_model = provider.model_id
                existing.embedding_dimension = provider.embedding_dimension
                existing.embedding_status = EMBEDDING_STATUS_ACTIVE
                existing.embedding_updated_at = datetime.now(timezone.utc)
                existing.embedding_error = None
                existing.reference_image_path = str(dest_path)
            else:
                student = Student(
                    class_id=classroom.id,
                    roll_number=roll_number,
                    name=name,
                    face_embedding=embedding_list,
                    face_model=provider.model_id,
                    embedding_dimension=provider.embedding_dimension,
                    embedding_status=EMBEDDING_STATUS_ACTIVE,
                    embedding_updated_at=datetime.now(timezone.utc),
                    reference_image_path=str(dest_path),
                )
                db.session.add(student)

            # Transactional per student: this file's DB write is
            # committed on its own, so a later file's failure cannot
            # roll back an already-succeeded enrolment.
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            results.append({"file": file_path.name, "success": False, "reason": f"Database error: {exc}"})
            continue

        results.append({"file": file_path.name, "success": True})

    shutil.rmtree(temp_dir, ignore_errors=True)
    return results
