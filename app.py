"""
Smart Attendance Analyser - Flask backend
Run locally :  python app.py
Run on Render: gunicorn app:app
"""
import csv
import io
import os
import re
import secrets
import sqlite3
import time
from datetime import date, datetime
from urllib.parse import urlencode
from xml.sax.saxutils import escape

from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import analysis

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "database", "attendance.db"))

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin123"

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
# IMPORTANT: set a long random SECRET_KEY environment variable in production.
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),  # HTTPS only on Render
    MAX_CONTENT_LENGTH=1024 * 1024,
)

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS admin (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name     TEXT NOT NULL DEFAULT 'Administrator',
    email         TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS students (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    reg_no     TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    email      TEXT NOT NULL DEFAULT '',
    phone      TEXT NOT NULL DEFAULT '',
    class_name TEXT NOT NULL DEFAULT 'BCA',
    semester   INTEGER NOT NULL CHECK (semester BETWEEN 1 AND 8),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS subjects (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    semester   INTEGER NOT NULL CHECK (semester BETWEEN 1 AND 8),
    teacher    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS attendance (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    date       TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('Present', 'Absent')),
    marked_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (student_id, subject_id, date)
);
CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date);
CREATE INDEX IF NOT EXISTS idx_attendance_subject ON attendance(subject_id);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
"""

DEFAULT_SETTINGS = {
    "college_name": "Your College Name",
    "college_address": "",
    "department": "BCA",
    "academic_year": "2026-2027",
}


def init_db():
    """Create the database file, tables and the default admin (first run only)."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    if not conn.execute("SELECT 1 FROM admin LIMIT 1").fetchone():
        conn.execute(
            "INSERT INTO admin (username, password_hash, full_name) VALUES (?, ?, ?)",
            (DEFAULT_USERNAME, generate_password_hash(DEFAULT_PASSWORD), "Administrator"))
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def get_settings(db):
    return {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM settings")}


def set_setting(db, key, value):
    db.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
               "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?\d{10,13}$")
REG_RE = re.compile(r"^[A-Z0-9/_.\-]+$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.]{3,30}$")


def clean(value):
    return (value or "").strip()


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def valid_date(value):
    try:
        datetime.strptime(value or "", "%Y-%m-%d")
        return value
    except ValueError:
        return ""


def valid_month(value):
    try:
        datetime.strptime(value or "", "%Y-%m")
        return value
    except ValueError:
        return ""


def today_str():
    return date.today().isoformat()


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = csrf_token
app.add_template_filter(analysis.dmy, "dmy")
app.add_template_filter(analysis.fmt_pct, "pctfmt")


@app.context_processor
def inject_globals():
    ctx = {"today": today_str(), "at_risk_total": 0, "settings": {}, "admin_name": ""}
    if session.get("admin_id"):
        db = get_db()
        ctx["settings"] = get_settings(db)
        ctx["at_risk_total"] = analysis.at_risk_count(db)
        ctx["admin_name"] = session.get("admin_name", "Admin")
    return ctx


@app.before_request
def security_gate():
    # CSRF protection for every form submission
    if request.method == "POST":
        token = session.get("csrf_token")
        if not token or not secrets.compare_digest(token, request.form.get("csrf_token", "")):
            abort(400)
    # Only logged-in admins may open protected pages
    if request.endpoint in (None, "static", "login"):
        return None
    if not session.get("admin_id"):
        return redirect(url_for("login"))
    return None


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


def errors_to_flash(errors):
    for e in errors:
        flash(e, "danger")


# ---------------------------------------------------------------------------
# Login / logout (simple brute-force throttle: 5 failures per 5 minutes per IP)
# ---------------------------------------------------------------------------
FAILED_LOGINS = {}


def too_many_attempts(ip):
    now = time.time()
    recent = [t for t in FAILED_LOGINS.get(ip, []) if now - t < 300]
    FAILED_LOGINS[ip] = recent
    return len(recent) >= 5


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin_id"):
        return redirect(url_for("dashboard"))
    db = get_db()
    if request.method == "POST":
        ip = request.remote_addr or "unknown"
        username, password = clean(request.form.get("username")), request.form.get("password", "")
        if too_many_attempts(ip):
            flash("Too many failed attempts. Please wait 5 minutes and try again.", "danger")
        elif not username or not password:
            flash("Please enter both username and password.", "danger")
        else:
            admin = db.execute("SELECT * FROM admin WHERE username = ?", (username,)).fetchone()
            if admin and check_password_hash(admin["password_hash"], password):
                session.clear()
                session["admin_id"] = admin["id"]
                session["admin_name"] = admin["full_name"]
                FAILED_LOGINS.pop(ip, None)
                flash(f"Welcome back, {admin['full_name']}!", "success")
                return redirect(url_for("dashboard"))
            FAILED_LOGINS.setdefault(ip, []).append(time.time())
            flash("Invalid username or password.", "danger")
    # Show the demo hint only while the default password is unchanged
    row = db.execute("SELECT password_hash FROM admin WHERE username = ?",
                     (DEFAULT_USERNAME,)).fetchone()
    show_demo = bool(row and check_password_hash(row["password_hash"], DEFAULT_PASSWORD))
    return render_template("login.html", show_demo=show_demo,
                           demo_user=DEFAULT_USERNAME, demo_pass=DEFAULT_PASSWORD)


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.route("/")
def dashboard():
    db = get_db()
    return render_template("dashboard.html",
                           s=analysis.dashboard_summary(db, today_str()),
                           recent=analysis.recent_records(db, 8))


@app.route("/api/dashboard")
def api_dashboard():
    db = get_db()
    rng = request.args.get("range", "month")
    return jsonify(summary=analysis.dashboard_summary(db, today_str()),
                   trend=analysis.trend(db, rng, today_str()),
                   recent=analysis.recent_records(db, 8))


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------
def parse_student_form(form, db, student_id=None):
    d = {
        "reg_no": clean(form.get("reg_no")).upper(),
        "name": clean(form.get("name")),
        "email": clean(form.get("email")).lower(),
        "phone": clean(form.get("phone")),
        "class_name": clean(form.get("class_name")) or "BCA",
        "semester": clean(form.get("semester")),
    }
    errors = []
    if not d["reg_no"]:
        errors.append("Student ID / Register Number is required.")
    elif len(d["reg_no"]) > 30 or not REG_RE.match(d["reg_no"]):
        errors.append("Register Number may contain only letters, digits and - _ . /")
    elif db.execute("SELECT 1 FROM students WHERE reg_no = ? AND id != ?",
                    (d["reg_no"], student_id or 0)).fetchone():
        errors.append(f"Register Number {d['reg_no']} already exists.")
    if not 2 <= len(d["name"]) <= 80:
        errors.append("Student name must be 2 to 80 characters.")
    if d["email"] and (len(d["email"]) > 120 or not EMAIL_RE.match(d["email"])):
        errors.append("Please enter a valid email address.")
    if d["phone"] and not PHONE_RE.match(d["phone"]):
        errors.append("Phone number must be 10 to 13 digits (optional + at the start).")
    if len(d["class_name"]) > 30:
        errors.append("Class name is too long (max 30 characters).")
    sem = to_int(d["semester"])
    if sem is None or not 1 <= sem <= 8:
        errors.append("Please select a semester between 1 and 8.")
    else:
        d["semester"] = sem
    return d, errors


@app.route("/students")
def students():
    q = clean(request.args.get("q")).lower()
    rows = analysis.student_stats(get_db())
    if q:
        rows = [r for r in rows if any(q in str(r[k]).lower() for k in
                                       ("reg_no", "name", "email", "phone", "class_name", "semester"))]
    return render_template("students.html", rows=rows, q=request.args.get("q", ""))


@app.route("/students/add", methods=["GET", "POST"])
def student_add():
    db = get_db()
    form = {"class_name": "BCA", "semester": "5"}
    if request.method == "POST":
        form, errors = parse_student_form(request.form, db)
        if errors:
            errors_to_flash(errors)
        else:
            db.execute("INSERT INTO students (reg_no, name, email, phone, class_name, semester) "
                       "VALUES (:reg_no, :name, :email, :phone, :class_name, :semester)", form)
            db.commit()
            flash(f"Student {form['name']} added successfully.", "success")
            return redirect(url_for("students"))
    return render_template("student_form.html", form=form, editing=False, student_id=None)


@app.route("/students/<int:sid>/edit", methods=["GET", "POST"])
def student_edit(sid):
    db = get_db()
    row = db.execute("SELECT * FROM students WHERE id = ?", (sid,)).fetchone()
    if not row:
        abort(404)
    form = dict(row)
    if request.method == "POST":
        form, errors = parse_student_form(request.form, db, sid)
        if errors:
            errors_to_flash(errors)
        else:
            form["id"] = sid
            db.execute("UPDATE students SET reg_no=:reg_no, name=:name, email=:email, "
                       "phone=:phone, class_name=:class_name, semester=:semester WHERE id=:id", form)
            db.commit()
            flash("Student updated successfully.", "success")
            return redirect(url_for("students"))
    return render_template("student_form.html", form=form, editing=True, student_id=sid)


@app.route("/students/<int:sid>/delete", methods=["POST"])
def student_delete(sid):
    db = get_db()
    row = db.execute("SELECT name FROM students WHERE id = ?", (sid,)).fetchone()
    if not row:
        abort(404)
    db.execute("DELETE FROM students WHERE id = ?", (sid,))
    db.commit()
    flash(f"Student {row['name']} and their attendance records were deleted.", "success")
    return redirect(url_for("students"))


@app.route("/students/<int:sid>")
def student_detail(sid):
    db = get_db()
    stats = analysis.student_stats(db, {"student_id": sid})
    if not stats:
        abort(404)
    return render_template("student_detail.html", st=stats[0],
                           subjectwise=analysis.student_subjectwise(db, sid),
                           history=analysis.records(db, {"student_id": sid}, limit=30))


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------
def parse_subject_form(form, db, subject_id=None):
    d = {
        "code": clean(form.get("code")).upper(),
        "name": clean(form.get("name")),
        "semester": clean(form.get("semester")),
        "teacher": clean(form.get("teacher")),
    }
    errors = []
    if not d["code"]:
        errors.append("Subject code is required.")
    elif len(d["code"]) > 20 or not REG_RE.match(d["code"]):
        errors.append("Subject code may contain only letters, digits and - _ . / (max 20).")
    elif db.execute("SELECT 1 FROM subjects WHERE code = ? AND id != ?",
                    (d["code"], subject_id or 0)).fetchone():
        errors.append(f"Subject code {d['code']} already exists.")
    if not 2 <= len(d["name"]) <= 80:
        errors.append("Subject name must be 2 to 80 characters.")
    if not 2 <= len(d["teacher"]) <= 80:
        errors.append("Subject teacher name must be 2 to 80 characters.")
    sem = to_int(d["semester"])
    if sem is None or not 1 <= sem <= 8:
        errors.append("Please select a semester between 1 and 8.")
    else:
        d["semester"] = sem
    return d, errors


@app.route("/subjects")
def subjects():
    q = clean(request.args.get("q")).lower()
    rows = analysis.subject_stats(get_db())
    if q:
        rows = [r for r in rows if any(q in str(r[k]).lower() for k in
                                       ("code", "name", "teacher", "semester"))]
    return render_template("subjects.html", rows=rows, q=request.args.get("q", ""))


@app.route("/subjects/add", methods=["GET", "POST"])
def subject_add():
    db = get_db()
    form = {"semester": "5"}
    if request.method == "POST":
        form, errors = parse_subject_form(request.form, db)
        if errors:
            errors_to_flash(errors)
        else:
            db.execute("INSERT INTO subjects (code, name, semester, teacher) "
                       "VALUES (:code, :name, :semester, :teacher)", form)
            db.commit()
            flash(f"Subject {form['name']} added successfully.", "success")
            return redirect(url_for("subjects"))
    return render_template("subject_form.html", form=form, editing=False, subject_id=None)


@app.route("/subjects/<int:sid>/edit", methods=["GET", "POST"])
def subject_edit(sid):
    db = get_db()
    row = db.execute("SELECT * FROM subjects WHERE id = ?", (sid,)).fetchone()
    if not row:
        abort(404)
    form = dict(row)
    if request.method == "POST":
        form, errors = parse_subject_form(request.form, db, sid)
        if errors:
            errors_to_flash(errors)
        else:
            form["id"] = sid
            db.execute("UPDATE subjects SET code=:code, name=:name, semester=:semester, "
                       "teacher=:teacher WHERE id=:id", form)
            db.commit()
            flash("Subject updated successfully.", "success")
            return redirect(url_for("subjects"))
    return render_template("subject_form.html", form=form, editing=True, subject_id=sid)


@app.route("/subjects/<int:sid>/delete", methods=["POST"])
def subject_delete(sid):
    db = get_db()
    row = db.execute("SELECT name FROM subjects WHERE id = ?", (sid,)).fetchone()
    if not row:
        abort(404)
    db.execute("DELETE FROM subjects WHERE id = ?", (sid,))
    db.commit()
    flash(f"Subject {row['name']} and its attendance records were deleted.", "success")
    return redirect(url_for("subjects"))


@app.route("/subjects/<int:sid>")
def subject_detail(sid):
    db = get_db()
    stats = analysis.subject_stats(db, {"subject_id": sid})
    if not stats:
        abort(404)
    return render_template("subject_detail.html", sub=stats[0],
                           students=analysis.student_stats(db, {"subject_id": sid}),
                           days=analysis.daily_stats(db, {"subject_id": sid})[::-1][:15])


# ---------------------------------------------------------------------------
# Mark attendance
# ---------------------------------------------------------------------------
@app.route("/attendance", methods=["GET", "POST"])
def attendance():
    db = get_db()
    subjects_list = db.execute("SELECT * FROM subjects ORDER BY name COLLATE NOCASE").fetchall()

    if request.method == "POST":
        d = valid_date(request.form.get("date"))
        sid = to_int(request.form.get("subject_id"))
        sem_only = "1" if request.form.get("semester_only") else ""
        subject = db.execute("SELECT * FROM subjects WHERE id = ?", (sid,)).fetchone()
        if not d:
            flash("Please select a valid date.", "danger")
        elif d > today_str():
            flash("Attendance cannot be marked for a future date.", "danger")
        elif not subject:
            flash("Please select a subject.", "danger")
        else:
            ids = [i for i in (to_int(x) for x in request.form.getlist("student_ids")) if i]
            valid_ids = {r["id"] for r in db.execute("SELECT id FROM students")}
            existing = {r["student_id"] for r in db.execute(
                "SELECT student_id FROM attendance WHERE subject_id = ? AND date = ?", (sid, d))}
            created = updated = 0
            for stud_id in ids:
                status = request.form.get(f"status_{stud_id}")
                if stud_id not in valid_ids or status not in ("Present", "Absent"):
                    continue
                # UNIQUE(student, subject, date) + upsert = no duplicates, only updates
                db.execute(
                    "INSERT INTO attendance (student_id, subject_id, date, status) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT(student_id, subject_id, date) "
                    "DO UPDATE SET status = excluded.status, marked_at = CURRENT_TIMESTAMP",
                    (stud_id, sid, d, status))
                if stud_id in existing:
                    updated += 1
                else:
                    created += 1
            db.commit()
            if created + updated == 0:
                flash("No students were selected, nothing was saved.", "warning")
            else:
                flash(f"Attendance saved for {subject['name']} on {analysis.dmy(d)}: "
                      f"{created} new record(s), {updated} updated.", "success")
            return redirect(url_for("attendance", date=d, subject_id=sid, semester_only=sem_only))
        return redirect(url_for("attendance", date=d or today_str(), subject_id=sid or "",
                                semester_only=sem_only))

    sel_date = valid_date(request.args.get("date")) or today_str()
    sel_subject = None
    sid = to_int(request.args.get("subject_id"))
    sem_only = bool(request.args.get("semester_only"))
    students_list, marks = [], {}
    if sid:
        sel_subject = db.execute("SELECT * FROM subjects WHERE id = ?", (sid,)).fetchone()
    if sel_subject:
        sql, params = "SELECT * FROM students", []
        if sem_only:
            sql += " WHERE semester = ?"
            params.append(sel_subject["semester"])
        students_list = db.execute(sql + " ORDER BY name COLLATE NOCASE", params).fetchall()
        marks = {r["student_id"]: r["status"] for r in db.execute(
            "SELECT student_id, status FROM attendance WHERE subject_id = ? AND date = ?",
            (sel_subject["id"], sel_date))}
    return render_template("attendance.html", subjects=subjects_list, sel_date=sel_date,
                           sel_subject=sel_subject, students=students_list, marks=marks,
                           sem_only=sem_only)


@app.route("/attendance/delete", methods=["POST"])
def attendance_delete():
    db = get_db()
    d, sid = valid_date(request.form.get("date")), to_int(request.form.get("subject_id"))
    if not d or not sid:
        abort(400)
    cur = db.execute("DELETE FROM attendance WHERE subject_id = ? AND date = ?", (sid, d))
    db.commit()
    flash(f"Deleted {cur.rowcount} attendance record(s) for {analysis.dmy(d)}.", "success")
    return redirect(url_for("attendance", date=d, subject_id=sid))


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def pick_lists(db):
    return (db.execute("SELECT id, reg_no, name FROM students ORDER BY name COLLATE NOCASE").fetchall(),
            db.execute("SELECT id, code, name FROM subjects ORDER BY name COLLATE NOCASE").fetchall())


@app.route("/analysis")
def analysis_page():
    db = get_db()
    f = {"student_id": to_int(request.args.get("student_id")),
         "subject_id": to_int(request.args.get("subject_id")),
         "date": valid_date(request.args.get("date")),
         "month": valid_month(request.args.get("month"))}
    ov = analysis.overall(db, f)
    stud = analysis.student_stats(db, f)
    subj = analysis.subject_stats(db, f)
    daily = analysis.daily_stats(db, f)
    weekly = analysis.weekly_stats(db, f)
    monthly = analysis.monthly_stats(db, f)
    rated = [s for s in stud if s["percentage"] is not None]
    lists = {
        "low": sorted([s for s in rated if s["status"] == "Low"], key=lambda s: s["percentage"]),
        "risk": sorted([s for s in rated if s["status"] == "At Risk"], key=lambda s: s["percentage"]),
        "excellent": sorted([s for s in rated if s["status"] == "Excellent"],
                            key=lambda s: -s["percentage"]),
    }
    chart = {
        "overall": {"present": ov["present"], "absent": ov["absent"]},
        "students": {"labels": [s["name"] for s in rated][:40],
                     "values": [s["percentage"] for s in rated][:40]},
        "subjects": {"labels": [s["name"] for s in subj if s["total"]],
                     "values": [s["percentage"] for s in subj if s["total"]]},
        "daily": analysis.chart_series(daily[-60:], "daily"),
        "weekly": analysis.chart_series(weekly[-26:], "weekly"),
        "monthly": analysis.chart_series(monthly, "monthly"),
    }
    students_pick, subjects_pick = pick_lists(db)
    return render_template(
        "analysis.html", f=f, ov=ov, stud=stud, subj=subj, daily=daily[::-1],
        weekly=weekly[::-1], monthly=monthly[::-1], lists=lists, chart=chart,
        students_pick=students_pick, subjects_pick=subjects_pick,
        month_label=analysis.month_label, week_label=analysis.week_label,
        filtered=any(f.values()))


# ---------------------------------------------------------------------------
# Reports (HTML preview, CSV, PDF, print)
# ---------------------------------------------------------------------------
def report_params():
    rtype = request.args.get("type", "overall")
    if rtype not in dict(analysis.REPORT_TYPES):
        rtype = "overall"
    f = {"student_id": to_int(request.args.get("student_id")),
         "subject_id": to_int(request.args.get("subject_id")),
         "date_from": valid_date(request.args.get("date_from")),
         "date_to": valid_date(request.args.get("date_to"))}
    if f["date_from"] and f["date_to"] and f["date_from"] > f["date_to"]:
        f["date_from"], f["date_to"] = f["date_to"], f["date_from"]
    return rtype, f


def query_string(rtype, f):
    params = {"type": rtype}
    params.update({k: v for k, v in f.items() if v})
    return urlencode(params)


@app.route("/reports")
def reports():
    db = get_db()
    rtype, f = report_params()
    report = analysis.build_report(db, rtype, f)
    total_rows = len(report["rows"])
    report["rows"] = report["rows"][:500]
    students_pick, subjects_pick = pick_lists(db)
    return render_template("reports.html", rtype=rtype, f=f, report=report,
                           total_rows=total_rows, report_types=analysis.REPORT_TYPES,
                           qs=query_string(rtype, f), students_pick=students_pick,
                           subjects_pick=subjects_pick, generated=datetime.now())


def safe_cell(value):
    """Stop spreadsheet formula injection when CSV is opened in Excel."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


@app.route("/reports/csv")
def report_csv():
    db = get_db()
    rtype, f = report_params()
    report = analysis.build_report(db, rtype, f)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([report["title"]])
    for label, value in report["summary"]:
        writer.writerow([label, value])
    writer.writerow([])
    writer.writerow(report["headers"])
    for row in report["rows"]:
        writer.writerow([safe_cell(c) for c in row])
    data = "﻿" + buf.getvalue()  # BOM so Excel shows text correctly
    return Response(data, mimetype="text/csv; charset=utf-8", headers={
        "Content-Disposition": f"attachment; filename={rtype}_report_{today_str()}.csv"})


def make_pdf(report, settings):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    page = landscape(A4) if len(report["headers"]) > 6 else A4
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm, title=report["title"])
    base = getSampleStyleSheet()["Normal"]
    college = ParagraphStyle("c", parent=base, fontName="Helvetica-Bold", fontSize=16,
                             textColor=colors.HexColor("#0b2a6b"), spaceAfter=2)
    title = ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=12, spaceAfter=2)
    small = ParagraphStyle("s", parent=base, fontSize=9, textColor=colors.HexColor("#475569"))
    cell = ParagraphStyle("cell", parent=base, fontSize=8.5, leading=11)
    head = ParagraphStyle("h", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)

    story = [Paragraph(escape(settings.get("college_name", "")), college),
             Paragraph(escape(report["title"]), title),
             Paragraph(f"Academic Year: {escape(settings.get('academic_year', ''))} &nbsp;|&nbsp; "
                       f"Generated: {datetime.now().strftime('%d-%m-%Y %H:%M')}", small)]
    if report["note"]:
        story.append(Paragraph(escape(report["note"]), small))
    story.append(Spacer(1, 4 * mm))
    if report["summary"]:
        story.append(Paragraph(" &nbsp;&nbsp;|&nbsp;&nbsp; ".join(
            f"<b>{escape(str(k))}:</b> {escape(str(v))}" for k, v in report["summary"]), cell))
        story.append(Spacer(1, 4 * mm))
    if report["rows"]:
        width = page[0] - 24 * mm
        n = len(report["headers"])
        widths = [width / n] * n
        widths[0] = 10 * mm  # '#' column
        rest = (width - widths[0]) / (n - 1)
        widths = [widths[0]] + [rest] * (n - 1)
        data = [[Paragraph(escape(h), head) for h in report["headers"]]]
        for row in report["rows"]:
            data.append([Paragraph(escape(str(c)), cell) for c in row])
        table = Table(data, colWidths=widths, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b2a6b")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef4ff")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(table)
    else:
        story.append(Paragraph("No attendance records found for the selected filters.", cell))
    doc.build(story)
    return buf.getvalue()


@app.route("/reports/pdf")
def report_pdf():
    db = get_db()
    rtype, f = report_params()
    report = analysis.build_report(db, rtype, f)
    pdf = make_pdf(report, get_settings(db))
    return Response(pdf, mimetype="application/pdf", headers={
        "Content-Disposition": f"attachment; filename={rtype}_report_{today_str()}.pdf"})


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def current_admin(db):
    return db.execute("SELECT * FROM admin WHERE id = ?", (session["admin_id"],)).fetchone()


@app.route("/settings")
def settings():
    db = get_db()
    return render_template("settings.html", admin=current_admin(db), cfg=get_settings(db))


@app.route("/settings/profile", methods=["POST"])
def settings_profile():
    db = get_db()
    name, email = clean(request.form.get("full_name")), clean(request.form.get("email")).lower()
    if not 2 <= len(name) <= 60:
        flash("Full name must be 2 to 60 characters.", "danger")
    elif email and not EMAIL_RE.match(email):
        flash("Please enter a valid email address.", "danger")
    else:
        db.execute("UPDATE admin SET full_name = ?, email = ? WHERE id = ?",
                   (name, email, session["admin_id"]))
        db.commit()
        session["admin_name"] = name
        flash("Admin profile updated.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/username", methods=["POST"])
def settings_username():
    db = get_db()
    new_user = clean(request.form.get("new_username"))
    admin = current_admin(db)
    if not check_password_hash(admin["password_hash"], request.form.get("current_password", "")):
        flash("Current password is incorrect.", "danger")
    elif not USERNAME_RE.match(new_user):
        flash("Username must be 3-30 characters: letters, digits, _ or . only.", "danger")
    elif db.execute("SELECT 1 FROM admin WHERE username = ? AND id != ?",
                    (new_user, admin["id"])).fetchone():
        flash("That username is already taken.", "danger")
    else:
        db.execute("UPDATE admin SET username = ? WHERE id = ?", (new_user, admin["id"]))
        db.commit()
        flash(f"Username changed to {new_user}. Use it next time you log in.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/password", methods=["POST"])
def settings_password():
    db = get_db()
    admin = current_admin(db)
    cur, new, confirm = (request.form.get("current_password", ""),
                         request.form.get("new_password", ""),
                         request.form.get("confirm_password", ""))
    if not check_password_hash(admin["password_hash"], cur):
        flash("Current password is incorrect.", "danger")
    elif len(new) < 6:
        flash("New password must be at least 6 characters.", "danger")
    elif new != confirm:
        flash("New password and confirmation do not match.", "danger")
    elif new == cur:
        flash("New password must be different from the current password.", "danger")
    else:
        db.execute("UPDATE admin SET password_hash = ? WHERE id = ?",
                   (generate_password_hash(new), admin["id"]))
        db.commit()
        flash("Password changed successfully.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/college", methods=["POST"])
def settings_college():
    db = get_db()
    name = clean(request.form.get("college_name"))
    address = clean(request.form.get("college_address"))
    dept = clean(request.form.get("department"))
    year = clean(request.form.get("academic_year"))
    if not 2 <= len(name) <= 120:
        flash("College name must be 2 to 120 characters.", "danger")
    elif not re.match(r"^\d{4}\s*[-/]\s*\d{2,4}$", year):
        flash("Academic year must look like 2026-2027.", "danger")
    elif len(address) > 200 or len(dept) > 60:
        flash("Address or department text is too long.", "danger")
    else:
        for key, value in (("college_name", name), ("college_address", address),
                           ("department", dept), ("academic_year", year)):
            set_setting(db, key, value)
        db.commit()
        flash("College information saved.", "success")
    return redirect(url_for("settings"))


# ---------------------------------------------------------------------------
# Error pages
# ---------------------------------------------------------------------------
def error_page(code, title, message):
    return render_template("error.html", code=code, title=title, message=message), code


@app.errorhandler(400)
def bad_request(_e):
    return error_page(400, "Request could not be verified",
                      "Your form session expired or was invalid. Go back, refresh the page and try again.")


@app.errorhandler(404)
def not_found(_e):
    return error_page(404, "Page not found", "The page or record you are looking for does not exist.")


@app.errorhandler(500)
def server_error(_e):
    return error_page(500, "Something went wrong", "An unexpected error occurred. Please try again.")


init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=True)
