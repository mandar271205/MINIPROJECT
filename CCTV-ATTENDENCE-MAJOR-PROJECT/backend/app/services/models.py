"""Data-transfer objects used across all architecture modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np


@dataclass
class FrameSample:
    """One sampled frame from the video."""
    index: int
    timestamp_sec: float
    frame: np.ndarray  # BGR HxWx3


@dataclass
class FaceDetection:
    """A single detected face in a frame."""
    bbox: tuple[int, int, int, int]       # x1, y1, x2, y2
    landmarks: np.ndarray                 # (5, 2) – five facial landmarks
    confidence: float
    aligned_face: np.ndarray              # 112x112 BGR aligned crop


@dataclass
class FaceEmbedding:
    """A 512-D face embedding vector."""
    vector: np.ndarray     # (512,) float32
    model_name: str


@dataclass
class MatchResult:
    """Result of matching a face against the enrolled database."""
    student_id: int | None
    student_name: str | None
    similarity: float
    is_match: bool


@dataclass
class FirstAppearance:
    """Earliest sighting of a student in the video."""
    student_id: int
    student_name: str
    first_seen_sec: float
    confidence: float


@dataclass
class AttendanceDecision:
    """Final attendance verdict for one student."""
    student_id: int
    student_name: str
    status: str              # 'present' | 'late-absent' | 'absent'
    first_seen_sec: float | None
    confidence: float | None


@dataclass
class EnrolledStudent:
    """A student record with their stored embedding."""
    student_id: int
    name: str
    class_id: int
    embedding: np.ndarray   # (512,) float32


@dataclass
class NotificationPayload:
    """Payload for an outbound notification."""
    channel: str             # 'email' | 'sms'
    recipient: str
    subject: str
    message: str
    attachment_path: str | None = None


@dataclass
class AttendanceReport:
    """A generated attendance report."""
    class_id: int
    session_id: int
    created_at: datetime
    rows: list[AttendanceDecision]
    xlsx_path: str | None = None
    pdf_path: str | None = None
