from datetime import datetime, timezone

from ..extensions import db


class Classroom(db.Model):
    __tablename__ = "classrooms"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(120), nullable=False)
    grace_period_minutes = db.Column(db.Integer, nullable=False, default=10)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    creator = db.relationship("User", backref=db.backref("classes", lazy=True))
    students = db.relationship(
        "Student",
        back_populates="classroom",
        cascade="all, delete-orphan",
    )
    sessions = db.relationship(
        "AttendanceSession",
        back_populates="classroom",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "subject": self.subject,
            "grace_period_minutes": self.grace_period_minutes,
        }
