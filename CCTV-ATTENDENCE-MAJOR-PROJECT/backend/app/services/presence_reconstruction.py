"""Phase 5 - presence-window reconstruction.

Converts trusted, confirmed recognition evidence (see the filtering
rules below) into explainable presence windows. A presence window is
NOT an attendance status - it is a time interval that trusted evidence
supports as "the student was likely present here", produced by:

  1. Filtering to trusted observations only (see filter_trusted_observations).
  2. Converting each trusted observation into a bounded coverage
     interval [t - half_width, t + half_width], clipped to the session.
  3. Merging overlapping/touching coverage into "observed" intervals
     (this is where cross-track evidence for the same student combines
     - never double-counted, since overlapping spans collapse into one).
  4. Bridging small gaps between observed intervals (<=
     max_bridge_gap_seconds) into a single window, recording the
     bridged time as "inferred" duration, separate from "observed".
  5. Leaving larger gaps as separate windows - a large absence is never
     hidden.

No raw embeddings are read or stored here. Only similarity scalars
already present on RecognitionObservation are used, and only for
mean/min/max confidence bookkeeping.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

CONFIRMED_SUPPORT = "CONFIRMED_SUPPORT"


class PresenceConfigError(ValueError):
    pass


def validate_presence_params(half_width: float, max_bridge_gap: float, algorithm_version: str) -> None:
    if not (half_width == half_width and math.isfinite(half_width)):
        raise PresenceConfigError(f"PRESENCE_EVIDENCE_HALF_WIDTH_SECONDS must be finite - got {half_width!r}")
    if not (half_width > 0.0):
        raise PresenceConfigError(
            f"PRESENCE_EVIDENCE_HALF_WIDTH_SECONDS must be greater than zero - got {half_width!r}"
        )
    if not (max_bridge_gap == max_bridge_gap and math.isfinite(max_bridge_gap)):
        raise PresenceConfigError(f"PRESENCE_MAX_BRIDGE_GAP_SECONDS must be finite - got {max_bridge_gap!r}")
    if not (max_bridge_gap >= 0.0):
        raise PresenceConfigError(
            f"PRESENCE_MAX_BRIDGE_GAP_SECONDS must be zero or greater - got {max_bridge_gap!r}"
        )
    if not (isinstance(algorithm_version, str) and algorithm_version.strip()):
        raise PresenceConfigError(f"PRESENCE_ALGORITHM_VERSION must be a non-empty string - got {algorithm_version!r}")


@dataclass
class TrustedObservation:
    """The minimal shape presence reconstruction needs, decoupled from
    the ORM so this module has no database dependency."""
    observation_id: int
    track_id: int
    timestamp_seconds: float
    confidence: float


@dataclass
class PresenceWindowResult:
    window_index: int
    start_seconds: float
    end_seconds: float
    observed_duration_seconds: float
    inferred_gap_seconds: float
    total_duration_seconds: float
    observation_count: int
    contributing_track_ids: set = field(default_factory=set)
    mean_confidence: float | None = None
    minimum_confidence: float | None = None
    maximum_confidence: float | None = None

    @property
    def contributing_track_count(self) -> int:
        return len(self.contributing_track_ids)


def _coverage_interval(
    timestamp: float, half_width: float, session_start: float, session_end: float
) -> tuple[float, float]:
    start = max(session_start, timestamp - half_width)
    end = min(session_end, timestamp + half_width)
    if end < start:
        end = start
    return start, end


def reconstruct_student_windows(
    observations: list[TrustedObservation],
    *,
    session_start: float,
    session_end: float,
    half_width: float,
    max_bridge_gap: float,
    algorithm_version: str,
) -> list[PresenceWindowResult]:
    """Reconstructs presence windows for a single student from their
    trusted observations (already filtered and already confirmed to
    belong to non-conflicting tracks - see filter_trusted_observations).

    Deterministic: identical input always produces identical output.
    Complexity is O(n log n) - one sort, then one linear merge pass.
    """
    validate_presence_params(half_width, max_bridge_gap, algorithm_version)

    if not observations or session_end <= session_start:
        return []

    # Deterministic order: timestamp, then track, then observation id -
    # ties never depend on incidental dict/query ordering.
    ordered = sorted(observations, key=lambda o: (o.timestamp_seconds, o.track_id, o.observation_id))

    # Step 1: per-observation bounded coverage interval.
    raw_intervals = []
    for obs in ordered:
        start, end = _coverage_interval(obs.timestamp_seconds, half_width, session_start, session_end)
        raw_intervals.append((start, end, obs))

    # Step 2: merge overlapping/touching coverage into "observed"
    # segments. This is exactly where multiple tracks for the same
    # student combine - and where overlapping coverage stops being
    # double-counted, because merged segment length is (end - start)
    # of the union, never the sum of the inputs that built it.
    merged_segments: list[dict] = []
    for start, end, obs in raw_intervals:
        if merged_segments and start <= merged_segments[-1]["end"]:
            seg = merged_segments[-1]
            seg["end"] = max(seg["end"], end)
            seg["observations"].append(obs)
        else:
            merged_segments.append({"start": start, "end": end, "observations": [obs]})

    # Step 3: bridge small gaps between merged segments into one final
    # window; larger gaps become separate windows. Deterministic
    # linear scan over the already-sorted, already-merged segments.
    windows: list[PresenceWindowResult] = []
    current: PresenceWindowResult | None = None

    for seg in merged_segments:
        seg_observed = seg["end"] - seg["start"]
        if current is None:
            current = PresenceWindowResult(
                window_index=len(windows),
                start_seconds=seg["start"],
                end_seconds=seg["end"],
                observed_duration_seconds=seg_observed,
                inferred_gap_seconds=0.0,
                total_duration_seconds=seg_observed,
                observation_count=len(seg["observations"]),
                contributing_track_ids={o.track_id for o in seg["observations"]},
            )
            current._obs = list(seg["observations"])  # type: ignore[attr-defined]
            continue

        gap = seg["start"] - current.end_seconds
        if gap <= max_bridge_gap:
            current.inferred_gap_seconds += max(0.0, gap)
            current.end_seconds = seg["end"]
            current.observed_duration_seconds += seg_observed
            current.observation_count += len(seg["observations"])
            current.contributing_track_ids |= {o.track_id for o in seg["observations"]}
            current.total_duration_seconds = current.observed_duration_seconds + current.inferred_gap_seconds
            current._obs.extend(seg["observations"])  # type: ignore[attr-defined]
        else:
            _finalize_confidence(current)
            windows.append(current)
            current = PresenceWindowResult(
                window_index=len(windows),
                start_seconds=seg["start"],
                end_seconds=seg["end"],
                observed_duration_seconds=seg_observed,
                inferred_gap_seconds=0.0,
                total_duration_seconds=seg_observed,
                observation_count=len(seg["observations"]),
                contributing_track_ids={o.track_id for o in seg["observations"]},
            )
            current._obs = list(seg["observations"])  # type: ignore[attr-defined]

    if current is not None:
        _finalize_confidence(current)
        windows.append(current)

    return windows


def filter_trusted_observations_by_student(session_id: int) -> tuple[dict[int, list[TrustedObservation]], int]:
    """Batch-loads all trusted evidence for a session in exactly two
    queries (tracks, then observations) - never one query per
    observation - grouped by the confirmed student id each track
    supports.

    Trusted means: the track is CONFIRMED, has a confirmed_student_id,
    and has NO identity conflict (a conflicted track is excluded in
    its entirety - the conservative rule from Phase 5 section D).
    Within a trusted track, only CONFIRMED_SUPPORT observations that
    themselves name the same confirmed student, with a finite
    non-negative timestamp and a finite similarity, are kept; exact
    duplicate observations are only ever counted once.

    Returns (observations_by_student_id, excluded_conflicting_track_count).
    """
    from ..models.observation import FaceTrack, RecognitionObservation

    tracks = FaceTrack.query.filter_by(session_id=session_id, track_state="CONFIRMED").all()
    excluded_conflicting_tracks = sum(1 for t in tracks if t.identity_conflict)
    trusted_track_to_student = {
        t.id: t.confirmed_student_id
        for t in tracks
        if t.confirmed_student_id is not None and not t.identity_conflict
    }

    if not trusted_track_to_student:
        return {}, excluded_conflicting_tracks

    observations = RecognitionObservation.query.filter(
        RecognitionObservation.session_id == session_id,
        RecognitionObservation.track_id.in_(trusted_track_to_student.keys()),
        RecognitionObservation.evidence_state == CONFIRMED_SUPPORT,
    ).all()

    by_student: dict[int, list[TrustedObservation]] = {}
    seen_keys: set[tuple] = set()
    for obs in observations:
        student_id = trusted_track_to_student.get(obs.track_id)
        if student_id is None or obs.top1_student_id != student_id:
            continue
        if obs.timestamp_seconds is None or not math.isfinite(obs.timestamp_seconds) or obs.timestamp_seconds < 0:
            continue
        if obs.top1_similarity is None or not math.isfinite(obs.top1_similarity):
            continue

        dedupe_key = (obs.session_id, obs.track_id, obs.frame_index, obs.detection_index)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        by_student.setdefault(student_id, []).append(
            TrustedObservation(
                observation_id=obs.id, track_id=obs.track_id,
                timestamp_seconds=obs.timestamp_seconds, confidence=obs.top1_similarity,
            )
        )

    return by_student, excluded_conflicting_tracks


def reconstruct_session_presence(
    *,
    session_id: int,
    eligible_students: list,
    ineligible_diagnostics: list[dict],
    session_start: float,
    session_end: float,
    half_width: float,
    max_bridge_gap: float,
    algorithm_version: str,
) -> dict:
    """Top-level Phase 5 orchestration for one session: filters trusted
    evidence, reconstructs windows per eligible student, and computes
    each student's presence summary (or a safe ineligible entry for
    students with no compatible template - never a fabricated 0%).

    *eligible_students* is a list of objects with `.student_id` and
    `.name` (e.g. the EnrolledStudent list already computed by
    recognition_eligibility.classify_enrolled_students()) - reused
    rather than re-deriving eligibility with different logic.
    """
    validate_presence_params(half_width, max_bridge_gap, algorithm_version)

    trusted_by_student, excluded_conflicting_tracks = filter_trusted_observations_by_student(session_id)
    valid_seconds = session_end - session_start

    windows_by_student: dict[int, list[PresenceWindowResult]] = {}
    summaries: list[dict] = []

    for student in eligible_students:
        observations = trusted_by_student.get(student.student_id, [])
        windows = (
            reconstruct_student_windows(
                observations, session_start=session_start, session_end=session_end,
                half_width=half_width, max_bridge_gap=max_bridge_gap, algorithm_version=algorithm_version,
            )
            if observations
            else []
        )
        windows_by_student[student.student_id] = windows

        total_presence = sum(w.total_duration_seconds for w in windows)
        percentage = None
        if valid_seconds > 0:
            raw_pct = (total_presence / valid_seconds) * 100.0
            # Clamped only for presentation, after the raw value is
            # already known - clamping is never used to hide a
            # double-counting bug; total_presence itself can never
            # exceed valid_seconds because windows are built from
            # already-unioned, non-overlapping coverage.
            percentage = min(100.0, max(0.0, raw_pct))

        confidences = [w.mean_confidence for w in windows if w.mean_confidence is not None]
        summaries.append(
            {
                "student_id": student.student_id,
                "eligible_for_reconstruction": True,
                "window_count": len(windows),
                "observation_count": sum(w.observation_count for w in windows),
                "observed_presence_seconds": sum(w.observed_duration_seconds for w in windows),
                "inferred_gap_seconds": sum(w.inferred_gap_seconds for w in windows),
                "total_presence_seconds": total_presence,
                "valid_session_seconds": valid_seconds,
                "presence_percentage": percentage,
                "first_confirmed_presence_seconds": windows[0].start_seconds if windows else None,
                "last_confirmed_presence_seconds": windows[-1].end_seconds if windows else None,
                "mean_confidence": (sum(confidences) / len(confidences)) if confidences else None,
                "algorithm_version": algorithm_version,
            }
        )

    for diagnostic in ineligible_diagnostics:
        summaries.append(
            {
                "student_id": diagnostic["student_id"],
                "eligible_for_reconstruction": False,
                "presence_calculated": False,
                "requires_reenrollment": diagnostic.get("requires_reenrollment", True),
                "reason_code": diagnostic.get("reason_code"),
            }
        )

    return {
        "summaries": summaries,
        "windows_by_student": windows_by_student,
        "excluded_conflicting_tracks": excluded_conflicting_tracks,
        "valid_session_seconds": valid_seconds,
    }


def _finalize_confidence(window: PresenceWindowResult) -> None:
    confidences = [o.confidence for o in window._obs if o.confidence is not None and math.isfinite(o.confidence)]  # type: ignore[attr-defined]
    if confidences:
        window.mean_confidence = sum(confidences) / len(confidences)
        window.minimum_confidence = min(confidences)
        window.maximum_confidence = max(confidences)
    del window._obs  # type: ignore[attr-defined]
