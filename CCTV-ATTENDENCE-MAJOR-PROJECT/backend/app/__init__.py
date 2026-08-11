from pathlib import Path

from flask import Flask, jsonify
from flask_cors import CORS

from .config import Config
from .extensions import bcrypt, db, jwt, migrate
from .routes import attendance_bp, auth_bp, classes_bp, reports_bp
from .utils.seed import ensure_default_hod


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config.from_object(Config)

    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError("DATABASE_URL is not set. Add it to your .env file.")

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    bcrypt.init_app(app)

    CORS(
        app,
        resources={r"/api/*": {"origins": app.config.get("CORS_ORIGINS", [])}},
        supports_credentials=True,
    )

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(classes_bp, url_prefix="/api/classes")
    app.register_blueprint(attendance_bp, url_prefix="/api/attendance")
    app.register_blueprint(reports_bp, url_prefix="/api/reports")

    for key in ("STORAGE_DIR", "VIDEO_DIR", "ENROLL_DIR", "REPORT_DIR", "TEMP_DIR"):
        Path(app.config[key]).mkdir(parents=True, exist_ok=True)

    @app.get("/api/health")
    def health_check():
        return jsonify({"status": "ok"})

    with app.app_context():
        db.create_all()
        ensure_default_hod()

    return app
