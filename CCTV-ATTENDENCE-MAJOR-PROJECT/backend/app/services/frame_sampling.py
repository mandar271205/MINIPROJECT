"""Step 2 – Frame sampling.

Extracts frames from a video at a configurable interval using OpenCV.
"""

from __future__ import annotations

from typing import Generator

import cv2
import numpy as np

from .models import FrameSample


def sample_frames(
    video_path: str,
    every_n_seconds: float = 2.0,
) -> Generator[FrameSample, None, None]:
    """
    Yield :class:`FrameSample` objects from *video_path*, extracting
    one frame every *every_n_seconds*.

    Parameters
    ----------
    video_path : str
        Path to the video file.
    every_n_seconds : float
        Interval between sampled frames (default 2.0 s).

    Yields
    ------
    FrameSample
        Contains the frame index, timestamp, and BGR pixel data.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(fps * every_n_seconds))

    frame_idx = 0
    sample_count = 0

    try:
        while frame_idx < total_frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                break

            timestamp = frame_idx / fps
            yield FrameSample(
                index=sample_count,
                timestamp_sec=round(timestamp, 3),
                frame=frame,
            )
            sample_count += 1
            frame_idx += step
    finally:
        cap.release()


def sample_frames_sequential(
    video_path: str,
    every_n_seconds: float = 2.0,
) -> Generator[FrameSample, None, None]:
    """
    Same as :func:`sample_frames` but reads frames sequentially
    (without seeking). More reliable for some codecs.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(fps * every_n_seconds))
    frame_idx = 0
    sample_count = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % step == 0:
                timestamp = frame_idx / fps
                yield FrameSample(
                    index=sample_count,
                    timestamp_sec=round(timestamp, 3),
                    frame=frame,
                )
                sample_count += 1
            frame_idx += 1
    finally:
        cap.release()
