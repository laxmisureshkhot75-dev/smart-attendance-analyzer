"""
analysis.py - all attendance calculations for Smart Attendance Analyser.

Every function here reads REAL records from the SQLite database.
Nothing is hard-coded.

Attendance categories (percentage of classes attended):
    At Risk   : below 75 %
    Low       : 75 % to below 85 %
    Good      : 85 % to below 90 %
    Excellent : 90 % and above
"""
from datetime import date, datetime, timedelta

AT_RISK_BELOW = 75.0
LOW_BELOW = 85.0
EXCELLENT_FROM = 90.0


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def pct(present, total):
    """Percentage rounded to 1 decimal, or None when there are no classes."""
    return round(present * 100.0 / total, 1) if total else None


def fmt_pct(p):
    """92.0 -> '92%', 84.3 -> '84.3%', None -> '—'."""
    return "—" if p is None else f"{p:g}%"


def classify(p):
    if p is None:
        return "No Data"
    if p < AT_RISK_BELOW:
        return "At Risk"
    if p < LOW_BELOW:
        return "Low"
    if p >= EXCELLENT_FROM:
        return "Excellent"
    return "Good"


def dmy(value):
    """'2026-11-08' -> '08-11-2026'."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d-%m-%Y")
    except (TypeError, ValueError):
        return value or ""


def _conds(f, skip=()):
    """Turn a filter dict into SQL conditions on the attendance table (alias a)."""
    conds, params = [], []
    mapping = (
        ("student_id", "a.student_id = ?"),
        ("subject_id", "a.subject_id = ?"),
        ("date", "a.date = ?"),
        ("date_from", "a.date >= ?"),
        ("date_to", "a.date <= ?"),
    )
    for key, sql in mapping:
        if key not in skip and f.get(key):
            conds.append(sql)
            params.append(f[key])
    if "month" not in skip and f.get("month"):
        conds.append("substr(a.date, 1, 7) = ?")
        params.append(f["month"])
    return conds, params


def _where(f, skip=()):
    conds, params = _conds(f, skip)
    return (" WHERE " + " AND ".join(conds) if conds else ""), params


def _decorate(row):
    d = dict(row)
    d["absent"] = d["total"] - d["present"]
    d["percentage"] = pct(d["present"], d["total"])
    d["status"] = classify(d["percentage"])
    return d


# --------------------------------------------------------------------------
# Core statistics
# --------------------------------------------------------------------------
def overall(db, f=None):
    f = f or {}
    where, params = _where(f)
    r = db.execute(
        "SELECT COUNT(*) AS t, COALESCE(SUM(a.status = 'Present'), 0) AS p "
        f"FROM attendance a{where}", params).fetchone()
    return {"total": r["t"], "present": r["p"], "absent": r["t"] - r["p"],
            "percentage": pct(r["p"], r["t"])}


def student_stats(db, f=None):
    """One row per student (all students are listed, even with 0 classes)."""
    f = f or {}
    conds, params = _conds(f, skip=("student_id",))
    on = "".join(" AND " + c for c in conds)
    where = ""
    if f.get("student_id"):
        where = " WHERE s.id = ?"
        params = params + [f["student_id"]]
    rows = db.execute(
        "SELECT s.id, s.reg_no, s.name, s.email, s.phone, s.class_name, s.semester, "
        "COUNT(a.id) AS total, COALESCE(SUM(a.status = 'Present'), 0) AS present "
        "FROM students s LEFT JOIN attendance a ON a.student_id = s.id"
        f"{on}{where} GROUP BY s.id ORDER BY s.name COLLATE NOCASE", params).fetchall()
    return [_decorate(r) for r in rows]


def subject_stats(db, f=None):
    """One row per subject."""
    f = f or {}
    conds, params = _conds(f, skip=("subject_id",))
    on = "".join(" AND " + c for c in conds)
    where = ""
    if f.get("subject_id"):
        where = " WHERE sub.id = ?"
        params = params + [f["subject_id"]]
    rows = db.execute(
        "SELECT sub.id, sub.code, sub.name, sub.semester, sub.teacher, "
        "COUNT(a.id) AS total, COALESCE(SUM(a.status = 'Present'), 0) AS present "
        "FROM subjects sub LEFT JOIN attendance a ON a.subject_id = sub.id"
        f"{on}{where} GROUP BY sub.id ORDER BY sub.name COLLATE NOCASE", params).fetchall()
    return [_decorate(r) for r in rows]


def _series(db, f, key_sql):
    where, params = _where(f)
    rows = db.execute(
        f"SELECT {key_sql} AS k, COUNT(*) AS total, "
        f"SUM(a.status = 'Present') AS present FROM attendance a{where} "
        "GROUP BY k ORDER BY k", params).fetchall()
    out = []
    for r in rows:
        out.append({"key": r["k"], "total": r["total"], "present": r["present"],
                    "absent": r["total"] - r["present"],
                    "percentage": pct(r["present"], r["total"])})
    return out


# Monday of the week the date falls in
_WEEK_SQL = ("date(a.date, '-' || ((CAST(strftime('%w', a.date) AS INTEGER) + 6) % 7) "
             "|| ' days')")


def daily_stats(db, f=None):
    return _series(db, f or {}, "a.date")


def weekly_stats(db, f=None):
    return _series(db, f or {}, _WEEK_SQL)


def monthly_stats(db, f=None):
    return _series(db, f or {}, "substr(a.date, 1, 7)")


def chart_series(series, kind):
    """Convert a stats series into chart labels / values."""
    labels, values = [], []
    for s in series:
        if kind == "daily":
            label = datetime.strptime(s["key"], "%Y-%m-%d").strftime("%d %b")
        elif kind == "weekly":
            label = "Wk " + datetime.strptime(s["key"], "%Y-%m-%d").strftime("%d %b")
        else:
            label = datetime.strptime(s["key"], "%Y-%m").strftime("%b %Y")
        labels.append(label)
        values.append(s["percentage"])
    return {"labels": labels, "values": values}


def month_label(key):
    return datetime.strptime(key, "%Y-%m").strftime("%B %Y")


def week_label(key):
    return "Week of " + dmy(key)


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
def at_risk_count(db):
    """Students whose overall attendance is below 75 %."""
    return db.execute(
        "SELECT COUNT(*) FROM (SELECT student_id FROM attendance GROUP BY student_id "
        "HAVING ROUND(100.0 * SUM(status = 'Present') / COUNT(*), 1) < ?)",
        (AT_RISK_BELOW,)).fetchone()[0]


def dashboard_summary(db, today):
    total_students = db.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    # Students (not records): present = attended at least one class today,
    # absent = marked today but absent in every class.
    row = db.execute(
        "SELECT COUNT(*) AS marked, COALESCE(SUM(any_p), 0) AS present FROM ("
        "SELECT MAX(status = 'Present') AS any_p FROM attendance WHERE date = ? "
        "GROUP BY student_id)", (today,)).fetchone()
    t = {"total": row["marked"], "present": row["present"], "absent": row["marked"] - row["present"]}
    ov = overall(db, {})
    title, subtitle = motivation(ov["percentage"])
    return {
        "total_students": total_students,
        "present_today": t["present"],
        "absent_today": t["absent"],
        "marked_today": t["total"],
        "present_pct": pct(t["present"], t["total"]),
        "absent_pct": pct(t["absent"], t["total"]),
        "at_risk": at_risk_count(db),
        "overall": ov,
        "motivation_title": title,
        "motivation_text": subtitle,
    }


def trend(db, rng, today):
    """Attendance % trend for the dashboard line chart."""
    today_d = datetime.strptime(today, "%Y-%m-%d").date()
    if rng == "week":
        f = {"date_from": (today_d - timedelta(days=6)).isoformat(), "date_to": today}
        return chart_series(daily_stats(db, f), "daily")
    if rng == "all":
        return chart_series(monthly_stats(db, {}), "monthly")
    return chart_series(daily_stats(db, {"month": today[:7]}), "daily")


def recent_records(db, limit=8):
    rows = db.execute(
        "SELECT a.id, a.date, a.status, s.name, s.reg_no, sub.name AS subject, "
        "(SELECT ROUND(100.0 * SUM(x.status = 'Present') / COUNT(*), 1) "
        " FROM attendance x WHERE x.student_id = s.id) AS pct "
        "FROM attendance a JOIN students s ON s.id = a.student_id "
        "JOIN subjects sub ON sub.id = a.subject_id "
        "ORDER BY a.date DESC, a.marked_at DESC, a.id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def motivation(p):
    if p is None:
        return "Get Started!", "Mark attendance to see insights"
    if p >= EXCELLENT_FROM:
        return "Keep Going!", "Excellent Attendance Performance"
    if p >= AT_RISK_BELOW:
        return "Good Work!", "Aim for 90% and above"
    return "Needs Attention!", "Overall attendance is below 75%"


# --------------------------------------------------------------------------
# Detail pages
# --------------------------------------------------------------------------
def student_subjectwise(db, student_id):
    return [s for s in subject_stats(db, {"student_id": student_id}) if s["total"] > 0]


def records(db, f=None, limit=None):
    """Detailed attendance records (newest first)."""
    f = f or {}
    where, params = _where(f)
    sql = ("SELECT a.id, a.date, a.status, s.reg_no, s.name, sub.code, sub.name AS subject "
           "FROM attendance a JOIN students s ON s.id = a.student_id "
           "JOIN subjects sub ON sub.id = a.subject_id"
           f"{where} ORDER BY a.date DESC, s.name COLLATE NOCASE, sub.name")
    if limit:
        sql += " LIMIT ?"
        params = params + [limit]
    return [dict(r) for r in db.execute(sql, params).fetchall()]


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------
REPORT_TYPES = [
    ("overall", "Overall Attendance Report"),
    ("student", "Student Attendance Report"),
    ("subject", "Subject Attendance Report"),
    ("daily", "Daily Attendance Report"),
    ("monthly", "Monthly Attendance Report"),
    ("low", "Low Attendance Report"),
]


def _number(rows):
    return [[i + 1] + list(r) for i, r in enumerate(rows)]


def _summary_from(ov):
    return [("Total Records", ov["total"]), ("Present", ov["present"]),
            ("Absent", ov["absent"]), ("Attendance", fmt_pct(ov["percentage"]))]


def build_report(db, rtype, f):
    """Return dict(title, headers, rows, summary, note). Rows contain plain strings."""
    f = dict(f)
    note = ""
    if rtype == "student":
        if f.get("student_id"):
            st = student_stats(db, f)
            st = st[0] if st else None
            recs = records(db, f)
            title = "Student Attendance Report"
            if st:
                title += f" - {st['name']} ({st['reg_no']})"
            headers = ["#", "Date", "Subject", "Status"]
            rows = _number([[dmy(r["date"]), r["subject"], r["status"]] for r in recs])
            summary = _summary_from(overall(db, f))
        else:
            title = "Student Attendance Report"
            headers = ["#", "Reg No", "Student Name", "Class / Sem", "Total", "Present",
                       "Absent", "Attendance", "Status"]
            stats = student_stats(db, f)
            rows = _number([[s["reg_no"], s["name"], f"{s['class_name']} / {s['semester']}",
                             s["total"], s["present"], s["absent"], fmt_pct(s["percentage"]),
                             s["status"]] for s in stats])
            summary = [("Students", len(stats))] + _summary_from(overall(db, f))
    elif rtype == "subject":
        title = "Subject Attendance Report"
        headers = ["#", "Code", "Subject", "Sem", "Teacher", "Total", "Present", "Absent",
                   "Attendance", "Status"]
        stats = subject_stats(db, f)
        rows = _number([[s["code"], s["name"], s["semester"], s["teacher"], s["total"],
                         s["present"], s["absent"], fmt_pct(s["percentage"]), s["status"]]
                        for s in stats])
        summary = [("Subjects", len(stats))] + _summary_from(overall(db, f))
    elif rtype == "daily":
        title = "Daily Attendance Report"
        if not f.get("date_from") and not f.get("date_to") and not f.get("date"):
            latest = db.execute("SELECT MAX(date) FROM attendance").fetchone()[0]
            if latest:
                f["date_from"] = f["date_to"] = latest
                note = (f"Showing the latest day with records ({dmy(latest)}). "
                        "Use the date filter to see other days.")
        recs = records(db, f)
        headers = ["#", "Date", "Reg No", "Student Name", "Subject", "Status"]
        rows = _number([[dmy(r["date"]), r["reg_no"], r["name"], r["subject"], r["status"]]
                        for r in recs])
        summary = _summary_from(overall(db, f))
    elif rtype == "monthly":
        title = "Monthly Attendance Report"
        headers = ["#", "Month", "Total", "Present", "Absent", "Attendance"]
        series = monthly_stats(db, f)
        rows = _number([[month_label(s["key"]), s["total"], s["present"], s["absent"],
                         fmt_pct(s["percentage"])] for s in series])
        summary = _summary_from(overall(db, f))
    elif rtype == "low":
        title = "Low Attendance Report (below 85%)"
        headers = ["#", "Reg No", "Student Name", "Class / Sem", "Total", "Present",
                   "Absent", "Attendance", "Status"]
        stats = [s for s in student_stats(db, f)
                 if s["percentage"] is not None and s["percentage"] < LOW_BELOW]
        stats.sort(key=lambda s: s["percentage"])
        rows = _number([[s["reg_no"], s["name"], f"{s['class_name']} / {s['semester']}",
                         s["total"], s["present"], s["absent"], fmt_pct(s["percentage"]),
                         s["status"]] for s in stats])
        summary = [("Students below 85%", len(stats)),
                   ("At Risk (below 75%)", sum(1 for s in stats if s["status"] == "At Risk"))]
    else:  # overall
        title = "Overall Attendance Report"
        headers = ["#", "Reg No", "Student Name", "Class / Sem", "Total", "Present",
                   "Absent", "Attendance", "Status"]
        stats = student_stats(db, f)
        rows = _number([[s["reg_no"], s["name"], f"{s['class_name']} / {s['semester']}",
                         s["total"], s["present"], s["absent"], fmt_pct(s["percentage"]),
                         s["status"]] for s in stats])
        summary = [("Students", len(stats))] + _summary_from(overall(db, f))
    return {"title": title, "headers": headers, "rows": rows, "summary": summary,
            "note": note}
