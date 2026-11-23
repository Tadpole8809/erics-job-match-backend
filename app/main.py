"""FastAPI server for Eric's Job Match.

Run:  uvicorn app.main:app --reload
Test page: http://127.0.0.1:8000/       (simple forms for the whole flow)
API docs:  http://127.0.0.1:8000/docs   (try every endpoint from the browser)
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config, db, fetcher, gemini, profile as profile_flow, scorer
from app.auth import require_passcode
from app.models import (
    AnswersRequest,
    JobWithMatch,
    MatchRequest,
    MatchResponse,
    Profile,
    ProfileResponse,
    ResumeTextRequest,
    SaveRequest,
    SearchResponse,
)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Safety net for the online server: never run open to the internet by accident.
    if config.passcode_mandatory() and len(config.app_passcode()) < 8:
        raise RuntimeError(
            "REQUIRE_PASSCODE is on, so APP_PASSCODE must be set (8+ characters). "
            "Add it in the host's environment settings."
        )
    db.init_db()
    yield


app = FastAPI(
    title="Eric's Job Match API",
    description="Search jobs, build Eric's profile from his resume, and score job matches.",
    version="0.2.0",
    lifespan=lifespan,
    # Every endpoint checks the passcode (if APP_PASSCODE is set). See app/auth.py.
    dependencies=[Depends(require_passcode)],
)

origins = config.cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials="*" not in origins,  # browsers forbid credentials with "*"
    allow_methods=["*"],
    allow_headers=["*"],
)

# The phone app (app/static): a PWA that can be added to the iPhone Home Screen.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest() -> FileResponse:
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    # Served from the root so it can manage the whole app; never cached by the browser.
    return FileResponse(
        STATIC_DIR / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"}
    )


def _require_job(job_id: str) -> JobWithMatch:
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, f"No job with id {job_id}. Run a search first.")
    return job


# ---------- health ----------

@app.get("/health", tags=["meta"])
def health() -> dict:
    """Quick check that the server is up, and which API keys are configured."""
    return {
        "ok": True,
        "passcode_required": bool(config.app_passcode()),
        "keys": {
            "serpapi": bool(config.serpapi_key()),
            "jsearch": bool(config.jsearch_key()),
            "gemini": gemini.is_configured(),
        },
    }


# ---------- search & jobs ----------

@app.get("/search", response_model=SearchResponse, tags=["jobs"])
def search(
    q: str = Query(..., min_length=1, description="What to search for, e.g. 'warehouse supervisor'"),
    location: str = Query("", description="City/state, e.g. 'Austin, TX'. Empty = anywhere."),
    source: str = Query("auto", pattern="^(auto|serpapi|jsearch)$"),
    page_token: str | None = Query(None, description="next_page_token from a previous search"),
) -> SearchResponse:
    """Fetch fresh jobs from a job API, store them, and return them."""
    try:
        used, jobs, next_token = fetcher.search_jobs(q, location, source, page_token)
    except fetcher.FetchError as exc:
        raise HTTPException(502, str(exc)) from exc
    db.upsert_jobs(jobs)
    stored = db.get_jobs_by_ids([j.id for j in jobs])
    return SearchResponse(source=used, query=q, location=location, jobs=stored, next_page_token=next_token)


@app.get("/jobs", response_model=list[JobWithMatch], tags=["jobs"])
def list_jobs(
    q: str = Query("", description="Filter stored jobs by title, company or location"),
    saved: bool = Query(False, description="Only saved jobs"),
    min_score: int | None = Query(None, ge=0, le=100, description="Only jobs scored at least this"),
    sort: str = Query("recent", pattern="^(recent|score)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[JobWithMatch]:
    """Jobs already stored in the database (from earlier searches)."""
    return db.list_jobs(q, saved, min_score, sort, limit, offset)


@app.get("/jobs/{job_id}", response_model=JobWithMatch, tags=["jobs"])
def get_job(job_id: str) -> JobWithMatch:
    return _require_job(job_id)


# ---------- matching ----------

@app.post("/match", response_model=MatchResponse, tags=["matching"])
def match(req: MatchRequest) -> MatchResponse:
    """Score up to 20 jobs against Eric's profile. Cached scores are reused unless force=true."""
    current = db.get_profile()
    if current.profile.is_empty():
        raise HTTPException(400, "Set up the profile first (POST /profile/resume).")

    jobs = [_require_job(job_id) for job_id in req.job_ids]
    results = []
    for job in jobs:
        if job.match and not req.force:
            results.append(job.match)
            continue
        try:
            result = scorer.score_job(current.profile, job)
        except scorer.ScoreError as exc:
            raise HTTPException(502, str(exc)) from exc
        db.save_match(result)
        results.append(result)
    return MatchResponse(matches=results)


# ---------- profile ----------

@app.get("/profile", response_model=ProfileResponse, tags=["profile"])
def get_profile() -> ProfileResponse:
    """Eric's profile plus any follow-up questions still waiting for answers."""
    return db.get_profile()


@app.post("/profile", response_model=ProfileResponse, tags=["profile"])
def set_profile(new_profile: Profile) -> ProfileResponse:
    """Replace the profile directly (e.g. after Eric edits it in the app)."""
    return db.save_profile(new_profile)


def _analyze_and_save(resume_text: str) -> ProfileResponse:
    try:
        extracted, questions = profile_flow.analyze_resume(resume_text)
    except profile_flow.ProfileError as exc:
        raise HTTPException(502, str(exc)) from exc
    return db.save_profile(extracted, follow_up_questions=questions, resume_text=resume_text)


@app.post("/profile/resume", response_model=ProfileResponse, tags=["profile"])
async def upload_resume(file: UploadFile = File(..., description="Resume as .pdf or .txt")) -> ProfileResponse:
    """Step 1: upload the resume. Gemini builds the profile and returns follow-up questions."""
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Resume file is too big (max 5 MB).")
    try:
        text = profile_flow.extract_text(file.filename or "", data)
    except profile_flow.ProfileError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _analyze_and_save(text)


@app.post("/profile/resume-text", response_model=ProfileResponse, tags=["profile"])
def paste_resume(req: ResumeTextRequest) -> ProfileResponse:
    """Step 1 (alternative): paste the resume as plain text instead of uploading a file."""
    return _analyze_and_save(req.text)


@app.post("/profile/answers", response_model=ProfileResponse, tags=["profile"])
def answer_questions(req: AnswersRequest) -> ProfileResponse:
    """Step 2: send answers to follow-up questions. Returns the updated profile and any new questions."""
    current = db.get_profile()
    try:
        updated, questions = profile_flow.apply_answers(
            current.profile, current.follow_up_questions, req.answers
        )
    except profile_flow.ProfileError as exc:
        raise HTTPException(502, str(exc)) from exc
    return db.save_profile(updated, follow_up_questions=questions)


# ---------- saved jobs ----------

@app.get("/saved", response_model=list[JobWithMatch], tags=["saved"])
def list_saved() -> list[JobWithMatch]:
    return db.list_jobs(saved_only=True, limit=200)


@app.post("/saved/{job_id}", response_model=JobWithMatch, tags=["saved"])
def save_job(job_id: str, req: SaveRequest | None = None) -> JobWithMatch:
    """Save a job (optionally with a note). Saving again updates the note."""
    _require_job(job_id)
    db.save_job(job_id, req.note if req else "")
    return _require_job(job_id)


@app.delete("/saved/{job_id}", tags=["saved"])
def unsave_job(job_id: str) -> dict:
    if not db.unsave_job(job_id):
        raise HTTPException(404, "That job isn't saved.")
    return {"ok": True}
