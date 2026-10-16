# Pharmacy Staff Attendance — Improved Starter

A local Flask web app for a single pharmacy, with employee management, camera-photo check-in/out, an admin dashboard, monthly CSV reports, CSRF protection, and an admin password-change page.

## Quick start on Windows

1. Install Python 3.11 or newer from https://www.python.org/downloads/windows/ (select **Add Python to PATH**).
2. Extract this ZIP to a folder such as `C:\pharmacy_attendance`.
3. Open the folder and double-click `START_PHARMACY_APP.bat`, or open Command Prompt in this folder and run the commands below.
4. Open http://127.0.0.1:5000/attendance for staff check-in and http://127.0.0.1:5000/admin/login for the admin portal.

Manual setup:

```bat
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
set PHARMACY_SECRET_KEY=replace-with-a-long-random-secret
set PHARMACY_ADMIN_USERNAME=admin
set PHARMACY_ADMIN_PASSWORD=replace-with-a-unique-password
set PHARMACY_TIMEZONE=Asia/Karachi
python app.py
```

Set those environment variables in the same Command Prompt before starting the app. For a fresh database, the configured admin is created on first run. If an admin already exists, changing the environment password does not reset the database password; log in and use **Change password**.

## Backups

Close the app before taking a manual backup, then run `BACKUP_DATA.bat`. It creates a timestamped ZIP backup of the `instance` folder. Store backups somewhere secure and periodically test restoring them. The instance folder contains the database and employee photos.

## Configuration

In `app.py`, adjust `SHIFT_START = time(9, 0)` and `LATE_GRACE_MINUTES = 10` to match the pharmacy's shift. The default timezone is `Asia/Karachi`.

## Important limitations before commercial use

- This version is for a single pharmacy on a trusted local computer. It is **not production-ready for public internet hosting**.
- Do not expose Flask's built-in development server to the internet. A hosted version needs HTTPS, production WSGI hosting, strong secret management, login rate limiting, monitoring, tested backups, and a security review.
- Multi-pharmacy subscriptions need tenant separation so each pharmacy can only access its own staff and records. This project does not implement multi-tenancy.
- Camera photos do not prove identity. Explain photo collection to employees, obtain appropriate consent, limit access and retention, and comply with applicable privacy laws.
- Historical absences need schedules, holidays, and approved leave rules. The current dashboard's no-check-in status is only a live daily indicator.
- Attendance is limited to one record per employee per calendar day and one shift.
- Before using real staff records, change the initial admin password, set a long random secret key, secure the computer, and back up the `instance` folder.
