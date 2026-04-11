# Project Swift Admin Panel — Flask Reimplementation

This project reimplements the provided HTML/CSS/JS admin panel as a Python backend application using Flask.

## What is included

- Flask app with page routes for all provided screens
- Static assets copied from the provided CSS and JavaScript files
- Server-side endpoints for records, users, analytics, and calendar data
- In-memory Python data layer for demo usage
- Working form submission for **Create Record**
- Working invite flow for **Users** via `/api/users/invite`

## Routes

- `/` → redirects to dashboard
- `/dashboard.html`
- `/filter-list.html`
- `/create-record.html`
- `/record-details.html?record_id=REC-1084`
- `/users.html`
- `/analytics.html`
- `/calendar.html`
- `/settings.html`

## API endpoints

- `GET /api/records`
- `POST /api/records`
- `GET /api/users`
- `POST /api/users/invite`
- `GET /api/calendar/events`
- `GET /api/analytics`
- `GET /health`

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open:

```text
http://127.0.0.1:5000/dashboard.html
```

## Notes

- Data is stored in memory inside `data.py`.
- This keeps the UI behavior close to the provided files while moving the app under a Python backend.
- For production use, the next step would be replacing the in-memory layer with a real database and moving more repeated HTML into shared Jinja templates.
