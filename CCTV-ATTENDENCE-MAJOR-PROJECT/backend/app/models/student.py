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

    classroom = db.relationship("Classroom", back_populates="students")

    __table_args__ = (db.UniqueConstraint("class_id", "roll_number", name="uq_student_roll"),)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "roll_number": self.roll_number,
            "name": self.name,
            "enrolled_at": self.enrolled_at.isoformat(),
        }
