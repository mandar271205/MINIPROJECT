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

    # Phase 2 transition fields. Nullable and unused by legacy routes so
    # existing classrooms keep operating exactly as before. `legacy_mode`
    # defaults to True and is only set False once a classroom has been
    # deliberately linked to the new academic hierarchy (not done
    # automatically for any pre-existing row — see the Phase 2 mapping
    # report).
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=True)
    division_id = db.Column(db.Integer, db.ForeignKey("divisions.id"), nullable=True)
    legacy_mode = db.Column(db.Boolean, nullable=False, default=True)

    creator = db.relationship("User", backref=db.backref("classes", lazy=True))
    academic_subject = db.relationship("Subject")
    academic_division = db.relationship("Division")
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
