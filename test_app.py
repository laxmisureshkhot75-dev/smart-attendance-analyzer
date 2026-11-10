"""
Automated checks - run from the project folder with:   python -m unittest -v
Uses a temporary database, so your real data is never touched.
"""
import os
import re
import sys
import tempfile
import unittest
from datetime import date, timedelta

_tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmp, "test.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as appmod  # noqa: E402


class AttendanceApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = appmod.app.test_client()

    def token(self, url="/login"):
        html = self.c.get(url).get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def post(self, url, data, form_page="/login", **kw):
        data = dict(data, csrf_token=self.token(form_page))
        return self.c.post(url, data=data, **kw)

    def login(self, user="admin", pw="admin123"):
        return self.post("/login", {"username": user, "password": pw}, follow_redirects=True)

    # ---- tests run in alphabetical order, so they are numbered ----
    def test_01_protected_pages_need_login(self):
        for url in ("/", "/students", "/subjects", "/attendance", "/analysis", "/reports", "/settings"):
            r = self.c.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn("/login", r.headers["Location"])

    def test_02_bad_login_and_csrf(self):
        r = self.login(pw="wrong")
        self.assertIn("Invalid username or password", r.get_data(as_text=True))
        r = self.c.post("/login", data={"username": "admin", "password": "admin123"})
        self.assertEqual(r.status_code, 400)   # missing CSRF token

    def test_03_full_flow(self):
        r = self.login()
        self.assertIn("Smart Attendance", r.get_data(as_text=True))
        for url in ("/", "/students", "/students/add", "/subjects", "/subjects/add", "/attendance",
                    "/analysis", "/reports", "/settings"):
            self.assertEqual(self.c.get(url).status_code, 200, url)

        # add students
        for reg, name, phone in (("S1", "Asha", "9999999991"), ("S2", "Bhaskar", "9999999992"),
                                 ("S3", "Chitra", "9999999993")):
            r = self.post("/students/add", {"reg_no": reg, "name": name, "email": "", "phone": phone,
                                            "class_name": "BCA", "semester": "5"},
                          "/students/add", follow_redirects=True)
            self.assertIn("added successfully", r.get_data(as_text=True))
        # duplicate / invalid
        r = self.post("/students/add", {"reg_no": "s1", "name": "X", "semester": "9", "email": "bad"},
                      "/students/add", follow_redirects=True)
        text = r.get_data(as_text=True)
        self.assertIn("already exists", text)
        self.assertIn("valid email", text)
        # subject
        r = self.post("/subjects/add", {"code": "bca501", "name": "Web Tech", "semester": "5",
                                        "teacher": "Prof. A"}, "/subjects/add", follow_redirects=True)
        self.assertIn("added successfully", r.get_data(as_text=True))

        # search
        self.assertIn("Bhaskar", self.c.get("/students?q=bhas").get_data(as_text=True))
        self.assertNotIn("Chitra", self.c.get("/students?q=bhas").get_data(as_text=True))

        # mark attendance twice (second time = update, no duplicates)
        today = date.today().isoformat()
        yday = (date.today() - timedelta(days=1)).isoformat()
        db = appmod.sqlite3.connect(appmod.DB_PATH)
        ids = [r[0] for r in db.execute("SELECT id FROM students ORDER BY id")]
        sub = db.execute("SELECT id FROM subjects").fetchone()[0]
        db.close()
        page = f"/attendance?date={today}&subject_id={sub}"
        form = {"date": today, "subject_id": sub, "student_ids": [str(i) for i in ids],
                f"status_{ids[0]}": "Present", f"status_{ids[1]}": "Absent", f"status_{ids[2]}": "Present"}
        r = self.post("/attendance", form, page, follow_redirects=True)
        self.assertIn("3 new record(s), 0 updated", r.get_data(as_text=True))
        form[f"status_{ids[1]}"] = "Present"
        r = self.post("/attendance", form, page, follow_redirects=True)
        self.assertIn("0 new record(s), 3 updated", r.get_data(as_text=True))
        db = appmod.sqlite3.connect(appmod.DB_PATH)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM attendance").fetchone()[0], 3)
        db.close()
        # yesterday: ids[1] absent -> 1 of 2 days present = 50 %
        form.update(date=yday, **{f"status_{ids[1]}": "Absent"})
        self.post("/attendance", form, page, follow_redirects=True)
        # future date rejected
        form["date"] = (date.today() + timedelta(days=3)).isoformat()
        r = self.post("/attendance", form, page, follow_redirects=True)
        self.assertIn("future date", r.get_data(as_text=True))

        # live dashboard numbers
        j = self.c.get("/api/dashboard").get_json()
        self.assertEqual(j["summary"]["total_students"], 3)
        self.assertEqual(j["summary"]["present_today"], 3)
        self.assertEqual(j["summary"]["absent_today"], 0)
        self.assertEqual(j["summary"]["at_risk"], 1)          # Bhaskar 50 %
        self.assertEqual(j["summary"]["overall"]["total"], 6)
        self.assertEqual(j["summary"]["overall"]["present"], 5)

        # analysis, filters, details
        for url in ("/analysis", f"/analysis?student_id={ids[1]}", f"/analysis?subject_id={sub}",
                    f"/analysis?date={today}", f"/analysis?month={today[:7]}",
                    f"/students/{ids[1]}", f"/subjects/{sub}"):
            self.assertEqual(self.c.get(url).status_code, 200, url)
        self.assertIn("Bhaskar", self.c.get("/analysis").get_data(as_text=True))

        # reports in every type and format
        for t in ("overall", "student", "subject", "daily", "monthly", "low"):
            self.assertEqual(self.c.get(f"/reports?type={t}").status_code, 200, t)
            csvr = self.c.get(f"/reports/csv?type={t}")
            self.assertEqual(csvr.status_code, 200)
            pdf = self.c.get(f"/reports/pdf?type={t}")
            self.assertTrue(pdf.data.startswith(b"%PDF"), t)
        self.assertIn("Bhaskar", self.c.get("/reports/csv?type=low").get_data(as_text=True))
        self.assertEqual(self.c.get(f"/reports/pdf?type=student&student_id={ids[1]}").status_code, 200)

        # edit + delete student (cascade)
        self.post(f"/students/{ids[2]}/edit", {"reg_no": "S3", "name": "Chitra K", "phone": "",
                                               "class_name": "BCA", "semester": "6"},
                  f"/students/{ids[2]}/edit", follow_redirects=True)
        self.assertIn("Chitra K", self.c.get("/students").get_data(as_text=True))
        self.post(f"/students/{ids[2]}/delete", {}, "/students", follow_redirects=True)
        db = appmod.sqlite3.connect(appmod.DB_PATH)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM attendance WHERE student_id=?", (ids[2],)).fetchone()[0], 0)
        db.close()

        # delete a day's attendance
        r = self.post("/attendance/delete", {"date": yday, "subject_id": sub}, page, follow_redirects=True)
        self.assertIn("Deleted 2", r.get_data(as_text=True))

        # settings
        r = self.post("/settings/college", {"college_name": "Demo College", "academic_year": "2026-2027",
                                            "college_address": "", "department": "BCA"},
                      "/settings", follow_redirects=True)
        self.assertIn("College information saved", r.get_data(as_text=True))
        r = self.post("/settings/password", {"current_password": "bad", "new_password": "secret1",
                                             "confirm_password": "secret1"}, "/settings", follow_redirects=True)
        self.assertIn("incorrect", r.get_data(as_text=True))
        self.post("/settings/password", {"current_password": "admin123", "new_password": "secret1",
                                         "confirm_password": "secret1"}, "/settings", follow_redirects=True)
        self.post("/settings/username", {"new_username": "principal", "current_password": "secret1"},
                  "/settings", follow_redirects=True)

        # logout, old credentials fail, new ones work, demo hint hidden
        self.c.get("/logout")
        self.assertNotIn("Demo login", self.c.get("/login").get_data(as_text=True))
        self.assertIn("Invalid", self.login("admin", "admin123").get_data(as_text=True))
        self.assertIn("Welcome back", self.login("principal", "secret1").get_data(as_text=True))
        self.assertEqual(self.c.get("/nope").status_code, 404)


if __name__ == "__main__":
    unittest.main()
