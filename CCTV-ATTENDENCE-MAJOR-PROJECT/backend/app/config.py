from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


def _split_origins(value: str) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", SECRET_KEY)
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=int(os.getenv("JWT_EXPIRE_HOURS", "8")))

    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    STORAGE_DIR = Path(os.getenv("STORAGE_DIR", BASE_DIR / "storage"))
    VIDEO_DIR = STORAGE_DIR / "videos"
    ENROLL_DIR = STORAGE_DIR / "enrollments"
    REPORT_DIR = STORAGE_DIR / "reports"
    TEMP_DIR = STORAGE_DIR / "tmp"

    MAX_CONTENT_LENGTH = None

    # Legacy names, kept so an existing .env keeps working unchanged.
    FRAME_SAMPLE_EVERY = float(os.getenv("FRAME_SAMPLE_EVERY", "2.0"))
    MATCH_THRESHOLD = float(os.getenv("MATCH_THRESHOLD", "0.55"))
    FLAG_MARGIN = float(os.getenv("FLAG_MARGIN", "0.05"))
    DEEPFACE_MODEL = os.getenv("DEEPFACE_MODEL", "Facenet512")
    DEEPFACE_BACKEND = os.getenv("DEEPFACE_BACKEND", "opencv")

    # Phase 3 explicit recognition configuration. Each falls back to the
    # legacy key above (never silently to a different value) so existing
    # deployments keep the same effective threshold/interval unless they
    # opt in to the new names. Validated once at app startup in
    # app/__init__.py - invalid values fail loudly, they are never
    # clamped or silently corrected.
    FACE_RECOGNITION_PROVIDER = os.getenv("FACE_RECOGNITION_PROVIDER", "insightface_arcface")
    FACE_MATCH_THRESHOLD = float(os.getenv("FACE_MATCH_THRESHOLD", str(MATCH_THRESHOLD)))
    FRAME_SAMPLE_INTERVAL_SECONDS = float(
        os.getenv("FRAME_SAMPLE_INTERVAL_SECONDS", str(FRAME_SAMPLE_EVERY))
    )

    CORS_ORIGINS = _split_origins(os.getenv("CORS_ORIGINS", "http://localhost:5173"))

    DEFAULT_HOD_NAME = os.getenv("DEFAULT_HOD_NAME", "HOD Admin")
    DEFAULT_HOD_EMAIL = os.getenv("DEFAULT_HOD_EMAIL", "")
    DEFAULT_HOD_PASSWORD = os.getenv("DEFAULT_HOD_PASSWORD", "")
    HOD_SEES_ALL = os.getenv("HOD_SEES_ALL", "true").lower() == "true"
