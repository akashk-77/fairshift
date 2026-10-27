"""Demo data across 3 sectors. Idempotent: runs only when the DB has no sites."""
import random
import secrets
from datetime import datetime, timedelta

from .. import timeutil as tu
from ..config import settings
from ..security import hash_pin

DEMO_PIN = "1234"
SITES = [  # name, sector, lat, lng, std_hours, ot_mult, prefix
    ("Riverside Tower Site", "construction", 13.0827, 80.2707, 8, 2.0, "CON"),
    ("Chengalpattu Auto Parts Plant", "factory", 12.6819, 79.9888, 8, 2.0, "FAC"),
    ("City Care Hospital", "hospital", 13.0604, 80.2496, 8, 1.5, "HOS"),
    ("St. Joseph's College Campus", "education", 12.9249, 80.1000, 8, 1.5, "COL"),
]
NAMES = {
    "construction": [("Murugan", "Mason"), ("Selvi", "Helper"), ("Ravi", "Electrician"), ("Kumar", "Scaffolder"),
                     ("Lakshmi", "Helper"), ("Ayyanar", "Carpenter"), ("Mala", "Helper"), ("Babu", "Operator")],
    "factory": [("Anitha", "Machine operator"), ("Dinesh", "Welder"), ("Priya", "Packer"), ("Suresh", "Fitter"),
                ("Kavitha", "QC inspector"), ("Manoj", "Press operator"), ("Geetha", "Packer"), ("Rahim", "Forklift driver")],
    "hospital": [("Revathi", "Ward attendant"), ("Joseph", "Nurse"), ("Fatima", "Nurse"), ("Gopal", "Cleaner"),
                 ("Meena", "Nurse"), ("Arun", "Lab technician"), ("Sumathi", "Ward attendant"), ("Vijay", "Security")],
    "education": [("Parvathi", "Hostel cleaner"), ("Ganesan", "Security guard"), ("Rukmini", "Canteen staff"), ("Saravanan", "Lab attendant"),
                  ("Deepa", "Library assistant"), ("Mohan", "Electrician"), ("Chitra", "Housekeeping"), ("Karthik", "Bus driver")],
}
HOURS = {"construction": 8, "factory": 6, "hospital": 7, "education": 8}
SKILLS = {"construction": ["Working at height", "Scaffold safety", "Electrical basics"],
          "factory": ["Machine guarding", "Forklift licence", "5S training"],
          "hospital": ["Infection control", "Basic life support", "Sharps handling"],
          "education": ["Fire drill warden", "Lab chemical safety", "First aid"]}


def seed(db) -> None:
    if db.execute("SELECT COUNT(*) c FROM sites").fetchone()["c"]:
        return
    rnd = random.Random(42)
    now, tz = tu.now(), settings.tz_offset_min
    pin_hash = hash_pin(DEMO_PIN)
    langs = ["ta", "hi", "te", "en"]
    for name, sector, lat, lng, std, mult, pre in SITES:
        sid = db.execute("INSERT INTO sites(name,sector,lat,lng,qr_secret,std_daily_hours,ot_multiplier) "
                         "VALUES(?,?,?,?,?,?,?)", (name, sector, lat, lng, secrets.token_hex(8), std, mult)).lastrowid
        mids = [db.execute("INSERT INTO managers(name,site_id) VALUES(?,?)", (n, sid)).lastrowid
                for n in ("Mr. Sharma", "Ms. D'Souza")]
        for i, (wname, title) in enumerate(NAMES[sector], 1):
            wid = db.execute(
                "INSERT INTO workers(code,name,pin_hash,job_title,site_id,manager_id,language,hourly_rate,joined_on) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (f"{pre}{i:02d}", wname, pin_hash, title, sid, mids[i % 2], langs[i % 4],
                 rnd.choice([75, 80, 90, 110, 140]), str((now - timedelta(days=rnd.choice([60, 150, 400, 900]))).date()))).lastrowid
            overworked, disengaged = i in (1, 5), i == 3
            for off in range(28, -1, -1):
                if off == 0 and i % 2:  # today: only even-numbered workers have started (odd ones are free for check-in demos)
                    continue
                day = now - timedelta(days=off)
                p = 0.9 if not (disengaged and off <= 14) else 0.35
                if overworked and off <= 10:
                    p, dur, start_h = 1.0, 12.5, 7
                else:
                    dur, start_h = std + rnd.choice([0, 0, 0.5, 1, 2]), HOURS[sector]
                if rnd.random() > p:
                    continue
                local = datetime(day.year, day.month, day.day, start_h, rnd.randint(0, 20), tzinfo=tu.UTC)
                cin = local - timedelta(minutes=tz)
                if off == 0 and cin > now:
                    continue
                cout = cin + timedelta(hours=dur)
                db.execute("INSERT INTO shifts(worker_id,site_id,check_in,check_out,method) VALUES(?,?,?,?,?)",
                           (wid, sid, tu.iso(cin), None if cout > now else tu.iso(cout), "qr"))
            for k, sk in enumerate(SKILLS[sector][: 1 + i % 3]):
                db.execute("INSERT INTO skills(worker_id,name,kind,issuer,issued_on) VALUES(?,?,?,?,?)",
                           (wid, sk, "training" if k else "certification", "Site Safety Cell", "2025-06-01"))
        for idx, mid in enumerate(mids):  # idx 1 = a poorly rated manager
            for n in range(5):
                rating = rnd.choice([1, 2, 2, 3]) if idx else rnd.choice([4, 4, 5, 3])
                cmt = ("Shouts and ignores breaks" if idx else "Listens and explains clearly") if n < 2 else ""
                db.execute("INSERT INTO feedback(site_id,manager_id,rating,comment,sentiment,week,dedupe_hash) "
                           "VALUES(?,?,?,?,?,?,?)",
                           (sid, mid, rating, cmt, (rating - 3) / 2, tu.iso_week(now - timedelta(weeks=n)), secrets.token_hex(16)))
        for n, rating in enumerate([2, 2, 3, 1]):  # site-wide "working conditions" reviews (anonymous)
            db.execute("INSERT INTO feedback(site_id,manager_id,topic,rating,comment,sentiment,week,dedupe_hash) "
                       "VALUES(?,?,?,?,?,?,?,?)", (sid, None, "conditions", rating, "No drinking water near the work area" if n < 2 else "",
                                                   (rating - 3) / 2, tu.iso_week(now - timedelta(weeks=n)), secrets.token_hex(16)))
        w1 = db.execute("SELECT id FROM workers WHERE site_id=? ORDER BY id LIMIT 1", (sid,)).fetchone()["id"]
        old = tu.iso(now - timedelta(days=10))
        db.execute("INSERT INTO safety_reports(worker_id,site_id,category,severity,location,description,summary,lang,"
                   "status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (w1, sid, "electrical", "high", "Block B", "Open wires near the water tank", "Exposed wiring near water tank",
                    "en", "open", old, old))
    db.commit()
