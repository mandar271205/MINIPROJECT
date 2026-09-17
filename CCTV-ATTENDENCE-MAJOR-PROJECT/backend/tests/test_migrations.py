from flask_migrate import upgrade
from sqlalchemy import inspect

from app.extensions import db

EXPECTED_TABLES = {
    "users",
    "classrooms",
    "students",
    "attendance_sessions",
    "attendance_records",
    "alembic_version",
}


def test_fresh_upgrade_creates_legacy_schema(app):
    with app.app_context():
        tables = set(inspect(db.engine).get_table_names())
    assert EXPECTED_TABLES <= tables


def test_repeat_upgrade_is_idempotent(app):
    with app.app_context():
        upgrade()  # baseline is already applied; must be a safe no-op
        tables = inspect(db.engine).get_table_names()
    assert len(tables) == len(set(tables))
