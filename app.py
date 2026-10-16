import os, base64, csv, io, re
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, Response, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

APP_SECRET = os.environ.get("PHARMACY_SECRET_KEY")
ADMIN_USERNAME = os.environ.get("PHARMACY_ADMIN_USERNAME")
ADMIN_PASSWORD = os.environ.get("PHARMACY_ADMIN_PASSWORD")
if not APP_SECRET or not ADMIN_USERNAME or not ADMIN_PASSWORD:
    raise RuntimeError(
        "Set PHARMACY_SECRET_KEY, PHARMACY_ADMIN_USERNAME, and PHARMACY_ADMIN_PASSWORD "
        "as environment variables before starting the app."
    )

app = Flask(__name__)
app.config.update(
    SECRET_KEY=APP_SECRET,
    SQLALCHEMY_DATABASE_URI="sqlite:///pharmacy_attendance.db",
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=3 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("PHARMACY_HTTPS", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)
db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = "admin_login"

# Change these settings to match your pharmacy.
LOCAL_TZ = ZoneInfo(os.environ.get("PHARMACY_TIMEZONE", "Asia/Karachi"))
SHIFT_START = time(9, 0)
LATE_GRACE_MINUTES = 10
ALLOWED_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}

def now_local():
    return datetime.now(LOCAL_TZ).replace(tzinfo=None)

class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_code = db.Column(db.String(30), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(80), default="Staff", nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=now_local, nullable=False)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    work_date = db.Column(db.Date, nullable=False, index=True)
    check_in = db.Column(db.DateTime, nullable=True)
    check_out = db.Column(db.DateTime, nullable=True)
    check_in_photo = db.Column(db.String(255), nullable=True)
    check_out_photo = db.Column(db.String(255), nullable=True)
    employee = db.relationship("Employee", backref="attendance")
    __table_args__ = (db.UniqueConstraint("employee_id", "work_date", name="one_attendance_per_employee_per_day"),)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Admin, int(user_id))

def admin_bootstrap():
    # Creates the configured admin only if no administrator exists.
    if not Admin.query.first():
        admin = Admin(username=ADMIN_USERNAME)
        admin.set_password(ADMIN_PASSWORD)
        db.session.add(admin)
        db.session.commit()

def save_photo(data_url, employee_id, kind):
    match = re.fullmatch(r"data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=\r\n]+)", data_url or "")
    if not match:
        raise ValueError("Please capture a valid photo using the camera.")
    mime, encoded = match.groups()
    if mime not in ALLOWED_IMAGE_TYPES:
        raise ValueError("Unsupported photo type.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception:
        raise ValueError("Photo data was not valid.")
    if not raw or len(raw) > 2 * 1024 * 1024:
        raise ValueError("Photo must be under 2 MB.")
    # Basic signature checks to avoid saving arbitrary files as images.
    valid = (
        (mime == "image/jpeg" and raw.startswith(b"\xff\xd8\xff")) or
        (mime == "image/png" and raw.startswith(b"\x89PNG\r\n\x1a\n")) or
        (mime == "image/webp" and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP")
    )
    if not valid:
        raise ValueError("Image format did not match its content.")
    folder = os.path.join(app.instance_path, "attendance_photos")
    os.makedirs(folder, exist_ok=True)
    filename = secure_filename(f"{employee_id}_{now_local():%Y%m%d_%H%M%S}_{kind}{ALLOWED_IMAGE_TYPES[mime]}")
    with open(os.path.join(folder, filename), "wb") as f:
        f.write(raw)
    return filename

@app.route("/")
def index():
    return redirect(url_for("attendance_page"))

@app.route("/attendance")
def attendance_page():
    employees = Employee.query.filter_by(active=True).order_by(Employee.name).all()
    return render_template("attendance.html", employees=employees, today=now_local().date())

@app.post("/attendance/<int:employee_id>/<action>")
def mark_attendance(employee_id, action):
    if action not in {"in", "out"}:
        abort(404)
    employee = db.session.get(Employee, employee_id)
    if not employee or not employee.active:
        flash("Employee not found or inactive.", "error")
        return redirect(url_for("attendance_page"))
    photo_data = request.form.get("photo", "")
    try:
        photo_name = save_photo(photo_data, employee.id, action)
        today = now_local().date()
        record = Attendance.query.filter_by(employee_id=employee.id, work_date=today).first()
        if action == "in":
            if record and record.check_in:
                raise ValueError("This employee has already checked in today.")
            if not record:
                record = Attendance(employee_id=employee.id, work_date=today)
                db.session.add(record)
            record.check_in = now_local()
            record.check_in_photo = photo_name
        else:
            if not record or not record.check_in:
                raise ValueError("Check in first before checking out.")
            if record.check_out:
                raise ValueError("This employee has already checked out today.")
            record.check_out = now_local()
            record.check_out_photo = photo_name
        db.session.commit()
        flash(f"{employee.name}: check-{action} recorded successfully.", "success")
    except ValueError as exc:
        db.session.rollback()
        # Remove any just-saved photo if the action could not be recorded.
        if 'photo_name' in locals():
            try: os.remove(os.path.join(app.instance_path, "attendance_photos", photo_name))
            except OSError: pass
        flash(str(exc), "error")
    return redirect(url_for("attendance_page"))

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        admin = Admin.query.filter_by(username=username).first()
        if admin and admin.check_password(password):
            login_user(admin)
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")

@app.route("/admin/logout", methods=["POST"])
@login_required
def admin_logout():
    logout_user()
    return redirect(url_for("admin_login"))

@app.route("/admin")
@login_required
def dashboard():
    today = now_local().date()
    employees = Employee.query.filter_by(active=True).order_by(Employee.name).all()
    records = Attendance.query.filter_by(work_date=today).all()
    by_employee = {r.employee_id: r for r in records}
    present = len([e for e in employees if e.id in by_employee and by_employee[e.id].check_in])
    late = len([e for e in employees if e.id in by_employee and by_employee[e.id].check_in and
                by_employee[e.id].check_in.time() > (datetime.combine(today, SHIFT_START) + timedelta(minutes=LATE_GRACE_MINUTES)).time()])
    rows = [{"employee": e, "record": by_employee.get(e.id)} for e in employees]
    return render_template("dashboard.html", rows=rows, today=today, present=present,
                           absent=len(employees)-present, late=late, active_count=len(employees))

@app.route("/admin/employees", methods=["GET", "POST"])
@login_required
def employees_page():
    if request.method == "POST":
        code = request.form.get("employee_code", "").strip()
        name = request.form.get("name", "").strip()
        role = request.form.get("role", "Staff").strip() or "Staff"
        if not code or not name:
            flash("Employee code and name are required.", "error")
        elif Employee.query.filter_by(employee_code=code).first():
            flash("That employee code already exists.", "error")
        else:
            db.session.add(Employee(employee_code=code, name=name, role=role))
            db.session.commit()
            flash("Employee added.", "success")
            return redirect(url_for("employees_page"))
    employees = Employee.query.order_by(Employee.active.desc(), Employee.name).all()
    return render_template("employees.html", employees=employees)

@app.post("/admin/employees/<int:employee_id>/toggle")
@login_required
def toggle_employee(employee_id):
    employee = db.session.get(Employee, employee_id)
    if not employee:
        abort(404)
    employee.active = not employee.active
    db.session.commit()
    flash("Employee status updated.", "success")
    return redirect(url_for("employees_page"))

@app.route("/admin/reports")
@login_required
def reports():
    month_text = request.args.get("month", now_local().strftime("%Y-%m"))
    if not re.fullmatch(r"\d{4}-\d{2}", month_text):
        abort(400)
    try:
        year, month = map(int, month_text.split("-"))
        start = date(year, month, 1)
    except ValueError:
        abort(400)
    end = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    records = Attendance.query.filter(Attendance.work_date >= start, Attendance.work_date < end)\
        .join(Employee).order_by(Attendance.work_date.desc(), Employee.name).all()
    if request.args.get("export") == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Date", "Employee ID", "Employee Name", "Role", "Check In", "Check Out", "Status", "Hours"])
        for r in records:
            status = "Absent" if not r.check_in else (
                "Late" if r.check_in.time() > (datetime.combine(r.work_date, SHIFT_START) + timedelta(minutes=LATE_GRACE_MINUTES)).time() else "Present"
            )
            hours = ""
            if r.check_in and r.check_out:
                hours = round((r.check_out-r.check_in).total_seconds()/3600, 2)
            writer.writerow([r.work_date.isoformat(), r.employee.employee_code, r.employee.name, r.employee.role,
                             r.check_in.strftime("%H:%M:%S") if r.check_in else "",
                             r.check_out.strftime("%H:%M:%S") if r.check_out else "", status, hours])
        return Response(output.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=attendance-{month_text}.csv"})
    return render_template("reports.html", records=records, month=month_text, start=start, end=end)

@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
    response.headers.setdefault("Cache-Control", "no-store")
    return response

@app.route("/admin/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not current_user.check_password(current_password):
            flash("Current password is incorrect.", "error")
        elif len(new_password) < 12:
            flash("Use at least 12 characters for the new password.", "error")
        elif new_password != confirm_password:
            flash("The new passwords do not match.", "error")
        elif new_password == current_password:
            flash("Choose a different password.", "error")
        else:
            current_user.set_password(new_password)
            db.session.commit()
            flash("Password changed successfully.", "success")
            return redirect(url_for("dashboard"))
    return render_template("change_password.html")

@app.errorhandler(413)
def upload_too_large(_error):
    flash("The submitted request is too large. Please use a smaller photo.", "error")
    return redirect(url_for("attendance_page")), 413

@app.route("/admin/photos/<path:filename>")
@login_required
def view_photo(filename):
    # Photo viewing is admin-only; serve only files from the designated photo folder.
    from flask import send_from_directory
    return send_from_directory(os.path.join(app.instance_path, "attendance_photos"), filename)

with app.app_context():
    os.makedirs(app.instance_path, exist_ok=True)
    db.create_all()
    admin_bootstrap()

if __name__ == "__main__":
    # Local-only by default. Do not expose the development server to the internet.
    app.run(host="127.0.0.1", port=5000, debug=False)
