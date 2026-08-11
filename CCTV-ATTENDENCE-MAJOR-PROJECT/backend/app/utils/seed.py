from flask import current_app

from ..extensions import db
from ..models.user import User


def ensure_default_hod() -> None:
    email = current_app.config.get("DEFAULT_HOD_EMAIL")
    password = current_app.config.get("DEFAULT_HOD_PASSWORD")
    name = current_app.config.get("DEFAULT_HOD_NAME")

    if not email or not password:
        return

    existing = User.query.filter_by(email=email.lower()).first()
    if existing:
        # Sync password & role with .env on every startup so that
        # changing DEFAULT_HOD_PASSWORD actually takes effect.
        if not existing.check_password(password):
            existing.set_password(password)
        if existing.role != "hod":
            existing.role = "hod"
        db.session.commit()
        return

    user = User(name=name, email=email.lower(), role="hod")
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
