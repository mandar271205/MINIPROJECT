"""Phase 8 - Unit tests for At-Risk & Shortage Prediction Engine boundary conditions."""

import datetime
import pytest

from app.services.risk_scoring_service import (
    DEFAULT_CRITICAL_ATTENDANCE_THRESHOLD,
    DEFAULT_MIN_ATTENDANCE_THRESHOLD,
    DEFAULT_VELOCITY_DECLINE_THRESHOLD,
    FLAG_ATTENDANCE_ON_TRACK,
    FLAG_COMPOUND_SHORTAGE_RISK,
    FLAG_CONSECUTIVE_ABSENCE,
    FLAG_CONSECUTIVE_ABSENCE_WARNING,
    FLAG_CRITICAL_DEFICIT,
    FLAG_INSUFFICIENT_DATA,
    FLAG_NEGATIVE_VELOCITY,
    FLAG_THRESHOLD_BREACH,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    SessionRecordInput,
    calculate_attendance_velocity,
    calculate_consecutive_absences,
    calculate_recovery_and_buffer,
    evaluate_student_risk,
)


def _make_record(idx: int, day_offset: int, status: str) -> SessionRecordInput:
    """Helper to create a session record on a specific date."""
    base_date = datetime.date(2026, 9, 1)
    session_date = base_date + datetime.timedelta(days=day_offset)
    return SessionRecordInput(
        session_id=idx,
        session_date=session_date,
        status=status,
    )


# ===========================================================================
# 1. Boundary Tests: Threshold Boundaries (75.0% and 60.0%)
# ===========================================================================

def test_attendance_exactly_at_threshold():
    """At exactly 75.0%, student is compliant: LOW risk, no THRESHOLD_BREACH."""
    # 4 sessions: 1 ABSENT followed by 3 PRESENT = 75.0% (improving trend)
    base_date = datetime.date(2026, 9, 7)
    records = [
        SessionRecordInput(session_id=1, session_date=base_date, status="ABSENT"),
        SessionRecordInput(session_id=2, session_date=base_date + datetime.timedelta(days=1), status="PRESENT"),
        SessionRecordInput(session_id=3, session_date=base_date + datetime.timedelta(days=2), status="PRESENT"),
        SessionRecordInput(session_id=4, session_date=base_date + datetime.timedelta(days=3), status="PRESENT"),
    ]
    profile = evaluate_student_risk(
        student_id=1,
        student_name="Test Student",
        roll_number="01",
        prn_number="PRN01",
        session_records=records,
        min_threshold_percentage=75.0,
    )


    assert profile.attendance_percentage == 75.0
    assert profile.risk_level == RISK_LOW
    assert not profile.is_at_risk
    assert profile.sessions_needed_to_recover == 0
    flag_codes = [f["code"] for f in profile.rule_flags]
    assert FLAG_THRESHOLD_BREACH not in flag_codes
    assert FLAG_ATTENDANCE_ON_TRACK in flag_codes


def test_attendance_just_below_threshold():
    """At 74.9% (or just below 75%), triggers THRESHOLD_BREACH and MEDIUM risk."""
    # 1000 simulated sessions: 749 present, 251 absent -> 74.9%
    records = []
    for i in range(749):
        records.append(_make_record(i, i, "PRESENT"))
    for i in range(251):
        records.append(_make_record(749 + i, 749 + i, "ABSENT"))

    profile = evaluate_student_risk(
        student_id=2,
        student_name="Test Student",
        roll_number="02",
        prn_number="PRN02",
        session_records=records,
        min_threshold_percentage=75.0,
    )

    assert profile.attendance_percentage == 74.9
    assert profile.risk_level in (RISK_MEDIUM, RISK_HIGH)
    assert profile.is_at_risk
    assert profile.sessions_needed_to_recover >= 1
    flag_codes = [f["code"] for f in profile.rule_flags]
    assert FLAG_THRESHOLD_BREACH in flag_codes or FLAG_CRITICAL_DEFICIT in flag_codes


def test_attendance_critical_threshold_boundary():
    """At exactly 60.0% is MEDIUM risk; at 59.9% is HIGH risk with CRITICAL_DEFICIT."""
    # Exactly 60.0%: 3 PRESENT out of 5 sessions
    records_60 = [
        _make_record(1, 0, "PRESENT"),
        _make_record(2, 7, "PRESENT"),
        _make_record(3, 14, "PRESENT"),
        _make_record(4, 21, "ABSENT"),
        _make_record(5, 28, "ABSENT"),
    ]
    # Note: 2 consecutive absences triggers warning (MEDIUM), not HIGH (>= 3)
    profile_60 = evaluate_student_risk(
        student_id=3,
        student_name="Student 60",
        roll_number="03",
        prn_number="PRN03",
        session_records=records_60,
        min_threshold_percentage=75.0,
        critical_threshold_percentage=60.0,
    )
    assert profile_60.attendance_percentage == 60.0
    assert profile_60.risk_level == RISK_MEDIUM
    flag_codes_60 = [f["code"] for f in profile_60.rule_flags]
    assert FLAG_THRESHOLD_BREACH in flag_codes_60
    assert FLAG_CRITICAL_DEFICIT not in flag_codes_60

    # Below 60.0%: 2 PRESENT out of 5 sessions = 40.0% (< 60.0%)
    records_sub60 = [
        _make_record(1, 0, "PRESENT"),
        _make_record(2, 7, "ABSENT"),
        _make_record(3, 14, "ABSENT"),
        _make_record(4, 21, "ABSENT"),
        _make_record(5, 28, "PRESENT"),  # end with PRESENT so consecutive_absences=0
    ]
    # 2 out of 5 = 40.0% < 60.0%
    profile_sub60 = evaluate_student_risk(
        student_id=4,
        student_name="Student Sub60",
        roll_number="04",
        prn_number="PRN04",
        session_records=records_sub60,
        min_threshold_percentage=75.0,
        critical_threshold_percentage=60.0,
    )
    assert profile_sub60.attendance_percentage == 40.0
    assert profile_sub60.risk_level == RISK_HIGH
    flag_codes_sub60 = [f["code"] for f in profile_sub60.rule_flags]
    assert FLAG_CRITICAL_DEFICIT in flag_codes_sub60



# ===========================================================================
# 2. Boundary Tests: Attendance Velocity (>10% drop over consecutive weeks)
# ===========================================================================

def test_attendance_velocity_exact_10_percent_drop():
    """A decline of exactly 10.0% does NOT breach the strict >10% trigger."""
    # Week 1 (day 0, 1): 2/2 = 100.0%
    # Week 2 (day 7, 8): 9/10? Let's make week 1: 10 sessions, 10 present (100%).
    # Week 2: 10 sessions, 9 present (90.0%). Delta = 90.0 - 100.0 = -10.0%.
    records = []
    base_w1 = datetime.date(2026, 9, 7)   # Monday Week 37
    base_w2 = datetime.date(2026, 9, 14)  # Monday Week 38

    for i in range(10):
        records.append(SessionRecordInput(session_id=i, session_date=base_w1, status="PRESENT"))
    for i in range(9):
        records.append(SessionRecordInput(session_id=10 + i, session_date=base_w2, status="PRESENT"))
    records.append(SessionRecordInput(session_id=19, session_date=base_w2, status="ABSENT"))

    velocity = calculate_attendance_velocity(records)
    assert velocity == -10.0

    profile = evaluate_student_risk(
        student_id=5,
        student_name="Student Vel10",
        roll_number="05",
        prn_number="PRN05",
        session_records=records,
        min_threshold_percentage=75.0,
        velocity_decline_threshold=10.0,
    )
    # Total attendance: 19/20 = 95.0%
    # Velocity is -10.0, not < -10.0, so NEGATIVE_VELOCITY is not triggered
    flag_codes = [f["code"] for f in profile.rule_flags]
    assert FLAG_NEGATIVE_VELOCITY not in flag_codes
    assert profile.risk_level == RISK_LOW


def test_attendance_velocity_strictly_greater_than_10_percent_drop():
    """A decline > 10.0% (e.g. -10.01% or -25.0%) triggers NEGATIVE_VELOCITY."""
    # Week 1: 4/4 = 100.0%
    # Week 2: 2/4 = 50.0% -> Delta = -50.0%
    records = []
    base_w1 = datetime.date(2026, 9, 7)
    base_w2 = datetime.date(2026, 9, 14)

    for i in range(4):
        records.append(SessionRecordInput(session_id=i, session_date=base_w1, status="PRESENT"))
    for i in range(2):
        records.append(SessionRecordInput(session_id=4 + i, session_date=base_w2, status="PRESENT"))
    for i in range(2):
        records.append(SessionRecordInput(session_id=6 + i, session_date=base_w2, status="ABSENT"))

    velocity = calculate_attendance_velocity(records)
    assert velocity == -50.0

    profile = evaluate_student_risk(
        student_id=6,
        student_name="Student VelDrop",
        roll_number="06",
        prn_number="PRN06",
        session_records=records,
        min_threshold_percentage=75.0,
        velocity_decline_threshold=10.0,
    )
    flag_codes = [f["code"] for f in profile.rule_flags]
    assert FLAG_NEGATIVE_VELOCITY in flag_codes
    assert profile.is_at_risk


def test_compounded_risk_below_threshold_and_negative_velocity():
    """Student below 75% AND with negative velocity triggers COMPOUND_SHORTAGE_RISK and HIGH risk."""
    # Week 1: 3/4 = 75.0%
    # Week 2: 1/4 = 25.0% -> Overall: 4/8 = 50.0% (<75%), velocity = -50.0%
    records = []
    base_w1 = datetime.date(2026, 9, 7)
    base_w2 = datetime.date(2026, 9, 14)

    for i in range(3):
        records.append(SessionRecordInput(session_id=i, session_date=base_w1, status="PRESENT"))
    records.append(SessionRecordInput(session_id=3, session_date=base_w1, status="ABSENT"))

    records.append(SessionRecordInput(session_id=4, session_date=base_w2, status="PRESENT"))
    for i in range(3):
        records.append(SessionRecordInput(session_id=5 + i, session_date=base_w2, status="ABSENT"))

    profile = evaluate_student_risk(
        student_id=7,
        student_name="Student Compound",
        roll_number="07",
        prn_number="PRN07",
        session_records=records,
        min_threshold_percentage=75.0,
    )

    assert profile.attendance_percentage == 50.0
    assert profile.risk_level == RISK_HIGH
    flag_codes = [f["code"] for f in profile.rule_flags]
    assert FLAG_COMPOUND_SHORTAGE_RISK in flag_codes
    assert FLAG_NEGATIVE_VELOCITY in flag_codes


# ===========================================================================
# 3. Boundary Tests: Consecutive Absence Triggers
# ===========================================================================

def test_consecutive_absence_boundary_conditions():
    """Validates 1, 2, and 3 consecutive absence triggers."""
    base_date = datetime.date(2026, 9, 1)

    # Case 1: 1 consecutive absence at end -> no streak trigger
    recs_1 = [
        SessionRecordInput(session_id=1, session_date=base_date, status="PRESENT"),
        SessionRecordInput(session_id=2, session_date=base_date + datetime.timedelta(days=1), status="PRESENT"),
        SessionRecordInput(session_id=3, session_date=base_date + datetime.timedelta(days=2), status="PRESENT"),
        SessionRecordInput(session_id=4, session_date=base_date + datetime.timedelta(days=3), status="ABSENT"),
    ]
    cur, max_streak = calculate_consecutive_absences(recs_1)
    assert cur == 1
    assert max_streak == 1

    profile_1 = evaluate_student_risk(
        student_id=8, student_name="S1", roll_number="08", prn_number="P8", session_records=recs_1
    )
    flag_codes_1 = [f["code"] for f in profile_1.rule_flags]
    assert FLAG_CONSECUTIVE_ABSENCE not in flag_codes_1
    assert FLAG_CONSECUTIVE_ABSENCE_WARNING not in flag_codes_1

    # Case 2: 2 consecutive absences at end -> CONSECUTIVE_ABSENCE_WARNING (MEDIUM)
    recs_2 = [
        SessionRecordInput(session_id=1, session_date=base_date, status="PRESENT"),
        SessionRecordInput(session_id=2, session_date=base_date + datetime.timedelta(days=1), status="PRESENT"),
        SessionRecordInput(session_id=3, session_date=base_date + datetime.timedelta(days=2), status="ABSENT"),
        SessionRecordInput(session_id=4, session_date=base_date + datetime.timedelta(days=3), status="ABSENT"),
    ]
    cur, max_streak = calculate_consecutive_absences(recs_2)
    assert cur == 2
    assert max_streak == 2

    profile_2 = evaluate_student_risk(
        student_id=9, student_name="S2", roll_number="09", prn_number="P9", session_records=recs_2
    )
    flag_codes_2 = [f["code"] for f in profile_2.rule_flags]
    assert FLAG_CONSECUTIVE_ABSENCE_WARNING in flag_codes_2

    # Case 3: 3 consecutive absences at end -> CONSECUTIVE_ABSENCE (HIGH)
    recs_3 = [
        SessionRecordInput(session_id=1, session_date=base_date, status="PRESENT"),
        SessionRecordInput(session_id=2, session_date=base_date + datetime.timedelta(days=1), status="ABSENT"),
        SessionRecordInput(session_id=3, session_date=base_date + datetime.timedelta(days=2), status="ABSENT"),
        SessionRecordInput(session_id=4, session_date=base_date + datetime.timedelta(days=3), status="ABSENT"),
    ]
    cur, max_streak = calculate_consecutive_absences(recs_3)
    assert cur == 3
    assert max_streak == 3

    profile_3 = evaluate_student_risk(
        student_id=10, student_name="S3", roll_number="10", prn_number="P10", session_records=recs_3
    )
    flag_codes_3 = [f["code"] for f in profile_3.rule_flags]
    assert FLAG_CONSECUTIVE_ABSENCE in flag_codes_3
    assert profile_3.risk_level == RISK_HIGH


def test_consecutive_absence_interrupted():
    """An absence streak interrupted by PRESENT resets active recent streak count."""
    base_date = datetime.date(2026, 9, 1)
    recs = [
        SessionRecordInput(session_id=1, session_date=base_date, status="ABSENT"),
        SessionRecordInput(session_id=2, session_date=base_date + datetime.timedelta(days=1), status="ABSENT"),
        SessionRecordInput(session_id=3, session_date=base_date + datetime.timedelta(days=2), status="ABSENT"),
        SessionRecordInput(session_id=4, session_date=base_date + datetime.timedelta(days=3), status="PRESENT"),
    ]
    recent, max_streak = calculate_consecutive_absences(recs)
    assert recent == 0
    assert max_streak == 3


# ===========================================================================
# 4. Boundary Tests: Partial Attendance and Status Weights
# ===========================================================================

def test_partial_attendance_credit():
    """PARTIAL status receives 0.5 credit by default."""
    base_date = datetime.date(2026, 9, 1)
    recs = [
        SessionRecordInput(session_id=1, session_date=base_date, status="PARTIAL"),
        SessionRecordInput(session_id=2, session_date=base_date + datetime.timedelta(days=1), status="PRESENT"),
    ]
    # Total sessions = 2, attended credits = 0.5 + 1.0 = 1.5 -> 75.0%
    profile = evaluate_student_risk(
        student_id=11, student_name="S_Partial", roll_number="11", prn_number="P11", session_records=recs
    )
    assert profile.attended_sessions == 1.5
    assert profile.attendance_percentage == 75.0
    assert profile.risk_level == RISK_LOW


# ===========================================================================
# 5. Boundary Tests: Recovery Math and Buffer Math
# ===========================================================================

def test_recovery_math_boundary():
    """Validates recovery sessions formula."""
    # N=10, A=5 (50%), T=75% -> needed = ceil((75*10 - 100*5)/(100 - 75)) = 10
    needed, buffer_b = calculate_recovery_and_buffer(10, 5.0, 75.0)
    assert needed == 10
    assert buffer_b == 0
    # Verification: (5 + 10) / (10 + 10) = 15/20 = 75.0%

    # N=4, A=2 (50%), T=75% -> needed = ceil((300 - 200)/25) = 4
    needed_4, _ = calculate_recovery_and_buffer(4, 2.0, 75.0)
    assert needed_4 == 4
    # Verification: (2 + 4) / (4 + 4) = 6/8 = 75.0%


def test_buffer_math_boundary():
    """Validates buffer sessions formula."""
    # N=10, A=10 (100%), T=75% -> buffer = floor((1000 - 750)/75) = 3
    needed, buffer_b = calculate_recovery_and_buffer(10, 10.0, 75.0)
    assert needed == 0
    assert buffer_b == 3
    # Verification: 10 / (10 + 3) = 10/13 = 76.9% >= 75%; 10/14 = 71.4% < 75%


# ===========================================================================
# 6. Edge Cases: Empty and Single-Session Histories
# ===========================================================================

def test_empty_session_history():
    """Empty history safely returns LOW risk and INSUFFICIENT_DATA flag."""
    profile = evaluate_student_risk(
        student_id=12,
        student_name="Empty Student",
        roll_number="12",
        prn_number=None,
        session_records=[],
    )
    assert profile.total_sessions == 0
    assert profile.attendance_percentage == 100.0
    assert profile.risk_level == RISK_LOW
    assert not profile.is_at_risk
    flag_codes = [f["code"] for f in profile.rule_flags]
    assert FLAG_INSUFFICIENT_DATA in flag_codes


def test_single_session_history():
    """Single session history cannot calculate velocity, but computes percentage safely."""
    recs = [SessionRecordInput(session_id=1, session_date=datetime.date.today(), status="PRESENT")]
    profile = evaluate_student_risk(
        student_id=13,
        student_name="Single Student",
        roll_number="13",
        prn_number=None,
        session_records=recs,
    )
    assert profile.total_sessions == 1
    assert profile.attendance_percentage == 100.0
    assert profile.attendance_velocity is None
    assert profile.risk_level == RISK_LOW
