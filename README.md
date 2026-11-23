# erics-job-match-backend

Eric's Job Match: upload a resume, search jobs, and see which ones fit best. It's a FastAPI server with a job fetcher (SerpApi / JSearch), a Gemini match scorer, and SQLite, plus a phone app (PWA) that installs to the iPhone Home Screen.

The server hosts the app itself at `/`, so there's only one thing to run. See [GEMINI.md](GEMINI.md) for project rules.

## Requirements

**Python 3.10 or newer** (3.12 recommended). Check with `python3 --version`.

Macs come with Python 3.9, which is too old. Install 3.12 first, using either:

- the macOS installer from https://www.python.org/downloads/, or
- Homebrew: `brew install python@3.12`

## Setup (Mac)

```bash
python3.12 -m venv .venv      # use 3.12 here, not the built-in python3
source .venv/bin/activate
python --version              # should say 3.12.x
pip install -r requirements.txt
cp .env.example .env        # then open .env and add your API keys
uvicorn app.main:app --reload
```

## Setup (Windows)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

Then open:

- **http://127.0.0.1:8000/** is the app: Profile (resume and follow-up questions), Search, and My jobs (scores and saved jobs). It's plain HTML, CSS and JS in `app/static/`, with no build step.
- **http://127.0.0.1:8000/docs** lists every API endpoint, with example inputs you can try.

## Using it on the iPhone

1. **Set a passcode.** Put a long `APP_PASSCODE` in `.env` before the server can be reached from anywhere but your own computer. The phone asks for it once and remembers it.
2. **Make the server reachable from the phone.**
   - *Same Wi-Fi (quick test):* run `uvicorn app.main:app --host 0.0.0.0 --port 8000` and open the computer's local IP on the phone, for example `http://192.168.1.20:8000`.
   - *From anywhere (optional, not set up):* the server would have to be hosted online. See "Put it online (Render), optional" below.
3. **Add it to the Home Screen.** In Safari, open the app, tap **Share → Add to Home Screen**, then tap **Add**. It opens full-screen with its own icon, named "Job Match".

Over plain `http://` on Wi-Fi, the app works but can't keep a copy of itself for fast loading. That needs HTTPS, which a cloud host or Tailscale provides.

## Put it online (Render), optional

**Not set up right now.** The app runs locally on the Mac. These steps are here in case you want it reachable from anywhere later.

The repo includes [render.yaml](render.yaml), which tells Render how to build and run the app. It also sets up a disk, so the database survives restarts. That needs a paid plan; check Render's current pricing.

1. Sign in at https://dashboard.render.com with GitHub.
2. Click **New → Blueprint** and pick the `erics-job-match-backend` repo.
3. Render asks for the secret settings. Fill them in:
   - `APP_PASSCODE`: a long passcode, 8 characters or more. The server won't start without one.
   - `GEMINI_API_KEY`, plus `JSEARCH_KEY` and/or `SERPAPI_KEY`. Leave a box empty if you don't use that API.
4. Click **Apply**. The first build takes a few minutes. When it's done, Render shows the app's address, something like `https://erics-job-match.onrender.com`.
5. Open that address on the iPhone in Safari, enter the passcode, then tap **Share → Add to Home Screen**.

After that, every push to `main` redeploys automatically. To change a key or the passcode, go to the service's **Environment** page in Render and save. Render restarts the server for you.

## API keys (.env)

| Key | What it's for | Required? |
|---|---|---|
| `SERPAPI_KEY` | Google Jobs search via SerpApi | One of these two |
| `JSEARCH_KEY` | JSearch on RapidAPI | One of these two |
| `GEMINI_API_KEY` | Reading the resume, follow-up questions, AI match scores | Strongly recommended |
| `APP_PASSCODE` | Locks the app and API behind a passcode | Yes, if the server can be reached from outside your computer |

Without a Gemini key, `/match` still works but gives a rough keyword score (`"method": "keyword"`), and the resume endpoints return an error.

## How the app flow works

1. **Profile.** Upload the resume with `POST /profile/resume`. Gemini pulls out roles, skills and experience, and returns `follow_up_questions` about anything missing.
2. **Follow-ups.** Show the questions, then send the answers with `POST /profile/answers`. Repeat while `follow_up_questions` isn't empty.
3. **Search.** `GET /search?q=...&location=...` fetches fresh jobs and stores them.
4. **Match.** `POST /match` with up to 20 `job_ids` scores each job from 0 to 100, with strengths and gaps.
5. **Browse and save.** `GET /jobs?sort=score` lists stored jobs, and `POST /saved/{id}` bookmarks one.

Changing the profile clears the old scores, because they were based on the old profile.

## Endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | Server is up, and which keys are set |
| GET | `/search?q=&location=&source=auto\|serpapi\|jsearch&page_token=` | Fetch new jobs from a job API |
| GET | `/jobs?q=&saved=&min_score=&sort=recent\|score&limit=&offset=` | Stored jobs, with match info |
| GET | `/jobs/{job_id}` | One job |
| POST | `/match` | `{"job_ids": ["..."], "force": false}` → scores |
| GET | `/profile` | Profile plus open follow-up questions |
| POST | `/profile` | Replace the profile (manual edits) |
| POST | `/profile/resume` | Upload the resume (.pdf or .txt, as form-data field `file`) |
| POST | `/profile/resume-text` | `{"text": "..."}`: paste the resume instead |
| POST | `/profile/answers` | `{"answers": {"question": "answer"}}` |
| GET | `/saved` | Saved jobs |
| POST | `/saved/{job_id}` | Save a job, optional `{"note": "..."}` |
| DELETE | `/saved/{job_id}` | Unsave |

Errors come back as `{"detail": "plain-language message"}` with status 400 (bad input), 404 (not found), or 502 (a job API or Gemini failed).

When `APP_PASSCODE` is set, every endpoint except `/health` needs an `X-App-Passcode` header. Without it, or with the wrong one, you get 401. After 10 wrong tries from the same address, you get 429 for 15 minutes. On the `/docs` page, click **Authorize** and enter the passcode.

## Project layout

```
app/
  main.py      FastAPI server and endpoints
  fetcher.py   SerpApi / JSearch fetch + normalize
  scorer.py    Gemini match scorer (+ keyword fallback)
  profile.py   Resume reading and follow-up questions
  gemini.py    Small Gemini API wrapper (returns JSON)
  db.py        SQLite: jobs, profile, matches, saved_jobs
  models.py    Pydantic models (the JSON shapes)
  auth.py      Passcode check (APP_PASSCODE)
  config.py    Reads settings from .env
  static/      The phone app: index.html, style.css, app.js,
               sw.js (service worker), manifest.webmanifest, icons/
tests/         pytest tests (no API keys needed)
```

## Tests

```bash
pytest
```

The tests don't call any real APIs and don't need keys.
