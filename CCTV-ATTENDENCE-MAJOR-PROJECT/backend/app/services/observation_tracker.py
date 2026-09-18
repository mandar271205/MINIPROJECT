"""Phase 4 - temporary spatial face-track association across sampled
frames within one video-processing run.

This is deliberately NOT FirstAppearanceTracker (kept separate, see
first_appearance.py) and NOT a general-purpose multi-object tracking
framework - just a small deterministic greedy nearest-box heuristic
that groups face detections likely to belong to the same physical face
across nearby sampled frames, so recognition evidence can be
accumulated per track before identity_voting.py decides anything.

A FaceTrackAssociator track is a temporary visual grouping, never a
confirmed student identity by itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Bbox = tuple[float, float, float, float]


class TrackConfigError(ValueError):
    """Raised for invalid tracker configuration. Never silently
    substituted with a different value."""


def validate_tracker_config(
    *, max_gap_seconds: float, min_iou: float, max_centroid_distance: float, close_after_seconds: float
) -> None:
    if not (max_gap_seconds > 0.0):
        raise TrackConfigError(f"TRACK_MAX_GAP_SECONDS must be greater than zero - got {max_gap_seconds!r}")
    if not (0.0 <= min_iou <= 1.0):
        raise TrackConfigError(f"TRACK_MIN_IOU must be between 0 and 1 - got {min_iou!r}")
    if not (max_centroid_distance > 0.0):
        raise TrackConfigError(
            f"TRACK_MAX_CENTROID_DISTANCE must be greater than zero - got {max_centroid_distance!r}"
        )
    if not (close_after_seconds > 0.0):
        raise TrackConfigError(
            f"TRACK_CLOSE_AFTER_SECONDS must be greater than zero - got {close_after_seconds!r}"
        )


def _centroid(bbox: Bbox) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def iou(a: Bbox, b: Bbox) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    if union <= 0.0:
        return 0.0
    return inter / union


def centroid_distance(a: Bbox, b: Bbox) -> float:
    ax, ay = _centroid(a)
    bx, by = _centroid(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


@dataclass
class TrackedDetection:
    """One face detection presented to the associator for one sampled
    frame."""
    bbox: Bbox
    frame_index: int | None = None
    detection_index: int = 0


@dataclass
class _ActiveTrack:
    track_key: str
    bbox: Bbox
    last_seen_sec: float
    first_seen_sec: float
    age: int = 1
    closed: bool = False


@dataclass
class AssociationResult:
    track_key: str
    is_new_track: bool


class FaceTrackAssociator:
    """Deterministic greedy nearest-box track association.

    For each sampled frame, computes an association cost between every
    still-active track and every new detection, gates candidates by
    time gap / IoU / centroid distance, then assigns greedily by best
    cost first, guaranteeing at most one detection per track and one
    track per detection. Unmatched detections start new tracks; tracks
    left unmatched for longer than close_after_seconds are marked
    closed and never reused.
    """

    def __init__(
        self,
        *,
        max_gap_seconds: float,
        min_iou: float,
        max_centroid_distance: float,
        close_after_seconds: float,
    ) -> None:
        validate_tracker_config(
            max_gap_seconds=max_gap_seconds,
            min_iou=min_iou,
            max_centroid_distance=max_centroid_distance,
            close_after_seconds=close_after_seconds,
        )
        self.max_gap_seconds = max_gap_seconds
        self.min_iou = min_iou
        self.max_centroid_distance = max_centroid_distance
        self.close_after_seconds = close_after_seconds
        self._tracks: list[_ActiveTrack] = []
        self._next_track_number = 1

    def _new_track_key(self) -> str:
        key = f"track-{self._next_track_number:04d}"
        self._next_track_number += 1
        return key

    def _close_stale_tracks(self, timestamp_sec: float) -> None:
        for track in self._tracks:
            if not track.closed and (timestamp_sec - track.last_seen_sec) > self.close_after_seconds:
                track.closed = True

    def associate(self, detections: list[TrackedDetection], timestamp_sec: float) -> list[AssociationResult]:
        """Returns one AssociationResult per detection, in the same
        order as `detections`. Deterministic for a given input
        sequence: candidate ties are broken by (cost, track_key,
        detection_index)."""
        self._close_stale_tracks(timestamp_sec)
        open_tracks = [t for t in self._tracks if not t.closed]

        candidates: list[tuple[float, int, int]] = []  # (cost, track_index, detection_index)
        for ti, track in enumerate(open_tracks):
            gap = timestamp_sec - track.last_seen_sec
            if gap < 0 or gap > self.max_gap_seconds:
                continue
            for di, det in enumerate(detections):
                overlap = iou(track.bbox, det.bbox)
                distance = centroid_distance(track.bbox, det.bbox)
                if overlap < self.min_iou and distance > self.max_centroid_distance:
                    continue
                # Lower cost = better match. IoU dominates; centroid
                # distance only breaks near-ties between similar-IoU
                # candidates.
                cost = (1.0 - overlap) + min(distance / max(self.max_centroid_distance, 1e-6), 1.0) * 0.01
                candidates.append((cost, ti, di))

        candidates.sort(key=lambda c: (c[0], open_tracks[c[1]].track_key, c[2]))

        assigned_track_indices: set[int] = set()
        assigned_detection_indices: set[int] = set()
        results: list[AssociationResult | None] = [None] * len(detections)

        for cost, ti, di in candidates:
            if ti in assigned_track_indices or di in assigned_detection_indices:
                continue
            assigned_track_indices.add(ti)
            assigned_detection_indices.add(di)
            track = open_tracks[ti]
            track.bbox = detections[di].bbox
            track.last_seen_sec = timestamp_sec
            track.age += 1
            results[di] = AssociationResult(track_key=track.track_key, is_new_track=False)

        for di, det in enumerate(detections):
            if results[di] is None:
                key = self._new_track_key()
                self._tracks.append(
                    _ActiveTrack(track_key=key, bbox=det.bbox, last_seen_sec=timestamp_sec, first_seen_sec=timestamp_sec)
                )
                results[di] = AssociationResult(track_key=key, is_new_track=True)

        return results  # type: ignore[return-value]

    def close_all(self) -> None:
        """Closes every remaining active track - called once at EOF."""
        for track in self._tracks:
            track.closed = True

    @property
    def track_keys(self) -> list[str]:
        return [t.track_key for t in self._tracks]
