from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from werkzeug.utils import secure_filename


ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def save_upload(file_storage, directory: Path, prefix: str | None = None) -> Path:
    ensure_dir(directory)
    filename = secure_filename(file_storage.filename or "upload.bin")
    unique_prefix = prefix or uuid4().hex
    target = directory / f"{unique_prefix}_{filename}"
    file_storage.save(target)
    return target


def allowed_extension(filename: str, allowed: set[str]) -> bool:
    return Path(filename).suffix.lower() in allowed
