import enum
from datetime import datetime, date
from typing import List

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash


db = SQLAlchemy()


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class AppointmentStatus(enum.StrEnum):
    BOOKED = "Booked"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"


class UserRole(enum.StrEnum):
    ADMIN = "admin"
    DOCTOR = "doctor"
    PATIENT = "patient"


class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(40))
    role = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True)

    doctor_profile = db.relationship("Doctor", backref="user", uselist=False)
    patient_profile = db.relationship("Patient", backref="user", uselist=False)

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role})>"


class Department(TimestampMixin, db.Model):
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    description = db.Column(db.Text)

    doctors = db.relationship("Doctor", backref="department", lazy=True)

    def __repr__(self) -> str:
        return f"<Department {self.name}>"


class Doctor(TimestampMixin, db.Model):
    __tablename__ = "doctors"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=False)
    specialization = db.Column(db.String(120), nullable=False)
    room = db.Column(db.String(50))
    availability_summary = db.Column(db.String(255))
    bio = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)

    availabilities = db.relationship(
        "DoctorAvailability",
        backref="doctor",
        lazy=True,
        cascade="all, delete-orphan",
    )
    appointments = db.relationship("Appointment", backref="doctor", lazy=True)

    def __repr__(self) -> str:
        return f"<Doctor {self.user.full_name} - {self.specialization}>"


class Patient(TimestampMixin, db.Model):
    __tablename__ = "patients"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    date_of_birth = db.Column(db.Date)
    gender = db.Column(db.String(10))
    blood_group = db.Column(db.String(5))
    address = db.Column(db.Text)
    emergency_contact = db.Column(db.String(120))
    insurance_provider = db.Column(db.String(120))

    appointments = db.relationship("Appointment", backref="patient", lazy=True)

    def __repr__(self) -> str:
        return f"<Patient {self.user.full_name}>"


class DoctorAvailability(TimestampMixin, db.Model):
    __tablename__ = "doctor_availability"

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False)
    available_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "doctor_id", "available_date", name="uniq_doctor_date_availability"
        ),
    )

    def __repr__(self) -> str:
        return f"<Availability doctor={self.doctor_id} {self.available_date}>"


class Appointment(TimestampMixin, db.Model):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=False)
    appointment_date = db.Column(db.Date, nullable=False)
    appointment_time = db.Column(db.Time, nullable=False)
    status = db.Column(
        db.Enum(AppointmentStatus), default=AppointmentStatus.BOOKED, nullable=False
    )
    reason = db.Column(db.String(255))

    department = db.relationship("Department")
    treatment_note = db.relationship(
        "TreatmentNote", backref="appointment", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.UniqueConstraint(
            "doctor_id",
            "appointment_date",
            "appointment_time",
            name="uniq_doctor_slot",
        ),
    )

    def __repr__(self) -> str:
        return f"<Appointment {self.id} {self.appointment_date} {self.status}>"


class TreatmentNote(TimestampMixin, db.Model):
    __tablename__ = "treatment_notes"

    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(
        db.Integer, db.ForeignKey("appointments.id"), nullable=False, unique=True
    )
    diagnosis = db.Column(db.Text)
    prescription = db.Column(db.Text)
    notes = db.Column(db.Text)

    def __repr__(self) -> str:
        return f"<TreatmentNote appointment={self.appointment_id}>"


def create_default_departments() -> List[Department]:
    return [
        Department(
            name="Cardiology", description="Heart and vascular care including diagnostics."
        ),
        Department(name="Orthopedics", description="Bone, joint and muscle treatments."),
        Department(name="Pediatrics", description="Child and adolescent wellness."),
        Department(name="Dermatology", description="Skin conditions and cosmetic care."),
        Department(name="General Medicine", description="Primary and preventive care."),
    ]


def init_db(app) -> None:
    """Create tables and seed default records if they don't exist."""
    with app.app_context():
        db.create_all()

        if Department.query.count() == 0:
            db.session.add_all(create_default_departments())
            db.session.commit()

        if not User.query.filter_by(role=UserRole.ADMIN).first():
            admin_user = User(
                full_name="Hospital Admin",
                email="admin@hms.local",
                phone="0000000000",
                role=UserRole.ADMIN,
                password_hash=generate_password_hash("Admin@123"),
            )
            db.session.add(admin_user)
            db.session.commit()

