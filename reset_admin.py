"""
Forgot the admin password?  Run:   python reset_admin.py
This resets the login to  admin / admin123  (change it again in Settings).
"""
import sqlite3

from werkzeug.security import generate_password_hash

import app as appmod

conn = sqlite3.connect(appmod.DB_PATH)
conn.execute("UPDATE admin SET username = ?, password_hash = ? WHERE id = (SELECT MIN(id) FROM admin)",
             (appmod.DEFAULT_USERNAME, generate_password_hash(appmod.DEFAULT_PASSWORD)))
conn.commit()
conn.close()
print("Admin login reset to:  username = admin   password = admin123")
