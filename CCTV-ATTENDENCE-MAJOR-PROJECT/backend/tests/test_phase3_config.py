"""Phase 3 - invalid recognition configuration must fail loudly at
app startup, never silently fall back to a different provider or a
clamped value.
"""

import os
import tempfile

import pytest


def _fresh_app_module():
    """Reloads only app.config and app.__init__ (not the model/route
    submodules, which must stay singletons to avoid re-declaring
    SQLAlchemy tables) so each test's monkeypatched env vars are picked
    up by a fresh Config class evaluation."""
    import importlib
    import sys

    for name in ("app.config", "app"):
        if name in sys.modules:
            del sys.modules[name]
    import app as app_module

    importlib.reload(app_module)
    return app_module


@pytest.fixture()
def isolated_db_env(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    monkeypatch.setenv("DEFAULT_HOD_EMAIL", "")
    monkeypatch.setenv("DEFAULT_HOD_PASSWORD", "")
    yield path
    if os.path.exists(path):
        os.remove(path)


def test_invalid_provider_name_rejected_at_startup(isolated_db_env, monkeypatch):
    monkeypatch.setenv("FACE_RECOGNITION_PROVIDER", "some_other_unverified_model")
    app_module = _fresh_app_module()
    with pytest.raises(RuntimeError, match="FACE_RECOGNITION_PROVIDER"):
        app_module.create_app()


def test_invalid_match_threshold_rejected_at_startup(isolated_db_env, monkeypatch):
    monkeypatch.setenv("FACE_MATCH_THRESHOLD", "1.5")
    app_module = _fresh_app_module()
    with pytest.raises(RuntimeError, match="FACE_MATCH_THRESHOLD"):
        app_module.create_app()


def test_invalid_frame_interval_rejected_at_startup(isolated_db_env, monkeypatch):
    monkeypatch.setenv("FRAME_SAMPLE_INTERVAL_SECONDS", "0")
    app_module = _fresh_app_module()
    with pytest.raises(RuntimeError, match="FRAME_SAMPLE_INTERVAL_SECONDS"):
        app_module.create_app()
