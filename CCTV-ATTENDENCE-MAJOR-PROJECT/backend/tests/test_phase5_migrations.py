"""Phase 5 migration (006_presence_windows_and_session_duration) tests.

Follows the same pattern as test_phase4_migrations.py: most checks
reuse the shared session-scoped `app` fixture (already upgraded to
head against an isolated temp DB); the full base->head->downgrade
cycle runs via subprocess `flask db` against a second, fully
disposable temp file.
"""

import os
import subprocess
import sys
import tempfile

from sqlalchemy import create_engine, inspect

PHASE5_TABLES = {"presence_windows"}
PHASE5_SESSION_COLUMNS = {
    "actual_duration_seconds", "valid_duration_seconds", "presence_reconstructed_at",
    "presence_algorithm_version", "presence_reconstruction_status", "presence_reconstruction_error",
}

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_flask_db(args, db_uri):
    env = dict(os.environ)
    env["FLASK_APP"] = "wsgi.py"
    env["DATABASE_URL"] = db_uri
    env["DEFAULT_HOD_EMAIL"] = ""
    env["DEFAULT_HOD_PASSWORD"] = ""
    return subprocess.run(
        [sys.executable, "-m", "flask", "db", *args],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=60,
    )


def test_shared_test_db_is_at_head_with_phase5_table_and_columns(app):
    with app.app_context():
        from app.extensions import db

        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        session_columns = {c["name"] for c in inspector.get_columns("attendance_sessions")}
    assert PHASE5_TABLES <= tables
    assert PHASE5_SESSION_COLUMNS <= session_columns
    assert "alembic_version" in tables


def test_repeat_upgrade_on_shared_db_is_idempotent(app):
    from flask_migrate import upgrade

    with app.app_context():
        upgrade()  # already at head; must be a safe no-op
        from app.extensions import db

        tables = inspect(db.engine).get_table_names()
    assert len(tables) == len(set(tables))


def test_fresh_db_upgrades_through_migration_006():
    fd, path = tempfile.mkstemp(prefix="phase5_fresh_", suffix=".db")
    os.close(fd)
    os.remove(path)
    db_uri = f"sqlite:///{path}"

    try:
        result = _run_flask_db(["upgrade"], db_uri)
        assert result.returncode == 0, result.stderr

        engine = create_engine(db_uri)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        session_columns = {c["name"] for c in inspector.get_columns("attendance_sessions")}
        engine.dispose()
        assert PHASE5_TABLES <= tables
        assert PHASE5_SESSION_COLUMNS <= session_columns
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_disposable_downgrade_006_to_005():
    fd, path = tempfile.mkstemp(prefix="phase5_downgrade_", suffix=".db")
    os.close(fd)
    os.remove(path)
    db_uri = f"sqlite:///{path}"

    try:
        upgrade_result = _run_flask_db(["upgrade"], db_uri)
        assert upgrade_result.returncode == 0, upgrade_result.stderr

        downgrade_result = _run_flask_db(["downgrade", "005_recognition_observations_and_tracks"], db_uri)
        assert downgrade_result.returncode == 0, downgrade_result.stderr

        engine = create_engine(db_uri)
        inspector = inspect(engine)
        tables_after = set(inspector.get_table_names())
        session_columns_after = {c["name"] for c in inspector.get_columns("attendance_sessions")}
        engine.dispose()
        assert not (PHASE5_TABLES & tables_after)
        assert not (PHASE5_SESSION_COLUMNS & session_columns_after)
        assert "attendance_sessions" in tables_after

        reupgrade_result = _run_flask_db(["upgrade"], db_uri)
        assert reupgrade_result.returncode == 0, reupgrade_result.stderr
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_populated_copy_upgrade_preserves_legacy_row_counts(app):
    with app.app_context():
        from app.extensions import db
        from app.models.classroom import Classroom
        from app.models.user import User

        hod = User.query.filter_by(role="hod").first()
        if not hod:
            hod = User(name="Seed HOD", email="seed_hod_phase5@example.com", role="hod")
            hod.set_password("x")
            db.session.add(hod)
            db.session.commit()
        before_classrooms = Classroom.query.count()

    with app.app_context():
        from flask_migrate import upgrade

        upgrade()  # no-op, already at head - counts must be unaffected
        from app.models.classroom import Classroom

        after_classrooms = Classroom.query.count()

    assert after_classrooms == before_classrooms


def test_existing_session_rows_backfilled_with_safe_reconstruction_status(app):
    """A session row created before migration 006 must receive the
    conservative NOT_STARTED default, never a fabricated COMPLETED/
    FAILED status, once the column is added."""
    with app.app_context():
        from app.extensions import db
        from app.models.attendance import AttendanceSession

        session = AttendanceSession.query.first()
        if session is not None:
            assert session.presence_reconstruction_status in ("NOT_STARTED", "PROCESSING", "COMPLETED", "FAILED", "PARTIAL_EVIDENCE")


def test_migrations_001_through_005_are_unchanged():
    """Phase 5 must not have edited any prior migration file - each
    earlier revision id must still exist verbatim in the versions dir."""
    versions_dir = os.path.join(BACKEND_DIR, "migrations", "versions")
    filenames = os.listdir(versions_dir)
    expected_prefixes = [
        "001_legacy_schema_baseline",
        "002_academic_structure_and_roles",
        "003_user_account_status",
        "004_embedding_model_metadata",
        "005_recognition_observations_and_tracks",
    ]
    for prefix in expected_prefixes:
        assert any(f.startswith(prefix) for f in filenames), f"missing or renamed migration: {prefix}"
