CREATE TABLE IF NOT EXISTS sites(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL,
  sector TEXT NOT NULL CHECK(sector IN ('construction','factory','hospital','education')),
  lat REAL, lng REAL, radius_m INTEGER DEFAULT 150,
  qr_secret TEXT NOT NULL,
  std_daily_hours REAL DEFAULT 8, ot_multiplier REAL DEFAULT 2.0);
CREATE TABLE IF NOT EXISTS managers(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, site_id INTEGER NOT NULL REFERENCES sites(id));
CREATE TABLE IF NOT EXISTS workers(
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, pin_hash TEXT NOT NULL,
  job_title TEXT, site_id INTEGER NOT NULL REFERENCES sites(id),
  manager_id INTEGER REFERENCES managers(id),
  language TEXT DEFAULT 'en', hourly_rate REAL NOT NULL, joined_on TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_workers_site ON workers(site_id);
CREATE TABLE IF NOT EXISTS shifts(
  id INTEGER PRIMARY KEY, worker_id INTEGER NOT NULL REFERENCES workers(id),
  site_id INTEGER NOT NULL REFERENCES sites(id),
  check_in TEXT NOT NULL, check_out TEXT, method TEXT, auto_closed INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_shifts_worker ON shifts(worker_id, check_in);
CREATE INDEX IF NOT EXISTS idx_shifts_checkin ON shifts(check_in);  -- dashboard queries scan by date range
-- Invariant: one active shift per worker, even under concurrent requests.
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_open_shift_per_worker
  ON shifts(worker_id) WHERE check_out IS NULL;
CREATE TABLE IF NOT EXISTS safety_reports(
  id INTEGER PRIMARY KEY, worker_id INTEGER NOT NULL REFERENCES workers(id),
  site_id INTEGER NOT NULL REFERENCES sites(id),
  category TEXT, severity TEXT, location TEXT, description TEXT NOT NULL, summary TEXT, lang TEXT,
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','acknowledged','in_progress','resolved')),
  admin_note TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_safety_status_site ON safety_reports(status, site_id);
CREATE INDEX IF NOT EXISTS idx_safety_worker ON safety_reports(worker_id, id);
-- Anonymous by design: NO worker_id and NO precise timestamp are stored.
CREATE TABLE IF NOT EXISTS feedback(
  id INTEGER PRIMARY KEY, site_id INTEGER NOT NULL REFERENCES sites(id),
  manager_id INTEGER REFERENCES managers(id),
  topic TEXT NOT NULL DEFAULT 'manager',
  rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5), comment TEXT, sentiment REAL,
  week TEXT NOT NULL, dedupe_hash TEXT NOT NULL UNIQUE);
CREATE INDEX IF NOT EXISTS idx_feedback_manager ON feedback(manager_id, id);
CREATE INDEX IF NOT EXISTS idx_feedback_site_topic ON feedback(site_id, topic, id);
CREATE TABLE IF NOT EXISTS skills(
  id INTEGER PRIMARY KEY, worker_id INTEGER NOT NULL REFERENCES workers(id),
  name TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('training','certification','experience')),
  issuer TEXT, issued_on TEXT, expires_on TEXT);
CREATE INDEX IF NOT EXISTS idx_skills_worker ON skills(worker_id);
