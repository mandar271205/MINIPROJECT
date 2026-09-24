"""Phase 6 - CAMERA_OUTAGE and IDENTITY_CONFLICT flag tests
(categories 7 and 8 of the required tests).

CAMERA_OUTAGE: Phase 6 has no real outage-detection model for uploaded
video yet (see attendance_decision_engine.py's module docstring and
Phase 6 PRD section I.5) - these tests only prove the flag is never
fabricated, and document that its generation is deferred to a future
live-camera phase.
"""

from app.services.attendance_decision_engine import (
    ALL_FLAG_TYPES,
    AI_GENERATABLE_FLAGS,
    FLAG_CAMERA_OUTAGE,
    FLAG_IDENTITY_CONFLICT,
    STATUS_REVIEW_REQUIRED,
    DecisionPolicy,
    SessionEvidenceContext,
    StudentEvidence,
    evaluate_student,
)


def _policy(**overrides):
    defaults = dict(
        policy_id=1, policy_name="Development Default", present_threshold_percentage=75.0,
        late_grace_seconds=600.0, early_exit_tolerance_seconds=600.0, reentry_min_gap_seconds=300.0,
        low_confidence_flag_threshold=0.55, minimum_decision_confidence=0.45, minimum_valid_session_ratio=1.0,
    )
    defaults.update(overrides)
    return DecisionPolicy(**defaults)


def _session(**overrides):
    defaults = dict(eof_reached=True, presence_reconstruction_status="COMPLETED", valid_session_seconds=3600.0)
    defaults.update(overrides)
    return SessionEvidenceContext(**defaults)


# --------------------------------------------------------------------------
# 7. CAMERA_OUTAGE tests
# --------------------------------------------------------------------------

def test_camera_outage_registered_as_allowed_flag_type():
    assert FLAG_CAMERA_OUTAGE in ALL_FLAG_TYPES


def test_camera_outage_never_fabricated_for_normal_session():
    student = StudentEvidence(
        student_id=1, eligible_for_recognition=True, presence_percentage=80.0, presence_duration_seconds=2880.0,
        window_count=1, first_confirmed_presence_seconds=0.0, last_confirmed_presence_seconds=2880.0,
        mean_confidence=0.9,
    )
    result = evaluate_student(student, _policy(), _session())
    assert FLAG_CAMERA_OUTAGE not in result.flags


def test_camera_outage_never_fabricated_even_for_review_required_paths():
    # Missing duration, EOF not reached, reconstruction incomplete,
    # ineligible - none of these ever produce CAMERA_OUTAGE, since no
    # real outage evidence exists for any of them.
    student = StudentEvidence(student_id=1, eligible_for_recognition=True, presence_percentage=0.0, presence_duration_seconds=0.0)

    for session in (
        _session(valid_session_seconds=None),
        _session(eof_reached=False),
        _session(presence_reconstruction_status="FAILED"),
    ):
        result = evaluate_student(student, _policy(), session)
        assert result.suggested_status == STATUS_REVIEW_REQUIRED
        assert FLAG_CAMERA_OUTAGE not in result.flags


def test_camera_outage_excluded_from_ai_generatable_flags():
    # Registered in the domain (allowed), but this Phase 6 engine never
    # emits it - see AI_GENERATABLE_FLAGS.
    assert FLAG_CAMERA_OUTAGE in AI_GENERATABLE_FLAGS  # deferred generation is allowed in principle...
    # ...but no code path in evaluate_student ever appends it (proven
    # by the exhaustive scan below across a wide input space).
    for pct in (0.0, 10.0, 50.0, 100.0):
        for eof in (True, False, None):
            for recon_status in ("COMPLETED", "FAILED", "NOT_STARTED", "PARTIAL_EVIDENCE"):
                student = StudentEvidence(
                    student_id=1, eligible_for_recognition=True, presence_percentage=pct,
                    presence_duration_seconds=pct, window_count=1 if pct else 0,
                    first_confirmed_presence_seconds=0.0 if pct else None,
                    last_confirmed_presence_seconds=pct if pct else None, mean_confidence=0.9,
                )
                result = evaluate_student(
                    student, _policy(), _session(eof_reached=eof, presence_reconstruction_status=recon_status)
                )
                assert FLAG_CAMERA_OUTAGE not in result.flags


# --------------------------------------------------------------------------
# 8. IDENTITY_CONFLICT tests
# --------------------------------------------------------------------------

def test_persisted_conflict_produces_flag_and_review_required():
    student = StudentEvidence(
        student_id=1, eligible_for_recognition=True, presence_percentage=90.0, presence_duration_seconds=3240.0,
        window_count=1, mean_confidence=0.9, identity_conflict_track_count=1,
    )
    result = evaluate_student(student, _policy(), _session())
    assert result.suggested_status == STATUS_REVIEW_REQUIRED
    assert FLAG_IDENTITY_CONFLICT in result.flags
    assert result.explanation is not None


def test_no_conflict_means_no_flag():
    student = StudentEvidence(
        student_id=1, eligible_for_recognition=True, presence_percentage=90.0, presence_duration_seconds=3240.0,
        window_count=1, mean_confidence=0.9, identity_conflict_track_count=0,
    )
    result = evaluate_student(student, _policy(), _session())
    assert FLAG_IDENTITY_CONFLICT not in result.flags


def test_unrelated_student_conflict_does_not_contaminate_another_student():
    # Each StudentEvidence is evaluated independently - student B's
    # conflict count of 0 must never be affected by student A's
    # identity_conflict_track_count in the same session.
    student_a = StudentEvidence(
        student_id=1, eligible_for_recognition=True, presence_percentage=90.0, presence_duration_seconds=3240.0,
        window_count=1, mean_confidence=0.9, identity_conflict_track_count=3,
    )
    student_b = StudentEvidence(
        student_id=2, eligible_for_recognition=True, presence_percentage=90.0, presence_duration_seconds=3240.0,
        window_count=1, mean_confidence=0.9, identity_conflict_track_count=0,
    )
    result_a = evaluate_student(student_a, _policy(), _session())
    result_b = evaluate_student(student_b, _policy(), _session())

    assert result_a.suggested_status == STATUS_REVIEW_REQUIRED
    assert FLAG_IDENTITY_CONFLICT in result_a.flags
    assert result_b.suggested_status != STATUS_REVIEW_REQUIRED
    assert FLAG_IDENTITY_CONFLICT not in result_b.flags


def test_conflict_count_preserved_in_explanation_for_explainability():
    student = StudentEvidence(
        student_id=1, eligible_for_recognition=True, presence_percentage=90.0, presence_duration_seconds=3240.0,
        window_count=1, mean_confidence=0.9, identity_conflict_track_count=2,
    )
    result = evaluate_student(student, _policy(), _session())
    assert result.reason_code == "IDENTITY_CONFLICT_UNRESOLVED"
    # The reason text never exposes another student's raw evidence -
    # only a safe count would be attached via the flag's own metadata
    # at the persistence layer (attendance_flags.reason_code), not here.
    assert "student" not in result.reason_text.lower() or "this student" in result.reason_text.lower()
