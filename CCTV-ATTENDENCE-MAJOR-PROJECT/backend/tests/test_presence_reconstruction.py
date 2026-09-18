"""Phase 5 - presence-window reconstruction: coverage-interval and
gap-smoothing unit tests (categories 2 and 3 of the required tests).
Uses the pure dataclass-level API (no database) for speed and
determinism.
"""

import pytest

from app.services.presence_reconstruction import (
    PresenceConfigError,
    TrustedObservation,
    reconstruct_student_windows,
    validate_presence_params,
)


def _obs(track_id, t, confidence=0.8, obs_id=None):
    return TrustedObservation(
        observation_id=obs_id if obs_id is not None else int(t * 1000),
        track_id=track_id, timestamp_seconds=t, confidence=confidence,
    )


# --------------------------------------------------------------------------
# Coverage-interval tests
# --------------------------------------------------------------------------

def test_one_observation_creates_only_bounded_coverage():
    windows = reconstruct_student_windows(
        [_obs(1, 20.0)], session_start=0.0, session_end=100.0,
        half_width=2.5, max_bridge_gap=5.0, algorithm_version="presence_v1",
    )
    assert len(windows) == 1
    assert windows[0].start_seconds == 17.5
    assert windows[0].end_seconds == 22.5
    assert windows[0].observed_duration_seconds == 5.0
    assert windows[0].inferred_gap_seconds == 0.0


def test_observation_near_session_start_is_clipped_to_zero():
    windows = reconstruct_student_windows(
        [_obs(1, 1.0)], session_start=0.0, session_end=100.0,
        half_width=2.5, max_bridge_gap=5.0, algorithm_version="presence_v1",
    )
    assert windows[0].start_seconds == 0.0  # clipped, not -1.5
    assert windows[0].end_seconds == 3.5


def test_observation_near_session_end_is_clipped_to_duration():
    windows = reconstruct_student_windows(
        [_obs(1, 99.0)], session_start=0.0, session_end=100.0,
        half_width=2.5, max_bridge_gap=5.0, algorithm_version="presence_v1",
    )
    assert windows[0].end_seconds == 100.0  # clipped, not 101.5
    assert windows[0].start_seconds == 96.5


def test_overlapping_coverage_intervals_are_unioned():
    # Two observations 1s apart with half_width=2.5 -> coverage overlaps
    windows = reconstruct_student_windows(
        [_obs(1, 20.0), _obs(1, 21.0)], session_start=0.0, session_end=100.0,
        half_width=2.5, max_bridge_gap=5.0, algorithm_version="presence_v1",
    )
    assert len(windows) == 1
    # Union of [17.5,22.5] and [18.5,23.5] = [17.5, 23.5], length 6 - not 10
    assert windows[0].observed_duration_seconds == 6.0


def test_duplicate_intervals_do_not_increase_duration():
    windows = reconstruct_student_windows(
        [_obs(1, 20.0, obs_id=1), _obs(1, 20.0, obs_id=2)], session_start=0.0, session_end=100.0,
        half_width=2.5, max_bridge_gap=5.0, algorithm_version="presence_v1",
    )
    assert len(windows) == 1
    assert windows[0].observed_duration_seconds == 5.0  # not 10.0


def test_coverage_never_exceeds_session_boundaries():
    windows = reconstruct_student_windows(
        [_obs(1, 0.0), _obs(1, 100.0)], session_start=0.0, session_end=100.0,
        half_width=50.0, max_bridge_gap=5.0, algorithm_version="presence_v1",
    )
    for w in windows:
        assert w.start_seconds >= 0.0
        assert w.end_seconds <= 100.0


# --------------------------------------------------------------------------
# Gap-smoothing tests
# --------------------------------------------------------------------------

def test_gap_below_threshold_merges_windows():
    # Coverage intervals (half_width=0): [0,5],[8,13],[35,40] via
    # observations at midpoints with half_width chosen to produce
    # exactly these bounds.
    obs = [
        _obs(1, 2.5, obs_id=1), _obs(1, 10.5, obs_id=2), _obs(1, 37.5, obs_id=3),
    ]
    # Use half_width=2.5 so obs at 2.5 -> [0,5], at 10.5 -> [8,13], at 37.5 -> [35,40]
    windows = reconstruct_student_windows(
        obs, session_start=0.0, session_end=100.0,
        half_width=2.5, max_bridge_gap=5.0, algorithm_version="presence_v1",
    )
    assert len(windows) == 2
    first, second = windows
    assert first.start_seconds == 0.0 and first.end_seconds == 13.0
    assert first.observed_duration_seconds == 10.0
    assert first.inferred_gap_seconds == 3.0
    assert first.total_duration_seconds == 13.0
    assert second.start_seconds == 35.0 and second.end_seconds == 40.0
    assert second.inferred_gap_seconds == 0.0


def test_gap_exactly_equal_to_threshold_merges_inclusive():
    # Gap between [0,5] and [10,15] is exactly 5 = max_bridge_gap -> merge (inclusive rule)
    obs = [_obs(1, 2.5, obs_id=1), _obs(1, 12.5, obs_id=2)]
    windows = reconstruct_student_windows(
        obs, session_start=0.0, session_end=100.0,
        half_width=2.5, max_bridge_gap=5.0, algorithm_version="presence_v1",
    )
    assert len(windows) == 1
    assert windows[0].inferred_gap_seconds == 5.0


def test_gap_above_threshold_remains_separate():
    obs = [_obs(1, 2.5, obs_id=1), _obs(1, 12.6, obs_id=2)]  # gap = 5.1 > 5.0
    windows = reconstruct_student_windows(
        obs, session_start=0.0, session_end=100.0,
        half_width=2.5, max_bridge_gap=5.0, algorithm_version="presence_v1",
    )
    assert len(windows) == 2


def test_observed_and_inferred_duration_remain_separate():
    obs = [_obs(1, 2.5, obs_id=1), _obs(1, 10.5, obs_id=2)]
    windows = reconstruct_student_windows(
        obs, session_start=0.0, session_end=100.0,
        half_width=2.5, max_bridge_gap=5.0, algorithm_version="presence_v1",
    )
    w = windows[0]
    assert w.observed_duration_seconds != w.inferred_gap_seconds
    assert w.total_duration_seconds == w.observed_duration_seconds + w.inferred_gap_seconds


def test_multiple_bridged_gaps_are_summed_correctly():
    # Three segments with two small gaps between them, all bridged.
    obs = [_obs(1, 2.5, obs_id=1), _obs(1, 10.5, obs_id=2), _obs(1, 18.5, obs_id=3)]
    windows = reconstruct_student_windows(
        obs, session_start=0.0, session_end=100.0,
        half_width=2.5, max_bridge_gap=5.0, algorithm_version="presence_v1",
    )
    assert len(windows) == 1
    # segments: [0,5],[8,13],[16,21] -> gaps 3 and 3 -> inferred = 6
    assert windows[0].inferred_gap_seconds == 6.0
    assert windows[0].observed_duration_seconds == 15.0
    assert windows[0].total_duration_seconds == 21.0


def test_large_absence_is_not_hidden():
    obs = [_obs(1, 2.5, obs_id=1), _obs(1, 97.5, obs_id=2)]
    windows = reconstruct_student_windows(
        obs, session_start=0.0, session_end=100.0,
        half_width=2.5, max_bridge_gap=5.0, algorithm_version="presence_v1",
    )
    assert len(windows) == 2  # the ~90s gap must remain visible, not one 100s window


def test_bridging_is_deterministic():
    obs = [_obs(1, 2.5, obs_id=1), _obs(1, 10.5, obs_id=2), _obs(1, 37.5, obs_id=3)]

    def run():
        return reconstruct_student_windows(
            list(obs), session_start=0.0, session_end=100.0,
            half_width=2.5, max_bridge_gap=5.0, algorithm_version="presence_v1",
        )

    r1, r2 = run(), run()
    assert [(w.start_seconds, w.end_seconds) for w in r1] == [(w.start_seconds, w.end_seconds) for w in r2]


def test_final_windows_do_not_overlap():
    obs = [_obs(1, 2.5, obs_id=1), _obs(1, 37.5, obs_id=2), _obs(1, 70.5, obs_id=3)]
    windows = reconstruct_student_windows(
        obs, session_start=0.0, session_end=100.0,
        half_width=2.5, max_bridge_gap=5.0, algorithm_version="presence_v1",
    )
    for a, b in zip(windows, windows[1:]):
        assert a.end_seconds <= b.start_seconds


def test_zero_observations_produces_no_windows():
    windows = reconstruct_student_windows(
        [], session_start=0.0, session_end=100.0,
        half_width=2.5, max_bridge_gap=5.0, algorithm_version="presence_v1",
    )
    assert windows == []


def test_invalid_presence_config_rejected():
    with pytest.raises(PresenceConfigError):
        validate_presence_params(0.0, 5.0, "presence_v1")
    with pytest.raises(PresenceConfigError):
        validate_presence_params(2.5, -1.0, "presence_v1")
    with pytest.raises(PresenceConfigError):
        validate_presence_params(2.5, 5.0, "")
    with pytest.raises(PresenceConfigError):
        validate_presence_params(float("inf"), 5.0, "presence_v1")
