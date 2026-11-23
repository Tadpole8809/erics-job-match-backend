"""SQLite storage: jobs, profile, matches, saved_jobs.

Uses Python's built-in sqlite3 module. The database file is created
automatically (path from DB_PATH in .env, default jobmatch.db).
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from app import config
from app.models import Job, JobWithMatch, Match, Profile, ProfileResponse

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    apply_url TEXT NOT NULL DEFAULT '',
    employment_type TEXT NOT NULL DEFAULT '',
    is_remote INTEGER NOT NULL DEFAULT 0,
    salary TEXT NOT NULL DEFAULT '',
    posted_at TEXT NOT NULL DEFAULT '',
    fetched_at TEXT NOT NULL
);

-- Single user, so the profile table only ever has one row (id = 1).
CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL,
    resume_text TEXT NOT NULL DEFAULT '',
    follow_up_questions TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    score INTEGER NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    strengths TEXT NOT NULL DEFAULT '[]',
    gaps TEXT NOT NULL DEFAULT '[]',
    method TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_jobs (
    job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    note TEXT NOT NULL DEFAULT '',
    saved_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    conn = sqlite3.connect(config.db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


# ---------- jobs ----------

JOB_FIELDS = [
    "id", "source", "external_id", "title", "company", "location", "description",
    "apply_url", "employment_type", "is_remote", "salary", "posted_at", "fetched_at",
]


def upsert_jobs(jobs: list[Job]) -> None:
    """Insert new jobs, or refresh existing ones (keeps their matches/saves)."""
    placeholders = ", ".join("?" for _ in JOB_FIELDS)
    updates = ", ".join(f"{f} = excluded.{f}" for f in JOB_FIELDS if f != "id")
    sql = (
        f"INSERT INTO jobs ({', '.join(JOB_FIELDS)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}"
    )
    with connect() as conn:
        for job in jobs:
            row = job.model_dump()
            row["is_remote"] = int(job.is_remote)
            conn.execute(sql, [row[f] for f in JOB_FIELDS])


_JOB_SELECT = """
SELECT j.*,
       m.score AS m_score, m.summary AS m_summary, m.strengths AS m_strengths,
       m.gaps AS m_gaps, m.method AS m_method, m.created_at AS m_created_at,
       s.job_id IS NOT NULL AS is_saved, COALESCE(s.note, '') AS saved_note
FROM jobs j
LEFT JOIN matches m ON m.job_id = j.id
LEFT JOIN saved_jobs s ON s.job_id = j.id
"""


def _row_to_job(row: sqlite3.Row) -> JobWithMatch:
    data = {f: row[f] for f in JOB_FIELDS}
    data["is_remote"] = bool(data["is_remote"])
    match = None
    if row["m_score"] is not None:
        match = Match(
            job_id=row["id"],
            score=row["m_score"],
            summary=row["m_summary"],
            strengths=json.loads(row["m_strengths"]),
            gaps=json.loads(row["m_gaps"]),
            method=row["m_method"],
            created_at=row["m_created_at"],
        )
    return JobWithMatch(**data, match=match, saved=bool(row["is_saved"]), saved_note=row["saved_note"])


def get_job(job_id: str) -> JobWithMatch | None:
    with connect() as conn:
        row = conn.execute(_JOB_SELECT + " WHERE j.id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def get_jobs_by_ids(job_ids: list[str]) -> list[JobWithMatch]:
    """Return jobs in the same order as job_ids (missing ids are skipped)."""
    if not job_ids:
        return []
    marks = ", ".join("?" for _ in job_ids)
    with connect() as conn:
        rows = conn.execute(_JOB_SELECT + f" WHERE j.id IN ({marks})", job_ids).fetchall()
    by_id = {row["id"]: _row_to_job(row) for row in rows}
    return [by_id[i] for i in job_ids if i in by_id]


def list_jobs(
    search: str = "",
    saved_only: bool = False,
    min_score: int | None = None,
    sort: str = "recent",
    limit: int = 50,
    offset: int = 0,
) -> list[JobWithMatch]:
    where, params = [], []
    if search:
        where.append("(j.title LIKE ? OR j.company LIKE ? OR j.location LIKE ?)")
        params += [f"%{search}%"] * 3
    if saved_only:
        where.append("s.job_id IS NOT NULL")
    if min_score is not None:
        where.append("m.score >= ?")
        params.append(min_score)
    sql = _JOB_SELECT
    if where:
        sql += " WHERE " + " AND ".join(where)
    if sort == "score":
        sql += " ORDER BY m.score IS NULL, m.score DESC, j.fetched_at DESC"
    else:
        sql += " ORDER BY j.fetched_at DESC, j.posted_at DESC"
    sql += " LIMIT ? OFFSET ?"
    params += [limit, offset]
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_job(row) for row in rows]


# ---------- profile ----------

def get_profile() -> ProfileResponse:
    with connect() as conn:
        row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    if not row:
        return ProfileResponse(profile=Profile())
    return ProfileResponse(
        profile=Profile.model_validate_json(row["data"]),
        has_resume=bool(row["resume_text"]),
        follow_up_questions=json.loads(row["follow_up_questions"]),
        updated_at=row["updated_at"],
    )


def get_resume_text() -> str:
    with connect() as conn:
        row = conn.execute("SELECT resume_text FROM profile WHERE id = 1").fetchone()
    return row["resume_text"] if row else ""


def save_profile(
    profile: Profile,
    follow_up_questions: list[str] | None = None,
    resume_text: str | None = None,
) -> ProfileResponse:
    """Save the profile. Old match scores are cleared, since they used the old profile.

    Passing None for follow_up_questions or resume_text keeps the stored value.
    """
    with connect() as conn:
        existing = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
        if resume_text is None:
            resume_text = existing["resume_text"] if existing else ""
        if follow_up_questions is None:
            follow_up_questions = json.loads(existing["follow_up_questions"]) if existing else []
        conn.execute(
            "INSERT INTO profile (id, data, resume_text, follow_up_questions, updated_at) "
            "VALUES (1, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data, resume_text = excluded.resume_text, "
            "follow_up_questions = excluded.follow_up_questions, updated_at = excluded.updated_at",
            (profile.model_dump_json(), resume_text, json.dumps(follow_up_questions), now()),
        )
        conn.execute("DELETE FROM matches")
    return get_profile()


# ---------- matches ----------

def save_match(match: Match) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO matches (job_id, score, summary, strengths, gaps, method, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(job_id) DO UPDATE SET score = excluded.score, summary = excluded.summary, "
            "strengths = excluded.strengths, gaps = excluded.gaps, method = excluded.method, "
            "created_at = excluded.created_at",
            (
                match.job_id, match.score, match.summary, json.dumps(match.strengths),
                json.dumps(match.gaps), match.method, match.created_at or now(),
            ),
        )


# ---------- saved jobs ----------

def save_job(job_id: str, note: str = "") -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO saved_jobs (job_id, note, saved_at) VALUES (?, ?, ?) "
            "ON CONFLICT(job_id) DO UPDATE SET note = excluded.note",
            (job_id, note, now()),
        )


def unsave_job(job_id: str) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM saved_jobs WHERE job_id = ?", (job_id,))
    return cur.rowcount > 0
