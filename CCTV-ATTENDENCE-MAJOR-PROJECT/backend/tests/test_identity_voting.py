"""Phase 4 - sliding-window identity voting tests."""

import pytest

from app.services.identity_voting import IdentityVotingEngine, VoteObservation, VotingConfigError


def _engine(**overrides):
    defaults = dict(
        window_size=5, min_support=3, min_support_ratio=0.60,
        min_mean_confidence=0.55, min_margin=0.03, conflict_support=2,
    )
    defaults.update(overrides)
    return IdentityVotingEngine(**defaults)


def _obs(student_id, sim, *, t, top2=None, top2_sim=None, above=True):
    return VoteObservation(
        top1_student_id=student_id, top1_similarity=sim,
        top2_student_id=top2, top2_similarity=top2_sim,
        above_threshold=above, timestamp_sec=t,
    )


def test_one_positive_frame_does_not_confirm():
    engine = _engine()
    result = engine.vote([_obs(1, 0.9, t=0.0)])
    assert result.state != "CONFIRMED"


def test_insufficient_observations_remain_unconfirmed():
    engine = _engine(min_support=3)
    result = engine.vote([_obs(1, 0.9, t=0.0), _obs(1, 0.9, t=1.0)])
    assert result.state == "UNCONFIRMED"


def test_consistent_3_of_5_evidence_confirms():
    engine = _engine(min_support=3, min_support_ratio=0.6, min_mean_confidence=0.5, min_margin=0.03)
    obs = [
        _obs(1, 0.9, t=0.0, top2=2, top2_sim=0.5),
        _obs(1, 0.85, t=1.0, top2=2, top2_sim=0.5),
        _obs(2, 0.6, t=2.0, top2=1, top2_sim=0.55),  # one weak "other" frame
        _obs(1, 0.88, t=3.0, top2=2, top2_sim=0.5),
        _obs(1, 0.9, t=4.0, top2=2, top2_sim=0.5),
    ]
    result = engine.vote(obs)
    assert result.state == "CONFIRMED"
    assert result.confirmed_student_id == 1
    assert result.support_count == 4


def test_insufficient_support_ratio_does_not_confirm():
    engine = _engine(min_support=2, min_support_ratio=0.9, min_mean_confidence=0.5, min_margin=0.0)
    obs = [
        _obs(1, 0.9, t=0.0),
        _obs(1, 0.9, t=1.0),
        _obs(2, 0.6, t=2.0),
        _obs(3, 0.6, t=3.0),
        _obs(4, 0.6, t=4.0),
    ]
    result = engine.vote(obs)
    assert result.state != "CONFIRMED"


def test_low_mean_confidence_does_not_confirm():
    engine = _engine(min_support=3, min_support_ratio=0.6, min_mean_confidence=0.9, min_margin=0.0)
    obs = [_obs(1, 0.6, t=i) for i in range(5)]
    result = engine.vote(obs)
    assert result.state != "CONFIRMED"
    assert result.state == "UNKNOWN"


def test_small_top_two_margin_becomes_ambiguous():
    engine = _engine(min_support=3, min_support_ratio=0.6, min_mean_confidence=0.5, min_margin=0.1)
    obs = [
        _obs(1, 0.70, t=0.0, top2=2, top2_sim=0.68),
        _obs(1, 0.71, t=1.0, top2=2, top2_sim=0.67),
        _obs(1, 0.70, t=2.0, top2=2, top2_sim=0.69),
    ]
    result = engine.vote(obs)
    assert result.state == "AMBIGUOUS"
    assert result.confirmed_student_id is None


def test_below_threshold_evidence_becomes_unknown():
    engine = _engine()
    obs = [_obs(1, 0.9, t=i, above=False) for i in range(5)]
    result = engine.vote(obs)
    assert result.state == "UNKNOWN"


def test_window_discards_observations_older_than_n():
    engine = _engine(window_size=3, min_support=2, min_support_ratio=0.5, min_mean_confidence=0.5, min_margin=0.0)
    # 3 old observations for student 1, then 3 new ones for student 2 -
    # only the last 3 (window_size=3) should count.
    obs = [_obs(1, 0.9, t=0.0), _obs(1, 0.9, t=1.0), _obs(1, 0.9, t=2.0)]
    obs += [_obs(2, 0.9, t=3.0), _obs(2, 0.9, t=4.0), _obs(2, 0.9, t=5.0)]
    result = engine.vote(obs)
    assert result.state == "CONFIRMED"
    assert result.confirmed_student_id == 2


def test_confirmation_timestamp_is_deterministic():
    engine = _engine(min_support=3, min_support_ratio=0.6, min_mean_confidence=0.5, min_margin=0.0)
    obs = [_obs(1, 0.9, t=5.0), _obs(1, 0.9, t=6.0), _obs(1, 0.9, t=7.0)]
    r1 = engine.vote(list(obs))
    r2 = engine.vote(list(obs))
    assert r1.confirmation_timestamp_sec == r2.confirmation_timestamp_sec == 5.0


def test_invalid_voting_config_rejected():
    with pytest.raises(VotingConfigError):
        IdentityVotingEngine(
            window_size=0, min_support=3, min_support_ratio=0.6,
            min_mean_confidence=0.5, min_margin=0.0, conflict_support=2,
        )
    with pytest.raises(VotingConfigError):
        IdentityVotingEngine(
            window_size=3, min_support=5, min_support_ratio=0.6,  # min_support > window_size
            min_mean_confidence=0.5, min_margin=0.0, conflict_support=2,
        )
    with pytest.raises(VotingConfigError):
        IdentityVotingEngine(
            window_size=5, min_support=3, min_support_ratio=1.5,  # out of range
            min_mean_confidence=0.5, min_margin=0.0, conflict_support=2,
        )
