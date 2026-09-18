"""Phase 4 - persistence for face tracks and recognition observations.

Reprocessing policy (explicit, per Phase 4 spec section I): existing
Phase 4 evidence for the exact session being reprocessed is
transactionally replaced - never appended to, so re-running the same
video never duplicates observations. Only this session's own
face_tracks/recognition_observations rows are ever touched; no other
session's evidence, and no attendance/student data, is ever affected.
"""

from __future__ import annotations

from ..extensions import db
from ..models.observation import FaceTrack, RecognitionObservation


class ObservationPersistence:
    def __init__(self, db_session=None) -> None:
        self._session = db_session or db.session

    def replace_session_evidence(
        self,
        session_id: int,
        tracks: list[dict],
        observations: list[dict],
    ) -> None:
        """Transactionally replaces all face_tracks/recognition_observations
        rows for *session_id* with the given data. On any failure, the
        whole replacement is rolled back - a partial write never
        persists.

        *tracks*: list of dicts with FaceTrack column values (excluding
        session_id/id), each including a "track_key".
        *observations*: list of dicts with RecognitionObservation
        column values (excluding session_id/id/track_id), each
        including a "track_key" identifying which track it belongs to;
        replaced here with the real track_id once tracks are flushed.
        Persisted in the exact order given - callers must supply a
        deterministic order (e.g. processing order).
        """
        try:
            # Only this session's own Phase 4 rows are ever deleted.
            # Observations first (FK references tracks).
            self._session.query(RecognitionObservation).filter_by(session_id=session_id).delete(
                synchronize_session=False
            )
            self._session.query(FaceTrack).filter_by(session_id=session_id).delete(
                synchronize_session=False
            )
            self._session.flush()

            track_key_to_id: dict[str, int] = {}
            for track_data in tracks:
                data = dict(track_data)
                track_key = data.pop("track_key")
                row = FaceTrack(session_id=session_id, track_key=track_key, **data)
                self._session.add(row)
                self._session.flush()  # need row.id before inserting its observations
                track_key_to_id[track_key] = row.id

            for obs_data in observations:
                data = dict(obs_data)
                track_key = data.pop("track_key")
                row = RecognitionObservation(
                    session_id=session_id, track_id=track_key_to_id[track_key], **data
                )
                self._session.add(row)

            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    def get_tracks(self, session_id: int) -> list[FaceTrack]:
        return (
            FaceTrack.query.filter_by(session_id=session_id)
            .order_by(FaceTrack.first_seen_seconds, FaceTrack.id)
            .all()
        )

    def get_observations_page(
        self, session_id: int, track_id: int, page: int, per_page: int
    ) -> tuple[list[RecognitionObservation], int]:
        query = RecognitionObservation.query.filter_by(session_id=session_id, track_id=track_id).order_by(
            RecognitionObservation.timestamp_seconds, RecognitionObservation.id
        )
        total = query.count()
        items = query.offset((page - 1) * per_page).limit(per_page).all()
        return items, total
