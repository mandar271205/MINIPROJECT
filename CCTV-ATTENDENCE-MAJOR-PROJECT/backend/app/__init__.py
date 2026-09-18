from pathlib import Path

from flask import Flask, current_app, jsonify
from flask_cors import CORS
from sqlalchemy import inspect
from werkzeug.exceptions import HTTPException

from .config import Config
from .extensions import bcrypt, db, jwt, migrate
from .routes import academic_bp, admin_bp, attendance_bp, auth_bp, classes_bp, faculty_bp, reports_bp, student_bp
from .utils.config_validation import validate_all as validate_recognition_and_tracking_config
from .utils.errors import DomainError
from .utils.responses import error as error_response
from .utils.seed import ensure_default_hod


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config.from_object(Config)

    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError("DATABASE_URL is not set. Add it to your .env file.")

    # Fail loudly at startup on invalid recognition/tracking/voting
    # config instead of letting a bad value surface later as a
    # confusing job failure, and never silently substitute a different
    # provider or an unsafe default.
    validate_recognition_and_tracking_config(app.config)

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
    app.register_blueprint(academic_bp, url_prefix="/api/academic")
    app.register_blueprint(faculty_bp, url_prefix="/api/faculty")
    app.register_blueprint(student_bp, url_prefix="/api/student")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")

    for key in ("STORAGE_DIR", "VIDEO_DIR", "ENROLL_DIR", "REPORT_DIR", "TEMP_DIR"):
        Path(app.config[key]).mkdir(parents=True, exist_ok=True)

    @app.get("/api/health")
    def health_check():
        return jsonify({"status": "ok"})

    @app.cli.command("transition-embeddings")
    def transition_embeddings_command():
        """Regenerate existing students' embeddings with the active
        InsightFaceArcFaceProvider where a valid reference image
        allows it; safely mark the rest for re-enrolment. Never run
        automatically - an operator invokes this explicitly:

            flask transition-embeddings
        """
        from .services.embedding_transition import transition_all_students

        report = transition_all_students()
        regenerated = sum(1 for r in report if r["result"] == "regenerated")
        skipped = sum(1 for r in report if r["result"] == "skipped")
        failed = sum(1 for r in report if r["result"] == "failed")
        print(f"Embedding transition complete: {len(report)} students processed")
        print(f"  regenerated={regenerated} skipped(reenroll)={skipped} failed={failed}")
        for entry in report:
            print(
                f"  student_id={entry['student_id']} result={entry['result']} "
                f"previous_model_id={entry['previous_model_id']} new_model_id={entry['new_model_id']} "
                f"reenrollment_required={entry['reenrollment_required']} "
                f"reason={entry['failure_reason']}"
            )

    @app.errorhandler(DomainError)
    def handle_domain_error(exc: DomainError):
        return error_response(exc.code, exc.message, exc.status)

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc: Exception):
        # HTTPExceptions (404 from unmatched routes, etc.) already carry
        # their own safe status/message - let Flask handle them normally.
        if isinstance(exc, HTTPException):
            return exc
        current_app.logger.exception("Unhandled exception")
        return error_response("INTERNAL_ERROR", "An unexpected error occurred", 500)

    with app.app_context():
        inspector = inspect(db.engine)
        # Both the table and the specific columns ensure_default_hod()
        # reads/writes must already exist. This matters during `flask db
        # migrate` autogenerate runs against a database sitting between
        # two revisions (e.g. mid-way through adding users.is_active) -
        # the app factory still gets called to load the app, and seeding
        # must not crash that with a "no such column" error.
        if inspector.has_table("users"):
            existing_columns = {c["name"] for c in inspector.get_columns("users")}
            required_columns = {c.name for c in db.metadata.tables["users"].columns}
            if required_columns <= existing_columns:
                ensure_default_hod()

    return app
