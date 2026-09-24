"""Phase 6 - explainable, deterministic attendance-decision rules.

This module contains no database dependency and no I/O: it takes
already-loaded plain data (presence summaries, policy values, conflict
counts) and returns a suggested main status plus independent flags. It
never produces a *final* attendance decision - see the module
docstring on attendance_recommendation_service.py for the full
separation between "AI-suggested" and "official/finalised".

Decision precedence (highest first - see Phase 6 PRD section E):
  1. REVIEW_REQUIRED - evidence is missing, incomplete, conflicting or
     unreliable enough that an automatic PRESENT/PARTIAL/ABSENT
     decision would be misleading.
  2. PRESENT - reliable presence_percentage >= policy threshold.
  3. PARTIAL - reliable presence_percentage in (0, threshold).
  4. ABSENT - reliable presence_percentage is exactly 0, with no
     unresolved evidence problems.

EXCUSED and ON_DUTY are valid statuses in the domain but this engine
never produces them - they require authorized human/administrative
evidence that does not exist yet (a later phase).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

DECISION_VERSION = "attendance_rules_v1"

# --- Main status domain --------------------------------------------------

STATUS_PRESENT = "PRESENT"
STATUS_PARTIAL = "PARTIAL"
STATUS_ABSENT = "ABSENT"
STATUS_EXCUSED = "EXCUSED"
STATUS_ON_DUTY = "ON_DUTY"
STATUS_REVIEW_REQUIRED = "REVIEW_REQUIRED"

ALL_MAIN_STATUSES = (
    STATUS_PRESENT, STATUS_PARTIAL, STATUS_ABSENT,
    STATUS_EXCUSED, STATUS_ON_DUTY, STATUS_REVIEW_REQUIRED,
)

# The only statuses this automatic engine is ever allowed to assign.
# EXCUSED/ON_DUTY are deliberately excluded - see module docstring.
AI_GENERATABLE_STATUSES = (STATUS_PRESENT, STATUS_PARTIAL, STATUS_ABSENT, STATUS_REVIEW_REQUIRED)

# --- Independent flag domain ---------------------------------------------

FLAG_LATE = "LATE"
FLAG_EARLY_EXIT = "EARLY_EXIT"
FLAG_RE_ENTRY = "RE_ENTRY"
FLAG_LOW_CONFIDENCE = "LOW_CONFIDENCE"
FLAG_CAMERA_OUTAGE = "CAMERA_OUTAGE"
FLAG_IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
FLAG_FACULTY_OVERRIDE = "FACULTY_OVERRIDE"

ALL_FLAG_TYPES = (
    FLAG_LATE, FLAG_EARLY_EXIT, FLAG_RE_ENTRY, FLAG_LOW_CONFIDENCE,
    FLAG_CAMERA_OUTAGE, FLAG_IDENTITY_CONFLICT, FLAG_FACULTY_OVERRIDE,
)

# FACULTY_OVERRIDE is registered as an allowed flag type but this engine
# (and Phase 6 as a whole) never generates it - only a later faculty
# override workflow does.
AI_GENERATABLE_FLAGS = (
    FLAG_LATE, FLAG_EARLY_EXIT, FLAG_RE_ENTRY, FLAG_LOW_CONFIDENCE,
    FLAG_CAMERA_OUTAGE, FLAG_IDENTITY_CONFLICT,
)

FLAG_SOURCE_AI_RULE = "AI_RULE"
ALL_FLAG_SOURCES = (FLAG_SOURCE_AI_RULE, "FACULTY", "SYSTEM")

# --- Stable, machine-readable reason codes --------------------------------

REASON_PRESENCE_MEETS_THRESHOLD = "PRESENCE_MEETS_THRESHOLD"
REASON_PRESENCE_BELOW_FULL_CREDIT = "PRESENCE_BELOW_FULL_CREDIT"
REASON_NO_RELIABLE_PRESENCE = "NO_RELIABLE_PRESENCE"
REASON_FACE_TEMPLATE_UNAVAILABLE = "FACE_TEMPLATE_UNAVAILABLE"
REASON_PRESENCE_RECONSTRUCTION_INCOMPLETE = "PRESENCE_RECONSTRUCTION_INCOMPLETE"
REASON_VALID_SESSION_DURATION_UNAVAILABLE = "VALID_SESSION_DURATION_UNAVAILABLE"
REASON_VIDEO_EOF_NOT_REACHED = "VIDEO_EOF_NOT_REACHED"
# Reliability correction: `eof_reached=None` (no persisted proof either
# way - e.g. a legacy session processed before this evidence existed)
# is NOT the same as `eof_reached=True`, and must never be silently
# treated as if the video had verifiably reached EOF.
REASON_FULL_VIDEO_COMPLETION_UNVERIFIED = "FULL_VIDEO_COMPLETION_UNVERIFIED"
REASON_IDENTITY_CONFLICT_UNRESOLVED = "IDENTITY_CONFLICT_UNRESOLVED"
REASON_PRESENCE_EXCEEDS_SESSION_DURATION = "PRESENCE_EXCEEDS_SESSION_DURATION"
REASON_CONFIDENCE_BELOW_DECISION_MINIMUM = "CONFIDENCE_BELOW_DECISION_MINIMUM"
REASON_EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
# Raised by the orchestration layer (attendance_recommendation_service.py),
# never by evaluate_student() itself - policy resolution happens once
# per session, before any per-student evaluation.
REASON_POLICY_UNRESOLVED = "POLICY_UNRESOLVED"

_INELIGIBLE_REASON_TEXT = "A compatible face template was unavailable, so attendance could not be determined automatically."


class PolicyValidationError(ValueError):
    pass


@dataclass
class DecisionPolicy:
    """The minimal set of policy values the engine needs, decoupled
    from the ORM. `policy_id`/`policy_name` are carried through purely
    for the explanation snapshot."""

    policy_id: int | None
    policy_name: str
    present_threshold_percentage: float
    late_grace_seconds: float
    early_exit_tolerance_seconds: float
    reentry_min_gap_seconds: float
    low_confidence_flag_threshold: float
    minimum_decision_confidence: float
    minimum_valid_session_ratio: float

    def validate(self) -> None:
        if not (0.0 < self.present_threshold_percentage <= 100.0):
            raise PolicyValidationError("present_threshold_percentage must be in (0, 100]")
        if self.late_grace_seconds < 0:
            raise PolicyValidationError("late_grace_seconds must be >= 0")
        if self.early_exit_tolerance_seconds < 0:
            raise PolicyValidationError("early_exit_tolerance_seconds must be >= 0")
        if self.reentry_min_gap_seconds <= 0:
            raise PolicyValidationError("reentry_min_gap_seconds must be > 0")
        if not (0.0 <= self.low_confidence_flag_threshold <= 1.0):
            raise PolicyValidationError("low_confidence_flag_threshold must be in [0, 1]")
        if not (0.0 <= self.minimum_decision_confidence <= 1.0):
            raise PolicyValidationError("minimum_decision_confidence must be in [0, 1]")
        if self.minimum_decision_confidence > self.low_confidence_flag_threshold:
            raise PolicyValidationError("minimum_decision_confidence must be <= low_confidence_flag_threshold")
        if not (0.0 <= self.minimum_valid_session_ratio <= 1.0):
            raise PolicyValidationError("minimum_valid_session_ratio must be in [0, 1]")

    def to_snapshot(self) -> dict:
        return {
            "policy_id": self.policy_id,
            "policy_name": self.policy_name,
            "present_threshold_percentage": self.present_threshold_percentage,
            "late_grace_seconds": self.late_grace_seconds,
            "early_exit_tolerance_seconds": self.early_exit_tolerance_seconds,
            "reentry_min_gap_seconds": self.reentry_min_gap_seconds,
            "low_confidence_flag_threshold": self.low_confidence_flag_threshold,
            "minimum_decision_confidence": self.minimum_decision_confidence,
            "minimum_valid_session_ratio": self.minimum_valid_session_ratio,
            "decision_version": DECISION_VERSION,
        }


@dataclass
class SessionEvidenceContext:
    """Session-wide facts the engine needs before evaluating any
    individual student."""

    eof_reached: bool | None
    presence_reconstruction_status: str
    valid_session_seconds: float | None


@dataclass
class StudentEvidence:
    """Everything the engine needs about one rostered student. All of
    this is derived from Phase 3/4/5 outputs - this module never reads
    raw embeddings, images, or filesystem paths."""

    student_id: int
    eligible_for_recognition: bool
    ineligible_reason_code: str | None = None
    presence_percentage: float | None = None
    presence_duration_seconds: float | None = None
    window_count: int = 0
    windows: list[tuple[float, float]] = field(default_factory=list)  # (start, end) pairs, sorted
    first_confirmed_presence_seconds: float | None = None
    last_confirmed_presence_seconds: float | None = None
    mean_confidence: float | None = None
    minimum_confidence: float | None = None
    identity_conflict_track_count: int = 0


@dataclass
class DecisionResult:
    student_id: int
    suggested_status: str
    is_evaluable: bool
    reason_code: str
    reason_text: str
    flags: list[str]
    confidence: float | None
    explanation: dict


def _finite(value) -> bool:
    return value is not None and isinstance(value, (int, float)) and math.isfinite(value)


def _review(student: StudentEvidence, reason_code: str, reason_text: str, *, flags: list[str] | None = None) -> DecisionResult:
    return DecisionResult(
        student_id=student.student_id,
        suggested_status=STATUS_REVIEW_REQUIRED,
        is_evaluable=False,
        reason_code=reason_code,
        reason_text=reason_text,
        flags=list(flags or []),
        confidence=student.mean_confidence,
        explanation={
            "suggested_status": STATUS_REVIEW_REQUIRED,
            "reason_code": reason_code,
            "presence_percentage": student.presence_percentage,
            "presence_duration_seconds": student.presence_duration_seconds,
            "window_count": student.window_count,
            "mean_confidence": student.mean_confidence,
            "flags": list(flags or []),
        },
    )


def _independent_flags(student: StudentEvidence, policy: DecisionPolicy, session_start_seconds: float) -> list[str]:
    """Flags that may co-occur with any main status, including
    REVIEW_REQUIRED - see Phase 6 PRD section I. LATE/EARLY_EXIT/
    RE_ENTRY require at least one trustworthy presence window;
    IDENTITY_CONFLICT and LOW_CONFIDENCE only require the relevant
    evidence to exist. CAMERA_OUTAGE and FACULTY_OVERRIDE are never
    generated here (see module docstring)."""
    flags: list[str] = []

    if student.identity_conflict_track_count > 0:
        flags.append(FLAG_IDENTITY_CONFLICT)

    if student.mean_confidence is not None and _finite(student.mean_confidence):
        if student.mean_confidence < policy.low_confidence_flag_threshold:
            flags.append(FLAG_LOW_CONFIDENCE)

    if student.first_confirmed_presence_seconds is not None:
        if student.first_confirmed_presence_seconds > session_start_seconds + policy.late_grace_seconds:
            flags.append(FLAG_LATE)

    # EARLY_EXIT needs the valid session end, which is only known to
    # evaluate_student() (not this helper) - applied there instead.

    if len(student.windows) >= 2:
        ordered = sorted(student.windows, key=lambda w: w[0])
        for (prev_start, prev_end), (next_start, _next_end) in zip(ordered, ordered[1:]):
            if next_start - prev_end >= policy.reentry_min_gap_seconds:
                flags.append(FLAG_RE_ENTRY)
                break

    return flags


def evaluate_student(
    student: StudentEvidence,
    policy: DecisionPolicy,
    session: SessionEvidenceContext,
    *,
    session_start_seconds: float = 0.0,
) -> DecisionResult:
    """Evaluates exactly one rostered student against one resolved
    policy and returns exactly one DecisionResult. Deterministic: the
    same inputs always produce the same output."""
    policy.validate()

    # --- Priority 1: REVIEW_REQUIRED (insufficient/unreliable evidence) ---

    if not student.eligible_for_recognition:
        return _review(student, student.ineligible_reason_code or REASON_FACE_TEMPLATE_UNAVAILABLE, _INELIGIBLE_REASON_TEXT)

    if session.eof_reached is False:
        return _review(
            student, REASON_VIDEO_EOF_NOT_REACHED,
            "Attendance could not be evaluated automatically because the video did not reach its end.",
        )

    if session.eof_reached is None:
        # No persisted proof either way - most commonly a legacy
        # session processed before full-video-completion evidence was
        # recorded (it may have used early-stop processing). NULL is
        # never treated as if EOF had been verifiably reached.
        return _review(
            student, REASON_FULL_VIDEO_COMPLETION_UNVERIFIED,
            "Attendance could not be evaluated automatically because full-video completion could not be verified for this session.",
        )

    if session.presence_reconstruction_status not in ("COMPLETED", "PARTIAL_EVIDENCE"):
        return _review(
            student, REASON_PRESENCE_RECONSTRUCTION_INCOMPLETE,
            "Attendance could not be evaluated automatically because presence reconstruction did not complete successfully.",
        )

    if not _finite(session.valid_session_seconds) or session.valid_session_seconds <= 0:
        return _review(
            student, REASON_VALID_SESSION_DURATION_UNAVAILABLE,
            "Attendance could not be evaluated automatically because the valid session duration is missing or zero.",
        )

    valid_seconds = session.valid_session_seconds

    # A material, unresolved identity conflict makes automatic
    # evaluation unsafe - still surfaced as a flag for explainability.
    conflict_flags = [FLAG_IDENTITY_CONFLICT] if student.identity_conflict_track_count > 0 else []
    if student.identity_conflict_track_count > 0:
        return _review(
            student, REASON_IDENTITY_CONFLICT_UNRESOLVED,
            "Attendance could not be evaluated automatically because an unresolved identity conflict affects this student's evidence.",
            flags=conflict_flags,
        )

    if student.presence_percentage is None or not _finite(student.presence_percentage):
        return _review(
            student, REASON_EVIDENCE_INCOMPLETE,
            "Attendance could not be evaluated automatically because required presence evidence is incomplete.",
        )

    raw_duration = student.presence_duration_seconds
    if raw_duration is not None and _finite(raw_duration) and raw_duration > valid_seconds + 1e-6:
        return _review(
            student, REASON_PRESENCE_EXCEEDS_SESSION_DURATION,
            "Attendance could not be evaluated automatically because reconstructed presence exceeded the valid session duration.",
        )

    if student.mean_confidence is not None and _finite(student.mean_confidence):
        if student.mean_confidence < policy.minimum_decision_confidence:
            return _review(
                student, REASON_CONFIDENCE_BELOW_DECISION_MINIMUM,
                "Attendance could not be evaluated automatically because recognition confidence was below the policy's reliable-decision threshold.",
                flags=[FLAG_LOW_CONFIDENCE],
            )

    # --- Priorities 2-4: PRESENT / PARTIAL / ABSENT ---

    percentage = student.presence_percentage
    flags = _independent_flags(student, policy, session_start_seconds)
    if student.last_confirmed_presence_seconds is not None:
        if student.last_confirmed_presence_seconds < valid_seconds - policy.early_exit_tolerance_seconds:
            flags.append(FLAG_EARLY_EXIT)

    if percentage >= policy.present_threshold_percentage:
        suggested_status, reason_code, is_evaluable = STATUS_PRESENT, REASON_PRESENCE_MEETS_THRESHOLD, True
        reason_text = (
            f"Reliable presence was {percentage:.1f}%, meeting the "
            f"{policy.present_threshold_percentage:.0f}% full-credit threshold."
        )
    elif percentage > 0.0:
        suggested_status, reason_code, is_evaluable = STATUS_PARTIAL, REASON_PRESENCE_BELOW_FULL_CREDIT, True
        reason_text = (
            f"Reliable presence was {percentage:.1f}%, above zero but below the "
            f"{policy.present_threshold_percentage:.0f}% full-credit threshold."
        )
    else:
        suggested_status, reason_code, is_evaluable = STATUS_ABSENT, REASON_NO_RELIABLE_PRESENCE, True
        reason_text = "No reliable presence was reconstructed during the valid session duration."

    return DecisionResult(
        student_id=student.student_id,
        suggested_status=suggested_status,
        is_evaluable=is_evaluable,
        reason_code=reason_code,
        reason_text=reason_text,
        flags=flags,
        confidence=student.mean_confidence,
        explanation={
            "suggested_status": suggested_status,
            "reason_code": reason_code,
            "presence_percentage": percentage,
            "presence_duration_seconds": student.presence_duration_seconds,
            "valid_session_seconds": valid_seconds,
            "window_count": student.window_count,
            "first_confirmed_presence_seconds": student.first_confirmed_presence_seconds,
            "last_confirmed_presence_seconds": student.last_confirmed_presence_seconds,
            "mean_confidence": student.mean_confidence,
            "flags": flags,
            "excluded_evidence": {"identity_conflict_tracks": student.identity_conflict_track_count},
        },
    )
