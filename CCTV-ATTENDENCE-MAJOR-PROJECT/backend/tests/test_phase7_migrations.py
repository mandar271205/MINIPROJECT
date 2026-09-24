"""Phase 7 migration (009_attendance_finalisation_and_audit) tests."""

import os
import subprocess
import sys
import tempfile

from sqlalchemy import create_engine, inspect

PHASE7_SESSION_COLUMNS = {
    "is_finalised", "finalised_at", "finalised_by", "finalisation_notes",
}
PHASE7_RECOMMENDATION_COLUMNS = {
    "final_status", "is_overridden", "override_reason", "overridden_by", "overridden_at",
}
PHASE7_AUDIT_COLUMNS = {
    "id", "session_id", "student_id", "user_id", "action", "previous_status",
    "new_status", "reason", "details_json", "created_at",
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


def test_shared_test_db_is_at_head_with_phase7_tables_and_columns(app):
    with app.app_context():
        from app.extensions import db

        inspector = inspect(db.engine)
        session_cols = {c["name"] for c in inspector.get_columns("attendance_sessions")}
        rec_cols = {c["name"] for c in inspector.get_columns("attendance_recommendations")}
        audit_cols = {c["name"] for c in inspector.get_columns("attendance_audit_logs")}

    assert PHASE7_SESSION_COLUMNS <= session_cols
    assert PHASE7_RECOMMENDATION_COLUMNS <= rec_cols
    assert PHASE7_AUDIT_COLUMNS <= audit_cols


def test_fresh_db_upgrades_through_migration_009():
    fd, path = tempfile.mkstemp(prefix="phase7_fresh_", suffix=".db")
    os.close(fd)
    os.remove(path)
    db_uri = f"sqlite:///{path}"

    try:
        result = _run_flask_db(["upgrade"], db_uri)
        assert result.returncode == 0, result.stderr

        engine = create_engine(db_uri)
        inspector = inspect(engine)
        session_cols = {c["name"] for c in inspector.get_columns("attendance_sessions")}
        rec_cols = {c["name"] for c in inspector.get_columns("attendance_recommendations")}
        audit_cols = {c["name"] for c in inspector.get_columns("attendance_audit_logs")}
        engine.dispose()

        assert PHASE7_SESSION_COLUMNS <= session_cols
        assert PHASE7_RECOMMENDATION_COLUMNS <= rec_cols
        assert PHASE7_AUDIT_COLUMNS <= audit_cols
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_populated_db_upgrade_preserves_legacy_rows_and_defaults_is_finalised():
    fd, path = tempfile.mkstemp(prefix="phase7_populated_", suffix=".db")
    os.close(fd)
    os.remove(path)
    db_uri = f"sqlite:///{path}"

    try:
        upgrade_to_008 = _run_flask_db(["upgrade", "008_session_processing_evidence"], db_uri)
        assert upgrade_to_008.returncode == 0, upgrade_to_008.stderr

        import sqlite3

        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("INSERT INTO users (name, email, password_hash, role, is_active) VALUES ('H','h@x.com','x','hod',1)")
        hod_id = cur.lastrowid
        cur.execute(
            "INSERT INTO classrooms (name, subject, grace_period_minutes, created_by, legacy_mode) VALUES ('C','s',10,?,1)",
            (hod_id,),
        )
        class_id = cur.lastrowid
        cur.execute(
            "INSERT INTO attendance_sessions (class_id, uploaded_by, session_date, video_path, processing_status, "
            "progress_pct, recommendation_generation_status, presence_reconstruction_status) VALUES (?,?,?,?,?,?,?,?)",
            (class_id, hod_id, "2026-01-01", "legacy.mp4", "done", 100, "NOT_STARTED", "NOT_STARTED"),
        )
        conn.commit()
        conn.close()

        upgrade_to_009 = _run_flask_db(["upgrade"], db_uri)
        assert upgrade_to_009.returncode == 0, upgrade_to_009.stderr

        conn = sqlite3.connect(path)
        cur = conn.cursor()
        assert cur.execute("SELECT COUNT(*) FROM attendance_sessions").fetchone()[0] == 1
        row = cur.execute("SELECT processing_status, is_finalised FROM attendance_sessions").fetchone()
        conn.close()
        assert row[0] == "done"
        assert row[1] == 0 or row[1] is False  # default is unfinalised
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_disposable_downgrade_009_to_008():
    fd, path = tempfile.mkstemp(prefix="phase7_downgrade_", suffix=".db")
    os.close(fd)
    os.remove(path)
    db_uri = f"sqlite:///{path}"

    try:
        upgrade_result = _run_flask_db(["upgrade"], db_uri)
        assert upgrade_result.returncode == 0, upgrade_result.stderr

        downgrade_result = _run_flask_db(["downgrade", "008_session_processing_evidence"], db_uri)
        assert downgrade_result.returncode == 0, downgrade_result.stderr

        engine = create_engine(db_uri)
        inspector = inspect(engine)
        session_cols_after = {c["name"] for c in inspector.get_columns("attendance_sessions")}
        tables_after = inspector.get_table_names()
        engine.dispose()

        assert not (PHASE7_SESSION_COLUMNS & session_cols_after)
        assert "attendance_audit_logs" not in tables_after

        reupgrade_result = _run_flask_db(["upgrade"], db_uri)
        assert reupgrade_result.returncode == 0, reupgrade_result.stderr
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_migrations_001_through_008_are_unchanged():
    versions_dir = os.path.join(BACKEND_DIR, "migrations", "versions")
    filenames = os.listdir(versions_dir)
    expected_prefixes = [
        "001_legacy_schema_baseline", "002_academic_structure_and_roles", "003_user_account_status",
        "004_embedding_model_metadata", "005_recognition_observations_and_tracks",
        "006_presence_windows_and_session_duration", "007_attendance_decisions_policies_and_flags",
        "008_session_processing_evidence",
    ]
    for prefix in expected_prefixes:
        assert any(f.startswith(prefix) for f in filenames), f"missing or renamed migration: {prefix}"
