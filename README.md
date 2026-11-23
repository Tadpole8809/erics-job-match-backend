# erics-job-match-backend

Backend for Eric's Job Match app: FastAPI, a job fetcher (SerpApi / JSearch), a Gemini match scorer, and SQLite.

The frontend (a web app / PWA for MacBook and iPhone) talks to this server over HTTP with JSON. See [GEMINI.md](GEMINI.md) for project rules.

## Setup (Mac)

```bash
python3 -m venv .venv
source .venv/bin/activate
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

- **http://127.0.0.1:8000/** is a simple built-in test page with forms for the whole flow: resume, follow-up questions, profile editing, search, scoring and saving. It's plain HTML and JS in `app/static/` and shows how to call every endpoint. The real frontend can copy it or replace it.
- **http://127.0.0.1:8000/docs** lists every endpoint, with example inputs you can try.

To reach the server from an iPhone on the same Wi-Fi, run `uvicorn app.main:app --host 0.0.0.0 --port 8000` and use the computer's local IP address, for example `http://192.168.1.20:8000`.

## API keys (.env)

| Key | What it's for | Required? |
|---|---|---|
| `SERPAPI_KEY` | Google Jobs search via SerpApi | One of these two |
| `JSEARCH_KEY` | JSearch on RapidAPI | One of these two |
| `GEMINI_API_KEY` | Reading the resume, follow-up questions, AI match scores | Strongly recommended |

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
  config.py    Reads settings from .env
tests/         pytest tests (no API keys needed)
```

## Tests

```bash
pytest
```

The tests don't call any real APIs and don't need keys.
