"""Phase 4 - identity lock / conflict handling tests."""

from app.services.identity_voting import IdentityVotingEngine, VoteObservation


def _engine(**overrides):
    defaults = dict(
        window_size=5, min_support=3, min_support_ratio=0.60,
        min_mean_confidence=0.55, min_margin=0.03, conflict_support=2,
    )
    defaults.update(overrides)
    return IdentityVotingEngine(**defaults)


def _obs(student_id, sim, *, t, above=True):
    return VoteObservation(
        top1_student_id=student_id, top1_similarity=sim,
        top2_student_id=None, top2_similarity=None,
        above_threshold=above, timestamp_sec=t,
    )


def _confirm_student_1(engine):
    obs = [_obs(1, 0.9, t=0.0), _obs(1, 0.9, t=1.0), _obs(1, 0.9, t=2.0)]
    result = engine.vote(obs)
    assert result.state == "CONFIRMED" and result.confirmed_student_id == 1
    return obs


def test_one_weak_conflicting_observation_does_not_switch_identity():
    engine = _engine(conflict_support=2)
    obs = _confirm_student_1(engine)
    obs.append(_obs(2, 0.9, t=3.0))  # single conflicting observation
    result = engine.vote(obs, previous_confirmed_student_id=1)
    assert result.state == "CONFIRMED"
    assert result.confirmed_student_id == 1
    assert result.identity_conflict is False


def test_multiple_strong_conflicts_set_identity_conflict_true():
    engine = _engine(conflict_support=2, window_size=6)
    obs = _confirm_student_1(engine)
    obs.append(_obs(2, 0.9, t=3.0))
    obs.append(_obs(2, 0.9, t=4.0))  # 2 conflicting observations >= conflict_support
    result = engine.vote(obs, previous_confirmed_student_id=1)
    assert result.identity_conflict is True
    assert result.state == "AMBIGUOUS"


def test_confirmed_student_id_does_not_silently_switch():
    engine = _engine(conflict_support=2, window_size=6)
    obs = _confirm_student_1(engine)
    obs.append(_obs(2, 0.95, t=3.0))
    obs.append(_obs(2, 0.95, t=4.0))
    obs.append(_obs(2, 0.95, t=5.0))  # student 2 now has MORE support than student 1
    result = engine.vote(obs, previous_confirmed_student_id=1)
    # Even though student 2 now has stronger raw evidence, the locked
    # identity must never silently switch away from student 1.
    assert result.confirmed_student_id == 1
    assert result.identity_conflict is True


def test_competing_candidates_produce_ambiguous_when_never_confirmed():
    engine = _engine(min_support=2, min_support_ratio=0.5, min_mean_confidence=0.5, min_margin=0.0)
    obs = [_obs(1, 0.9, t=0.0), _obs(2, 0.9, t=1.0), _obs(1, 0.9, t=2.0), _obs(2, 0.9, t=3.0)]
    result = engine.vote(obs)
    assert result.state == "AMBIGUOUS"
    assert result.confirmed_student_id is None


def test_conflict_reason_is_stored_safely():
    engine = _engine(conflict_support=2, window_size=6)
    obs = _confirm_student_1(engine)
    obs.append(_obs(2, 0.9, t=3.0))
    obs.append(_obs(2, 0.9, t=4.0))
    result = engine.vote(obs, previous_confirmed_student_id=1)
    assert result.conflict_reason is not None
    assert isinstance(result.conflict_reason, str)
    # No raw embedding/similarity vector leaks into the reason string.
    assert "0." not in result.conflict_reason.replace("2)", "")  # crude check: no stray float dump
