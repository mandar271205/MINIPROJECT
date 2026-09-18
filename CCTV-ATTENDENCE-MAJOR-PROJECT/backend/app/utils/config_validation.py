"""Validates Phase 3/4 recognition, tracking and voting configuration
at app startup. Invalid values fail loudly (RuntimeError) - never
clamped, never silently substituted with a "safe" default.
"""

from __future__ import annotations


class ConfigValidationError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigValidationError(message)


def validate_recognition_config(config: dict) -> None:
    _require(
        config["FACE_RECOGNITION_PROVIDER"] == "insightface_arcface",
        "FACE_RECOGNITION_PROVIDER must be 'insightface_arcface' - "
        f"got {config['FACE_RECOGNITION_PROVIDER']!r}",
    )
    _require(
        0.0 < config["FACE_MATCH_THRESHOLD"] < 1.0,
        f"FACE_MATCH_THRESHOLD must be strictly between 0 and 1 - got {config['FACE_MATCH_THRESHOLD']!r}",
    )
    _require(
        config["FRAME_SAMPLE_INTERVAL_SECONDS"] > 0.0,
        "FRAME_SAMPLE_INTERVAL_SECONDS must be greater than zero - "
        f"got {config['FRAME_SAMPLE_INTERVAL_SECONDS']!r}",
    )


def validate_tracking_config(config: dict) -> None:
    _require(
        config["TRACK_MAX_GAP_SECONDS"] > 0.0,
        f"TRACK_MAX_GAP_SECONDS must be greater than zero - got {config['TRACK_MAX_GAP_SECONDS']!r}",
    )
    _require(
        0.0 <= config["TRACK_MIN_IOU"] <= 1.0,
        f"TRACK_MIN_IOU must be between 0 and 1 - got {config['TRACK_MIN_IOU']!r}",
    )
    _require(
        config["TRACK_MAX_CENTROID_DISTANCE"] > 0.0,
        "TRACK_MAX_CENTROID_DISTANCE must be greater than zero - "
        f"got {config['TRACK_MAX_CENTROID_DISTANCE']!r}",
    )
    _require(
        config["TRACK_CLOSE_AFTER_SECONDS"] > 0.0,
        f"TRACK_CLOSE_AFTER_SECONDS must be greater than zero - got {config['TRACK_CLOSE_AFTER_SECONDS']!r}",
    )


def validate_voting_config(config: dict) -> None:
    window = config["IDENTITY_VOTE_WINDOW_SIZE"]
    min_support = config["IDENTITY_MIN_SUPPORT"]

    _require(window > 0, f"IDENTITY_VOTE_WINDOW_SIZE must be greater than zero - got {window!r}")
    _require(min_support > 0, f"IDENTITY_MIN_SUPPORT must be greater than zero - got {min_support!r}")
    _require(
        min_support <= window,
        f"IDENTITY_MIN_SUPPORT ({min_support!r}) must not exceed IDENTITY_VOTE_WINDOW_SIZE ({window!r})",
    )
    _require(
        0.0 <= config["IDENTITY_MIN_SUPPORT_RATIO"] <= 1.0,
        f"IDENTITY_MIN_SUPPORT_RATIO must be between 0 and 1 - got {config['IDENTITY_MIN_SUPPORT_RATIO']!r}",
    )
    _require(
        0.0 <= config["IDENTITY_MIN_MEAN_CONFIDENCE"] <= 1.0,
        "IDENTITY_MIN_MEAN_CONFIDENCE must be between 0 and 1 - "
        f"got {config['IDENTITY_MIN_MEAN_CONFIDENCE']!r}",
    )
    _require(
        0.0 <= config["IDENTITY_MIN_MARGIN"] <= 1.0,
        f"IDENTITY_MIN_MARGIN must be between 0 and 1 - got {config['IDENTITY_MIN_MARGIN']!r}",
    )
    _require(
        config["IDENTITY_CONFLICT_SUPPORT"] > 0,
        f"IDENTITY_CONFLICT_SUPPORT must be greater than zero - got {config['IDENTITY_CONFLICT_SUPPORT']!r}",
    )
    _require(
        config["IDENTITY_UNLOCK_POLICY"] in ("never",),
        "IDENTITY_UNLOCK_POLICY must be 'never' in Phase 4 - "
        f"got {config['IDENTITY_UNLOCK_POLICY']!r}. Unlocking a confirmed identity is a Phase 5+ policy decision.",
    )


def validate_all(config: dict) -> None:
    validate_recognition_config(config)
    validate_tracking_config(config)
    validate_voting_config(config)
