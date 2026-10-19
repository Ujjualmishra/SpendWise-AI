# SpendWise AI

SpendWise AI is an academic project starter for private household income and expense tracking. The current implementation is a functional local milestone, not a production launch.

## Implemented in this milestone

- Flask API with SQLite by default, SQLAlchemy models, schema creation, and family membership records.
- Signup creates a family administrator; login, server-side session cookie, logout, and request throttling.
- Authenticated users can add, edit, list, and delete their own income and expense entries. All transaction queries enforce user and family ownership on the server.
- Personal dashboard totals, category sums, monthly budgets, and admin-only member listing.
- React/Vite interface with responsive navigation, transaction entry, budget entry, and persistent light/dark theme preference (including system preference on first load).
- One login per household can now contain PIN-locked family profiles. Each profile has private income and expense records; the administrator profile can open a family overview with household totals and each profile's transactions.
- The profile-selection screen includes an administrator-only **Add user** form. Incorrect PIN attempts clear the entered PIN and briefly shake/highlight the profile card with an inline error.
- Project team footer with member names, responsibilities, and academic credit.

## Run locally

Requirements: Python 3.11+ and Node.js 20+.

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
python backend\app.py
```

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

In local development, the API runs on `http://127.0.0.1:5001` by default and Vite proxies `/api` requests to it, keeping browser requests same-origin and avoiding local CORS issues. Port 5001 avoids collisions with stale servers that may still be using the previous port 5000. Set `PORT` to change the backend port and `SPENDWISE_API_TARGET` to change the Vite proxy target. For the currently implemented API and profile features only, install the smaller set with `pip install -r backend\requirements-api.txt`; use the full requirements file for the planned ML/reporting modules. Set `SECRET_KEY`, `DATABASE_URL`, `FRONTEND_ORIGIN`, and `COOKIE_SECURE` from the environment before deployment. Set a long random `SECRET_KEY`, use PostgreSQL, set `COOKIE_SECURE=true`, serve over HTTPS, and configure the actual frontend origin for any hosted deployment. Set `VITE_API_BASE_URL` if the deployed API is not served from the same origin under `/api`.

## Data model

- `User` owns their credentials and profile.
- `Family` is the household boundary.
- `FamilyMembership` associates a user with a family and server-assigned `admin` or `member` role. Signup always creates the first admin; the client cannot submit a role.
- `FamilyProfile` represents a person using the shared household login. It is linked to the account and family, has a member/admin role, and stores a Werkzeug-hashed PIN. Only the first profile is assigned admin; profiles added from the Family Overview are members.
- `Transaction` stores account owner, family, active profile, type, title, category, fixed precision amount, date, notes, and timestamps. The authenticated account, family, and selected profile are checked on reads and mutations.
- `Budget` stores a user's monthly overall or category budget, with a uniqueness constraint by owner/category/month.

Money is represented using `NUMERIC(12,2)` and Python `Decimal`. Displayed balance is period income minus period expenses; there is no opening-balance or transfer model yet.

## API routes available

- `POST /api/auth/signup`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/me`
- `GET/POST /api/transactions`, `PATCH/DELETE /api/transactions/<id>`
- `GET /api/dashboard?start=YYYY-MM-DD&end=YYYY-MM-DD`
- `GET/POST /api/budgets`
- `GET /api/family/members` (administrator only)
- `GET /api/profiles`, `POST /api/profiles/select`, `POST /api/profiles/lock`, `POST /api/profiles` (administrator adds a profile), `POST /api/profiles/change-pin`, `POST /api/profiles/reset-pin` (admin password required), `DELETE /api/profiles/<id>` (admin password and exact profile name required; also deletes that profile's transactions)
- `DELETE /api/account` (administrator profile, account password, and exact account email required; deletes the household account and its data)
- `GET /api/family/overview?start=YYYY-MM-DD&end=YYYY-MM-DD` (administrator profile only)
- `GET /api/health`

The SQLite schema is created on app startup. The app performs an additive local migration for the profile ownership column and associates existing account transactions with that account's first profile. Although Flask-Migrate is included, migration scripts have not yet been generated; do not rely on startup schema changes for production upgrades. Back up the database file before local upgrades. Configure managed database backups and recovery before production use.

## Incomplete work and launch readiness

The following requested features are not implemented yet: email invitations or separate family logins, password reset, CSRF tokens, robust authentication lockout, receipt handling, notifications and deduplicated alerts, PDF/CSV exports, report filters, transaction search/sort UI, forecast and anomaly services, trained categorization model and evaluation, privacy policy and terms pages, audit log, API documentation, migration history, automated tests, deployment configuration, custom domain, HTTPS verification, favicon, and production build verification. AI Insights explicitly explains that forecast is unavailable; it does not fabricate a prediction.

Profile PINs are hashed on the server. The PIN prompt is rate limited. A profile without a PIN is initialized by the first person who opens it after signing into the shared household email; this is a convenience lock for family members sharing a device/account, not a separate identity verification system. Use unique email accounts and an invitation/verification workflow for stronger identity assurance. The account password holder can add profiles; only the administrator profile can see other profiles' transactions. Signing out clears the household session; switching profiles returns to the PIN selection screen.

The footer's legal links are currently display placeholders and must not be treated as published legal pages. The built-in password login uses Werkzeug's password hash, HTTP-only and SameSite cookies, and a configurable Secure flag. Cookie-based CSRF protection and complete production security review remain necessary before deployment. The development secret fallback must be replaced via environment configuration.

**Launch status: blocked.** No production database, secrets, hosting, DNS, domain, HTTPS, migrations, or authorization test results have been configured or verified.
