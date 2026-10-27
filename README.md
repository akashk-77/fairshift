# Fairshift

Fairshift is a modern workforce, shift scheduling, and payroll management application designed to streamline shift allocation, worker management, and operational analytics.

## 🚀 Tech Stack

* **Backend:** Python, FastAPI
* **Database:** SQLite / Relational Database with custom schema (`schema.sql`)
* **Services:** Workforce management, Payroll calculation, Internationalization (i18n), Gemini integration, and Analytics
* **Frontend:** HTML5, CSS3, Vanilla JavaScript (`admin.html`, `worker.html`, `index.html`)
* **Containerization:** Docker & Docker Compose

---

## 📁 Project Structure

```text
fairshift/
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
├── README.md
├── .env.example
├── app/
│   ├── main.py
│   ├── config.py
│   ├── api.py
│   ├── db.py
│   ├── schema.sql
│   ├── security.py
│   ├── timeutil.py
│   ├── services/
│   │   ├── analytics.py
│   │   ├── gemini.py
│   │   ├── i18n.py
│   │   ├── payroll.py
│   │   ├── seed.py
│   │   └── workforce.py
│   └── static/
│       ├── admin.html
│       ├── index.html
│       ├── worker.html
│       ├── css/
│       │   └── app.css
│       └── js/
│           ├── admin.js
│           ├── common.js
│           └── worker.js
└── tests/
    ├── conftest.py
    └── test_core.py
