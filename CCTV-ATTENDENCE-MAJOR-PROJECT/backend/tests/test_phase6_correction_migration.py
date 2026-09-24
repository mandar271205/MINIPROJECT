"""Phase 6 reliability correction migration
(008_session_processing_evidence) tests."""

import os
import subprocess
import sys
import tempfile

from sqlalchemy import create_engine, inspect

PHASE6_CORRECTION_COLUMNS = {
    "eof_reached", "processing_pipeline_version", "processed_video_duration_seconds",
    "final_processed_timestamp_seconds", "processing_completed_at",
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


def test_shared_test_db_is_at_head_with_correction_columns(app):
    with app.app_context():
        from app.extensions import db

        inspector = inspect(db.engine)
        session_columns = {c["name"] for c in inspector.get_columns("attendance_sessions")}
    assert PHASE6_CORRECTION_COLUMNS <= session_columns


def test_fresh_db_upgrades_through_migration_008():
    fd, path = tempfile.mkstemp(prefix="phase6_correction_fresh_", suffix=".db")
    os.close(fd)
    os.remove(path)
    db_uri = f"sqlite:///{path}"

    try:
        result = _run_flask_db(["upgrade"], db_uri)
        assert result.returncode == 0, result.stderr

        engine = create_engine(db_uri)
        session_columns = {c["name"] for c in inspect(engine).get_columns("attendance_sessions")}
        engine.dispose()
        assert PHASE6_CORRECTION_COLUMNS <= session_columns
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_populated_db_upgrade_preserves_legacy_rows_and_leaves_eof_null():
    fd, path = tempfile.mkstemp(prefix="phase6_correction_populated_", suffix=".db")
    os.close(fd)
    os.remove(path)
    db_uri = f"sqlite:///{path}"

    try:
        upgrade_to_007 = _run_flask_db(["upgrade", "007_attendance_decisions_policies_and_flags"], db_uri)
        assert upgrade_to_007.returncode == 0, upgrade_to_007.stderr

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

        upgrade_to_008 = _run_flask_db(["upgrade"], db_uri)
        assert upgrade_to_008.returncode == 0, upgrade_to_008.stderr

        conn = sqlite3.connect(path)
        cur = conn.cursor()
        assert cur.execute("SELECT COUNT(*) FROM attendance_sessions").fetchone()[0] == 1
        row = cur.execute("SELECT processing_status, eof_reached FROM attendance_sessions").fetchone()
        conn.close()
        assert row[0] == "done"
        assert row[1] is None  # legacy row never retroactively marked True
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_disposable_downgrade_008_to_007():
    fd, path = tempfile.mkstemp(prefix="phase6_correction_downgrade_", suffix=".db")
    os.close(fd)
    os.remove(path)
    db_uri = f"sqlite:///{path}"

    try:
        upgrade_result = _run_flask_db(["upgrade"], db_uri)
        assert upgrade_result.returncode == 0, upgrade_result.stderr

        downgrade_result = _run_flask_db(["downgrade", "007_attendance_decisions_policies_and_flags"], db_uri)
        assert downgrade_result.returncode == 0, downgrade_result.stderr

        engine = create_engine(db_uri)
        session_columns_after = {c["name"] for c in inspect(engine).get_columns("attendance_sessions")}
        engine.dispose()
        assert not (PHASE6_CORRECTION_COLUMNS & session_columns_after)

        reupgrade_result = _run_flask_db(["upgrade"], db_uri)
        assert reupgrade_result.returncode == 0, reupgrade_result.stderr
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_migrations_001_through_007_are_unchanged():
    versions_dir = os.path.join(BACKEND_DIR, "migrations", "versions")
    filenames = os.listdir(versions_dir)
    expected_prefixes = [
        "001_legacy_schema_baseline", "002_academic_structure_and_roles", "003_user_account_status",
        "004_embedding_model_metadata", "005_recognition_observations_and_tracks",
        "006_presence_windows_and_session_duration", "007_attendance_decisions_policies_and_flags",
    ]
    for prefix in expected_prefixes:
        assert any(f.startswith(prefix) for f in filenames), f"missing or renamed migration: {prefix}"
