"""Step 7   Attendance decision logic.

For each enrolled student, determines their attendance status:
  • **present**   first seen ≤ class_start_time + late_threshold
  • **late-absent**   first seen > class_start_time + late_threshold
  • **absent**   never appeared in the entire video

This matches the decision flowchart in the architecture diagram.
"""

from __future__ import annotations

from .models import AttendanceDecision, EnrolledStudent, FirstAppearance


def decide_attendance(
    enrolled: list[EnrolledStudent],
    appearances: list[FirstAppearance],
    grace_period_minutes: int = 10,
) -> list[AttendanceDecision]:
    """
    Apply the attendance decision logic for every enrolled student.

    Parameters
    ----------
    enrolled : list[EnrolledStudent]
        All students enrolled in the class.
    appearances : list[FirstAppearance]
        First-appearance records from the tracker.
    grace_period_minutes : int
        Minutes after class start before a student is marked late-absent.

    Returns
    -------
    list[AttendanceDecision]
        One decision per enrolled student.
    """
    grace_seconds = grace_period_minutes * 60

    # Build lookup: student_id -> FirstAppearance
    seen_map: dict[int, FirstAppearance] = {
        a.student_id: a for a in appearances
    }

    decisions: list[AttendanceDecision] = []

    for student in enrolled:
        appearance = seen_map.get(student.student_id)

        if appearance is None:
            # Never appeared in the entire video → ABSENT
            decisions.append(
                AttendanceDecision(
                    student_id=student.student_id,
                    student_name=student.name,
                    status="absent",
                    first_seen_sec=None,
                    confidence=None,
                )
            )
        elif appearance.first_seen_sec <= grace_seconds:
            # First seen within grace period → PRESENT
            decisions.append(
                AttendanceDecision(
                    student_id=student.student_id,
                    student_name=student.name,
                    status="present",
                    first_seen_sec=appearance.first_seen_sec,
                    confidence=appearance.confidence,
                )
            )
        else:
            # First seen after grace period → LATE-ABSENT
            decisions.append(
                AttendanceDecision(
                    student_id=student.student_id,
                    student_name=student.name,
                    status="late-absent",
                    first_seen_sec=appearance.first_seen_sec,
                    confidence=appearance.confidence,
                )
            )

    return decisions


def format_timestamp(seconds: float | None) -> str:
    """Convert seconds to HH:MM:SS format for display."""
    if seconds is None:
        return "--"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
