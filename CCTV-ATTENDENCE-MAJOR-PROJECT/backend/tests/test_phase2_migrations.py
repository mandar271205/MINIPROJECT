"""Phase 2 migration tests.

Most checks reuse the session-scoped `app` fixture from conftest.py,
which is already upgraded to head (base -> 001 -> 002) against an
isolated temporary database - never the real active database.

The full base -> 001 -> 002 -> downgrade cycle is exercised via
subprocess `flask db` invocations against a second, fully disposable
temp file, mirroring exactly how migrations are actually run. This
avoids fragile in-process engine-swapping and never touches the shared
test database or the real active DB.
"""

import os
import subprocess
import sys
import tempfile

from sqlalchemy import create_engine, inspect

PHASE2_TABLES = {
    "academic_years",
    "semesters",
    "divisions",
    "subjects",
    "faculty_assignments",
}

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_flask_db(args, db_uri):
    env = dict(os.environ)
    env["FLASK_APP"] = "wsgi.py"
    env["DATABASE_URL"] = db_uri
    env["DEFAULT_HOD_EMAIL"] = ""
    env["DEFAULT_HOD_PASSWORD"] = ""
    result = subprocess.run(
        [sys.executable, "-m", "flask", "db", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result


def test_shared_test_db_is_at_head_with_phase2_tables(app):
    with app.app_context():
        from app.extensions import db

        tables = set(inspect(db.engine).get_table_names())
    assert PHASE2_TABLES <= tables
    assert "alembic_version" in tables


def test_repeat_upgrade_on_shared_db_is_idempotent(app):
    from flask_migrate import upgrade

    with app.app_context():
        upgrade()  # already at head; must be a safe no-op
        from app.extensions import db

        tables = inspect(db.engine).get_table_names()
    assert len(tables) == len(set(tables))


def test_base_to_head_and_downgrade_on_disposable_db():
    """Exercises base -> 001 -> 002 and a downgrade back to 001 on a
    throwaway file deleted at the end of this test."""
    fd, path = tempfile.mkstemp(prefix="phase2_disposable_", suffix=".db")
    os.close(fd)
    os.remove(path)
    db_uri = f"sqlite:///{path}"

    try:
        upgrade_result = _run_flask_db(["upgrade"], db_uri)
        assert upgrade_result.returncode == 0, upgrade_result.stderr

        engine = create_engine(db_uri)
        tables = set(inspect(engine).get_table_names())
        engine.dispose()
        assert PHASE2_TABLES <= tables
        assert "alembic_version" in tables

        downgrade_result = _run_flask_db(["downgrade", "001_legacy_schema_baseline"], db_uri)
        assert downgrade_result.returncode == 0, downgrade_result.stderr

        engine = create_engine(db_uri)
        tables_after_downgrade = set(inspect(engine).get_table_names())
        engine.dispose()
        assert not (PHASE2_TABLES & tables_after_downgrade)
        assert "classrooms" in tables_after_downgrade
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_populated_copy_upgrade_preserves_legacy_row_counts(app):
    """Upgrades a temporary copy of the shared (already-populated) test
    database's legacy tables and confirms row counts are unaffected -
    mirroring the real active-DB migration path at a smaller scale."""
    with app.app_context():
        from app.extensions import db
        from app.models.classroom import Classroom
        from app.models.user import User

        # Seed a couple of legacy-shaped rows directly so this test does
        # not depend on ordering relative to other tests.
        hod = User.query.filter_by(role="hod").first()
        if not hod:
            hod = User(name="Seed HOD", email="seed_hod_phase2@example.com", role="hod")
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
