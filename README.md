# Smart Attendance Analyser

**Smarter Attendance. Better Insights.**
A Flask + SQLite web application to manage students and subjects, mark attendance, analyse it with charts, and export reports (PDF / CSV / Print).
BCA Final Year Project.

---

## 1. Features

| Page | What it does |
|---|---|
| Login | Admin login, hashed password, session, logout, CSRF protection |
| Dashboard | Live cards (Total, Present Today, Absent Today, At Risk), doughnut chart, trend line chart, recent records. Refreshes itself every 30 s |
| Students | Add / edit / delete / search / view details, attendance % per student |
| Subjects | Add / edit / delete / search / view details |
| Mark Attendance | Pick date + subject, mark Present/Absent, save, update, delete a day. Duplicates are impossible (database `UNIQUE` rule) |
| Analysis | Overall %, student-wise, subject-wise, daily, weekly, monthly, Present-vs-Absent chart, Low / At Risk / Excellent lists, filters (student, subject, date, month) |
| Reports | 6 report types, filters, **Download PDF**, **Export CSV**, **Print** |
| Settings | Admin profile, change username, change password, college info, academic year, logout |

**How the numbers are defined (useful for viva)**

- Attendance % = Present records ÷ total records × 100.
- **At Risk** = below 75 %. **Low** = 75 to below 85 %. **Good** = 85 to below 90 %. **Excellent** = 90 % and above. (Change `AT_RISK_BELOW`, `LOW_BELOW`, `EXCELLENT_FROM` at the top of `analysis.py`.)
- **Present Today** = students present in at least one class today. **Absent Today** = students marked today who were absent in every class. The percentage beside them is out of students marked today.
- Students with no attendance records yet show "—" and are never counted as At Risk.

## 2. Technology

Python 3 · Flask · SQLite · HTML5 · CSS3 · JavaScript · Bootstrap 5 · Chart.js · ReportLab (PDF) · Gunicorn (Render)

Bootstrap, Chart.js, Font Awesome icons and the Poppins font load from the internet (CDN), so **you need internet while using the app** for the charts and icons to appear.

## 3. Project structure

```
smart_attendance_analyser/
├── app.py              # Flask routes, database, login, validation, PDF/CSV
├── analysis.py         # All attendance calculations and report building
├── seed_demo.py        # OPTIONAL demo data (10 students, 4 subjects, 30 days)
├── reset_admin.py      # Reset login to admin / admin123 if you forget it
├── requirements.txt    # Python packages
├── Procfile            # Start command for Render
├── README.md
├── .gitignore
├── database/           # attendance.db is created here automatically
├── templates/          # HTML pages (base, login, dashboard, students, subjects,
│                       #   attendance, analysis, reports, settings, forms, error)
├── static/
│   ├── css/style.css
│   ├── js/script.js
│   └── images/
└── tests/test_app.py   # Automated tests
```

The four required tables are `admin`, `students`, `subjects`, `attendance` (plus a small `settings` table for college name and academic year).
`attendance` has foreign keys to `students` and `subjects` with `ON DELETE CASCADE`, and `UNIQUE(student_id, subject_id, date)`.

---

## 4. Run on your computer (Windows)

> **ಕನ್ನಡ:** ಈ ಹಂತಗಳನ್ನು ಒಂದೊಂದಾಗಿ ಅನುಸರಿಸಿ. ಪ್ರತಿ ಕಮಾಂಡ್ ನಂತರ Enter ಒತ್ತಿ.

**Step 1 – Install Python.** Download Python 3.10 or newer from python.org. During install tick **"Add Python to PATH"**.
Check: open Command Prompt and type `python --version`.

**Step 2 – Get the folder.** Unzip `smart_attendance_analyser.zip`. You should see `app.py` inside the folder.
Open the folder in **VS Code** (File → Open Folder).
> **ಕನ್ನಡ:** ಜಿಪ್ ಫೈಲ್ ಅನ್ನು ಅನ್‌ಜಿಪ್ ಮಾಡಿ, VS Code ನಲ್ಲಿ ಫೋಲ್ಡರ್ ತೆರೆಯಿರಿ.

**Step 3 – Open the terminal** in VS Code (Terminal → New Terminal) and create a virtual environment:

```
python -m venv venv
venv\Scripts\activate
```
(Mac/Linux: `python3 -m venv venv` then `source venv/bin/activate`)

**Step 4 – Install packages.**
```
pip install -r requirements.txt
```
> **ಕನ್ನಡ:** ಅಗತ್ಯವಿರುವ ಪ್ಯಾಕೇಜ್‌ಗಳನ್ನು ಇನ್‌ಸ್ಟಾಲ್ ಮಾಡಿ.

**Step 5 – (Optional) add demo data** so your charts are not empty during the demo:
```
python seed_demo.py
```

**Step 6 – Run.**
```
python app.py
```
Open **http://127.0.0.1:5000** in your browser. Stop the server with `Ctrl + C`.
> **ಕನ್ನಡ:** ಪ್ರಾಜೆಕ್ಟ್ ರನ್ ಮಾಡಿ, ಬ್ರೌಸರ್‌ನಲ್ಲಿ http://127.0.0.1:5000 ತೆರೆಯಿರಿ.

### Demo login

| Username | Password |
|---|---|
| `admin` | `admin123` |

> **ಕನ್ನಡ:** `admin / admin123` ಬಳಸಿ ಲಾಗಿನ್ ಆಗಿ. ಮೊದಲ ಬಾರಿ ಲಾಗಿನ್ ಆದ ನಂತರ ಪಾಸ್‌ವರ್ಡ್ ಬದಲಾಯಿಸಿ.

**How to change them:** log in → **Settings** → *Change Username* / *Change Password*. Once you change the password, the demo hint disappears from the login page.
Forgot it? Stop the server and run `python reset_admin.py` (resets to `admin / admin123`).

### Starting with real data
If you loaded the demo data, delete it before real use: stop the app, delete the file `database/attendance.db`, run `python app.py` again. A fresh empty database and the default admin are created.

---

## 5. How to test every feature (checklist for your demo)

1. **Login**: wrong password shows an error; `admin / admin123` opens the dashboard. Opening `/students` while logged out sends you to login.
2. **Settings**: set College Name and Academic Year (they appear on reports and the top bar).
3. **Subjects → Add Subject**: add e.g. `BCA501 – Web Technologies`. Try the same code again (error), then Edit, View, Search.
4. **Students → Add New Student**: add a few students. Try a bad email or duplicate register number (error shown). Edit, View, Search.
5. **Mark Attendance**: pick today's date and a subject, press *Load Students*, mark some Absent, **Save Attendance**. Save again after changing one student: message says "updated", and no duplicate rows appear.
6. **Dashboard**: cards, doughnut chart, trend and recent records now show your data. Mark more attendance in another tab; the dashboard updates within 30 s.
7. **Analysis**: use the Student / Subject / Date / Month filters; check the Low, At Risk and Excellent lists.
8. **Reports**: choose a type and filters → *Generate*, then **Download PDF**, **Export CSV** (opens in Excel), **Print Report**.
9. **Delete**: delete a student (confirmation appears, their attendance is removed too).
10. **Logout**: sidebar or admin menu.

**Automated tests** (optional, shows quality in viva):
```
python -m unittest discover -s tests -v
```

---

## 6. Upload to GitHub

1. Create a free account at github.com → **New repository** → name `smart-attendance-analyser` → keep it empty (no README) → Create.
2. Install Git from git-scm.com. In the VS Code terminal, inside the project folder:

```
git init
git add .
git commit -m "Smart Attendance Analyser - first version"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/smart-attendance-analyser.git
git push -u origin main
```
Replace `YOUR-USERNAME` with your GitHub username. GitHub may ask you to sign in in the browser.
The file `.gitignore` keeps your `venv` folder and your local database out of GitHub.

> **ಕನ್ನಡ:** GitHub ನಲ್ಲಿ ಹೊಸ repository ರಚಿಸಿ, ಮೇಲಿನ ಕಮಾಂಡ್‌ಗಳನ್ನು ಟರ್ಮಿನಲ್‌ನಲ್ಲಿ ರನ್ ಮಾಡಿ. `YOUR-USERNAME` ಬದಲು ನಿಮ್ಮ GitHub ಹೆಸರು ಹಾಕಿ.

Later changes: `git add .` → `git commit -m "your message"` → `git push`.

---

## 7. Deploy on Render

1. Go to render.com and sign up (you can use your GitHub account).
2. **New +** → **Web Service** → connect your GitHub repository `smart-attendance-analyser`.
3. Fill in:

| Field | Value |
|---|---|
| Language / Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app:app` |
| Instance Type | Free |

4. Open **Environment** (Environment Variables) and add:
   - `SECRET_KEY` = a long random text (for example, 40 random letters and digits). **Required for security.**
   - If the build complains about the Python version, add `PYTHON_VERSION` = `3.12.3`.
5. Click **Create Web Service**. Wait for the build; Render gives you a URL like `https://smart-attendance-analyser.onrender.com`.
6. Open the URL and log in with `admin / admin123`, then **change the password immediately** (the site is public).

> **ಕನ್ನಡ:** Render ನಲ್ಲಿ ಡಿಪ್ಲಾಯ್ ಮಾಡಿದ ನಂತರ ತಕ್ಷಣ ಪಾಸ್‌ವರ್ಡ್ ಬದಲಾಯಿಸಿ. `SECRET_KEY` ಹಾಕುವುದು ಕಡ್ಡಾಯ.

### ⚠️ Important: free Render and your data

Render's **free** web services have a temporary filesystem: local file changes (including the SQLite database file) are lost on redeploy, restart or spin-down, and free services cannot attach persistent disks. The service also sleeps after 15 minutes without visitors and takes about a minute to wake up.
(Source: [Render – Deploy for Free](https://render.com/docs/free))

What this means for you:
- The app **works** on Render, but data you enter there can disappear. For the college demo, either use it from your own laptop (data is saved permanently there), or add your demo data again on Render right before the demo (you can't run `seed_demo.py` on the free plan because it has no shell access; add a few records through the pages instead).
- To keep data permanently on Render you need a paid plan with a persistent disk (set the environment variable `DB_PATH` to a file on the disk, e.g. `/var/data/attendance.db`), or move the project to PostgreSQL.

> **ಕನ್ನಡ:** Render ಉಚಿತ ಪ್ಲಾನ್‌ನಲ್ಲಿ ಡೇಟಾಬೇಸ್ ಮರುಹೊಂದಿಕೆ (reset) ಆಗಬಹುದು. ಶಾಶ್ವತ ಡೇಟಾಗಾಗಿ ನಿಮ್ಮ ಲ್ಯಾಪ್‌ಟಾಪ್‌ನಲ್ಲಿ ಬಳಸಿ ಅಥವಾ ಪಾವತಿ ಪ್ಲಾನ್ ಬಳಸಿ.

---

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| `python` not recognised | Reinstall Python with "Add to PATH" ticked, or try `py` instead of `python` |
| `No module named flask` | Activate the venv (`venv\Scripts\activate`) and run `pip install -r requirements.txt` |
| Charts or icons missing | Check your internet connection (libraries load from CDN) |
| "Request could not be verified" | Your form page was open too long; refresh the page and submit again |
| Port 5000 already in use | Run `set PORT=5001` (Windows) then `python app.py`, and open port 5001 |
| Forgot password | `python reset_admin.py` |

## 9. Likely viva questions

- **Why Flask?** Lightweight Python framework; routes map directly to pages.
- **How is duplicate attendance prevented?** `UNIQUE(student_id, subject_id, date)` in the database plus an upsert query (`INSERT … ON CONFLICT DO UPDATE`).
- **How are passwords stored?** Hashed with Werkzeug `generate_password_hash`; never saved as plain text.
- **How is the app secured?** Session login on every page, CSRF token on every form, parameterised SQL (no SQL injection), input validation, brute-force login throttle.
- **How do dashboard values stay live?** They are computed from SQL queries on every request, and the page re-fetches `/api/dashboard` every 30 seconds.
- **Future scope:** SMS/email alerts for at-risk students, student login, QR/face attendance, PostgreSQL.
