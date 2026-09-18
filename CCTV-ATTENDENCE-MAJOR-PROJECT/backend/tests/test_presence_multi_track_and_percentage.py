"""Phase 5 - multiple-track merging and presence-percentage tests
(categories 4 and 5 of the required tests). Uses the pure
dataclass-level reconstruct_student_windows/reconstruct_session_presence
API - no database needed for these calculations.
"""

from types import SimpleNamespace

from app.services.presence_reconstruction import (
    TrustedObservation,
    reconstruct_session_presence,
    reconstruct_student_windows,
)


def _obs(track_id, t, confidence=0.8, obs_id=None):
    return TrustedObservation(
        observation_id=obs_id if obs_id is not None else int(t * 1000) + track_id,
        track_id=track_id, timestamp_seconds=t, confidence=confidence,
    )


# --------------------------------------------------------------------------
# Multiple-track tests
# --------------------------------------------------------------------------

def test_two_clean_nonoverlapping_tracks_merge_chronologically():
    obs = [_obs(1, 2.5), _obs(2, 37.5)]
    windows = reconstruct_student_windows(
        obs, session_start=0.0, session_end=100.0,
        half_width=2.5, max_bridge_gap=5.0, algorithm_version="presence_v1",
    )
    assert len(windows) == 2
    assert windows[0].start_seconds < windows[1].start_seconds
    assert windows[0].contributing_track_ids == {1}
    assert windows[1].contributing_track_ids == {2}


def test_overlapping_tracks_for_same_student_do_not_double_count():
    # Track 1 and track 2 both cover ~t=20 at the same time -> must merge
    # into a single window, never sum both tracks' coverage.
    obs = [_obs(1, 20.0), _obs(2, 20.5)]
    windows = reconstruct_student_windows(
        obs, session_start=0.0, session_end=100.0,
        half_width=2.5, max_bridge_gap=5.0, algorithm_version="presence_v1",
    )
    assert len(windows) == 1
    assert windows[0].contributing_track_ids == {1, 2}
    assert windows[0].contributing_track_count == 2
    # Union of [17.5,22.5] and [18,23] = [17.5,23] = 5.5s, not 10s.
    assert windows[0].observed_duration_seconds == 5.5


def test_closed_and_recreated_track_still_contributes():
    # Track 1 closes, then track 3 (a re-detection of the same student
    # later) picks up - both must still contribute to the final windows.
    obs = [_obs(1, 2.5), _obs(3, 60.5)]
    windows = reconstruct_student_windows(
        obs, session_start=0.0, session_end=100.0,
        half_width=2.5, max_bridge_gap=5.0, algorithm_version="presence_v1",
    )
    assert len(windows) == 2
    all_tracks = set()
    for w in windows:
        all_tracks |= w.contributing_track_ids
    assert all_tracks == {1, 3}


def test_large_cross_track_gap_creates_separate_windows():
    obs = [_obs(1, 2.5), _obs(2, 97.5)]
    windows = reconstruct_student_windows(
        obs, session_start=0.0, session_end=100.0,
        half_width=2.5, max_bridge_gap=5.0, algorithm_version="presence_v1",
    )
    assert len(windows) == 2


def test_contributing_track_count_reported_correctly():
    obs = [_obs(1, 20.0), _obs(2, 20.5), _obs(5, 21.0)]
    windows = reconstruct_student_windows(
        obs, session_start=0.0, session_end=100.0,
        half_width=2.5, max_bridge_gap=5.0, algorithm_version="presence_v1",
    )
    assert len(windows) == 1
    assert windows[0].contributing_track_count == 3


# --------------------------------------------------------------------------
# Presence-percentage tests (via reconstruct_session_presence)
# --------------------------------------------------------------------------

def _student(sid):
    return SimpleNamespace(student_id=sid, name=f"Student {sid}")


def test_percentage_formula_correctness():
    # Session is 100s; student is present for exactly 25s of observed
    # coverage with no gaps -> 25%.
    trusted = {1: [_obs(10, 12.5)]}  # half_width=12.5 -> coverage [0,25]

    class _Patch:
        pass

    result = _run_session_presence(trusted, half_width=12.5, session_end=100.0)
    summary = result["summaries"][0]
    assert summary["total_presence_seconds"] == 25.0
    assert summary["presence_percentage"] == 25.0


def test_zero_evidence_gives_zero_seconds_not_none():
    result = _run_session_presence({}, half_width=2.5, session_end=100.0)
    summary = result["summaries"][0]
    assert summary["total_presence_seconds"] == 0.0
    assert summary["presence_percentage"] == 0.0
    assert summary["window_count"] == 0


def test_zero_valid_duration_fails_safely_with_none_percentage():
    result = _run_session_presence({1: [_obs(10, 12.5)]}, half_width=2.5, session_end=0.0)
    summary = result["summaries"][0]
    assert summary["presence_percentage"] is None
    assert summary["valid_session_seconds"] == 0.0


def test_percentage_never_exceeds_100():
    # Half-width large enough that raw coverage would exceed the session
    # duration if summed naively; percentage must still clamp to 100.
    trusted = {1: [_obs(1, 50.0)]}
    result = _run_session_presence(trusted, half_width=200.0, session_end=100.0)
    summary = result["summaries"][0]
    assert summary["presence_percentage"] == 100.0
    assert summary["total_presence_seconds"] <= summary["valid_session_seconds"]


def test_percentage_rounding_only_at_presentation_not_internal():
    # 1/3 of a 30s session -> repeating decimal; internal seconds value
    # must retain full float precision, only display-layer rounds it.
    trusted = {1: [_obs(10, 5.0)]}  # half_width=5 -> coverage [0,10], 10/30
    result = _run_session_presence(trusted, half_width=5.0, session_end=30.0)
    summary = result["summaries"][0]
    assert summary["total_presence_seconds"] == 10.0
    assert abs(summary["presence_percentage"] - (10.0 / 30.0 * 100.0)) < 1e-9


def _run_session_presence(trusted_by_student, *, half_width, session_end):
    eligible = [_student(sid) for sid in ({1} | set(trusted_by_student.keys()))]

    import app.services.presence_reconstruction as pr

    original = pr.filter_trusted_observations_by_student
    pr.filter_trusted_observations_by_student = lambda session_id: (trusted_by_student, 0)
    try:
        return pr.reconstruct_session_presence(
            session_id=1, eligible_students=eligible, ineligible_diagnostics=[],
            session_start=0.0, session_end=session_end, half_width=half_width,
            max_bridge_gap=5.0, algorithm_version="presence_v1",
        )
    finally:
        pr.filter_trusted_observations_by_student = original
