import pytest

from app.extensions import db
from app.models.user import User

TEST_EMAIL = "pytest_phase1_user@example.com"
TEST_PASSWORD = "Phase1TestPass!234"


def test_health_check(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_protected_route_rejects_missing_token(client):
    resp = client.get("/api/classes/")
    assert resp.status_code == 401


@pytest.fixture()
def registered_user(app, client):
    client.post(
        "/api/auth/register",
        json={"name": "Phase1 Test User", "email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    yield {"email": TEST_EMAIL, "password": TEST_PASSWORD}
    with app.app_context():
        User.query.filter_by(email=TEST_EMAIL).delete()
        db.session.commit()


def test_valid_login_succeeds(client, registered_user):
    resp = client.post("/api/auth/login", json=registered_user)
    assert resp.status_code == 200
    assert "token" in resp.get_json()


def test_invalid_password_rejected(client, registered_user):
    resp = client.post(
        "/api/auth/login",
        json={"email": registered_user["email"], "password": "wrong-password"},
    )
    assert resp.status_code == 401
