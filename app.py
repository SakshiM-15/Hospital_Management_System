from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import wraps
from typing import Callable, Optional

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import or_

from database import (
    Appointment,
    AppointmentStatus,
    Department,
    Doctor,
    DoctorAvailability,
    Patient,
    TreatmentNote,
    User,
    UserRole,
    db,
    init_db,
)


app = Flask(__name__)
app.config["SECRET_KEY"] = "super-secret-hms-key"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///hospital.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

with app.app_context():
    init_db(app)

@login_manager.user_loader
def load_user(user_id: str) -> Optional[User]:
    return User.query.get(int(user_id))


def role_required(*roles: UserRole) -> Callable:
    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            allowed_roles = {getattr(role, "value", role) for role in roles}
            if current_user.role not in allowed_roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


@app.context_processor
def inject_globals():
    return {
        "UserRole": UserRole,
        "AppointmentStatus": AppointmentStatus,
        "datetime": datetime,
    }


@app.route("/")
def index():
    departments = Department.query.order_by(Department.name).all()
    doctors = (
        Doctor.query.filter_by(is_active=True)
        .join(User)
        .order_by(User.full_name.asc())
        .limit(6)
        .all()
    )
    return render_template("index.html", departments=departments, doctors=doctors)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("redirect_dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.is_active and check_password_hash(user.password_hash, password):
            login_user(user)
            flash("Welcome back!", "success")
            return redirect(url_for("redirect_dashboard"))
        flash("Invalid credentials or inactive account.", "danger")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        phone = request.form.get("phone", "")

        if User.query.filter_by(email=email).first():
            flash("Email already registered.", "warning")
            return redirect(url_for("register"))

        user = User(
            full_name=full_name,
            email=email,
            phone=phone,
            role=UserRole.PATIENT,
            password_hash=generate_password_hash(password),
        )
        patient = Patient(user=user)
        db.session.add_all([user, patient])
        db.session.commit()
        flash("Registration successful. Please login.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/logout", methods=["POST", "GET"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def redirect_dashboard():
    if current_user.role == UserRole.ADMIN:
        return redirect(url_for("admin_dashboard"))
    if current_user.role == UserRole.DOCTOR:
        return redirect(url_for("doctor_dashboard"))
    return redirect(url_for("patient_dashboard"))


@app.route("/admin/dashboard")
@login_required
@role_required(UserRole.ADMIN)
def admin_dashboard():
    search_doctor = request.args.get("doctor_query", "").strip()
    search_patient = request.args.get("patient_query", "").strip()

    doctor_query = Doctor.query.join(User)
    if search_doctor:
        like = f"%{search_doctor}%"
        doctor_query = doctor_query.filter(
            or_(User.full_name.ilike(like), Doctor.specialization.ilike(like))
        )
    doctors = doctor_query.all()

    patient_query = Patient.query.join(User)
    if search_patient:
        like = f"%{search_patient}%"
        filters = [User.full_name.ilike(like), User.phone.ilike(like)]
        if search_patient.isdigit():
            filters.append(Patient.id == int(search_patient))
        patient_query = patient_query.filter(or_(*filters))
    patients = patient_query.all()

    total_doctors = Doctor.query.count()
    total_patients = Patient.query.count()
    total_appointments = Appointment.query.count()

    appointments = Appointment.query.order_by(
        Appointment.appointment_date.desc(), Appointment.appointment_time.desc()
    ).all()

    return render_template(
        "admin_dashboard.html",
        total_doctors=total_doctors,
        total_patients=total_patients,
        total_appointments=total_appointments,
        doctors=doctors,
        patients=patients,
        appointments=appointments,
        doctor_query=search_doctor,
        patient_query=search_patient,
        departments=Department.query.all(),
    )


@app.route("/admin/doctors/create", methods=["POST"])
@login_required
@role_required(UserRole.ADMIN)
def create_doctor():
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "")
    specialization = request.form.get("specialization", "").strip()
    department_id = int(request.form.get("department_id"))
    room = request.form.get("room", "")
    availability_summary = request.form.get("availability_summary", "")
    password = request.form.get("password", "Doctor@123")

    if User.query.filter_by(email=email).first():
        flash("Doctor email already exists.", "warning")
        return redirect(url_for("admin_dashboard"))

    doctor_user = User(
        full_name=full_name,
        email=email,
        phone=phone,
        role=UserRole.DOCTOR,
        password_hash=generate_password_hash(password),
    )
    doctor_profile = Doctor(
        user=doctor_user,
        specialization=specialization,
        department_id=department_id,
        room=room,
        availability_summary=availability_summary,
    )
    db.session.add_all([doctor_user, doctor_profile])
    db.session.commit()
    flash("Doctor profile created.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/doctors/<int:doctor_id>/toggle", methods=["POST"])
@login_required
@role_required(UserRole.ADMIN)
def toggle_doctor(doctor_id: int):
    doctor = Doctor.query.get_or_404(doctor_id)
    doctor.is_active = not doctor.is_active
    doctor.user.is_active = doctor.is_active
    db.session.commit()
    flash("Doctor status updated.", "info")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/doctors/<int:doctor_id>/update", methods=["POST"])
@login_required
@role_required(UserRole.ADMIN)
def update_doctor(doctor_id: int):
    doctor = Doctor.query.get_or_404(doctor_id)
    doctor.user.full_name = request.form.get("full_name", doctor.user.full_name)
    doctor.user.phone = request.form.get("phone", doctor.user.phone)
    doctor.specialization = request.form.get("specialization", doctor.specialization)
    department_value = request.form.get("department_id")
    if department_value:
        doctor.department_id = int(department_value)
    doctor.room = request.form.get("room", doctor.room)
    doctor.availability_summary = request.form.get(
        "availability_summary", doctor.availability_summary
    )
    db.session.commit()
    flash("Doctor profile updated.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/patients/<int:patient_id>/update", methods=["POST"])
@login_required
@role_required(UserRole.ADMIN)
def admin_update_patient(patient_id: int):
    patient = Patient.query.get_or_404(patient_id)
    patient.user.full_name = request.form.get("full_name", patient.user.full_name)
    patient.user.phone = request.form.get("phone", patient.user.phone)
    patient.address = request.form.get("address", patient.address)
    patient.blood_group = request.form.get("blood_group", patient.blood_group)
    db.session.commit()
    flash("Patient information updated.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/patients/<int:patient_id>/toggle", methods=["POST"])
@login_required
@role_required(UserRole.ADMIN)
def toggle_patient(patient_id: int):
    patient = Patient.query.get_or_404(patient_id)
    patient.user.is_active = not patient.user.is_active
    db.session.commit()
    flash("Patient status updated.", "info")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/appointments/<int:appointment_id>/status", methods=["POST"])
@login_required
@role_required(UserRole.ADMIN)
def admin_update_appointment(appointment_id: int):
    appointment = Appointment.query.get_or_404(appointment_id)
    status = request.form.get("status")
    if status in AppointmentStatus.__members__:
        appointment.status = AppointmentStatus[status]
    db.session.commit()
    flash("Appointment status updated.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/doctor/dashboard")
@login_required
@role_required(UserRole.DOCTOR)
def doctor_dashboard():
    doctor = current_user.doctor_profile
    today = date.today()
    end_date = today + timedelta(days=7)
    upcoming = (
        Appointment.query.filter(
            Appointment.doctor_id == doctor.id,
            Appointment.appointment_date >= today,
            Appointment.appointment_date <= end_date,
        )
        .order_by(Appointment.appointment_date.asc())
        .all()
    )
    patients = (
        Patient.query.join(Appointment)
        .filter(Appointment.doctor_id == doctor.id)
        .distinct()
        .all()
    )
    return render_template(
        "doctor_dashboard.html",
        doctor=doctor,
        upcoming_appointments=upcoming,
        patients=patients,
    )


@app.route("/doctor/appointments/<int:appointment_id>", methods=["POST"])
@login_required
@role_required(UserRole.DOCTOR)
def update_appointment_status(appointment_id: int):
    appointment = Appointment.query.get_or_404(appointment_id)
    if appointment.doctor_id != current_user.doctor_profile.id:
        abort(403)
    status = request.form.get("status")
    diagnosis = request.form.get("diagnosis", "")
    prescription = request.form.get("prescription", "")
    notes = request.form.get("notes", "")

    if status in AppointmentStatus.__members__:
        appointment.status = AppointmentStatus[status]

    if appointment.treatment_note:
        appointment.treatment_note.diagnosis = diagnosis
        appointment.treatment_note.prescription = prescription
        appointment.treatment_note.notes = notes
    else:
        db.session.add(
            TreatmentNote(
                appointment=appointment,
                diagnosis=diagnosis,
                prescription=prescription,
                notes=notes,
            )
        )
    db.session.commit()
    flash("Appointment updated.", "success")
    return redirect(url_for("doctor_dashboard"))


@app.route("/doctor/availability", methods=["POST"])
@login_required
@role_required(UserRole.DOCTOR)
def update_availability():
    doctor = current_user.doctor_profile
    available_date = datetime.strptime(request.form["date"], "%Y-%m-%d").date()
    start_time = datetime.strptime(request.form["start_time"], "%H:%M").time()
    end_time = datetime.strptime(request.form["end_time"], "%H:%M").time()

    today = date.today()
    if not (today <= available_date <= today + timedelta(days=7)):
        flash("Select a date within the next 7 days.", "warning")
        return redirect(url_for("doctor_dashboard"))

    availability = DoctorAvailability.query.filter_by(
        doctor_id=doctor.id, available_date=available_date
    ).first()
    if availability:
        availability.start_time = start_time
        availability.end_time = end_time
    else:
        db.session.add(
            DoctorAvailability(
                doctor_id=doctor.id,
                available_date=available_date,
                start_time=start_time,
                end_time=end_time,
            )
        )
    db.session.commit()
    flash("Availability saved.", "success")
    return redirect(url_for("doctor_dashboard"))


@app.route("/doctor/patients/<int:patient_id>")
@login_required
@role_required(UserRole.DOCTOR)
def doctor_patient_history(patient_id: int):
    doctor = current_user.doctor_profile
    patient = Patient.query.get_or_404(patient_id)
    has_relationship = (
        Appointment.query.filter_by(patient_id=patient.id, doctor_id=doctor.id).count()
        > 0
    )
    if not has_relationship:
        abort(403)
    history = (
        Appointment.query.filter_by(patient_id=patient.id, doctor_id=doctor.id)
        .order_by(Appointment.appointment_date.desc())
        .all()
    )
    return render_template(
        "doctor_patient_history.html", patient=patient, doctor=doctor, history=history
    )


@app.route("/patient/dashboard")
@login_required
@role_required(UserRole.PATIENT)
def patient_dashboard():
    patient = current_user.patient_profile
    upcoming = (
        Appointment.query.filter(
            Appointment.patient_id == patient.id,
            Appointment.appointment_date >= date.today(),
        )
        .order_by(Appointment.appointment_date.asc())
        .all()
    )
    history = (
        Appointment.query.filter(
            Appointment.patient_id == patient.id,
            Appointment.appointment_date < date.today(),
        )
        .order_by(Appointment.appointment_date.desc())
        .all()
    )
    departments = Department.query.order_by(Department.name).all()
    doctor_availability = (
        DoctorAvailability.query.join(Doctor)
        .join(User)
        .filter(
            Doctor.is_active.is_(True),
            DoctorAvailability.available_date.between(
                date.today(), date.today() + timedelta(days=7)
            ),
        )
        .order_by(DoctorAvailability.available_date.asc())
        .all()
    )

    return render_template(
        "patient_dashboard.html",
        patient=patient,
        upcoming_appointments=upcoming,
        past_appointments=history,
        departments=departments,
        doctor_availability=doctor_availability,
    )


@app.route("/patient/profile", methods=["GET", "POST"])
@login_required
@role_required(UserRole.PATIENT)
def patient_profile():
    patient = current_user.patient_profile
    if request.method == "POST":
        patient.user.full_name = request.form.get("full_name", patient.user.full_name)
        patient.user.phone = request.form.get("phone", patient.user.phone)
        patient.address = request.form.get("address", patient.address)
        patient.blood_group = request.form.get("blood_group", patient.blood_group)
        patient.emergency_contact = request.form.get(
            "emergency_contact", patient.emergency_contact
        )
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("patient_profile"))
    return render_template("patient_profile.html", patient=patient)


@app.route("/patient/appointments/book", methods=["GET", "POST"])
@login_required
@role_required(UserRole.PATIENT)
def book_appointment():
    patient = current_user.patient_profile
    doctors = Doctor.query.filter_by(is_active=True).all()
    departments = Department.query.all()
    if request.method == "POST":
        doctor_id = int(request.form["doctor_id"])
        department_id = int(request.form["department_id"])
        appointment_date = datetime.strptime(
            request.form["appointment_date"], "%Y-%m-%d"
        ).date()
        appointment_time = datetime.strptime(
            request.form["appointment_time"], "%H:%M"
        ).time()
        reason = request.form.get("reason", "")

        existing = Appointment.query.filter_by(
            doctor_id=doctor_id,
            appointment_date=appointment_date,
            appointment_time=appointment_time,
        ).first()
        if existing:
            flash("Slot already booked. Pick another time.", "danger")
            return redirect(url_for("book_appointment"))

        appt = Appointment(
            patient_id=patient.id,
            doctor_id=doctor_id,
            department_id=department_id,
            appointment_date=appointment_date,
            appointment_time=appointment_time,
            reason=reason,
        )
        db.session.add(appt)
        db.session.commit()
        flash("Appointment booked successfully.", "success")
        return redirect(url_for("patient_dashboard"))

    return render_template(
        "book_appointment.html", doctors=doctors, departments=departments
    )


@app.route("/patient/appointments/<int:appointment_id>/cancel", methods=["POST"])
@login_required
@role_required(UserRole.PATIENT)
def cancel_appointment(appointment_id: int):
    appointment = Appointment.query.get_or_404(appointment_id)
    if appointment.patient_id != current_user.patient_profile.id:
        abort(403)
    appointment.status = AppointmentStatus.CANCELLED
    db.session.commit()
    flash("Appointment cancelled.", "info")
    return redirect(url_for("patient_dashboard"))


@app.route("/patient/appointments/<int:appointment_id>/reschedule", methods=["POST"])
@login_required
@role_required(UserRole.PATIENT)
def reschedule_appointment(appointment_id: int):
    appointment = Appointment.query.get_or_404(appointment_id)
    if appointment.patient_id != current_user.patient_profile.id:
        abort(403)
    new_date = datetime.strptime(request.form["appointment_date"], "%Y-%m-%d").date()
    new_time = datetime.strptime(request.form["appointment_time"], "%H:%M").time()

    conflict = Appointment.query.filter_by(
        doctor_id=appointment.doctor_id,
        appointment_date=new_date,
        appointment_time=new_time,
    ).first()
    if conflict and conflict.id != appointment.id:
        flash("Selected slot is unavailable.", "danger")
        return redirect(url_for("patient_dashboard"))

    appointment.appointment_date = new_date
    appointment.appointment_time = new_time
    appointment.status = AppointmentStatus.BOOKED
    db.session.commit()
    flash("Appointment rescheduled.", "success")
    return redirect(url_for("patient_dashboard"))


@app.route("/search/doctors")
def search_doctors():
    specialization = request.args.get("specialization", "")
    name = request.args.get("name", "")

    doctors = (
        Doctor.query.join(User)
        .filter(
            Doctor.is_active.is_(True),
            Doctor.specialization.ilike(f"%{specialization}%")
            if specialization
            else True,
            User.full_name.ilike(f"%{name}%") if name else True,
        )
        .all()
    )
    return render_template("doctor_search.html", doctors=doctors)


@app.errorhandler(403)
def forbidden(_):
    return render_template("403.html"), 403


@app.errorhandler(404)
def not_found(_):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(debug=True)

