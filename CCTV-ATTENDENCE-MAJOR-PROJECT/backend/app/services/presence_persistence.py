"""Phase 5 - transactional, idempotent persistence of reconstructed
presence windows.

Policy (per Phase 5 spec section K): reconstruction always targets one
exact session and replaces only that session's existing presence
windows. All new windows are computed and validated BEFORE any old row
is deleted, and the delete + insert + session-metadata update happen
in a single transaction - so a failure at any point rolls back
entirely and the previous successful reconstruction (if any) survives
untouched.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from ..extensions import db
from ..models.attendance import (
    PRESENCE_STATUS_COMPLETED,
    PRESENCE_STATUS_FAILED,
    PRESENCE_STATUS_PARTIAL_EVIDENCE,
    PRESENCE_STATUS_PROCESSING,
    AttendanceSession,
)
from ..models.presence import PresenceWindow


class PresenceValidationError(ValueError):
    """A computed window failed a sanity check - reconstruction is
    aborted before anything is written, so the previous state is
    preserved untouched."""


def _validate_window_row(row: dict) -> None:
    if row["start_seconds"] < 0:
        raise PresenceValidationError("start_seconds must be >= 0")
    if row["end_seconds"] < row["start_seconds"]:
        raise PresenceValidationError("end_seconds must be >= start_seconds")
    if row["observed_duration_seconds"] < 0 or row["inferred_gap_seconds"] < 0:
        raise PresenceValidationError("observed/inferred duration must be >= 0")
    expected_total = row["observed_duration_seconds"] + row["inferred_gap_seconds"]
    if not math.isclose(row["total_duration_seconds"], expected_total, rel_tol=1e-6, abs_tol=1e-6):
        raise PresenceValidationError(
            f"total_duration_seconds ({row['total_duration_seconds']}) does not match "
            f"observed + inferred ({expected_total})"
        )
    if row["observation_count"] <= 0:
        raise PresenceValidationError("observation_count must be > 0")
    if row["contributing_track_count"] <= 0:
        raise PresenceValidationError("contributing_track_count must be > 0")
    for key in ("mean_confidence", "minimum_confidence", "maximum_confidence"):
        value = row.get(key)
        if value is not None and not (0.0 <= value <= 1.0):
            raise PresenceValidationError(f"{key} must be between 0 and 1, got {value!r}")


def replace_session_presence(
    session: AttendanceSession,
    *,
    window_rows: list[dict],
    actual_duration_seconds: float,
    valid_duration_seconds: float,
    algorithm_version: str,
    status: str,
    error_message: str | None = None,
    db_session=None,
) -> None:
    """Validates every row, then performs delete-old + insert-new +
    session-metadata-update for `session` in one transaction. Raises
    on the first invalid row without writing anything. Unrelated
    sessions, attendance records, face tracks, recognition
    observations, and student rows are never touched here."""
    sa_session = db_session or db.session

    for row in window_rows:
        _validate_window_row(row)

    try:
        PresenceWindow.query.filter_by(session_id=session.id).delete(synchronize_session=False)
        sa_session.flush()

        for row in window_rows:
            sa_session.add(PresenceWindow(session_id=session.id, **row))

        session.actual_duration_seconds = actual_duration_seconds
        session.valid_duration_seconds = valid_duration_seconds
        session.presence_algorithm_version = algorithm_version
        session.presence_reconstruction_status = status
        session.presence_reconstruction_error = error_message
        session.presence_reconstructed_at = datetime.now(timezone.utc)

        sa_session.commit()
    except Exception:
        sa_session.rollback()
        raise


def mark_reconstruction_processing(session: AttendanceSession, db_session=None) -> None:
    """Session/database-level guard against concurrent reconstruction
    of the same session - sufficient for this prototype without adding
    Redis or another lock service."""
    sa_session = db_session or db.session
    session.presence_reconstruction_status = PRESENCE_STATUS_PROCESSING
    session.presence_reconstruction_error = None
    sa_session.commit()


def mark_reconstruction_failed(session: AttendanceSession, error_message: str, db_session=None) -> None:
    sa_session = db_session or db.session
    session.presence_reconstruction_status = PRESENCE_STATUS_FAILED
    session.presence_reconstruction_error = error_message
    sa_session.commit()


__all__ = [
    "PresenceValidationError",
    "replace_session_presence",
    "mark_reconstruction_processing",
    "mark_reconstruction_failed",
    "PRESENCE_STATUS_COMPLETED",
    "PRESENCE_STATUS_PARTIAL_EVIDENCE",
    "PRESENCE_STATUS_FAILED",
    "PRESENCE_STATUS_PROCESSING",
]
