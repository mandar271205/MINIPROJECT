"""Phase 4 - pipeline integration tests: tracking + voting wired into
the actual video-processing run. Uses fake detector/provider (as in
test_pipeline_fullvideo.py) so these tests are fast, deterministic, and
don't depend on the real InsightFace model or real face images.
"""

import os
import tempfile

import cv2
import numpy as np
import pytest

from app.services.models import EnrolledStudent, FaceDetection
from app.services.pipeline import CctvAttendancePipeline

FAKE_MODEL_ID = "test_fake_provider_v1"
FAKE_DIMENSION = 4


class _FakeProvider:
    model_id = FAKE_MODEL_ID
    embedding_dimension = FAKE_DIMENSION
    execution_provider = "FakeExecutionProvider"

    def __init__(self, vector=None):
        self._vector = vector if vector is not None else np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    def extract_embedding(self, aligned_face):
        return self._vector

    def is_compatible(self, stored_model_id, stored_dimension):
        return stored_model_id == self.model_id and stored_dimension == self.embedding_dimension

    def validate_embedding(self, vector):
        arr = np.asarray(vector, dtype=np.float32).flatten()
        if arr.size != self.embedding_dimension or not np.all(np.isfinite(arr)):
            raise ValueError("invalid embedding")
        if float(np.linalg.norm(arr)) < 1e-8:
            raise ValueError("zero norm")
        return arr


class _FixedCountFakeDetector:
    """Returns exactly one face for the first `active_frames` calls,
    then no face for the rest - simulates a face that only appears
    briefly."""

    def __init__(self, active_frames: int):
        self._active_frames = active_frames
        self._calls = 0

    def detect(self, sample):
        self._calls += 1
        if self._calls > self._active_frames:
            return []
        return [
            FaceDetection(
                bbox=(10.0, 10.0, 60.0, 60.0),
                landmarks=np.zeros((5, 2), dtype=np.float32),
                confidence=0.99,
                aligned_face=np.zeros((112, 112, 3), dtype=np.uint8),
            )
        ]


class _NoAttendanceRepo:
    def __init__(self):
        self.saved = None

    def save_decisions(self, session_id, decisions):
        self.saved = (session_id, decisions)


class _NoObservationPersistence:
    def replace_session_evidence(self, session_id, tracks, observations):
        pass


class _StudentRepoStub:
    def __init__(self, students):
        self._students = students

    def get_enrolled(self, class_id):
        return self._students


def _eligible_student(student_id, name="Eligible") -> EnrolledStudent:
    return EnrolledStudent(
        student_id=student_id, name=name, class_id=1,
        embedding=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
        model_id=FAKE_MODEL_ID, embedding_dimension=FAKE_DIMENSION,
        embedding_status="ACTIVE",
    )


def _make_synthetic_video(path: str, num_frames: int = 40, fps: float = 10.0) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, (64, 64))
    for i in range(num_frames):
        frame = np.full((64, 64, 3), fill_value=(i * 5) % 256, dtype=np.uint8)
        writer.write(frame)
    writer.release()


@pytest.fixture()
def synthetic_video():
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    _make_synthetic_video(path, num_frames=40, fps=10.0)  # 4 seconds @ 10fps
    yield path
    if os.path.exists(path):
        os.remove(path)


def _make_pipeline(video_path, *, detector, provider, students, attendance_repo=None, **overrides):
    kwargs = dict(
        detector=detector,
        provider=provider,
        student_repo=_StudentRepoStub(students),
        attendance_repo=attendance_repo or _NoAttendanceRepo(),
        observation_persistence=_NoObservationPersistence(),
        frame_interval=0.5,
        match_threshold=0.5,
        identity_vote_window_size=5,
        identity_min_support=3,
        identity_min_support_ratio=0.6,
        identity_min_mean_confidence=0.5,
        identity_min_margin=0.0,
        identity_conflict_support=2,
    )
    kwargs.update(overrides)
    return CctvAttendancePipeline(**kwargs)


def test_full_video_still_reaches_eof(synthetic_video):
    repo = _NoAttendanceRepo()
    pipeline = _make_pipeline(
        synthetic_video, detector=_FixedCountFakeDetector(active_frames=2),
        provider=_FakeProvider(), students=[_eligible_student(1)], attendance_repo=repo,
    )
    results = pipeline.run(video_path=synthetic_video, class_id=1, session_id=1)
    assert "error" not in results
    assert results["diagnostics"]["eof_reached"] is True
    assert results["diagnostics"]["frames_sampled"] >= 6


def test_one_frame_match_does_not_mark_legacy_attendance(synthetic_video):
    """A face appearing for only ONE sampled frame must never confirm
    a track (min_support=3), so no legacy attendance record is
    created - matching the acceptance criterion that a single
    successful cosine match cannot directly mark attendance."""
    repo = _NoAttendanceRepo()
    pipeline = _make_pipeline(
        synthetic_video, detector=_FixedCountFakeDetector(active_frames=1),
        provider=_FakeProvider(), students=[_eligible_student(1)], attendance_repo=repo,
    )
    results = pipeline.run(video_path=synthetic_video, class_id=1, session_id=1)
    assert "error" not in results
    # The eligible student still gets a legacy decision row (as
    # always), but it must be "absent" - a single-frame match must
    # never be strong enough evidence to mark them "present".
    row = next(r for r in results["attendance"] if r["student_id"] == 1)
    assert row["status"] == "absent"
    assert results["diagnostics"]["confirmed_tracks"] == 0


def test_confirmed_multi_observation_identity_feeds_legacy_attendance(synthetic_video):
    """A face appearing consistently for many frames accumulates
    enough evidence to CONFIRM, and only then feeds legacy attendance
    as 'present'."""
    repo = _NoAttendanceRepo()
    pipeline = _make_pipeline(
        synthetic_video, detector=_FixedCountFakeDetector(active_frames=10),
        provider=_FakeProvider(), students=[_eligible_student(1)], attendance_repo=repo,
        grace_period_minutes=1000,  # avoid a spurious late-absent from a slow synthetic run
    )
    results = pipeline.run(video_path=synthetic_video, class_id=1, session_id=1)
    assert "error" not in results
    assert results["diagnostics"]["confirmed_tracks"] >= 1
    student_ids = {row["student_id"] for row in results["attendance"]}
    assert 1 in student_ids
    present_row = next(row for row in results["attendance"] if row["student_id"] == 1)
    assert present_row["status"] == "present"
    assert repo.saved is not None


def test_unknown_track_does_not_mark_any_student_present(synthetic_video):
    """A face with no compatible template ever matching above
    threshold stays UNKNOWN and must not mark anyone present."""
    off_threshold_provider = _FakeProvider(vector=np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32))
    repo = _NoAttendanceRepo()
    pipeline = _make_pipeline(
        synthetic_video, detector=_FixedCountFakeDetector(active_frames=10),
        provider=off_threshold_provider, students=[_eligible_student(1)], attendance_repo=repo,
    )
    results = pipeline.run(video_path=synthetic_video, class_id=1, session_id=1)
    assert "error" not in results
    assert results["diagnostics"]["unknown_tracks"] >= 1 or results["diagnostics"]["confirmed_tracks"] == 0
    student_ids = {row["student_id"] for row in results["attendance"] if row["status"] == "present"}
    assert 1 not in student_ids


def test_incompatible_students_remain_excluded(synthetic_video):
    from app.services.models import EnrolledStudent as ES

    incompatible = ES(
        student_id=2, name="Incompatible", class_id=1,
        embedding=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
        model_id="fused_ada_swin", embedding_dimension=FAKE_DIMENSION, embedding_status="LEGACY_INCOMPATIBLE",
    )
    repo = _NoAttendanceRepo()
    pipeline = _make_pipeline(
        synthetic_video, detector=_FixedCountFakeDetector(active_frames=10),
        provider=_FakeProvider(), students=[_eligible_student(1), incompatible], attendance_repo=repo,
        grace_period_minutes=1000,
    )
    results = pipeline.run(video_path=synthetic_video, class_id=1, session_id=1)
    assert results["recognition_ineligible_count"] == 1
    attendance_ids = {row["student_id"] for row in results["attendance"]}
    assert 2 not in attendance_ids
    ineligible_ids = {d["student_id"] for d in results["ineligible_students"]}
    assert ineligible_ids == {2}


def test_zero_compatible_roster_generates_no_attendance(synthetic_video):
    repo = _NoAttendanceRepo()
    pipeline = _make_pipeline(
        synthetic_video, detector=_FixedCountFakeDetector(active_frames=10),
        provider=_FakeProvider(), students=[], attendance_repo=repo,
    )
    results = pipeline.run(video_path=synthetic_video, class_id=1, session_id=1)
    assert results["attendance_generation_status"] == "NOT_GENERATED"
    assert results["attendance"] == []
    assert repo.saved is None
    assert results["diagnostics"]["eof_reached"] is True


def test_progress_remains_monotonic(synthetic_video):
    progress_values = []
    pipeline = _make_pipeline(
        synthetic_video, detector=_FixedCountFakeDetector(active_frames=10),
        provider=_FakeProvider(), students=[_eligible_student(1)],
    )
    pipeline.run(video_path=synthetic_video, class_id=1, session_id=1, progress_callback=progress_values.append)
    assert progress_values == sorted(progress_values)
    assert all(0 <= p < 100 for p in progress_values)


def test_existing_phase3_diagnostics_remain_present(synthetic_video):
    pipeline = _make_pipeline(
        synthetic_video, detector=_FixedCountFakeDetector(active_frames=10),
        provider=_FakeProvider(), students=[_eligible_student(1)],
    )
    results = pipeline.run(video_path=synthetic_video, class_id=1, session_id=1)
    diagnostics = results["diagnostics"]
    for key in (
        "video_duration_sec", "total_frames", "frames_sampled", "faces_detected",
        "compatible_templates", "successful_matches", "eof_reached",
        "provider_model_id", "execution_provider", "recognition_eligible_count",
        "recognition_ineligible_count",
    ):
        assert key in diagnostics
