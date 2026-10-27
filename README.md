# FairShift: Decent work for every shift (UN SDG 8)

Two interfaces: **Worker app (`/worker`)** and **Employer dashboard (`/admin`)**, linked from a home page (`/`).
Four sectors are seeded: Construction, Factory, Hospital, College. FastAPI + SQLite, vanilla JS (no build step, ~60 KB of frontend), Gemini via Google AI Studio.

## Features
| Worker (`/worker`, EN/हिन्दी/தமிழ்/తెలుగు, icons + read-aloud) | Admin (`/admin`) |
|---|---|
| QR or geofenced check-in, automatic daily overtime | Sector toggle: All / Construction / Factory / Hospital |
| Payslip with PF/ESI breakdown in the worker's language + spoken explanation | Attendance trend, KPIs |
| Hazard report by voice (Gemini transcribes + triages) or text, with status tracking | Fatigue alerts (48h/60h week, >12h shift, <11h rest, 7 days straight) |
| Anonymous manager reviews (no worker id stored, hidden until 3+ reviews) | Quit-risk scores with plain-language reasons |
| Skill passport (JSON export) | Safety queue, status updates, site QR printing, AI insights |

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # then: set -a; source .env; set +a
uvicorn app.main:app --reload --port 8080
pytest -q
```
Demo logins: worker `CON01`, `FAC01`, `HOS01`, `COL01` (…`02`–`08`), PIN `1234`. Admin: `ADMIN_PASSWORD`, or `admin123` when it is unset in demo mode
(the login pages show these hints). Set `SEED_DEMO=0` and a real `ADMIN_PASSWORD` for real data.
Check-in demo: log in as admin, open "Site check-in QR", copy the text encoded (or scan it) on the worker side.
API docs: `/api/docs`.

## Deploy to Google Cloud Run
```bash
PROJECT=your-project-id; REGION=asia-south1
gcloud config set project $PROJECT
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com

# secrets (never in code or git)
printf '%s' "$GEMINI_KEY"        | gcloud secrets create gemini-api-key --data-file=-
openssl rand -hex 32 | tr -d '\n' | gcloud secrets create fairshift-secret-key --data-file=-
printf '%s' "$ADMIN_PW"          | gcloud secrets create fairshift-admin-pw --data-file=-

SA=$(gcloud projects describe $PROJECT --format='value(projectNumber)')-compute@developer.gserviceaccount.com
for s in gemini-api-key fairshift-secret-key fairshift-admin-pw; do
  gcloud secrets add-iam-policy-binding $s --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor; done

gcloud run deploy fairshift --source . --region $REGION --allow-unauthenticated \
  --max-instances 1 --memory 512Mi \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest,SECRET_KEY=fairshift-secret-key:latest,ADMIN_PASSWORD=fairshift-admin-pw:latest
```
`--max-instances 1` because SQLite lives in the container's `/tmp` (demo data re-seeds on cold start).
For production persistence, swap `app/db.py` for Cloud SQL (PostgreSQL); all SQL is plain and portable.

## Design notes & honest limits
- Security: PBKDF2 PINs, HMAC-signed expiring tokens, login throttling, strict CSP, all rendered text escaped, role-separated tokens, parameterised SQL, validated inputs, non-root container, no secrets in repo.
- Anonymity: feedback rows hold no worker id or timestamp; a keyed one-way hash limits it to one review per manager per week. An operator with the server secret could still test a guessed worker, so for stronger guarantees move to blind-signature tokens.
- AI: Gemini outputs are validated against allow-lists; every AI feature has an offline fallback. Voice reports require a Gemini key.
- Payroll rates (PF 12%, ESI 0.75%, OT multiplier) are illustrative; confirm against local labour law.
- Translations are static and should be reviewed by native speakers.

## Cross-sector adoption (2+ industries)
Construction, Factory, Hospital and College/School run on the same engine. Each site sets standard hours, overtime multiplier and a check-in QR/geofence;
hazard categories and fatigue rules are shared. Example: a construction site flags working-at-height and 12-hour days, a hospital flags
sharps/infection risks and night-shift rest gaps, a college flags lab-chemical hazards and unpaid extra hours. The home page (`/`) shows this table.

## Escalation
High/critical hazards unresolved for 2+ days (others 7+) are flagged "overdue" on the admin dashboard so issues don't reach management only after they turn severe.
