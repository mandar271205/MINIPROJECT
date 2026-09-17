"""Phase 3 correction - single source of truth for deciding which
enrolled students are eligible to enter recognition/matching/legacy
attendance decision logic, and which are not.

Used by both the pipeline (to build the actual eligible roster for a
video-processing run) and the attendance routes (to report live
eligible/ineligible counts for a class without needing to run a video).
Keeping this logic in one place avoids the exact bug this correction
fixes: an inconsistent, duplicated notion of "compatible" letting an
ineligible student fall through to the legacy present/absent decision.
"""

from __future__ import annotations

from .models import EnrolledStudent

REENROLLMENT_MESSAGE = "A compatible face template is required before attendance can be evaluated."

# Reason codes, in the order they are checked. Every one of these
# implies requires_reenrollment=True - there is no ineligible reason in
# Phase 3 that doesn't ultimately need a new/valid template.
REASON_EMBEDDING_MISSING = "EMBEDDING_MISSING"
REASON_LEGACY_INCOMPATIBLE = "LEGACY_INCOMPATIBLE"
REASON_REENROLL_REQUIRED = "REENROLL_REQUIRED"
REASON_FAILED = "FAILED"
REASON_STATUS_NOT_ACTIVE = "EMBEDDING_STATUS_NOT_ACTIVE"
REASON_MODEL_INCOMPATIBLE = "EMBEDDING_MODEL_INCOMPATIBLE"
REASON_DIMENSION_MISMATCH = "EMBEDDING_DIMENSION_MISMATCH"
REASON_INVALID_VECTOR = "EMBEDDING_INVALID"


def classify_one(student: EnrolledStudent, provider) -> str | None:
    """Returns None if *student* is eligible for recognition, or a
    reason code string if not. Never raises - an exception while
    validating the stored embedding itself is a clear ineligibility
    signal (EMBEDDING_INVALID), not a bug to propagate."""
    if student.embedding is None or student.embedding.size == 0:
        return REASON_EMBEDDING_MISSING

    status = student.embedding_status
    if status == "LEGACY_INCOMPATIBLE":
        return REASON_LEGACY_INCOMPATIBLE
    if status == "REENROLL_REQUIRED":
        return REASON_REENROLL_REQUIRED
    if status == "FAILED":
        return REASON_FAILED
    if status != "ACTIVE":
        return REASON_STATUS_NOT_ACTIVE

    if student.model_id != provider.model_id:
        return REASON_MODEL_INCOMPATIBLE
    if student.embedding_dimension != provider.embedding_dimension:
        return REASON_DIMENSION_MISMATCH

    try:
        provider.validate_embedding(student.embedding)
    except Exception:
        # Any failure validating the stored vector - wrong shape, NaN,
        # zero norm, or a provider-specific validation error - means
        # this student is not eligible. Never propagated as a bug.
        return REASON_INVALID_VECTOR

    return None


def classify_enrolled_students(
    students: list[EnrolledStudent], provider
) -> tuple[list[EnrolledStudent], list[dict]]:
    """Splits *students* into (eligible, ineligible_diagnostics).

    Each ineligible entry has exactly the shape required downstream -
    safe to return directly from an API or store in job diagnostics,
    never containing raw embedding data."""
    eligible: list[EnrolledStudent] = []
    diagnostics: list[dict] = []

    for student in students:
        reason_code = classify_one(student, provider)
        if reason_code is None:
            eligible.append(student)
        else:
            diagnostics.append(
                {
                    "student_id": student.student_id,
                    "eligible_for_recognition": False,
                    "attendance_generated": False,
                    "requires_reenrollment": True,
                    "reason_code": reason_code,
                    "message": REENROLLMENT_MESSAGE,
                }
            )

    return eligible, diagnostics
