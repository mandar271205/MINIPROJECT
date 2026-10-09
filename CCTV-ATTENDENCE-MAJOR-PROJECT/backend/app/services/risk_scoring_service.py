"""Phase 8 - At-Risk & Shortage Prediction Engine.

Provides deterministic, explainable risk scoring based on:
  1. Overall subject attendance falling below the minimum threshold (default 75%).
  2. Negative attendance velocity (declining > 10% over consecutive periods).
  3. Consecutive absence triggers (critical streaks >= 3, warnings == 2).
  4. Categorization into LOW, MEDIUM, and HIGH risk levels with explainable rule flags.
  5. Recovery forecasting (sessions needed to recover, buffer sessions remaining).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..extensions import db
from ..models.academic import FacultyAssignment, Subject
from ..models.attendance import AttendanceRecord, AttendanceSession
from ..models.classroom import Classroom
from ..models.student import Student

# --- Constants & Risk Levels -------------------------------------------------

RISK_HIGH = "HIGH"
RISK_MEDIUM = "MEDIUM"
RISK_LOW = "LOW"
ALL_RISK_LEVELS = (RISK_HIGH, RISK_MEDIUM, RISK_LOW)

# --- Rule Flag Codes ---------------------------------------------------------

FLAG_THRESHOLD_BREACH = "THRESHOLD_BREACH"
FLAG_CRITICAL_DEFICIT = "CRITICAL_DEFICIT"
FLAG_NEGATIVE_VELOCITY = "NEGATIVE_VELOCITY"
FLAG_CONSECUTIVE_ABSENCE = "CONSECUTIVE_ABSENCE"
FLAG_CONSECUTIVE_ABSENCE_WARNING = "CONSECUTIVE_ABSENCE_WARNING"
FLAG_COMPOUND_SHORTAGE_RISK = "COMPOUND_SHORTAGE_RISK"
FLAG_ATTENDANCE_ON_TRACK = "ATTENDANCE_ON_TRACK"
FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

# --- Default Threshold Configurations ----------------------------------------

DEFAULT_MIN_ATTENDANCE_THRESHOLD = 75.0
DEFAULT_CRITICAL_ATTENDANCE_THRESHOLD = 60.0
DEFAULT_VELOCITY_DECLINE_THRESHOLD = 10.0  # decline > 10%
DEFAULT_CONSECUTIVE_ABSENCE_HIGH = 3
DEFAULT_CONSECUTIVE_ABSENCE_MEDIUM = 2
DEFAULT_PARTIAL_CREDIT_WEIGHT = 0.5


# --- In-Memory Data Structures (Decoupled from ORM) ---------------------------

@dataclass
class SessionRecordInput:
    """Represents a student's attendance record in a single session."""
    session_id: int
    session_date: datetime.date
    status: str
    class_start_time: Optional[datetime.datetime] = None


@dataclass
class StudentRiskProfile:
    """Calculated risk evaluation and explanation for a single student."""
    student_id: int
    student_name: str
    roll_number: str
    prn_number: Optional[str]
    total_sessions: int
    attended_sessions: float
    attendance_percentage: float
    min_threshold_percentage: float
    attendance_velocity: Optional[float]
    consecutive_absences: int
    max_consecutive_absences: int
    risk_level: str
    is_at_risk: bool
    risk_score: int
    sessions_needed_to_recover: int
    buffer_sessions_allowed: int
    rule_flags: List[Dict[str, Any]] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "student_id": self.student_id,
            "student_name": self.student_name,
            "roll_number": self.roll_number,
            "prn_number": self.prn_number,
            "total_sessions": self.total_sessions,
            "attended_sessions": self.attended_sessions,
            "attendance_percentage": self.attendance_percentage,
            "min_threshold_percentage": self.min_threshold_percentage,
            "attendance_velocity": self.attendance_velocity,
            "consecutive_absences": self.consecutive_absences,
            "max_consecutive_absences": self.max_consecutive_absences,
            "risk_level": self.risk_level,
            "is_at_risk": self.is_at_risk,
            "risk_score": self.risk_score,
            "sessions_needed_to_recover": self.sessions_needed_to_recover,
            "buffer_sessions_allowed": self.buffer_sessions_allowed,
            "rule_flags": self.rule_flags,
            "recommendations": self.recommendations,
        }


# --- Core Pure Scoring Engine (No DB Dependency) ------------------------------

def _status_credit(status: Optional[str], partial_credit: float = DEFAULT_PARTIAL_CREDIT_WEIGHT) -> float:
    if not status:
        return 0.0
    norm = status.strip().upper()
    if norm in ("PRESENT", "P"):
        return 1.0
    if norm in ("PARTIAL",):
        return partial_credit
    if norm in ("EXCUSED", "ON_DUTY"):
        return 1.0
    return 0.0


def calculate_attendance_velocity(
    records: Sequence[SessionRecordInput],
    partial_credit: float = DEFAULT_PARTIAL_CREDIT_WEIGHT,
) -> Optional[float]:
    """Computes attendance velocity across consecutive periods.

    Primary method: Week-over-week difference between the two most recent weeks
    with recorded sessions.
    Fallback method: If sessions span only 1 week but total sessions >= 4,
    compares recent half vs older half.
    Returns:
      Signed float percentage delta (e.g. -15.5 for a 15.5% drop), or None if
      insufficient temporal data exists.
    """
    if not records or len(records) < 2:
        return None

    # Group by ISO week (year, week_number)
    weekly_buckets: Dict[Tuple[int, int], List[SessionRecordInput]] = {}
    for r in records:
        iso_year, iso_week, _ = r.session_date.isocalendar()
        key = (iso_year, iso_week)
        weekly_buckets.setdefault(key, []).append(r)

    sorted_weeks = sorted(weekly_buckets.keys())

    if len(sorted_weeks) >= 2:
        # Compare the most recent week with the one immediately preceding it
        prev_week_key = sorted_weeks[-2]
        curr_week_key = sorted_weeks[-1]

        prev_recs = weekly_buckets[prev_week_key]
        curr_recs = weekly_buckets[curr_week_key]

        prev_pct = (sum(_status_credit(r.status, partial_credit) for r in prev_recs) / len(prev_recs)) * 100.0
        curr_pct = (sum(_status_credit(r.status, partial_credit) for r in curr_recs) / len(curr_recs)) * 100.0

        return round(curr_pct - prev_pct, 2)

    # Fallback for single-week distribution with at least 4 sessions
    if len(records) >= 4:
        halfway = len(records) // 2
        older_half = records[:halfway]
        newer_half = records[halfway:]

        older_pct = (sum(_status_credit(r.status, partial_credit) for r in older_half) / len(older_half)) * 100.0
        newer_pct = (sum(_status_credit(r.status, partial_credit) for r in newer_half) / len(newer_half)) * 100.0

        return round(newer_pct - older_pct, 2)

    return None


def calculate_consecutive_absences(
    records: Sequence[SessionRecordInput],
    partial_credit: float = DEFAULT_PARTIAL_CREDIT_WEIGHT,
) -> Tuple[int, int]:
    """Computes (current_recent_consecutive_absences, max_consecutive_absences)."""
    if not records:
        return 0, 0

    # 1. Recent consecutive absences from tail backwards
    recent_consecutive = 0
    for r in reversed(records):
        credit = _status_credit(r.status, partial_credit)
        if credit == 0.0:
            recent_consecutive += 1
        else:
            break

    # 2. Maximum consecutive absences across the entire timeline
    max_streak = 0
    curr_streak = 0
    for r in records:
        credit = _status_credit(r.status, partial_credit)
        if credit == 0.0:
            curr_streak += 1
            if curr_streak > max_streak:
                max_streak = curr_streak
        else:
            curr_streak = 0

    return recent_consecutive, max_streak


def calculate_recovery_and_buffer(
    total_sessions: int,
    attended_credits: float,
    threshold_pct: float,
) -> Tuple[int, int]:
    """Calculates:
      - sessions_needed_to_recover: sessions student must attend with full credit
        to reach >= threshold_pct.
      - buffer_sessions_allowed: sessions student can miss before falling below
        threshold_pct.
    """
    if total_sessions <= 0:
        return 0, 0

    # Avoid division by zero if threshold_pct == 100
    effective_t = min(max(threshold_pct, 1.0), 99.99)
    current_pct = (attended_credits / total_sessions) * 100.0

    if current_pct < threshold_pct:
        # Solve (attended + k) / (total + k) >= T/100
        # k * (100 - T) >= T * total - 100 * attended
        needed_num = (effective_t * total_sessions) - (100.0 * attended_credits)
        needed_den = 100.0 - effective_t
        needed_k = math.ceil(needed_num / needed_den)
        return max(0, needed_k), 0
    else:
        # Solve attended / (total + b) >= T/100
        # b * T <= 100 * attended - T * total
        allowed_num = (100.0 * attended_credits) - (effective_t * total_sessions)
        allowed_b = math.floor(allowed_num / effective_t)
        return 0, max(0, allowed_b)


def evaluate_student_risk(
    student_id: int,
    student_name: str,
    roll_number: str,
    prn_number: Optional[str],
    session_records: Sequence[SessionRecordInput],
    *,
    min_threshold_percentage: float = DEFAULT_MIN_ATTENDANCE_THRESHOLD,
    critical_threshold_percentage: float = DEFAULT_CRITICAL_ATTENDANCE_THRESHOLD,
    velocity_decline_threshold: float = DEFAULT_VELOCITY_DECLINE_THRESHOLD,
    consecutive_absence_high: int = DEFAULT_CONSECUTIVE_ABSENCE_HIGH,
    consecutive_absence_medium: int = DEFAULT_CONSECUTIVE_ABSENCE_MEDIUM,
    partial_credit: float = DEFAULT_PARTIAL_CREDIT_WEIGHT,
) -> StudentRiskProfile:
    """Pure evaluation function that computes risk categorization and rule flags."""
    # Ensure chronological sort
    sorted_records = sorted(
        session_records,
        key=lambda r: (r.session_date, r.class_start_time or datetime.datetime.min, r.session_id),
    )

    total_sessions = len(sorted_records)

    # Empty history edge case
    if total_sessions == 0:
        return StudentRiskProfile(
            student_id=student_id,
            student_name=student_name,
            roll_number=roll_number,
            prn_number=prn_number,
            total_sessions=0,
            attended_sessions=0.0,
            attendance_percentage=100.0,
            min_threshold_percentage=min_threshold_percentage,
            attendance_velocity=None,
            consecutive_absences=0,
            max_consecutive_absences=0,
            risk_level=RISK_LOW,
            is_at_risk=False,
            risk_score=0,
            sessions_needed_to_recover=0,
            buffer_sessions_allowed=0,
            rule_flags=[
                {
                    "code": FLAG_INSUFFICIENT_DATA,
                    "severity": "INFO",
                    "description": "No attendance sessions recorded yet.",
                }
            ],
            recommendations=["No session history available to calculate attendance risk."],
        )

    attended_credits = sum(_status_credit(r.status, partial_credit) for r in sorted_records)
    attendance_pct = round((attended_credits / total_sessions) * 100.0, 2)

    velocity = calculate_attendance_velocity(sorted_records, partial_credit)
    recent_consecutive, max_consecutive = calculate_consecutive_absences(sorted_records, partial_credit)
    needed_k, buffer_b = calculate_recovery_and_buffer(total_sessions, attended_credits, min_threshold_percentage)

    rule_flags: List[Dict[str, Any]] = []
    recommendations: List[str] = []

    # 1. Threshold rules
    is_below_threshold = attendance_pct < min_threshold_percentage
    is_critical_deficit = attendance_pct < critical_threshold_percentage

    if is_critical_deficit:
        rule_flags.append({
            "code": FLAG_CRITICAL_DEFICIT,
            "severity": "HIGH",
            "description": (
                f"Critical attendance deficit: {attendance_pct}% is severely below "
                f"the critical floor ({critical_threshold_percentage}%)."
            ),
        })
        recommendations.append(
            f"Immediate student intervention required. Attendance is critically low ({attendance_pct}%)."
        )
    elif is_below_threshold:
        rule_flags.append({
            "code": FLAG_THRESHOLD_BREACH,
            "severity": "MEDIUM",
            "description": (
                f"Attendance shortage: {attendance_pct}% has fallen below "
                f"the minimum required threshold ({min_threshold_percentage}%)."
            ),
        })

    # 2. Consecutive absences
    if recent_consecutive >= consecutive_absence_high:
        rule_flags.append({
            "code": FLAG_CONSECUTIVE_ABSENCE,
            "severity": "HIGH",
            "description": (
                f"Critical absence streak: absent for the last {recent_consecutive} "
                f"consecutive sessions."
            ),
        })
        recommendations.append(
            f"Investigate active absence streak of {recent_consecutive} consecutive sessions."
        )
    elif recent_consecutive >= consecutive_absence_medium:
        rule_flags.append({
            "code": FLAG_CONSECUTIVE_ABSENCE_WARNING,
            "severity": "MEDIUM",
            "description": (
                f"Consecutive absence warning: absent for the last {recent_consecutive} "
                f"consecutive sessions."
            ),
        })
        recommendations.append(
            f"Monitor student: missed {recent_consecutive} consecutive sessions."
        )

    # 3. Attendance Velocity
    has_negative_velocity = False
    if velocity is not None and velocity < -velocity_decline_threshold:
        has_negative_velocity = True
        velocity_severity = "HIGH" if is_below_threshold else "MEDIUM"
        rule_flags.append({
            "code": FLAG_NEGATIVE_VELOCITY,
            "severity": velocity_severity,
            "description": (
                f"Negative attendance velocity: attendance dropped by {abs(velocity):.1f}% "
                f"over consecutive periods (exceeds {velocity_decline_threshold}% decline threshold)."
            ),
        })
        recommendations.append(
            f"Rapid attendance drop detected ({velocity}% decline). Check for recent disengagement."
        )

    # 4. Compound Shortage Risk
    if is_below_threshold and has_negative_velocity:
        rule_flags.append({
            "code": FLAG_COMPOUND_SHORTAGE_RISK,
            "severity": "HIGH",
            "description": (
                f"Compounded shortage risk: student is already below threshold ({attendance_pct}%) "
                f"and continuing to decline ({velocity}%)."
            ),
        })

    # 5. Recovery Recommendation
    if is_below_threshold and needed_k > 0:
        recommendations.append(
            f"Student must attend the next {needed_k} consecutive sessions with 100% presence "
            f"to reach the minimum {min_threshold_percentage}% threshold."
        )
    elif buffer_b > 0:
        recommendations.append(
            f"Student can afford to miss up to {buffer_b} more session(s) before falling below {min_threshold_percentage}%."
        )

    # 6. Categorization into LOW, MEDIUM, HIGH
    # High risk conditions
    is_high_risk = (
        is_critical_deficit
        or (recent_consecutive >= consecutive_absence_high)
        or (is_below_threshold and has_negative_velocity)
    )

    # Medium risk conditions (if not High)
    is_medium_risk = (
        not is_high_risk and (
            is_below_threshold
            or (recent_consecutive >= consecutive_absence_medium)
            or has_negative_velocity
        )
    )

    if is_high_risk:
        risk_level = RISK_HIGH
        is_at_risk = True
    elif is_medium_risk:
        risk_level = RISK_MEDIUM
        is_at_risk = True
    else:
        risk_level = RISK_LOW
        is_at_risk = False
        rule_flags.append({
            "code": FLAG_ATTENDANCE_ON_TRACK,
            "severity": "LOW",
            "description": (
                f"Attendance ({attendance_pct}%) satisfies institutional requirements "
                f"(>= {min_threshold_percentage}%)."
            ),
        })
        if not recommendations:
            recommendations.append("Attendance is in good standing. No corrective action required.")

    # 7. Continuous Risk Score Calculation (0-100)
    # Deficit points
    deficit_pts = max(0.0, (min_threshold_percentage - attendance_pct)) * 1.2
    # Streak points
    streak_pts = min(30.0, recent_consecutive * 10.0)
    # Velocity points
    velocity_pts = min(25.0, max(0.0, -(velocity or 0.0)) * 0.5)

    base_score = int(round(deficit_pts + streak_pts + velocity_pts))

    if risk_level == RISK_HIGH:
        risk_score = max(70, min(100, base_score if base_score >= 70 else 70 + (recent_consecutive * 5)))
    elif risk_level == RISK_MEDIUM:
        risk_score = max(40, min(69, base_score if base_score >= 40 else 45))
    else:
        risk_score = max(0, min(39, base_score))

    return StudentRiskProfile(
        student_id=student_id,
        student_name=student_name,
        roll_number=roll_number,
        prn_number=prn_number,
        total_sessions=total_sessions,
        attended_sessions=attended_credits,
        attendance_percentage=attendance_pct,
        min_threshold_percentage=min_threshold_percentage,
        attendance_velocity=velocity,
        consecutive_absences=recent_consecutive,
        max_consecutive_absences=max_consecutive,
        risk_level=risk_level,
        is_at_risk=is_at_risk,
        risk_score=risk_score,
        sessions_needed_to_recover=needed_k,
        buffer_sessions_allowed=buffer_b,
        rule_flags=rule_flags,
        recommendations=recommendations,
    )


# --- Database Query Service Layer --------------------------------------------

def _resolve_effective_threshold(
    classroom: Classroom,
    reference_date: datetime.date,
    override_threshold: Optional[float] = None,
    db_session=None,
) -> float:
    """Resolves policy threshold for classroom or returns default/override."""
    if override_threshold is not None:
        return float(override_threshold)

    try:
        from .policy_resolution import resolve_policy

        policy = resolve_policy(
            subject_id=classroom.subject_id,
            division_id=classroom.division_id,
            reference_date=reference_date,
            db_session=db_session,
        )
        if policy and policy.present_threshold_percentage:
            return float(policy.present_threshold_percentage)
    except Exception:
        pass

    return DEFAULT_MIN_ATTENDANCE_THRESHOLD


def calculate_class_at_risk_students(
    class_id: int,
    *,
    threshold: Optional[float] = None,
    risk_level_filter: Optional[str] = None,
    only_finalised: bool = False,
    db_session=None,
) -> Dict[str, Any]:
    """Evaluates attendance risk for all students enrolled in a classroom.

    Args:
      class_id: Classroom identifier.
      threshold: Optional minimum attendance percentage threshold override.
      risk_level_filter: Optional filter ('HIGH', 'MEDIUM', 'LOW', or 'AT_RISK').
      only_finalised: If True, only sessions with is_finalised=True are evaluated.
      db_session: Optional SQLAlchemy session.

    Returns:
      Comprehensive at-risk summary dictionary.
    """
    sa_session = db_session or db.session

    classroom = sa_session.query(Classroom).get(class_id)
    if not classroom:
        raise ValueError(f"Classroom {class_id} not found")

    today = datetime.date.today()
    effective_threshold = _resolve_effective_threshold(classroom, today, threshold, sa_session)

    # Query sessions for this classroom
    sess_query = sa_session.query(AttendanceSession).filter_by(class_id=class_id)
    if only_finalised:
        sess_query = sess_query.filter_by(is_finalised=True)
    sessions = sess_query.order_by(
        AttendanceSession.session_date.asc(),
        AttendanceSession.class_start_time.asc(),
        AttendanceSession.id.asc(),
    ).all()

    session_ids = [s.id for s in sessions]
    session_map = {s.id: s for s in sessions}

    # Query students enrolled in the class
    students = sa_session.query(Student).filter_by(class_id=class_id).order_by(Student.roll_number.asc()).all()

    # Query all attendance records for these sessions
    records_by_student: Dict[int, List[SessionRecordInput]] = {st.id: [] for st in students}
    if session_ids and students:
        records = sa_session.query(AttendanceRecord).filter(
            AttendanceRecord.session_id.in_(session_ids),
        ).all()

        record_lookup: Dict[Tuple[int, int], str] = {}
        for r in records:
            record_lookup[(r.student_id, r.session_id)] = r.status

        # Build chronological record sequence for each student across all sessions
        for st in students:
            for s in sessions:
                status = record_lookup.get((st.id, s.id), "ABSENT")
                records_by_student[st.id].append(
                    SessionRecordInput(
                        session_id=s.id,
                        session_date=s.session_date,
                        status=status,
                        class_start_time=s.class_start_time,
                    )
                )

    evaluated_profiles: List[StudentRiskProfile] = []
    for st in students:
        profile = evaluate_student_risk(
            student_id=st.id,
            student_name=st.name,
            roll_number=st.roll_number,
            prn_number=st.prn_number,
            session_records=records_by_student[st.id],
            min_threshold_percentage=effective_threshold,
        )
        evaluated_profiles.append(profile)

    # Apply optional filter
    if risk_level_filter:
        norm_filter = risk_level_filter.strip().upper()
        if norm_filter == "AT_RISK":
            filtered_profiles = [p for p in evaluated_profiles if p.is_at_risk]
        elif norm_filter in ALL_RISK_LEVELS:
            filtered_profiles = [p for p in evaluated_profiles if p.risk_level == norm_filter]
        else:
            filtered_profiles = evaluated_profiles
    else:
        filtered_profiles = evaluated_profiles

    # Sort profiles: highest risk score first, then roll number
    filtered_profiles.sort(key=lambda p: (-p.risk_score, p.roll_number))

    high_risk_count = sum(1 for p in evaluated_profiles if p.risk_level == RISK_HIGH)
    medium_risk_count = sum(1 for p in evaluated_profiles if p.risk_level == RISK_MEDIUM)
    low_risk_count = sum(1 for p in evaluated_profiles if p.risk_level == RISK_LOW)

    return {
        "class_id": classroom.id,
        "class_name": classroom.name,
        "subject": classroom.subject,
        "subject_id": classroom.subject_id,
        "division_id": classroom.division_id,
        "threshold_percentage": effective_threshold,
        "total_students": len(students),
        "total_sessions": len(sessions),
        "summary": {
            "high_risk_count": high_risk_count,
            "medium_risk_count": medium_risk_count,
            "low_risk_count": low_risk_count,
            "at_risk_total": high_risk_count + medium_risk_count,
        },
        "students": [p.to_dict() for p in filtered_profiles],
    }


def calculate_subject_at_risk_students(
    subject_id: int,
    *,
    division_id: Optional[int] = None,
    threshold: Optional[float] = None,
    risk_level_filter: Optional[str] = None,
    only_finalised: bool = False,
    db_session=None,
) -> Dict[str, Any]:
    """Evaluates attendance risk across all classrooms associated with an academic subject."""
    sa_session = db_session or db.session

    subject = sa_session.query(Subject).get(subject_id)
    if not subject:
        raise ValueError(f"Subject {subject_id} not found")

    cls_query = sa_session.query(Classroom).filter_by(subject_id=subject_id)
    if division_id is not None:
        cls_query = cls_query.filter_by(division_id=division_id)
    classrooms = cls_query.all()

    class_results: List[Dict[str, Any]] = []
    all_students_map: Dict[int, Dict[str, Any]] = {}

    for cls in classrooms:
        res = calculate_class_at_risk_students(
            cls.id,
            threshold=threshold,
            risk_level_filter=risk_level_filter,
            only_finalised=only_finalised,
            db_session=sa_session,
        )
        class_results.append(res)
        for st in res["students"]:
            all_students_map[st["student_id"]] = st

    combined_students = list(all_students_map.values())
    combined_students.sort(key=lambda s: (-s["risk_score"], s["roll_number"]))

    high_risk_count = sum(1 for s in combined_students if s["risk_level"] == RISK_HIGH)
    medium_risk_count = sum(1 for s in combined_students if s["risk_level"] == RISK_MEDIUM)
    low_risk_count = sum(1 for s in combined_students if s["risk_level"] == RISK_LOW)

    return {
        "subject_id": subject.id,
        "subject_code": subject.code,
        "subject_name": subject.name,
        "division_id": division_id,
        "total_classes": len(classrooms),
        "total_students": len(combined_students),
        "summary": {
            "high_risk_count": high_risk_count,
            "medium_risk_count": medium_risk_count,
            "low_risk_count": low_risk_count,
            "at_risk_total": high_risk_count + medium_risk_count,
        },
        "classes": class_results,
        "students": combined_students,
    }


def calculate_student_risk_profile(
    student_id: int,
    *,
    class_id: Optional[int] = None,
    threshold: Optional[float] = None,
    only_finalised: bool = False,
    db_session=None,
) -> Dict[str, Any]:
    """Fetches full attendance risk profile and session timeline for a single student."""
    sa_session = db_session or db.session

    student = sa_session.query(Student).get(student_id)
    if not student:
        raise ValueError(f"Student {student_id} not found")

    target_class_id = class_id or student.class_id
    classroom = sa_session.query(Classroom).get(target_class_id)
    if not classroom:
        raise ValueError(f"Classroom {target_class_id} not found")

    today = datetime.date.today()
    effective_threshold = _resolve_effective_threshold(classroom, today, threshold, sa_session)

    sess_query = sa_session.query(AttendanceSession).filter_by(class_id=target_class_id)
    if only_finalised:
        sess_query = sess_query.filter_by(is_finalised=True)
    sessions = sess_query.order_by(
        AttendanceSession.session_date.asc(),
        AttendanceSession.class_start_time.asc(),
        AttendanceSession.id.asc(),
    ).all()

    session_ids = [s.id for s in sessions]
    record_lookup: Dict[int, AttendanceRecord] = {}
    if session_ids:
        records = sa_session.query(AttendanceRecord).filter(
            AttendanceRecord.session_id.in_(session_ids),
            AttendanceRecord.student_id == student.id,
        ).all()
        for r in records:
            record_lookup[r.session_id] = r

    session_records: List[SessionRecordInput] = []
    timeline: List[Dict[str, Any]] = []

    for s in sessions:
        rec = record_lookup.get(s.id)
        status = rec.status if rec else "ABSENT"
        session_records.append(
            SessionRecordInput(
                session_id=s.id,
                session_date=s.session_date,
                status=status,
                class_start_time=s.class_start_time,
            )
        )
        timeline.append({
            "session_id": s.id,
            "session_date": s.session_date.isoformat(),
            "class_start_time": s.class_start_time.isoformat() if s.class_start_time else None,
            "status": status,
            "is_finalised": s.is_finalised,
            "flagged": rec.flagged if rec else False,
        })

    profile = evaluate_student_risk(
        student_id=student.id,
        student_name=student.name,
        roll_number=student.roll_number,
        prn_number=student.prn_number,
        session_records=session_records,
        min_threshold_percentage=effective_threshold,
    )

    data = profile.to_dict()
    data["class_id"] = classroom.id
    data["class_name"] = classroom.name
    data["subject"] = classroom.subject
    data["timeline"] = timeline
    return data


def get_at_risk_dashboard_overview(
    user,
    *,
    threshold: Optional[float] = None,
    only_finalised: bool = False,
    db_session=None,
) -> Dict[str, Any]:
    """Generates an aggregated at-risk overview across all classrooms visible to a user."""
    from flask import current_app

    sa_session = db_session or db.session

    cls_query = sa_session.query(Classroom)
    if not (user.role == "hod" and current_app.config.get("HOD_SEES_ALL")):
        cls_query = cls_query.filter_by(created_by=user.id)

    classrooms = cls_query.order_by(Classroom.created_at.desc()).all()

    class_summaries: List[Dict[str, Any]] = []
    all_at_risk_students: List[Dict[str, Any]] = []

    total_students_monitored = 0
    total_high = 0
    total_medium = 0
    total_low = 0

    for cls in classrooms:
        try:
            res = calculate_class_at_risk_students(
                cls.id,
                threshold=threshold,
                only_finalised=only_finalised,
                db_session=sa_session,
            )
            total_students_monitored += res["total_students"]
            total_high += res["summary"]["high_risk_count"]
            total_medium += res["summary"]["medium_risk_count"]
            total_low += res["summary"]["low_risk_count"]

            class_summaries.append({
                "class_id": cls.id,
                "class_name": cls.name,
                "subject": cls.subject,
                "total_students": res["total_students"],
                "total_sessions": res["total_sessions"],
                "summary": res["summary"],
            })

            for s in res["students"]:
                if s["is_at_risk"]:
                    s_copy = dict(s)
                    s_copy["class_id"] = cls.id
                    s_copy["class_name"] = cls.name
                    all_at_risk_students.append(s_copy)
        except Exception:
            continue

    # Sort at-risk students by highest risk score first
    all_at_risk_students.sort(key=lambda s: -s["risk_score"])

    return {
        "total_classes_monitored": len(classrooms),
        "total_students_monitored": total_students_monitored,
        "high_risk_count": total_high,
        "medium_risk_count": total_medium,
        "low_risk_count": total_low,
        "total_at_risk": total_high + total_medium,
        "classrooms": class_summaries,
        "top_at_risk_students": all_at_risk_students[:15],
    }
