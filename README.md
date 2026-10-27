# FairShift

Attendance, payslips, safety reporting and workforce-wellbeing analytics for shift workers, built for low-literacy, multilingual, mobile-first use (English, Hindi, Tamil, Telugu).

- **Workers** check in by site QR or GPS, read a plain-language payslip (with read-aloud), report hazards by text or voice, leave *anonymous* feedback, and keep a skill passport.
- **Employers** get a dashboard with attendance, explainable fatigue and quit-risk flags, safety-report escalation, k-anonymous manager ratings and printable site QR codes.

Every score is rule-based and shows its reasons, so there is no black box. AI (Gemini) is optional and always has a deterministic offline fallback.

---

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env                                   # demo config; never expose publicly
uvicorn app.main:app --reload
```

| URL | What |
| --- | --- |
| `http://localhost:8000/` | Landing page |
| `/worker` | Worker app. Demo logins `CON01`, `FAC01`, `HOS01`, `COL01`, PIN `1234` |
| `/admin` | Employer dashboard. Demo password `admin123` (only when `ADMIN_PASSWORD` is unset and `SEED_DEMO=1`) |
| `/api/docs` | Interactive API docs |
| `/healthz`, `/readyz` | Liveness and readiness (database reachable) probes |

Run the tests with `pytest -q`.

### Docker

```bash
docker build -t fairshift .
docker run -p 8080:8080 --env-file .env fairshift
```

The image defaults to `DB_PATH=/tmp/fairshift.db`, which is **ephemeral**. Mount a volume and point `DB_PATH` at it for anything you want to keep.

---

## Configuration

All settings are environment variables (see `.env.example`).

| Variable | Default | Notes |
| --- | --- | --- |
| `APP_ENV` | `development` | `production` enforces the safety rules below |
| `SECRET_KEY` | random per start (dev) | Signs tokens and anonymous-feedback hashes. **Required in production** |
| `ADMIN_PASSWORD` | demo value if seeding | Production needs 14+ characters and not the demo value |
| `SEED_DEMO` | `1` | Loads demo sites, workers and history. **Must be `0` in production** |
| `DB_PATH` | `/tmp/fairshift.db` | SQLite file (WAL mode) |
| `TZ_OFFSET_MIN` | `330` | Local-time offset in minutes; drives daily overtime and attendance days |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | empty / `gemini-2.5-flash` | Optional. Without a key, hazard triage, sentiment and insights fall back to rules |

**Production checklist:** `APP_ENV=production`, `SEED_DEMO=0`, strong `ADMIN_PASSWORD`, explicit random `SECRET_KEY`, persistent `DB_PATH`, HTTPS in front.

---

## How it works

### Attendance
Check-in needs either the site QR or a GPS fix inside the site radius. The database enforces **one open shift per worker** with a partial unique index, so concurrent check-ins return HTTP 409 rather than creating duplicates. A shift left open for 20+ hours is auto-closed at the standard day length on the next check-in, and checkout of such a shift is refused pending supervisor review.

### Payroll
Shifts are split at **local midnight**, overtime is calculated **per local day** above the site's standard hours and paid at the site multiplier. PF and ESI use illustrative rates in `services/payroll.py`. Validate them against applicable law before real payroll use.

### Fatigue and quit risk (`services/analytics.py`)
Thresholds are named constants at the top of the file.

| Fatigue flag | Rule |
| --- | --- |
| `WEEKLY_OVER_48` / `WEEKLY_OVER_60` | Hours worked in the last 7 days |
| `LONG_SHIFT` | Any shift over 12 h |
| `BACK_TO_BACK` | Under 11 h rest between shifts |
| `NO_REST_DAY` | 7 or more consecutive days worked |

Quit risk combines an attendance drop, the fatigue score, new-joiner status, long-unresolved safety reports and a low manager rating. Each triggered rule is returned as a human-readable reason.

### Privacy by design
- Feedback rows contain **no worker id and no precise timestamp**. A keyed one-way hash limits each worker to one review per manager per week.
- Managers and sites with fewer than 3 reviews are hidden (k-anonymity).
- Worker text sent to the AI is treated as untrusted data; model output is validated against allow-lists and never rendered as HTML.

### Safety escalation
High and critical reports unresolved after 2 days, and others after 7 days, are flagged as overdue on the dashboard.

---

## Project structure

```text
app/
├── main.py          App factory, security headers, gzip, health probes, static pages
├── config.py        Environment-driven settings and production guards
├── api.py           All HTTP routes (auth, worker, admin)
├── db.py            SQLite connection, migrations, per-request session
├── schema.sql       Tables, constraints and indexes (idempotent)
├── security.py      PBKDF2 PIN hashing, signed tokens, login throttle
├── timeutil.py      UTC helpers, local dates, month bounds
├── services/
│   ├── analytics.py   Pure fatigue and attrition rules
│   ├── workforce.py   Joins DB rows with analytics; attendance trend; short TTL cache
│   ├── payroll.py     Daily-overtime payslip maths
│   ├── gemini.py      Optional AI with offline fallbacks
│   ├── i18n.py        Payslip labels in four languages
│   └── seed.py        Demo data
└── static/           Vanilla-JS worker and admin apps (no build step)
tests/                pytest suite (logic, API, concurrency, security headers)
```

## API overview

Auth is a bearer token from `POST /api/auth/worker` or `POST /api/auth/admin`. Failed logins are throttled (5 per minute per client and code).

| Area | Endpoints |
| --- | --- |
| Worker | `GET /api/me`, `POST /api/shifts/check-in`, `POST /api/shifts/check-out`, `GET /api/shifts/mine` |
| Payslip | `GET /api/payslip?month=YYYY-MM`, `GET /api/payslip/explain` |
| Safety | `POST /api/safety`, `POST /api/safety/voice`, `GET /api/safety/mine` |
| Feedback / skills | `POST /api/feedback`, `GET /api/passport` |
| Admin | `/api/admin/overview`, `attendance-trend`, `fatigue`, `attrition`, `safety`, `feedback`, `insights`, `sites`, `sites/{id}/qr.svg`, `skills` |

Admin list endpoints accept `?sector=all|construction|factory|hospital|education`.

## Performance notes
- Attendance is aggregated **inside SQLite** (grouped by local date) rather than parsed row by row in Python.
- Per-worker analytics are cached for 5 seconds per sector, so one dashboard load computes them once instead of four times.
- Manager and site comments load in a single window-function query (no N+1).
- Indexes cover the dashboard's date-range, status and feedback lookups. Responses are gzip-compressed.

---

## Known limitations
- **QR codes are static site credentials**, not strong attendance proof. Rotating, short-lived signed tokens are needed before real-world use.
- Login throttling is in-process and does not coordinate across multiple instances. Use a shared store if you scale out.
- SQLite suits a single instance; move to a server database for multi-instance deployments.
- Payroll rates and AI hazard classification need review (legal and labelled multilingual evaluation) before production use, and AI endpoints need quotas.
- Translations should be reviewed by native speakers.
