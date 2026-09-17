from datetime import datetime, timezone

from ..extensions import db


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey("classrooms.id"), nullable=False)
    roll_number = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    face_embedding = db.Column(db.JSON, nullable=False)
    face_model = db.Column(db.String(50), nullable=False)
    reference_image_path = db.Column(db.String(500), nullable=True)
    enrolled_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Phase 2 additions. All nullable so pre-existing legacy student rows
    # (enrolled via ZIP with no user account or academic hierarchy) keep
    # working unchanged.
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=True)
    division_id = db.Column(db.Integer, db.ForeignKey("divisions.id"), nullable=True)
    prn_number = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    classroom = db.relationship("Classroom", back_populates="students")
    division = db.relationship("Division", back_populates="students")
    user = db.relationship("User", backref=db.backref("student_profile", uselist=False))

    __table_args__ = (db.UniqueConstraint("class_id", "roll_number", name="uq_student_roll"),)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "roll_number": self.roll_number,
            "name": self.name,
            "enrolled_at": self.enrolled_at.isoformat(),
        }

    def to_profile_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "roll_number": self.roll_number,
            "prn_number": self.prn_number,
            "email": self.email,
            "class_id": self.class_id,
            "division_id": self.division_id,
            "is_active": self.is_active,
        }
