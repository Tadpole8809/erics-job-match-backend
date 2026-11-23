# Eric's Job Match — Backend (GEMINI.md)

This repo is the backend for Eric's Job Match app. Eric will continue development on his MacBook using Gemini. Keep everything Gemini-friendly: small files, clear names, plain README instructions, no Claude-specific tooling.

## Architecture
- Acer Predator (backend): Python fetcher + normalizer, Gemini API match scorer, FastAPI REST server, local SQLite database
- MacBook Air & iPhone (frontend): Responsive web app / PWA in app/static/ (plain HTML/CSS/JS, no build step), served by this same server at /, saved to iPhone Home Screen, talks to the API over HTTP / JSON
- Passcode: if APP_PASSCODE is set in .env, every API call needs the X-App-Passcode header (app/auth.py). The app asks once and remembers it
- Hosting: Render, configured in render.yaml (persistent disk at /var/data for SQLite). Pushes to main redeploy automatically. Secrets are set in Render's dashboard, never in the repo
- Job APIs: SerpApi / JSearch
- Single user: Eric only. Open experience — match depends on his resume / profile.

## Planned structure
- app/main.py — FastAPI server, endpoints: GET /jobs, GET /search, POST /match, GET/POST /profile
- app/fetcher.py — SerpApi / JSearch fetch + normalize jobs
- app/scorer.py — Gemini API match scorer (profile/resume vs job)
- app/db.py — SQLite: jobs, profile, matches, saved_jobs
- app/models.py — Pydantic models
- app/static/ — the phone app: index.html, style.css, app.js, sw.js (service worker), manifest.webmanifest, icons/. When changing style.css or app.js, bump ?v= in index.html and CACHE in sw.js
- requirements.txt, .env.example (never commit .env or API keys)

## Rules for Gemini
- Never hardcode API keys or the passcode. Use environment variables from .env: SERPAPI_KEY, JSEARCH_KEY, GEMINI_API_KEY, APP_PASSCODE
- Never commit .env, *.db, or __pycache__
- Profile flow: scan Eric's resume first, extract roles/skills/experience, then ask follow-up questions to fill gaps — do not make him fill a long form blind
- Keep endpoints JSON-only, with CORS enabled for the frontend
- Small, focused commits. Explain what changed in plain language.

## Local dev
- Needs Python 3.10+ (3.12 recommended). macOS ships 3.9, which is too old: install 3.12 and use python3.12 -m venv .venv
- python -m venv .venv, activate it, pip install -r requirements.txt
- Copy .env.example to .env and fill in keys
- Run: uvicorn app.main:app --reload
- App at http://127.0.0.1:8000/ and API docs at http://127.0.0.1:8000/docs
