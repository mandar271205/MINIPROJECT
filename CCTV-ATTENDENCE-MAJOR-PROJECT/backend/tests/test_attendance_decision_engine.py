"""Phase 6 - attendance decision engine unit tests (categories 1-6 of
the required tests): main-status rules, precedence, LATE, EARLY_EXIT,
RE_ENTRY, and confidence handling. Pure dataclass-level tests - no
database needed.
"""

import pytest

from app.services.attendance_decision_engine import (
    DecisionPolicy,
    PolicyValidationError,
    SessionEvidenceContext,
    StudentEvidence,
    STATUS_ABSENT,
    STATUS_PARTIAL,
    STATUS_PRESENT,
    STATUS_REVIEW_REQUIRED,
    FLAG_EARLY_EXIT,
    FLAG_IDENTITY_CONFLICT,
    FLAG_LATE,
    FLAG_LOW_CONFIDENCE,
    FLAG_RE_ENTRY,
    REASON_CONFIDENCE_BELOW_DECISION_MINIMUM,
    REASON_FACE_TEMPLATE_UNAVAILABLE,
    REASON_IDENTITY_CONFLICT_UNRESOLVED,
    REASON_NO_RELIABLE_PRESENCE,
    REASON_PRESENCE_BELOW_FULL_CREDIT,
    REASON_PRESENCE_MEETS_THRESHOLD,
    REASON_PRESENCE_RECONSTRUCTION_INCOMPLETE,
    REASON_VALID_SESSION_DURATION_UNAVAILABLE,
    REASON_VIDEO_EOF_NOT_REACHED,
    evaluate_student,
)


def _policy(**overrides):
    defaults = dict(
        policy_id=1, policy_name="Development Default",
        present_threshold_percentage=75.0, late_grace_seconds=600.0,
        early_exit_tolerance_seconds=600.0, reentry_min_gap_seconds=300.0,
        low_confidence_flag_threshold=0.55, minimum_decision_confidence=0.45,
        minimum_valid_session_ratio=1.0,
    )
    defaults.update(overrides)
    return DecisionPolicy(**defaults)


def _session(**overrides):
    defaults = dict(eof_reached=True, presence_reconstruction_status="COMPLETED", valid_session_seconds=3600.0)
    defaults.update(overrides)
    return SessionEvidenceContext(**defaults)


def _student(**overrides):
    defaults = dict(student_id=1, eligible_for_recognition=True)
    defaults.update(overrides)
    return StudentEvidence(**defaults)


# --------------------------------------------------------------------------
# 1. Main-status tests
# --------------------------------------------------------------------------

def test_presence_exactly_at_threshold_is_present():
    student = _student(presence_percentage=75.0, presence_duration_seconds=2700.0, window_count=1,
                        first_confirmed_presence_seconds=0.0, last_confirmed_presence_seconds=2700.0, mean_confidence=0.9)
    result = evaluate_student(student, _policy(), _session())
    assert result.suggested_status == STATUS_PRESENT
    assert result.reason_code == REASON_PRESENCE_MEETS_THRESHOLD


def test_presence_above_threshold_is_present():
    student = _student(presence_percentage=90.0, presence_duration_seconds=3240.0, window_count=1,
                        first_confirmed_presence_seconds=0.0, last_confirmed_presence_seconds=3240.0, mean_confidence=0.9)
    result = evaluate_student(student, _policy(), _session())
    assert result.suggested_status == STATUS_PRESENT


def test_positive_below_threshold_is_partial():
    student = _student(presence_percentage=61.2, presence_duration_seconds=2200.0, window_count=1,
                        first_confirmed_presence_seconds=0.0, last_confirmed_presence_seconds=2200.0, mean_confidence=0.8)
    result = evaluate_student(student, _policy(), _session())
    assert result.suggested_status == STATUS_PARTIAL
    assert result.reason_code == REASON_PRESENCE_BELOW_FULL_CREDIT


def test_tiny_but_positive_presence_is_partial():
    student = _student(presence_percentage=0.5, presence_duration_seconds=18.0, window_count=1,
                        first_confirmed_presence_seconds=0.0, last_confirmed_presence_seconds=18.0, mean_confidence=0.8)
    result = evaluate_student(student, _policy(), _session())
    assert result.suggested_status == STATUS_PARTIAL


def test_reliable_zero_presence_is_absent():
    student = _student(presence_percentage=0.0, presence_duration_seconds=0.0, window_count=0)
    result = evaluate_student(student, _policy(), _session())
    assert result.suggested_status == STATUS_ABSENT
    assert result.reason_code == REASON_NO_RELIABLE_PRESENCE
    assert result.is_evaluable is True


def test_incompatible_template_is_review_required():
    student = _student(eligible_for_recognition=False, ineligible_reason_code=REASON_FACE_TEMPLATE_UNAVAILABLE)
    result = evaluate_student(student, _policy(), _session())
    assert result.suggested_status == STATUS_REVIEW_REQUIRED
    assert result.is_evaluable is False
    assert result.flags == []


def test_missing_duration_is_review_required():
    student = _student(presence_percentage=0.0, presence_duration_seconds=0.0, window_count=0)
    result = evaluate_student(student, _policy(), _session(valid_session_seconds=None))
    assert result.suggested_status == STATUS_REVIEW_REQUIRED
    assert result.reason_code == REASON_VALID_SESSION_DURATION_UNAVAILABLE


def test_reconstruction_failure_is_review_required():
    student = _student(presence_percentage=0.0, presence_duration_seconds=0.0, window_count=0)
    result = evaluate_student(student, _policy(), _session(presence_reconstruction_status="FAILED"))
    assert result.suggested_status == STATUS_REVIEW_REQUIRED
    assert result.reason_code == REASON_PRESENCE_RECONSTRUCTION_INCOMPLETE


def test_eof_not_reached_is_review_required():
    student = _student(presence_percentage=0.0, presence_duration_seconds=0.0, window_count=0)
    result = evaluate_student(student, _policy(), _session(eof_reached=False))
    assert result.suggested_status == STATUS_REVIEW_REQUIRED
    assert result.reason_code == REASON_VIDEO_EOF_NOT_REACHED


def test_identity_conflict_affecting_evaluation_is_review_required():
    student = _student(presence_percentage=90.0, presence_duration_seconds=3240.0, window_count=1,
                        mean_confidence=0.9, identity_conflict_track_count=1)
    result = evaluate_student(student, _policy(), _session())
    assert result.suggested_status == STATUS_REVIEW_REQUIRED
    assert result.reason_code == REASON_IDENTITY_CONFLICT_UNRESOLVED
    assert FLAG_IDENTITY_CONFLICT in result.flags


def test_invalid_policy_raises_instead_of_silently_deciding():
    student = _student(presence_percentage=50.0, presence_duration_seconds=100.0, window_count=1)
    with pytest.raises(PolicyValidationError):
        evaluate_student(student, _policy(present_threshold_percentage=0.0), _session())


def test_excused_and_on_duty_never_generated():
    # Exhaustively scan a range of inputs and confirm the engine never
    # returns EXCUSED/ON_DUTY under any circumstance.
    from app.services.attendance_decision_engine import STATUS_EXCUSED, STATUS_ON_DUTY

    for pct in (0.0, 1.0, 50.0, 75.0, 100.0):
        for conflict in (0, 1):
            for eof in (True, False):
                student = _student(
                    presence_percentage=pct, presence_duration_seconds=pct, window_count=1 if pct else 0,
                    mean_confidence=0.9, identity_conflict_track_count=conflict,
                )
                result = evaluate_student(student, _policy(), _session(eof_reached=eof))
                assert result.suggested_status not in (STATUS_EXCUSED, STATUS_ON_DUTY)


def test_exactly_one_suggestion_per_student():
    student = _student(presence_percentage=50.0, presence_duration_seconds=100.0, window_count=1, mean_confidence=0.9)
    result = evaluate_student(student, _policy(), _session())
    assert isinstance(result.suggested_status, str)
    assert result.student_id == 1


# --------------------------------------------------------------------------
# 2. Precedence tests
# --------------------------------------------------------------------------

def test_identity_conflict_beats_high_presence():
    student = _student(presence_percentage=100.0, presence_duration_seconds=3600.0, window_count=1,
                        mean_confidence=0.9, identity_conflict_track_count=2)
    result = evaluate_student(student, _policy(), _session())
    assert result.suggested_status == STATUS_REVIEW_REQUIRED


def test_incompatible_template_beats_zero_presence():
    student = _student(eligible_for_recognition=False, ineligible_reason_code=REASON_FACE_TEMPLATE_UNAVAILABLE,
                        presence_percentage=0.0)
    result = evaluate_student(student, _policy(), _session())
    assert result.suggested_status == STATUS_REVIEW_REQUIRED
    assert result.reason_code != REASON_NO_RELIABLE_PRESENCE


def test_missing_duration_beats_zero_presence():
    student = _student(presence_percentage=0.0, presence_duration_seconds=0.0)
    result = evaluate_student(student, _policy(), _session(valid_session_seconds=0.0))
    assert result.suggested_status == STATUS_REVIEW_REQUIRED


def test_reliable_zero_presence_is_absent_precedence():
    student = _student(presence_percentage=0.0, presence_duration_seconds=0.0, window_count=0)
    result = evaluate_student(student, _policy(), _session())
    assert result.suggested_status == STATUS_ABSENT


def test_reliable_below_threshold_is_partial_precedence():
    student = _student(presence_percentage=40.0, presence_duration_seconds=1440.0, window_count=1, mean_confidence=0.9)
    result = evaluate_student(student, _policy(), _session())
    assert result.suggested_status == STATUS_PARTIAL


def test_reliable_threshold_presence_is_present_precedence():
    student = _student(presence_percentage=75.0, presence_duration_seconds=2700.0, window_count=1, mean_confidence=0.9)
    result = evaluate_student(student, _policy(), _session())
    assert result.suggested_status == STATUS_PRESENT


# --------------------------------------------------------------------------
# 3. LATE tests
# --------------------------------------------------------------------------

def test_first_presence_after_grace_is_late():
    student = _student(presence_percentage=80.0, presence_duration_seconds=2880.0, window_count=1,
                        first_confirmed_presence_seconds=700.0, last_confirmed_presence_seconds=3580.0, mean_confidence=0.9)
    result = evaluate_student(student, _policy(late_grace_seconds=600.0), _session())
    assert FLAG_LATE in result.flags


def test_first_presence_exactly_at_grace_is_not_late():
    # Documented rule: strictly greater than grace, so exactly-at-grace is NOT late.
    student = _student(presence_percentage=80.0, presence_duration_seconds=2880.0, window_count=1,
                        first_confirmed_presence_seconds=600.0, last_confirmed_presence_seconds=3580.0, mean_confidence=0.9)
    result = evaluate_student(student, _policy(late_grace_seconds=600.0), _session())
    assert FLAG_LATE not in result.flags


def test_first_presence_before_grace_is_not_late():
    student = _student(presence_percentage=80.0, presence_duration_seconds=2880.0, window_count=1,
                        first_confirmed_presence_seconds=10.0, last_confirmed_presence_seconds=3580.0, mean_confidence=0.9)
    result = evaluate_student(student, _policy(late_grace_seconds=600.0), _session())
    assert FLAG_LATE not in result.flags


def test_zero_presence_has_no_late_flag():
    student = _student(presence_percentage=0.0, presence_duration_seconds=0.0, window_count=0)
    result = evaluate_student(student, _policy(), _session())
    assert FLAG_LATE not in result.flags


def test_unknown_first_presence_has_no_late_flag():
    student = _student(presence_percentage=50.0, presence_duration_seconds=1800.0, window_count=1,
                        first_confirmed_presence_seconds=None, mean_confidence=0.9)
    result = evaluate_student(student, _policy(), _session())
    assert FLAG_LATE not in result.flags


# --------------------------------------------------------------------------
# 4. EARLY_EXIT tests
# --------------------------------------------------------------------------

def test_last_presence_before_boundary_is_early_exit():
    student = _student(presence_percentage=80.0, presence_duration_seconds=2880.0, window_count=1,
                        first_confirmed_presence_seconds=0.0, last_confirmed_presence_seconds=2900.0, mean_confidence=0.9)
    result = evaluate_student(student, _policy(early_exit_tolerance_seconds=600.0), _session(valid_session_seconds=3600.0))
    assert FLAG_EARLY_EXIT in result.flags


def test_last_presence_exactly_at_boundary_is_not_early_exit():
    # Documented rule: strictly earlier than boundary, so exactly-at-boundary is NOT early exit.
    student = _student(presence_percentage=80.0, presence_duration_seconds=2880.0, window_count=1,
                        first_confirmed_presence_seconds=0.0, last_confirmed_presence_seconds=3000.0, mean_confidence=0.9)
    result = evaluate_student(student, _policy(early_exit_tolerance_seconds=600.0), _session(valid_session_seconds=3600.0))
    assert FLAG_EARLY_EXIT not in result.flags


def test_last_presence_within_tolerance_is_not_early_exit():
    student = _student(presence_percentage=95.0, presence_duration_seconds=3420.0, window_count=1,
                        first_confirmed_presence_seconds=0.0, last_confirmed_presence_seconds=3590.0, mean_confidence=0.9)
    result = evaluate_student(student, _policy(early_exit_tolerance_seconds=600.0), _session(valid_session_seconds=3600.0))
    assert FLAG_EARLY_EXIT not in result.flags


def test_zero_presence_has_no_early_exit_flag():
    student = _student(presence_percentage=0.0, presence_duration_seconds=0.0, window_count=0)
    result = evaluate_student(student, _policy(), _session())
    assert FLAG_EARLY_EXIT not in result.flags


def test_unreliable_duration_never_fabricates_early_exit():
    student = _student(presence_percentage=0.0, presence_duration_seconds=0.0, window_count=0,
                        last_confirmed_presence_seconds=100.0)
    result = evaluate_student(student, _policy(), _session(valid_session_seconds=None))
    # REVIEW_REQUIRED short-circuits before flags are even computed.
    assert result.suggested_status == STATUS_REVIEW_REQUIRED
    assert FLAG_EARLY_EXIT not in result.flags


# --------------------------------------------------------------------------
# 5. RE_ENTRY tests
# --------------------------------------------------------------------------

def test_two_windows_with_qualifying_gap_is_re_entry():
    student = _student(presence_percentage=50.0, presence_duration_seconds=1800.0, window_count=2,
                        windows=[(0.0, 900.0), (1300.0, 1800.0)], first_confirmed_presence_seconds=0.0,
                        last_confirmed_presence_seconds=1800.0, mean_confidence=0.9)
    result = evaluate_student(student, _policy(reentry_min_gap_seconds=300.0), _session())
    assert FLAG_RE_ENTRY in result.flags


def test_two_windows_with_gap_below_threshold_is_not_re_entry():
    student = _student(presence_percentage=50.0, presence_duration_seconds=1800.0, window_count=2,
                        windows=[(0.0, 900.0), (1000.0, 1800.0)], mean_confidence=0.9)
    result = evaluate_student(student, _policy(reentry_min_gap_seconds=300.0), _session())
    assert FLAG_RE_ENTRY not in result.flags


def test_one_window_is_not_re_entry():
    student = _student(presence_percentage=50.0, presence_duration_seconds=1800.0, window_count=1,
                        windows=[(0.0, 1800.0)], mean_confidence=0.9)
    result = evaluate_student(student, _policy(), _session())
    assert FLAG_RE_ENTRY not in result.flags


def test_smoothed_gap_already_one_window_is_not_re_entry():
    # Presence reconstruction already bridged a small gap into a single
    # window - so there's only one window here, never two.
    student = _student(presence_percentage=50.0, presence_duration_seconds=1800.0, window_count=1,
                        windows=[(0.0, 1800.0)], mean_confidence=0.9)
    result = evaluate_student(student, _policy(reentry_min_gap_seconds=1.0), _session())
    assert FLAG_RE_ENTRY not in result.flags


def test_multiple_tracks_but_one_window_is_not_re_entry():
    # contributing_track_count doesn't matter here at all - only the
    # number of reconstructed windows does.
    student = _student(presence_percentage=50.0, presence_duration_seconds=1800.0, window_count=1,
                        windows=[(0.0, 1800.0)], mean_confidence=0.9)
    result = evaluate_student(student, _policy(), _session())
    assert FLAG_RE_ENTRY not in result.flags


# --------------------------------------------------------------------------
# 6. Confidence tests
# --------------------------------------------------------------------------

def test_high_confidence_has_no_low_confidence_flag():
    student = _student(presence_percentage=80.0, presence_duration_seconds=2880.0, window_count=1, mean_confidence=0.95)
    result = evaluate_student(student, _policy(), _session())
    assert FLAG_LOW_CONFIDENCE not in result.flags


def test_flag_band_confidence_is_low_confidence_but_evaluable():
    student = _student(presence_percentage=80.0, presence_duration_seconds=2880.0, window_count=1, mean_confidence=0.5)
    result = evaluate_student(student, _policy(low_confidence_flag_threshold=0.55, minimum_decision_confidence=0.45), _session())
    assert FLAG_LOW_CONFIDENCE in result.flags
    assert result.is_evaluable is True
    assert result.suggested_status == STATUS_PRESENT


def test_confidence_below_decision_minimum_is_review_required():
    student = _student(presence_percentage=80.0, presence_duration_seconds=2880.0, window_count=1, mean_confidence=0.3)
    result = evaluate_student(student, _policy(low_confidence_flag_threshold=0.55, minimum_decision_confidence=0.45), _session())
    assert result.suggested_status == STATUS_REVIEW_REQUIRED
    assert result.reason_code == REASON_CONFIDENCE_BELOW_DECISION_MINIMUM
    assert FLAG_LOW_CONFIDENCE in result.flags


def test_missing_confidence_handled_conservatively():
    # No evidence at all -> zero presence -> ABSENT, confidence checks
    # simply don't apply (there is nothing to have low confidence about).
    student = _student(presence_percentage=0.0, presence_duration_seconds=0.0, window_count=0, mean_confidence=None)
    result = evaluate_student(student, _policy(), _session())
    assert result.suggested_status == STATUS_ABSENT
    assert FLAG_LOW_CONFIDENCE not in result.flags


def test_invalid_confidence_value_does_not_crash_and_is_ignored():
    student = _student(presence_percentage=80.0, presence_duration_seconds=2880.0, window_count=1, mean_confidence=float("nan"))
    result = evaluate_student(student, _policy(), _session())
    assert result.suggested_status == STATUS_PRESENT
    assert FLAG_LOW_CONFIDENCE not in result.flags
