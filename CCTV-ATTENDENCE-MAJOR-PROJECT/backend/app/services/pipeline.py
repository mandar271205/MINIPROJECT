"""End-to-end attendance pipeline.

Orchestrates:

  1. Video upload / ingest
  2. Frame sampling (configurable interval) - read through to actual EOF
  3. Face detection & alignment (RetinaFace/SCRFD via insightface)
  4. Recognition via the single verified InsightFaceArcFaceProvider
  5. Temporary spatial face-track association (observation_tracker.py)
  6. Top-1/top-2 matching evidence against compatible enrolled
     embeddings only (matching.match_face_evidence)
  7. Recognition-observation creation + sliding-window identity voting
     per track (identity_voting.py)
  8. Track/observation persistence (observation_persistence.py)
  9. Legacy first-appearance tracking - fed ONLY from CONFIRMED track
     evidence, never from a single frame (legacy output format,
     temporarily preserved; does not control termination)
  10. Report generation (XLSX / PDF)

Phase 3 established: no early-stop (reads to actual EOF), the single
verified ArcFace provider, and eligibility filtering so a student with
no compatible template never gets a fabricated legacy attendance
record.

Phase 4 adds: recognition is evidence, not an immediate identity
decision. A single successful cosine match no longer feeds legacy
attendance directly - only a track that the sliding-window voting
engine has CONFIRMED (multi-observation, above threshold, margin and
support all pass) may do so.

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
from .identity_voting import IdentityVotingEngine, VoteObservation
from .matching import match_face_evidence
from .models import AttendanceReport, FaceEmbedding, MatchResult
from .notifications import NotificationDispatcher
from .observation_persistence import ObservationPersistence
from .observation_tracker import FaceTrackAssociator, TrackedDetection
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
    """Raised for invalid pipeline configuration. Never silently
    clamped - the job is failed with a clear message."""


def _validate_config(match_threshold: float, frame_interval: float) -> None:
    if not (0.0 < match_threshold < 1.0):
        raise PipelineConfigError(
            f"FACE_MATCH_THRESHOLD must be strictly between 0 and 1, got {match_threshold!r}"
        )
    if not (frame_interval > 0.0):
        raise PipelineConfigError(
            f"FRAME_SAMPLE_INTERVAL_SECONDS must be greater than zero, got {frame_interval!r}"
        )


class _TrackBookkeeping:
    """In-memory running state for one face track during a single
    pipeline run, before it is written to face_tracks."""

    __slots__ = (
        "first_seen", "last_seen", "observation_count", "state",
        "confirmed_student_id", "confirmed_at", "mean_confidence",
        "max_confidence", "identity_conflict", "conflict_reason",
    )

    def __init__(self, timestamp_sec: float) -> None:
        self.first_seen = timestamp_sec
        self.last_seen = timestamp_sec
        self.observation_count = 0
        self.state = "UNCONFIRMED"
        self.confirmed_student_id: int | None = None
        self.confirmed_at: float | None = None
        self.mean_confidence: float | None = None
        self.max_confidence: float | None = None
        self.identity_conflict = False
        self.conflict_reason: str | None = None


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
        observation_persistence: ObservationPersistence | None = None,
        notifier: NotificationDispatcher | None = None,
        frame_interval: float = 2.0,
        match_threshold: float = 0.55,
        grace_period_minutes: int = 10,
        track_max_gap_seconds: float = 3.0,
        track_min_iou: float = 0.3,
        track_max_centroid_distance: float = 80.0,
        track_close_after_seconds: float = 6.0,
        identity_vote_window_size: int = 5,
        identity_min_support: int = 3,
        identity_min_support_ratio: float = 0.60,
        identity_min_mean_confidence: float | None = None,
        identity_min_margin: float = 0.03,
        identity_conflict_support: int = 2,
    ) -> None:
        _validate_config(match_threshold, frame_interval)

        self.detector = detector or RetinaFaceDetector()
        self.provider = provider or get_provider()
        self.student_repo = student_repo
        self.attendance_repo = attendance_repo
        # Deliberately no default instance here (unlike detector/
        # provider): constructing one would bind to Flask-SQLAlchemy's
        # global db.session, which requires an active app context that
        # unit tests exercising the pipeline in isolation don't have.
        # Production wiring (attendance_service.py) always passes one
        # explicitly.
        self.observation_persistence = observation_persistence
        self.notifier = notifier

        self.frame_interval = frame_interval
        self.match_threshold = match_threshold
        self.grace_period_minutes = grace_period_minutes

        self.track_max_gap_seconds = track_max_gap_seconds
        self.track_min_iou = track_min_iou
        self.track_max_centroid_distance = track_max_centroid_distance
        self.track_close_after_seconds = track_close_after_seconds

        self.voting_engine = IdentityVotingEngine(
            window_size=identity_vote_window_size,
            min_support=identity_min_support,
            min_support_ratio=identity_min_support_ratio,
            min_mean_confidence=(
                identity_min_mean_confidence if identity_min_mean_confidence is not None else match_threshold
            ),
            min_margin=identity_min_margin,
            conflict_support=identity_conflict_support,
        )

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
            "total_tracks": 0,
            "confirmed_tracks": 0,
            "unconfirmed_tracks": 0,
            "unknown_tracks": 0,
            "ambiguous_tracks": 0,
            "identity_conflict_tracks": 0,
            "total_observations": 0,
            "confirmed_support_observations": 0,
            "below_threshold_observations": 0,
        }

        # ------------------------------------------------------------ #
        # Step 1 - Load enrolled students & split by eligibility.      #
        # Only ACTIVE, exact-model-id, exact-dimension, valid-vector   #
        # students are eligible. Ineligible students NEVER enter       #
        # matching, tracks, voting, or the legacy present/late-absent/ #
        # absent decision below.                                       #
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
        # Step 3-8 - Sample frames through to EOF: detect, recognize,  #
        # associate into tracks, vote, buffer evidence.                #
        # ------------------------------------------------------------ #
        legacy_tracker = FirstAppearanceTracker()
        associator = FaceTrackAssociator(
            max_gap_seconds=self.track_max_gap_seconds,
            min_iou=self.track_min_iou,
            max_centroid_distance=self.track_max_centroid_distance,
            close_after_seconds=self.track_close_after_seconds,
        )
        track_bookkeeping: dict[str, _TrackBookkeeping] = {}
        track_vote_observations: dict[str, list[VoteObservation]] = {}
        observation_rows: list[dict] = []

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

                tracked_detections = [
                    TrackedDetection(bbox=d.bbox, frame_index=sample.index, detection_index=i)
                    for i, d in enumerate(detections)
                ]
                associations = associator.associate(tracked_detections, sample.timestamp_sec)

                for detection_index, (detection, assoc) in enumerate(zip(detections, associations)):
                    track_key = assoc.track_key

                    try:
                        embedding_vec = self.provider.extract_embedding(detection.aligned_face)
                    except EmbeddingValidationError:
                        diagnostics["invalid_embeddings"] += 1
                        continue

                    query = FaceEmbedding(vector=embedding_vec, model_name=self.provider.model_id)
                    evidence = match_face_evidence(query, eligible, threshold=self.match_threshold)

                    if track_key not in track_bookkeeping:
                        track_bookkeeping[track_key] = _TrackBookkeeping(sample.timestamp_sec)
                        track_vote_observations[track_key] = []
                    book = track_bookkeeping[track_key]
                    book.last_seen = sample.timestamp_sec
                    book.observation_count += 1

                    vote_obs = VoteObservation(
                        top1_student_id=evidence.top1_student_id,
                        top1_similarity=evidence.top1_similarity,
                        top2_student_id=evidence.top2_student_id,
                        top2_similarity=evidence.top2_similarity,
                        above_threshold=evidence.above_threshold,
                        timestamp_sec=sample.timestamp_sec,
                    )
                    track_vote_observations[track_key].append(vote_obs)

                    vote_result = self.voting_engine.vote(
                        track_vote_observations[track_key],
                        previous_confirmed_student_id=book.confirmed_student_id,
                    )

                    book.state = vote_result.state
                    book.mean_confidence = vote_result.mean_confidence
                    book.max_confidence = vote_result.max_confidence
                    book.identity_conflict = book.identity_conflict or vote_result.identity_conflict
                    if vote_result.conflict_reason:
                        book.conflict_reason = vote_result.conflict_reason
                    if book.confirmed_student_id is None and vote_result.state == "CONFIRMED":
                        book.confirmed_student_id = vote_result.confirmed_student_id
                        book.confirmed_at = vote_result.confirmation_timestamp_sec

                    if not evidence.above_threshold:
                        evidence_state = "BELOW_THRESHOLD"
                    elif evidence.top1_student_id is None:
                        evidence_state = "UNKNOWN"
                    elif book.confirmed_student_id is not None and evidence.top1_student_id == book.confirmed_student_id:
                        evidence_state = "CONFIRMED_SUPPORT"
                    elif book.identity_conflict and evidence.top1_student_id != book.confirmed_student_id:
                        evidence_state = "CONFLICTING"
                    elif vote_result.state == "AMBIGUOUS":
                        evidence_state = "AMBIGUOUS"
                    else:
                        evidence_state = "MATCH_CANDIDATE"

                    if evidence.above_threshold:
                        diagnostics["successful_matches"] += 1
                    if evidence_state == "CONFIRMED_SUPPORT":
                        diagnostics["confirmed_support_observations"] += 1
                    if evidence_state == "BELOW_THRESHOLD":
                        diagnostics["below_threshold_observations"] += 1
                    diagnostics["total_observations"] += 1

                    observation_rows.append(
                        {
                            "track_key": track_key,
                            "frame_index": sample.index,
                            "detection_index": detection_index,
                            "timestamp_seconds": sample.timestamp_sec,
                            "bbox_x1": float(detection.bbox[0]),
                            "bbox_y1": float(detection.bbox[1]),
                            "bbox_x2": float(detection.bbox[2]),
                            "bbox_y2": float(detection.bbox[3]),
                            "detection_confidence": float(detection.confidence),
                            "top1_student_id": evidence.top1_student_id,
                            "top1_similarity": evidence.top1_similarity,
                            "top2_student_id": evidence.top2_student_id,
                            "top2_similarity": evidence.top2_similarity,
                            "similarity_margin": evidence.similarity_margin,
                            "evidence_state": evidence_state,
                            "provider_model_id": self.provider.model_id,
                        }
                    )

                # Deliberately no early-stop here: processing continues
                # through every scheduled frame regardless of how many
                # tracks have already been confirmed.

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

        # ------------------------------------------------------------ #
        # EOF - close every track. A track that never reached a       #
        # decided state (UNCONFIRMED, never enough evidence and never  #
        # will get more) becomes CLOSED. CONFIRMED/UNKNOWN/AMBIGUOUS   #
        # tracks keep their decided state as the final label -         #
        # closed_at_seconds still records when evidence stopped.       #
        # ------------------------------------------------------------ #
        associator.close_all()
        for track_key, book in track_bookkeeping.items():
            if book.state == "UNCONFIRMED":
                book.state = "CLOSED"

        # ------------------------------------------------------------ #
        # Persist tracks/observations transactionally, replacing any   #
        # prior Phase 4 evidence for this exact session (reprocessing  #
        # never duplicates).                                            #
        # ------------------------------------------------------------ #
        track_rows = [
            {
                "track_key": track_key,
                "first_seen_seconds": book.first_seen,
                "last_seen_seconds": book.last_seen,
                "observation_count": book.observation_count,
                "track_state": book.state,
                "confirmed_student_id": book.confirmed_student_id,
                "confirmed_at_seconds": book.confirmed_at,
                "mean_confidence": book.mean_confidence,
                "max_confidence": book.max_confidence,
                "identity_conflict": book.identity_conflict,
                "conflict_reason": book.conflict_reason,
                "closed_at_seconds": book.last_seen,
            }
            for track_key, book in track_bookkeeping.items()
        ]
        if self.observation_persistence is not None:
            self.observation_persistence.replace_session_evidence(session_id, track_rows, observation_rows)

        diagnostics["total_tracks"] = len(track_bookkeeping)
        diagnostics["confirmed_tracks"] = sum(1 for b in track_bookkeeping.values() if b.state == "CONFIRMED")
        diagnostics["unconfirmed_tracks"] = sum(1 for b in track_bookkeeping.values() if b.state in ("UNCONFIRMED", "CLOSED"))
        diagnostics["unknown_tracks"] = sum(1 for b in track_bookkeeping.values() if b.state == "UNKNOWN")
        diagnostics["ambiguous_tracks"] = sum(1 for b in track_bookkeeping.values() if b.state == "AMBIGUOUS")
        diagnostics["identity_conflict_tracks"] = sum(1 for b in track_bookkeeping.values() if b.identity_conflict)

        log.info(
            "session=%d frames_sampled=%d faces_detected=%d total_tracks=%d confirmed_tracks=%d "
            "unknown_tracks=%d ambiguous_tracks=%d total_observations=%d eof_reached=%s",
            session_id, diagnostics["frames_sampled"], diagnostics["faces_detected"], diagnostics["total_tracks"],
            diagnostics["confirmed_tracks"], diagnostics["unknown_tracks"], diagnostics["ambiguous_tracks"],
            diagnostics["total_observations"], diagnostics["eof_reached"],
        )

        # ------------------------------------------------------------ #
        # Legacy first-appearance feed: ONLY confirmed track evidence  #
        # ever reaches FirstAppearanceTracker. The timestamp used is   #
        # the earliest observation inside the successful confirmation  #
        # window that supported the confirmed identity (i.e. the       #
        # voting engine's confirmation_timestamp_sec) - never an        #
        # earlier, unconfirmed single-frame candidate sighting.         #
        # ------------------------------------------------------------ #
        for book in track_bookkeeping.values():
            if book.state == "CONFIRMED" and book.confirmed_student_id is not None:
                confirmed_match = MatchResult(
                    student_id=book.confirmed_student_id,
                    student_name=next(
                        (s.name for s in eligible if s.student_id == book.confirmed_student_id), None
                    ),
                    similarity=book.mean_confidence or 0.0,
                    is_match=True,
                )
                legacy_tracker.update(confirmed_match, book.confirmed_at if book.confirmed_at is not None else book.first_seen)

        # ------------------------------------------------------------ #
        # Legacy first-appearance attendance decision.                 #
        # Only ever evaluated over `eligible` - an ineligible student  #
        # can never receive PRESENT/LATE-ABSENT/ABSENT from this run.  #
        # (temporarily preserved output format; see FirstAppearanceTracker) #
        # ------------------------------------------------------------ #
        appearances = legacy_tracker.get_all()
        decisions = (
            decide_attendance(eligible, appearances, grace_period_minutes=self.grace_period_minutes)
            if eligible
            else []
        )

        # ------------------------------------------------------------ #
        # Persist legacy results.                                      #
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
        # legacy attendance was generated - never a Phase 4/5 attendance
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
            "students_identified": len(legacy_tracker),
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
