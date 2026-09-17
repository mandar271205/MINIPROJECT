"""Phase 3 - proves the pipeline reads scheduled frames through to the
video's actual EOF, even after every enrolled student has already been
matched near the start. Uses a synthetic video and fake
detector/provider (dependency-injected into CctvAttendancePipeline) so
this test is fast and deterministic - it does not depend on the real
InsightFace model or real face images.
"""

import os
import tempfile

import cv2
import numpy as np
import pytest

from app.services.models import EnrolledStudent, FaceDetection
from app.services.pipeline import CctvAttendancePipeline, PipelineConfigError

FAKE_MODEL_ID = "test_fake_provider_v1"
FAKE_DIMENSION = 4


class _FakeProvider:
    model_id = FAKE_MODEL_ID
    embedding_dimension = FAKE_DIMENSION
    execution_provider = "FakeExecutionProvider"

    def extract_embedding(self, aligned_face):
        return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    def is_compatible(self, stored_model_id, stored_dimension):
        return stored_model_id == self.model_id and stored_dimension == self.embedding_dimension

    def validate_embedding(self, vector):
        arr = np.asarray(vector, dtype=np.float32).flatten()
        if arr.size != self.embedding_dimension or not np.all(np.isfinite(arr)):
            raise ValueError("invalid embedding")
        if float(np.linalg.norm(arr)) < 1e-8:
            raise ValueError("zero norm")
        return arr


class _AlwaysDetectsFakeFace:
    """Detects exactly one "face" on every sampled frame - the video
    continuing after a match must not depend on faces stopping."""

    def detect(self, sample):
        return [
            FaceDetection(
                bbox=(0, 0, 10, 10),
                landmarks=np.zeros((5, 2), dtype=np.float32),
                confidence=0.99,
                aligned_face=np.zeros((112, 112, 3), dtype=np.uint8),
            )
        ]


class _NoAttendanceRepo:
    def save_decisions(self, session_id, decisions):
        pass


class _StudentRepoStub:
    def __init__(self, students):
        self._students = students

    def get_enrolled(self, class_id):
        return self._students


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


def test_pipeline_reads_to_eof_even_after_all_students_matched(synthetic_video):
    enrolled = [
        EnrolledStudent(
            student_id=1, name="Student One", class_id=1,
            embedding=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
            model_id=FAKE_MODEL_ID, embedding_dimension=FAKE_DIMENSION,
            embedding_status="ACTIVE",
        ),
        EnrolledStudent(
            student_id=2, name="Student Two", class_id=1,
            embedding=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
            model_id=FAKE_MODEL_ID, embedding_dimension=FAKE_DIMENSION,
            embedding_status="ACTIVE",
        ),
    ]

    pipeline = CctvAttendancePipeline(
        detector=_AlwaysDetectsFakeFace(),
        provider=_FakeProvider(),
        student_repo=_StudentRepoStub(enrolled),
        attendance_repo=_NoAttendanceRepo(),
        frame_interval=0.5,  # video is 4s long -> ~8 samples
        match_threshold=0.5,
        grace_period_minutes=10,
    )

    progress_values = []
    results = pipeline.run(
        video_path=synthetic_video,
        class_id=1,
        session_id=1,
        progress_callback=progress_values.append,
    )

    assert "error" not in results
    diagnostics = results["diagnostics"]

    # Both students match on the very first sampled frame (fake
    # detector always returns a face, fake provider always returns the
    # same embedding), yet the pipeline must keep sampling.
    assert diagnostics["eof_reached"] is True
    assert diagnostics["frames_sampled"] >= 6  # ~8 expected for a 4s video at 0.5s interval
    assert diagnostics["successful_matches"] >= diagnostics["frames_sampled"]  # both match every frame

    # The last sampled timestamp must be near the video's actual end
    # (4 seconds), not near the first frame where matches occurred.
    assert diagnostics["final_sampled_timestamp_sec"] >= 3.0

    # Progress must never reach 100 while still inside the sampling
    # loop - only the caller (attendance_service) sets 100, and only
    # after this function has already returned with eof_reached=True.
    assert all(p < 100 for p in progress_values)
    assert progress_values == sorted(progress_values)  # monotonic


def test_pipeline_rejects_invalid_match_threshold(synthetic_video):
    with pytest.raises(PipelineConfigError):
        CctvAttendancePipeline(
            detector=_AlwaysDetectsFakeFace(),
            provider=_FakeProvider(),
            student_repo=_StudentRepoStub([]),
            attendance_repo=_NoAttendanceRepo(),
            frame_interval=1.0,
            match_threshold=1.5,  # invalid: must be < 1
        )


def test_pipeline_rejects_invalid_sample_interval(synthetic_video):
    with pytest.raises(PipelineConfigError):
        CctvAttendancePipeline(
            detector=_AlwaysDetectsFakeFace(),
            provider=_FakeProvider(),
            student_repo=_StudentRepoStub([]),
            attendance_repo=_NoAttendanceRepo(),
            frame_interval=0.0,  # invalid: must be > 0
            match_threshold=0.5,
        )


def test_pipeline_handles_empty_roster_without_early_completion(synthetic_video):
    """An empty enrolment roster must not short-circuit into an
    instant 'complete' result - the video is still read through to
    EOF, with compatible_templates correctly reported as zero."""
    pipeline = CctvAttendancePipeline(
        detector=_AlwaysDetectsFakeFace(),
        provider=_FakeProvider(),
        student_repo=_StudentRepoStub([]),
        attendance_repo=_NoAttendanceRepo(),
        frame_interval=0.5,
        match_threshold=0.5,
    )

    results = pipeline.run(video_path=synthetic_video, class_id=1, session_id=1)

    assert "error" not in results
    diagnostics = results["diagnostics"]
    assert diagnostics["eof_reached"] is True
    assert diagnostics["compatible_templates"] == 0
    assert diagnostics["frames_sampled"] >= 6
    assert diagnostics["successful_matches"] == 0


def test_pipeline_fails_safely_on_unreadable_video():
    pipeline = CctvAttendancePipeline(
        detector=_AlwaysDetectsFakeFace(),
        provider=_FakeProvider(),
        student_repo=_StudentRepoStub([]),
        attendance_repo=_NoAttendanceRepo(),
        frame_interval=0.5,
        match_threshold=0.5,
    )

    results = pipeline.run(video_path="/no/such/video/file.mp4", class_id=1, session_id=1)

    assert "error" in results and results["error"]
    assert results["diagnostics"]["eof_reached"] is False
