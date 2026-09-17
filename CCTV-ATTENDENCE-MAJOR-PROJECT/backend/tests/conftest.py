import os
import tempfile
import uuid

import pytest

# Point the app at a disposable temporary SQLite database before any app
# module is imported, so Config picks up this URI instead of the real
# DATABASE_URL from .env. Phase 1 tests must never touch the active DB.
_TEST_DB_FD, _TEST_DB_PATH = tempfile.mkstemp(prefix="attendiq_phase1_test_", suffix=".db")
os.close(_TEST_DB_FD)
os.remove(_TEST_DB_PATH)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"
os.environ["DEFAULT_HOD_EMAIL"] = ""
os.environ["DEFAULT_HOD_PASSWORD"] = ""

from app import create_app  # noqa: E402
from flask_migrate import upgrade  # noqa: E402


@pytest.fixture(scope="session")
def app():
    flask_app = create_app()
    with flask_app.app_context():
        upgrade()
    yield flask_app
    with flask_app.app_context():
        from app.extensions import db

        db.engine.dispose()
    if os.path.exists(_TEST_DB_PATH):
        os.remove(_TEST_DB_PATH)


@pytest.fixture()
def client(app):
    return app.test_client()


def _make_user_and_headers(app, role: str):
    from flask_jwt_extended import create_access_token

    from app.extensions import db
    from app.models.user import User

    with app.app_context():
        email = f"{role}_{uuid.uuid4().hex[:10]}@example.com"
        user = User(name=f"Test {role.capitalize()}", email=email, role=role)
        user.set_password("TestPass!234")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
        token = create_access_token(identity=str(user_id), additional_claims={"role": role})
    return user_id, {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def hod_identity(app):
    return _make_user_and_headers(app, "hod")


@pytest.fixture()
def hod_headers(hod_identity):
    return hod_identity[1]


@pytest.fixture()
def faculty_identity(app):
    return _make_user_and_headers(app, "faculty")


@pytest.fixture()
def faculty_headers(faculty_identity):
    return faculty_identity[1]


@pytest.fixture()
def second_faculty_identity(app):
    return _make_user_and_headers(app, "faculty")


@pytest.fixture()
def student_identity(app):
    return _make_user_and_headers(app, "student")


@pytest.fixture()
def student_headers(student_identity):
    return student_identity[1]
