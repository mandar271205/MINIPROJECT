"""Step 1 – Video upload / ingest.

Accepts MP4, AVI, or MOV files, validates them with OpenCV,
and stores them in the destination directory.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import cv2

ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}


def ingest_video(file_path: str | Path, destination_dir: str | Path) -> Path:
    """
    Validate and copy/move a video file into *destination_dir*.

    Parameters
    ----------
    file_path : str | Path
        Path to the uploaded video on disk.
    destination_dir : str | Path
        Target directory for permanent storage.

    Returns
    -------
    Path
        Absolute path to the saved video.

    Raises
    ------
    ValueError
        If the file extension is not supported or OpenCV cannot read it.
    """
    src = Path(file_path)
    dest_dir = Path(destination_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    if src.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported video format '{src.suffix}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # Quick validation: can OpenCV open the file?
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        cap.release()
        raise ValueError(f"OpenCV cannot open video file: {src.name}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    if frame_count < 1:
        raise ValueError("Video file contains no frames.")

    # Copy to destination with a unique name
    unique_name = f"{uuid.uuid4().hex}{src.suffix.lower()}"
    dest_path = dest_dir / unique_name
    shutil.copy2(src, dest_path)

    return dest_path.resolve()


def get_video_metadata(video_path: str | Path) -> dict:
    """Return basic metadata for a video file."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")

    metadata = {
        "fps": cap.get(cv2.CAP_PROP_FPS),
        "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "duration_sec": (
            int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) / cap.get(cv2.CAP_PROP_FPS)
            if cap.get(cv2.CAP_PROP_FPS) > 0
            else 0.0
        ),
        "codec": int(cap.get(cv2.CAP_PROP_FOURCC)),
    }
    cap.release()
    return metadata
