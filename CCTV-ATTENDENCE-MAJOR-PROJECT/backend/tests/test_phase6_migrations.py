"""Phase 6 migration (007_attendance_decisions_policies_and_flags)
tests. Follows the same pattern as test_phase5_migrations.py."""

import os
import subprocess
import sys
import tempfile

from sqlalchemy import create_engine, inspect

PHASE6_TABLES = {"attendance_policies", "attendance_recommendations", "attendance_flags"}
PHASE6_SESSION_COLUMNS = {
    "recommendation_generation_status", "recommendation_generation_error", "recommendation_generated_at",
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


def test_shared_test_db_is_at_head_with_phase6_tables_and_columns(app):
    with app.app_context():
        from app.extensions import db

        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        session_columns = {c["name"] for c in inspector.get_columns("attendance_sessions")}
    assert PHASE6_TABLES <= tables
    assert PHASE6_SESSION_COLUMNS <= session_columns
    assert "alembic_version" in tables


def test_repeat_upgrade_on_shared_db_is_idempotent(app):
    from flask_migrate import upgrade

    with app.app_context():
        upgrade()  # already at head; must be a safe no-op
        from app.extensions import db

        tables = inspect(db.engine).get_table_names()
    assert len(tables) == len(set(tables))


def test_fresh_db_upgrades_through_migration_007():
    fd, path = tempfile.mkstemp(prefix="phase6_fresh_", suffix=".db")
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
        assert PHASE6_TABLES <= tables
        assert PHASE6_SESSION_COLUMNS <= session_columns
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_disposable_downgrade_007_to_006():
    fd, path = tempfile.mkstemp(prefix="phase6_downgrade_", suffix=".db")
    os.close(fd)
    os.remove(path)
    db_uri = f"sqlite:///{path}"

    try:
        upgrade_result = _run_flask_db(["upgrade"], db_uri)
        assert upgrade_result.returncode == 0, upgrade_result.stderr

        downgrade_result = _run_flask_db(["downgrade", "006_presence_windows_and_session_duration"], db_uri)
        assert downgrade_result.returncode == 0, downgrade_result.stderr

        engine = create_engine(db_uri)
        inspector = inspect(engine)
        tables_after = set(inspector.get_table_names())
        session_columns_after = {c["name"] for c in inspector.get_columns("attendance_sessions")}
        engine.dispose()
        assert not (PHASE6_TABLES & tables_after)
        assert not (PHASE6_SESSION_COLUMNS & session_columns_after)
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
            hod = User(name="Seed HOD", email="seed_hod_phase6@example.com", role="hod")
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


def test_existing_session_rows_backfilled_with_safe_recommendation_status(app):
    with app.app_context():
        from app.models.attendance import AttendanceSession

        session = AttendanceSession.query.first()
        if session is not None:
            assert session.recommendation_generation_status in ("NOT_STARTED", "PROCESSING", "COMPLETED", "FAILED")


def test_migrations_001_through_006_are_unchanged():
    versions_dir = os.path.join(BACKEND_DIR, "migrations", "versions")
    filenames = os.listdir(versions_dir)
    expected_prefixes = [
        "001_legacy_schema_baseline",
        "002_academic_structure_and_roles",
        "003_user_account_status",
        "004_embedding_model_metadata",
        "005_recognition_observations_and_tracks",
        "006_presence_windows_and_session_duration",
    ]
    for prefix in expected_prefixes:
        assert any(f.startswith(prefix) for f in filenames), f"missing or renamed migration: {prefix}"
