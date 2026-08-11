from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from flask import current_app

from ..extensions import db
from ..models.student import Student
from ..utils.files import ALLOWED_IMAGE_EXTENSIONS, allowed_extension, ensure_dir
from .face_recognition import compute_embedding


def _parse_student_filename(filename: str) -> tuple[str | None, str | None]:
    stem = Path(filename).stem
    if "_" not in stem:
        return None, None
    roll_number, name_part = stem.split("_", 1)
    roll_number = roll_number.strip()
    name = name_part.replace("_", " ").strip()
    if not roll_number or not name:
        return None, None
    return roll_number, name


def enroll_students_from_zip(classroom, zip_path: Path) -> list[dict]:
    temp_dir = Path(current_app.config["TEMP_DIR"]) / zip_path.stem
    ensure_dir(temp_dir)

    results: list[dict] = []
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(temp_dir)

    model_name = current_app.config["DEEPFACE_MODEL"]
    detector_backend = current_app.config["DEEPFACE_BACKEND"]
    class_dir = Path(current_app.config["ENROLL_DIR"]) / f"class_{classroom.id}"
    ensure_dir(class_dir)

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
            from .face_detection import RetinaFaceDetector
            from .recognition_adaptive import AdaFaceRecognizer
            from .recognition_transformer import SwinTransformerRecognizer
            from .fusion import EmbeddingFusion
            import cv2

            # Instantiate components inside function for simplicity
            # Note: in production, you might want these pre-loaded if you do frequent enrollments.
            detector = RetinaFaceDetector()
            adaface = AdaFaceRecognizer()
            swin = SwinTransformerRecognizer()
            fusion = EmbeddingFusion()

            frame = cv2.imread(str(file_path))
            if frame is None:
                raise Exception("Could not read image file")
            
            detections = detector.detect_raw(frame)
            if not detections:
                raise Exception("No face detected in image")
                
            # Use largest face
            det = max(detections, key=lambda d: (d.bbox[2]-d.bbox[0])*(d.bbox[3]-d.bbox[1]))
            
            ada_emb = adaface.embed(det)
            swin_emb = swin.embed(det)
            fused_emb = fusion.fuse(ada_emb, swin_emb)
            
            embedding_list = fused_emb.vector.tolist()
            model_name = "fused_ada_swin"
            
        except Exception as exc:
            results.append({"file": file_path.name, "success": False, "reason": str(exc)})
            continue

        existing = Student.query.filter_by(class_id=classroom.id, roll_number=roll_number).first()
        dest_path = class_dir / file_path.name
        shutil.copy(file_path, dest_path)

        if existing:
            existing.name = name
            existing.face_embedding = embedding_list
            existing.face_model = model_name
            existing.reference_image_path = str(dest_path)
        else:
            student = Student(
                class_id=classroom.id,
                roll_number=roll_number,
                name=name,
                face_embedding=embedding_list,
                face_model=model_name,
                reference_image_path=str(dest_path),
            )
            db.session.add(student)

        results.append({"file": file_path.name, "success": True})

    db.session.commit()
    shutil.rmtree(temp_dir, ignore_errors=True)
    return results
