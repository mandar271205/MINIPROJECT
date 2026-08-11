"""End-to-end attendance pipeline.

Orchestrates steps 1–8 from the architecture diagram:

  1. Video upload / ingest
  2. Frame sampling (configurable interval)
  3. Face detection & alignment (RetinaFace via insightface)
  4. Dual-branch recognition (AdaFace + Swin Transformer)
  5. Feature fusion (concatenation + FC → 512-D)
  6. Matching against enrolled student embeddings (cosine similarity)
  7. First-appearance tracking & attendance decision
  8. Report generation (XLSX / PDF) & notifications (email / SMS)

This module is a **reference implementation** – the running server uses
``app.services.attendance_service`` instead.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from .attendance_decision import decide_attendance, format_timestamp
from .face_detection import RetinaFaceDetector
from .first_appearance import FirstAppearanceTracker
from .frame_sampling import sample_frames
from .fusion import EmbeddingFusion
from .matching import match_face
from .models import AttendanceReport, EnrolledStudent
from .notifications import NotificationDispatcher
from .output_reports import generate_pdf, generate_xlsx
from .recognition_adaptive import AdaFaceRecognizer
from .recognition_transformer import SwinTransformerRecognizer
from .repositories import AttendanceRepository, StudentRepository

log = logging.getLogger(__name__)


class CctvAttendancePipeline:
    """
    Full CCTV-based automated attendance pipeline.

    Wires all architecture components together and executes them
    in sequence for a single video / session.
    """

    def __init__(
        self,
        *,
        detector: RetinaFaceDetector | None = None,
        adaface: AdaFaceRecognizer | None = None,
        swin: SwinTransformerRecognizer | None = None,
        fusion: EmbeddingFusion | None = None,
        student_repo: StudentRepository | None = None,
        attendance_repo: AttendanceRepository | None = None,
        notifier: NotificationDispatcher | None = None,
        frame_interval: float = 2.0,
        match_threshold: float = 0.55,
        grace_period_minutes: int = 10,
    ) -> None:
        self.detector = detector or RetinaFaceDetector()
        self.adaface = adaface or AdaFaceRecognizer()
        self.swin = swin or SwinTransformerRecognizer()
        self.fusion = fusion or EmbeddingFusion()
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
    ) -> dict:
        """
        Execute the full CCTV attendance pipeline.

        Parameters
        ----------
        video_path : str
            Path to the uploaded MP4 / AVI / MOV file.
        class_id : int
            ID of the classroom whose enrolled students we compare against.
        session_id : int
            ID of the attendance session being processed.
        class_start_time : str | None
            ISO-8601 datetime string for the official class start.
        report_dir : str | None
            Directory to save generated reports. If None, reports are
            returned as in-memory buffers.

        Returns
        -------
        dict
            Pipeline results including attendance decisions and report paths.
        """
        log.info(
            "Starting pipeline: video=%s, class=%d, session=%d",
            video_path, class_id, session_id,
        )

        # ------------------------------------------------------------ #
        # Step 1 – Load enrolled students                               #
        # ------------------------------------------------------------ #
        if self.student_repo:
            enrolled = self.student_repo.get_enrolled(class_id)
        else:
            enrolled = []

        if not enrolled:
            log.warning("No enrolled students found for class %d", class_id)
            return {
                "session_id": session_id,
                "error": "No enrolled students found",
                "attendance": [],
            }

        log.info("Loaded %d enrolled students", len(enrolled))

        # ------------------------------------------------------------ #
        # Step 2 – Frame sampling                                       #
        # ------------------------------------------------------------ #
        tracker = FirstAppearanceTracker()
        frames_processed = 0
        faces_detected = 0

        for sample in sample_frames(video_path, every_n_seconds=self.frame_interval):
            frames_processed += 1

            # -------------------------------------------------------- #
            # Step 3 – Face detection & alignment                       #
            # -------------------------------------------------------- #
            detections = self.detector.detect(sample)
            if not detections:
                continue

            faces_detected += len(detections)

            for detection in detections:
                # ---------------------------------------------------- #
                # Step 4a – AdaFace embedding                           #
                # ---------------------------------------------------- #
                ada_emb = self.adaface.embed(detection)

                # ---------------------------------------------------- #
                # Step 4b – Swin Transformer embedding                  #
                # ---------------------------------------------------- #
                swin_emb = self.swin.embed(detection)

                # ---------------------------------------------------- #
                # Step 5 – Fusion (AdaFace + Swin-T → 512-D)           #
                # ---------------------------------------------------- #
                fused_emb = self.fusion.fuse(ada_emb, swin_emb)

                # ---------------------------------------------------- #
                # Step 6 – Matching against enrolled embeddings         #
                # ---------------------------------------------------- #
                match = match_face(
                    fused_emb,
                    enrolled,
                    threshold=self.match_threshold,
                )

                # ---------------------------------------------------- #
                # Step 7a – Track first appearance                      #
                # ---------------------------------------------------- #
                if match.is_match:
                    tracker.update(match, sample.timestamp_sec)

            # Early exit if all students have been identified
            if len(tracker) == len(enrolled):
                log.info(
                    "All %d students identified by frame %d (%.1fs)",
                    len(enrolled), sample.index, sample.timestamp_sec,
                )
                break

        log.info(
            "Processed %d frames, detected %d faces, identified %d students",
            frames_processed, faces_detected, len(tracker),
        )

        # ------------------------------------------------------------ #
        # Step 7b – Attendance decisions                                #
        # ------------------------------------------------------------ #
        appearances = tracker.get_all()
        decisions = decide_attendance(
            enrolled,
            appearances,
            grace_period_minutes=self.grace_period_minutes,
        )

        # ------------------------------------------------------------ #
        # Step 8a – Persist results                                     #
        # ------------------------------------------------------------ #
        if self.attendance_repo:
            self.attendance_repo.save_decisions(session_id, decisions)
            log.info("Saved attendance decisions for session %d", session_id)

        # ------------------------------------------------------------ #
        # Step 8b – Generate reports                                    #
        # ------------------------------------------------------------ #
        report = AttendanceReport(
            class_id=class_id,
            session_id=session_id,
            created_at=datetime.now(timezone.utc),
            rows=decisions,
        )

        report_paths = {}
        if report_dir:
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

        # ------------------------------------------------------------ #
        # Step 8c – Notifications                                       #
        # ------------------------------------------------------------ #
        if self.notifier:
            # Notifications would be configured per-user in production
            log.info("Notification dispatcher available (not sending by default)")

        # ------------------------------------------------------------ #
        # Build response                                                #
        # ------------------------------------------------------------ #
        present = sum(1 for d in decisions if d.status == "present")
        late = sum(1 for d in decisions if d.status == "late-absent")
        absent = sum(1 for d in decisions if d.status == "absent")

        return {
            "session_id": session_id,
            "class_id": class_id,
            "frames_processed": frames_processed,
            "faces_detected": faces_detected,
            "students_identified": len(tracker),
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
            "reports": report_paths,
        }
