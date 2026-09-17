"""End-to-end attendance pipeline.

Orchestrates:

  1. Video upload / ingest
  2. Frame sampling (configurable interval) - read through to actual EOF
  3. Face detection & alignment (RetinaFace/SCRFD via insightface)
  4. Recognition via the single verified InsightFaceArcFaceProvider
  5. Matching against compatible enrolled student embeddings only
  6. First-appearance tracking (legacy output, does not control
     termination) & attendance decision
  7. Report generation (XLSX / PDF)

Phase 3 changes from the earlier reference implementation:

  - Removed the "all enrolled students identified" early-stop. The
    pipeline now always samples frames until the video's actual EOF.
  - Replaced the AdaFace + Swin Transformer + arithmetic-fusion path
    with the single verified ``InsightFaceArcFaceProvider``.
  - Matching only ever considers embeddings whose stored model id and
    dimension exactly match the active provider; incompatible legacy
    templates are excluded, never force-converted or silently ignored.
  - Structured diagnostics are returned for every run, whether it
    succeeds or fails.

This is the module actually used at runtime, via
``app.services.attendance_service``.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2

from .attendance_decision import decide_attendance, format_timestamp
from .face_detection import RetinaFaceDetector
from .first_appearance import FirstAppearanceTracker
from .frame_sampling import sample_frames
from .matching import match_face
from .models import AttendanceReport
from .notifications import NotificationDispatcher
from .output_reports import generate_pdf, generate_xlsx
from .recognition_eligibility import classify_enrolled_students
from .recognition_provider import (
    EmbeddingValidationError,
    InsightFaceArcFaceProvider,
    get_provider,
)
from .repositories import AttendanceRepository, StudentRepository

log = logging.getLogger(__name__)


class PipelineConfigError(ValueError):
    """Raised for invalid pipeline configuration (threshold, interval).
    Never silently clamped - the job is failed with a clear message."""


def _validate_config(match_threshold: float, frame_interval: float) -> None:
    if not (0.0 < match_threshold < 1.0):
        raise PipelineConfigError(
            f"FACE_MATCH_THRESHOLD must be strictly between 0 and 1, got {match_threshold!r}"
        )
    if not (frame_interval > 0.0):
        raise PipelineConfigError(
            f"FRAME_SAMPLE_INTERVAL_SECONDS must be greater than zero, got {frame_interval!r}"
        )


class CctvAttendancePipeline:
    """
    Full CCTV-based automated attendance pipeline.
    """

    def __init__(
        self,
        *,
        detector: RetinaFaceDetector | None = None,
        provider: InsightFaceArcFaceProvider | None = None,
        student_repo: StudentRepository | None = None,
        attendance_repo: AttendanceRepository | None = None,
        notifier: NotificationDispatcher | None = None,
        frame_interval: float = 2.0,
        match_threshold: float = 0.55,
        grace_period_minutes: int = 10,
    ) -> None:
        _validate_config(match_threshold, frame_interval)

        self.detector = detector or RetinaFaceDetector()
        self.provider = provider or get_provider()
        self.student_repo = student_repo
        self.attendance_repo = attendance_repo
        self.notifier = notifier

        self.frame_interval = frame_interval
        self.match_threshold = match_threshold
        self.grace_period_minutes = grace_period_minutes

    def run(
        self,
        video_path: str,
        class_id: int,
        session_id: int,
        class_start_time: str | None = None,
        report_dir: str | None = None,
        progress_callback=None,
    ) -> dict:
        """
        Execute the full CCTV attendance pipeline.

        Returns a dict of results including structured diagnostics
        (see module docstring). On any hard error, returns a dict with
        an "error" key and a "diagnostics" key with whatever partial
        information was gathered - the caller is responsible for
        marking the session as failed, never as completed.
        """
        start_wall = time.monotonic()
        log.info(
            "Starting pipeline: video=%s, class=%d, session=%d, provider=%s, execution_provider=%s",
            video_path, class_id, session_id, self.provider.model_id, self.provider.execution_provider,
        )

        diagnostics: dict = {
            "video_duration_sec": None,
            "total_frames": None,
            "frames_read": 0,
            "frames_sampled": 0,
            "final_sampled_timestamp_sec": None,
            "faces_detected": 0,
            "compatible_templates": 0,
            "successful_matches": 0,
            "invalid_embeddings": 0,
            "processing_duration_sec": None,
            "eof_reached": False,
            "provider_model_id": self.provider.model_id,
            "execution_provider": self.provider.execution_provider,
            "recognition_eligible_count": 0,
            "recognition_ineligible_count": 0,
            "students_requiring_reenrollment": 0,
            "attendance_not_generated_count": 0,
        }

        # ------------------------------------------------------------ #
        # Step 1 - Load enrolled students & split by eligibility.      #
        # Only ACTIVE, exact-model-id, exact-dimension, valid-vector   #
        # students are eligible. Ineligible students (LEGACY_          #
        # INCOMPATIBLE / REENROLL_REQUIRED / FAILED / missing /        #
        # wrong model / wrong dimension / invalid vector) NEVER enter  #
        # matching, FirstAppearanceTracker, or the legacy present/     #
        # late-absent/absent decision below - they get a diagnostic    #
        # instead, never a fabricated ABSENT record.                   #
        # ------------------------------------------------------------ #
        enrolled_all = self.student_repo.get_enrolled(class_id) if self.student_repo else []
        eligible, ineligible_diagnostics = classify_enrolled_students(enrolled_all, self.provider)

        diagnostics["compatible_templates"] = len(eligible)
        diagnostics["recognition_eligible_count"] = len(eligible)
        diagnostics["recognition_ineligible_count"] = len(ineligible_diagnostics)
        diagnostics["students_requiring_reenrollment"] = sum(
            1 for d in ineligible_diagnostics if d["requires_reenrollment"]
        )
        diagnostics["attendance_not_generated_count"] = len(ineligible_diagnostics)

        log.info(
            "Loaded %d enrolled students for class %d (%d eligible, %d ineligible/require re-enrolment)",
            len(enrolled_all), class_id, len(eligible), len(ineligible_diagnostics),
        )

        # ------------------------------------------------------------ #
        # Step 2 - Probe video metadata (duration, total frames)       #
        # ------------------------------------------------------------ #
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            cap.release()
            diagnostics["processing_duration_sec"] = round(time.monotonic() - start_wall, 3)
            return {
                "session_id": session_id,
                "error": f"Cannot open or read video file: {video_path}",
                "diagnostics": diagnostics,
                "ineligible_students": ineligible_diagnostics,
            }

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        cap.release()
        diagnostics["total_frames"] = total_frames if total_frames > 0 else None
        diagnostics["video_duration_sec"] = round(total_frames / fps, 3) if total_frames > 0 else None
        total_samples_estimate = max(1, int(total_frames / (fps * self.frame_interval))) if total_frames > 0 else None

        # ------------------------------------------------------------ #
        # Step 3-6 - Sample frames through to EOF, detect, recognize,  #
        #            match, track first appearance                    #
        # ------------------------------------------------------------ #
        tracker = FirstAppearanceTracker()

        try:
            for sample in sample_frames(video_path, every_n_seconds=self.frame_interval):
                diagnostics["frames_read"] += 1
                diagnostics["frames_sampled"] += 1
                diagnostics["final_sampled_timestamp_sec"] = sample.timestamp_sec

                if progress_callback and total_samples_estimate:
                    # 5%-95% during processing; 100% is only ever set by
                    # the caller after results have been persisted.
                    pct = min(95, 5 + int(90 * diagnostics["frames_sampled"] / total_samples_estimate))
                    progress_callback(pct)

                detections = self.detector.detect(sample)
                if not detections:
                    continue

                diagnostics["faces_detected"] += len(detections)

                for detection in detections:
                    try:
                        embedding_vec = self.provider.extract_embedding(detection.aligned_face)
                    except EmbeddingValidationError:
                        diagnostics["invalid_embeddings"] += 1
                        continue

                    if not eligible:
                        # No eligible template exists for this class -
                        # a real, reportable state, not a silent skip.
                        continue

                    from .models import FaceEmbedding

                    query = FaceEmbedding(vector=embedding_vec, model_name=self.provider.model_id)
                    match = match_face(query, eligible, threshold=self.match_threshold)

                    if match.is_match:
                        diagnostics["successful_matches"] += 1
                        tracker.update(match, sample.timestamp_sec)

                # Deliberately no early-stop here: processing continues
                # through every scheduled frame regardless of how many
                # students FirstAppearanceTracker has already recorded.

            diagnostics["eof_reached"] = True
        except Exception as exc:
            diagnostics["processing_duration_sec"] = round(time.monotonic() - start_wall, 3)
            log.exception("Pipeline failed while reading video for session %d", session_id)
            return {
                "session_id": session_id,
                "error": f"Video processing failed: {exc}",
                "diagnostics": diagnostics,
                "ineligible_students": ineligible_diagnostics,
            }

        log.info(
            "session=%d frames_sampled=%d faces_detected=%d compatible_templates=%d successful_matches=%d eof_reached=%s",
            session_id, diagnostics["frames_sampled"], diagnostics["faces_detected"],
            diagnostics["compatible_templates"], diagnostics["successful_matches"], diagnostics["eof_reached"],
        )

        # ------------------------------------------------------------ #
        # Step 7 - Legacy first-appearance attendance decision.        #
        # Only ever evaluated over `eligible` - an ineligible student  #
        # can never receive PRESENT/LATE-ABSENT/ABSENT from this run.  #
        # (temporarily preserved output format; see FirstAppearanceTracker) #
        # ------------------------------------------------------------ #
        appearances = tracker.get_all()
        decisions = (
            decide_attendance(eligible, appearances, grace_period_minutes=self.grace_period_minutes)
            if eligible
            else []
        )

        # ------------------------------------------------------------ #
        # Step 8 - Persist results.                                    #
        # Skipped entirely when there is no eligible student: nothing  #
        # is written, so any previously existing valid records for     #
        # this session are left untouched rather than being cleared.  #
        # ------------------------------------------------------------ #
        if self.attendance_repo and decisions:
            self.attendance_repo.save_decisions(session_id, decisions)
            log.info("Saved attendance decisions for session %d", session_id)

        report = AttendanceReport(
            class_id=class_id,
            session_id=session_id,
            created_at=datetime.now(timezone.utc),
            rows=decisions,
        )

        report_paths = {}
        if report_dir and decisions:
            rd = Path(report_dir)
            rd.mkdir(parents=True, exist_ok=True)
            xlsx_path = rd / f"attendance_session_{session_id}.xlsx"
            pdf_path = rd / f"attendance_session_{session_id}.pdf"
            generate_xlsx(report, output_path=xlsx_path)
            generate_pdf(report, output_path=pdf_path)
            report.xlsx_path = str(xlsx_path)
            report.pdf_path = str(pdf_path)
            report_paths = {"xlsx": str(xlsx_path), "pdf": str(pdf_path)}
            log.info("Reports saved to %s", report_dir)

        diagnostics["processing_duration_sec"] = round(time.monotonic() - start_wall, 3)

        present = sum(1 for d in decisions if d.status == "present")
        late = sum(1 for d in decisions if d.status == "late-absent")
        absent = sum(1 for d in decisions if d.status == "absent")

        # This is processing metadata describing whether/how much
        # legacy attendance was generated - never a Phase 4 attendance
        # status, and never claiming success when no eligible student
        # existed to evaluate.
        if not eligible:
            attendance_generation_status = "NOT_GENERATED"
        elif ineligible_diagnostics:
            attendance_generation_status = "PARTIAL_ROSTER"
        else:
            attendance_generation_status = "GENERATED"

        result = {
            "session_id": session_id,
            "class_id": class_id,
            "frames_processed": diagnostics["frames_sampled"],
            "faces_detected": diagnostics["faces_detected"],
            "students_identified": len(tracker),
            "attendance_generation_status": attendance_generation_status,
            "recognition_eligible_count": diagnostics["recognition_eligible_count"],
            "recognition_ineligible_count": diagnostics["recognition_ineligible_count"],
            "students_requiring_reenrollment": diagnostics["students_requiring_reenrollment"],
            "attendance_not_generated_count": diagnostics["attendance_not_generated_count"],
            "summary": {
                "present": present,
                "late_absent": late,
                "absent": absent,
                "total": len(decisions),
            },
            "attendance": [
                {
                    "student_id": d.student_id,
                    "name": d.student_name,
                    "status": d.status,
                    "first_seen": format_timestamp(d.first_seen_sec),
                    "confidence": (
                        round(d.confidence, 4) if d.confidence else None
                    ),
                }
                for d in decisions
            ],
            "ineligible_students": ineligible_diagnostics,
            "reports": report_paths,
            "diagnostics": diagnostics,
        }

        if not eligible:
            result["message"] = (
                "Attendance could not be evaluated: no student in this class has a compatible "
                "face template. Re-enrolment is required."
            )

        return result
