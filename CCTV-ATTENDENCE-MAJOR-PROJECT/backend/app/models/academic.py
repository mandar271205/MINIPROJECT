from datetime import datetime, timezone

from ..extensions import db

MIN_SEMESTER_NUMBER = 1
MAX_SEMESTER_NUMBER = 8


def _utcnow():
    return datetime.now(timezone.utc)


class AcademicYear(db.Model):
    __tablename__ = "academic_years"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    is_current = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    semesters = db.relationship(
        "Semester", back_populates="academic_year", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.CheckConstraint("end_date > start_date", name="ck_academic_year_dates"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "is_current": self.is_current,
            "is_active": self.is_active,
        }


class Semester(db.Model):
    __tablename__ = "semesters"

    id = db.Column(db.Integer, primary_key=True)
    academic_year_id = db.Column(db.Integer, db.ForeignKey("academic_years.id"), nullable=False)
    number = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(80), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    academic_year = db.relationship("AcademicYear", back_populates="semesters")
    divisions = db.relationship("Division", back_populates="semester", cascade="all, delete-orphan")
    subjects = db.relationship("Subject", back_populates="semester", cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint("academic_year_id", "number", name="uq_semester_year_number"),
        db.CheckConstraint(
            f"number >= {MIN_SEMESTER_NUMBER} AND number <= {MAX_SEMESTER_NUMBER}",
            name="ck_semester_number_range",
        ),
        db.Index("ix_semesters_academic_year_id", "academic_year_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "academic_year_id": self.academic_year_id,
            "number": self.number,
            "name": self.name,
            "is_active": self.is_active,
        }


class Division(db.Model):
    __tablename__ = "divisions"

    id = db.Column(db.Integer, primary_key=True)
    semester_id = db.Column(db.Integer, db.ForeignKey("semesters.id"), nullable=False)
    name = db.Column(db.String(20), nullable=False)
    program = db.Column(db.String(80), nullable=False)
    batch_year = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    semester = db.relationship("Semester", back_populates="divisions")
    students = db.relationship("Student", back_populates="division")
    faculty_assignments = db.relationship(
        "FacultyAssignment", back_populates="division", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.UniqueConstraint("semester_id", "program", "name", name="uq_division_semester_program_name"),
        db.Index("ix_divisions_semester_id", "semester_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "semester_id": self.semester_id,
            "name": self.name,
            "program": self.program,
            "batch_year": self.batch_year,
            "is_active": self.is_active,
        }


class Subject(db.Model):
    __tablename__ = "subjects"

    id = db.Column(db.Integer, primary_key=True)
    semester_id = db.Column(db.Integer, db.ForeignKey("semesters.id"), nullable=False)
    code = db.Column(db.String(30), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    credits = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    semester = db.relationship("Semester", back_populates="subjects")
    faculty_assignments = db.relationship(
        "FacultyAssignment", back_populates="subject", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.UniqueConstraint("semester_id", "code", name="uq_subject_semester_code"),
        db.Index("ix_subjects_semester_id", "semester_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "semester_id": self.semester_id,
            "code": self.code,
            "name": self.name,
            "credits": self.credits,
            "is_active": self.is_active,
        }


class FacultyAssignment(db.Model):
    __tablename__ = "faculty_assignments"

    id = db.Column(db.Integer, primary_key=True)
    faculty_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False)
    division_id = db.Column(db.Integer, db.ForeignKey("divisions.id"), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    faculty = db.relationship("User")
    subject = db.relationship("Subject", back_populates="faculty_assignments")
    division = db.relationship("Division", back_populates="faculty_assignments")

    __table_args__ = (
        db.UniqueConstraint(
            "faculty_id", "subject_id", "division_id", name="uq_faculty_assignment"
        ),
        db.Index("ix_faculty_assignments_faculty_id", "faculty_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "faculty_id": self.faculty_id,
            "subject_id": self.subject_id,
            "division_id": self.division_id,
            "is_active": self.is_active,
        }
