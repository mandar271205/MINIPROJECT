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

    # Phase 4 - temporary face-track association. Validated once at app
    # startup in app/__init__.py; invalid values fail loudly, never
    # silently substituted with an unsafe default.
    TRACK_MAX_GAP_SECONDS = float(os.getenv("TRACK_MAX_GAP_SECONDS", "3.0"))
    TRACK_MIN_IOU = float(os.getenv("TRACK_MIN_IOU", "0.3"))
    TRACK_MAX_CENTROID_DISTANCE = float(os.getenv("TRACK_MAX_CENTROID_DISTANCE", "80.0"))
    TRACK_CLOSE_AFTER_SECONDS = float(os.getenv("TRACK_CLOSE_AFTER_SECONDS", "6.0"))

    # Phase 4 - sliding-window identity voting. Development defaults
    # only, not scientifically calibrated - real calibration requires
    # labelled footage. See app/services/identity_voting.py.
    IDENTITY_VOTE_WINDOW_SIZE = int(os.getenv("IDENTITY_VOTE_WINDOW_SIZE", "5"))
    IDENTITY_MIN_SUPPORT = int(os.getenv("IDENTITY_MIN_SUPPORT", "3"))
    IDENTITY_MIN_SUPPORT_RATIO = float(os.getenv("IDENTITY_MIN_SUPPORT_RATIO", "0.60"))
    IDENTITY_MIN_MEAN_CONFIDENCE = float(os.getenv("IDENTITY_MIN_MEAN_CONFIDENCE", str(FACE_MATCH_THRESHOLD)))
    IDENTITY_MIN_MARGIN = float(os.getenv("IDENTITY_MIN_MARGIN", "0.03"))
    IDENTITY_CONFLICT_SUPPORT = int(os.getenv("IDENTITY_CONFLICT_SUPPORT", "2"))
    IDENTITY_UNLOCK_POLICY = os.getenv("IDENTITY_UNLOCK_POLICY", "never")

    # Phase 5 - presence-window reconstruction (gap smoothing, not
    # attendance decisions). Development defaults only - real
    # calibration requires labelled footage. See
    # app/services/presence_reconstruction.py. Half-width defaults to
    # half the sampling interval; bridge gap defaults to one full
    # sampling interval, deliberately small so a short sighting can
    # never be smoothed into full-lecture presence.
    PRESENCE_EVIDENCE_HALF_WIDTH_SECONDS = float(
        os.getenv("PRESENCE_EVIDENCE_HALF_WIDTH_SECONDS", str(FRAME_SAMPLE_INTERVAL_SECONDS / 2.0))
    )
    PRESENCE_MAX_BRIDGE_GAP_SECONDS = float(
        os.getenv("PRESENCE_MAX_BRIDGE_GAP_SECONDS", str(FRAME_SAMPLE_INTERVAL_SECONDS))
    )
    PRESENCE_ALGORITHM_VERSION = os.getenv("PRESENCE_ALGORITHM_VERSION", "presence_v1")

    CORS_ORIGINS = _split_origins(os.getenv("CORS_ORIGINS", "http://localhost:5173"))

    DEFAULT_HOD_NAME = os.getenv("DEFAULT_HOD_NAME", "HOD Admin")
    DEFAULT_HOD_EMAIL = os.getenv("DEFAULT_HOD_EMAIL", "")
    DEFAULT_HOD_PASSWORD = os.getenv("DEFAULT_HOD_PASSWORD", "")
    HOD_SEES_ALL = os.getenv("HOD_SEES_ALL", "true").lower() == "true"
