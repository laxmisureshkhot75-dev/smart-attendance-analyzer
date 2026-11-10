"""
OPTIONAL: fill the database with demo students, subjects and 30 days of attendance
so you can see the dashboard, charts and reports working during your demo.

    python seed_demo.py

It refuses to run if students already exist. To start fresh later, delete
database/attendance.db and run the app again (the admin login is re-created).
"""
import random
import sys
from datetime import date, timedelta

import app as appmod

STUDENTS = [
    ("U01AB23S0001", "Sakshi Mudalagi", "sakshi@example.com", "9876500001"),
    ("U01AB23S0002", "Priya S Kulkarni", "priya@example.com", "9876500002"),
    ("U01AB23S0003", "Anjali Patil", "anjali@example.com", "9876500003"),
    ("U01AB23S0004", "Rahul Naik", "rahul@example.com", "9876500004"),
    ("U01AB23S0005", "Kiran Hegde", "kiran@example.com", "9876500005"),
    ("U01AB23S0006", "Meghana Shetty", "meghana@example.com", "9876500006"),
    ("U01AB23S0007", "Arjun Gowda", "arjun@example.com", "9876500007"),
    ("U01AB23S0008", "Divya Rao", "divya@example.com", "9876500008"),
    ("U01AB23S0009", "Vinay Desai", "vinay@example.com", "9876500009"),
    ("U01AB23S0010", "Shruti Bhat", "shruti@example.com", "9876500010"),
]
SUBJECTS = [
    ("BCA501", "Web Technologies", "Prof. Ramesh K"),
    ("BCA502", "Computer Networks", "Prof. Sunita M"),
    ("BCA503", "Database Management", "Prof. Anand P"),
    ("BCA504", "Python Programming", "Prof. Latha R"),
]


def main():
    random.seed(7)
    conn = appmod.sqlite3.connect(appmod.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    if conn.execute("SELECT 1 FROM students LIMIT 1").fetchone():
        print("Students already exist - nothing was changed.")
        return 1
    for reg, name, email, phone in STUDENTS:
        conn.execute("INSERT INTO students (reg_no, name, email, phone, class_name, semester) "
                     "VALUES (?, ?, ?, ?, 'BCA', 5)", (reg, name, email, phone))
    for code, name, teacher in SUBJECTS:
        conn.execute("INSERT INTO subjects (code, name, semester, teacher) VALUES (?, ?, 5, ?)",
                     (code, name, teacher))
    sids = [r[0] for r in conn.execute("SELECT id FROM students ORDER BY id")]
    subids = [r[0] for r in conn.execute("SELECT id FROM subjects ORDER BY id")]
    # each student gets a "habit" so some are excellent and some are at risk
    habits = [0.95, 0.68, 0.88, 0.92, 0.72, 0.97, 0.80, 0.90, 0.60, 0.86]
    today = date.today()
    rows = 0
    for back in range(30, -1, -1):
        d = today - timedelta(days=back)
        if d.weekday() == 6 and back != 0:      # skip Sundays (but always include today)
            continue
        for subid in random.sample(subids, 2):  # two subjects are taught each day
            for sid, habit in zip(sids, habits):
                status = "Present" if random.random() < habit else "Absent"
                conn.execute("INSERT INTO attendance (student_id, subject_id, date, status) "
                             "VALUES (?, ?, ?, ?)", (sid, subid, d.isoformat(), status))
                rows += 1
    conn.commit()
    conn.close()
    print(f"Demo data added: {len(STUDENTS)} students, {len(SUBJECTS)} subjects, {rows} attendance records.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
