"""Phase 6 - attendance policy resolution and validation tests
(category 9 of the required tests)."""

import datetime
import uuid

import pytest

from app.extensions import db
from app.models.attendance_policy import AttendancePolicy
from app.models.user import User
from app.services.policy_resolution import (
    PolicyAmbiguousError,
    PolicyNotFoundError,
    resolve_policy,
)
from app.utils.errors import DomainError


def _uniq_hod_id():
    hod = User.query.filter_by(role="hod").first()
    if not hod:
        hod = User(name="Seed HOD", email=f"seed_hod_{uuid.uuid4().hex[:8]}@example.com", role="hod")
        hod.set_password("x")
        db.session.add(hod)
        db.session.commit()
    return hod.id


def _make_policy(created_by, **overrides):
    defaults = dict(
        name="Test Policy", subject_id=None, division_id=None, is_default=False, is_active=True,
        effective_from=None, effective_until=None, present_threshold_percentage=75.0,
        late_grace_seconds=600.0, early_exit_tolerance_seconds=600.0, reentry_min_gap_seconds=300.0,
        low_confidence_flag_threshold=0.55, minimum_decision_confidence=0.45, minimum_valid_session_ratio=1.0,
        created_by=created_by,
    )
    defaults.update(overrides)
    policy = AttendancePolicy(**defaults)
    db.session.add(policy)
    db.session.commit()
    return policy


@pytest.fixture()
def hod_id(app):
    with app.app_context():
        return _uniq_hod_id()


@pytest.fixture(autouse=True)
def _no_leftover_active_default(app):
    """The `app` fixture shares one database across this whole test
    module. A global default policy created by one test and left
    active would silently satisfy resolve_policy() for every other
    test's subject/division-scoped scenario (a default always matches
    at specificity level 4), masking the exact "no policy resolves"
    cases this file is testing. Every test starts with a clean slate."""
    with app.app_context():
        for leftover in AttendancePolicy.query.filter_by(is_default=True, is_active=True).all():
            leftover.is_active = False
        db.session.commit()
    yield


def test_subject_and_division_policy_outranks_subject_only(app, hod_id):
    with app.app_context():
        subj, div = 9001, 9002
        general = _make_policy(hod_id, subject_id=subj, division_id=None, name="Subject Only")
        specific = _make_policy(hod_id, subject_id=subj, division_id=div, name="Subject+Division")

        resolved = resolve_policy(subject_id=subj, division_id=div, reference_date=datetime.date.today())
        assert resolved.id == specific.id


def test_subject_policy_outranks_default(app, hod_id):
    with app.app_context():
        subj = 9003
        default = _make_policy(hod_id, is_default=True, name="Global Default " + uuid.uuid4().hex[:6])
        subject_policy = _make_policy(hod_id, subject_id=subj, name="Subject Policy")

        try:
            resolved = resolve_policy(subject_id=subj, division_id=None, reference_date=datetime.date.today())
            assert resolved.id == subject_policy.id
        finally:
            # A global default is a session-wide fallback that would
            # otherwise leak into every later test in this module (the
            # `app` fixture shares one database across the whole test
            # session) - deactivate it immediately after use.
            default.is_active = False
            db.session.commit()


def test_inactive_policy_is_ignored(app, hod_id):
    with app.app_context():
        subj = 9004
        _make_policy(hod_id, subject_id=subj, is_active=False, name="Inactive")

        with pytest.raises(PolicyNotFoundError):
            resolve_policy(subject_id=subj, division_id=None, reference_date=datetime.date.today())


def test_future_policy_is_ignored(app, hod_id):
    with app.app_context():
        subj = 9005
        future = datetime.date.today() + datetime.timedelta(days=30)
        _make_policy(hod_id, subject_id=subj, effective_from=future, name="Future")

        with pytest.raises(PolicyNotFoundError):
            resolve_policy(subject_id=subj, division_id=None, reference_date=datetime.date.today())


def test_expired_policy_is_ignored(app, hod_id):
    with app.app_context():
        subj = 9006
        past = datetime.date.today() - datetime.timedelta(days=30)
        _make_policy(hod_id, subject_id=subj, effective_until=past, name="Expired")

        with pytest.raises(PolicyNotFoundError):
            resolve_policy(subject_id=subj, division_id=None, reference_date=datetime.date.today())


def test_ambiguous_equally_specific_policy_is_rejected(app, hod_id):
    with app.app_context():
        subj = 9007
        _make_policy(hod_id, subject_id=subj, name="First")
        _make_policy(hod_id, subject_id=subj, name="Second")

        with pytest.raises(PolicyAmbiguousError):
            resolve_policy(subject_id=subj, division_id=None, reference_date=datetime.date.today())


def test_only_one_active_default_allowed(app, hod_id):
    with app.app_context():
        from app.services.attendance_policy_service import check_no_conflicting_active_policy

        # Defensive: any active default left behind by an earlier test
        # in this shared-database session must not affect this test.
        for leftover in AttendancePolicy.query.filter_by(is_default=True, is_active=True).all():
            leftover.is_active = False
        db.session.commit()

        first_default = _make_policy(hod_id, is_default=True, name="Default One " + uuid.uuid4().hex[:6])
        try:
            with pytest.raises(DomainError):
                check_no_conflicting_active_policy(
                    subject_id=None, division_id=None, is_default=True,
                    effective_from=None, effective_until=None,
                )
        finally:
            first_default.is_active = False
            db.session.commit()


def test_invalid_thresholds_are_rejected(app, hod_id):
    with app.app_context():
        from app.services.attendance_policy_service import validate_policy_payload

        with pytest.raises(DomainError):
            validate_policy_payload({
                "name": "Bad", "present_threshold_percentage": 0.0, "late_grace_seconds": 0,
                "early_exit_tolerance_seconds": 0, "reentry_min_gap_seconds": 1, "low_confidence_flag_threshold": 0.5,
                "minimum_decision_confidence": 0.4,
            })
        with pytest.raises(DomainError):
            validate_policy_payload({
                "name": "Bad", "present_threshold_percentage": 75, "late_grace_seconds": 0,
                "early_exit_tolerance_seconds": 0, "reentry_min_gap_seconds": 0, "low_confidence_flag_threshold": 0.5,
                "minimum_decision_confidence": 0.4,
            })
        with pytest.raises(DomainError):
            validate_policy_payload({
                "name": "Bad", "present_threshold_percentage": 75, "late_grace_seconds": 0,
                "early_exit_tolerance_seconds": 0, "reentry_min_gap_seconds": 1, "low_confidence_flag_threshold": 0.4,
                "minimum_decision_confidence": 0.5,  # minimum > flag threshold - invalid ordering
            })


def test_policy_edit_does_not_change_old_snapshot(app, hod_id):
    with app.app_context():
        from app.services.policy_resolution import to_decision_policy

        subj = 9008
        policy = _make_policy(hod_id, subject_id=subj, present_threshold_percentage=75.0, name="Snapshot Test")
        old_snapshot = to_decision_policy(policy).to_snapshot()

        policy.present_threshold_percentage = 90.0
        db.session.commit()

        assert old_snapshot["present_threshold_percentage"] == 75.0  # the captured dict is immutable history

        new_snapshot = to_decision_policy(policy).to_snapshot()
        assert new_snapshot["present_threshold_percentage"] == 90.0
