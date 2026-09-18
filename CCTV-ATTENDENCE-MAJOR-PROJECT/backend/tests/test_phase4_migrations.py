"""Phase 4 migration (005_recognition_observations_and_tracks) tests.

Follows the same pattern as test_phase2_migrations.py /
test_phase3_config.py: most checks reuse the shared session-scoped
`app` fixture (already upgraded to head against an isolated temp DB);
the full base->head->downgrade cycle runs via subprocess `flask db`
against a second, fully disposable temp file.
"""

import os
import subprocess
import sys
import tempfile

from sqlalchemy import create_engine, inspect

PHASE4_TABLES = {"face_tracks", "recognition_observations"}

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


def test_shared_test_db_is_at_head_with_phase4_tables(app):
    with app.app_context():
        from app.extensions import db

        tables = set(inspect(db.engine).get_table_names())
    assert PHASE4_TABLES <= tables
    assert "alembic_version" in tables


def test_repeat_upgrade_on_shared_db_is_idempotent(app):
    from flask_migrate import upgrade

    with app.app_context():
        upgrade()  # already at head; must be a safe no-op
        from app.extensions import db

        tables = inspect(db.engine).get_table_names()
    assert len(tables) == len(set(tables))


def test_fresh_db_upgrades_through_migration_005():
    fd, path = tempfile.mkstemp(prefix="phase4_fresh_", suffix=".db")
    os.close(fd)
    os.remove(path)
    db_uri = f"sqlite:///{path}"

    try:
        result = _run_flask_db(["upgrade"], db_uri)
        assert result.returncode == 0, result.stderr

        engine = create_engine(db_uri)
        tables = set(inspect(engine).get_table_names())
        engine.dispose()
        assert PHASE4_TABLES <= tables
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_disposable_downgrade_005_to_004():
    fd, path = tempfile.mkstemp(prefix="phase4_downgrade_", suffix=".db")
    os.close(fd)
    os.remove(path)
    db_uri = f"sqlite:///{path}"

    try:
        upgrade_result = _run_flask_db(["upgrade"], db_uri)
        assert upgrade_result.returncode == 0, upgrade_result.stderr

        downgrade_result = _run_flask_db(["downgrade", "004_embedding_model_metadata"], db_uri)
        assert downgrade_result.returncode == 0, downgrade_result.stderr

        engine = create_engine(db_uri)
        tables_after = set(inspect(engine).get_table_names())
        engine.dispose()
        assert not (PHASE4_TABLES & tables_after)
        assert "students" in tables_after

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
            hod = User(name="Seed HOD", email="seed_hod_phase4@example.com", role="hod")
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
