# FairShift hardening changes

This archive contains the existing project with a targeted set of fixes. It is not a certification that the application is production-ready.

## Included changes

- `/api/meta` no longer exposes an admin-password hint.
- Production startup (`APP_ENV=production`) requires an explicit strong admin password and explicit signing secret, and rejects demo seeding.
- Database schema enforces at most one open shift per worker with a partial unique index.
- Database initialization detects legacy duplicate open shifts and stops with an actionable error instead of silently modifying attendance history.
- Concurrent check-in uniqueness violations are converted to HTTP 409.
- Check-out refuses to close shifts older than 20 hours so suspicious records are reviewed rather than silently included in payroll.
- Payroll splits shifts at local midnight before calculating daily overtime and rejects reversed intervals and invalid rate configuration.
- Added `/readyz` to check database connectivity; `/healthz` remains a liveness endpoint.
- Added regression tests for credential disclosure, overnight payroll, reversed intervals, and readiness.
- Updated README with production/demo safety notes and known QR limitation.

## Validation performed

- `python -m compileall -q app tests`: passed.
- `pytest -q`: 31 passed when a temporary test-only `segno` stub was supplied because the real `segno` dependency was not installed in the environment. The stub only returns a minimal SVG; it does **not** validate actual QR generation. Install dependencies and rerun the suite without the stub before submission.

## Remaining known work

- QR codes are still static site credentials. Do not treat them as strong attendance proof; implement short-lived signed rotating tokens before real-world deployment.
- In-memory login throttling does not coordinate across multiple app instances.
- Validate payroll contribution rules against applicable law before real payroll use.
- Evaluate AI hazard classification with a labelled multilingual test set and add quotas for AI-backed endpoints.
- Review frontend flows and deployment persistence in the actual target environment.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload
```

For the local demo, demo seeding is enabled in `.env.example`. Do not expose the local demo configuration publicly. For production, configure `APP_ENV=production`, `SEED_DEMO=0`, a strong `ADMIN_PASSWORD`, an explicit random `SECRET_KEY`, and persistent database storage.
