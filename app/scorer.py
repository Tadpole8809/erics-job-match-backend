"""Score how well a job matches Eric's profile.

Uses Gemini when GEMINI_API_KEY is set. Without a key it falls back to a
simple keyword-overlap score (method="keyword") so the app still works in dev.
"""
import re

from pydantic import ValidationError

from app import gemini
from app.db import now
from app.models import Job, Match, Profile

MAX_DESCRIPTION_CHARS = 6000

PROMPT = """You are a career coach scoring how well a job fits a candidate.

Candidate profile (JSON):
{profile}

Job:
Title: {title}
Company: {company}
Location: {location}
Remote: {remote}
Employment type: {employment_type}
Salary: {salary}
Description:
{description}

Score the fit from 0 to 100, where 100 is an ideal fit. Consider skills,
experience level, target roles, location/remote and the candidate's stated
preferences. Be honest: transferable experience counts, but don't inflate.

Reply with JSON only, in exactly this shape:
{{"score": <int 0-100>, "summary": "<one or two plain sentences>",
  "strengths": ["<short reason he fits>", ...], "gaps": ["<short missing thing>", ...]}}
Keep strengths and gaps to at most 4 items each.
"""


class ScoreError(Exception):
    pass


def score_job(profile: Profile, job: Job) -> Match:
    if gemini.is_configured():
        return score_with_gemini(profile, job)
    return score_with_keywords(profile, job)


def score_with_gemini(profile: Profile, job: Job) -> Match:
    prompt = PROMPT.format(
        profile=profile.model_dump_json(indent=2),
        title=job.title,
        company=job.company,
        location=job.location,
        remote="yes" if job.is_remote else "no / unknown",
        employment_type=job.employment_type or "unknown",
        salary=job.salary or "not listed",
        description=job.description[:MAX_DESCRIPTION_CHARS],
    )
    try:
        data = gemini.generate_json(prompt)
    except gemini.GeminiError as exc:
        raise ScoreError(str(exc)) from exc
    try:
        score = max(0, min(100, int(data.get("score", 0))))
        return Match(
            job_id=job.id,
            score=score,
            summary=str(data.get("summary", "")),
            strengths=[str(s) for s in data.get("strengths", [])][:4],
            gaps=[str(g) for g in data.get("gaps", [])][:4],
            method="gemini",
            created_at=now(),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise ScoreError(f"Gemini's score was in an unexpected format: {data}") from exc


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#.]+", text.lower()))


def score_with_keywords(profile: Profile, job: Job) -> Match:
    """Rough fallback: what share of his skills and target roles appear in the job."""
    job_text = f"{job.title} {job.description}".lower()
    job_words = _words(job_text)

    def found(term: str) -> bool:
        term = term.lower().strip()
        if not term:
            return False
        if " " in term:
            return term in job_text
        return term in job_words

    skills_hit = [s for s in profile.skills if found(s)]
    skills_missing = [s for s in profile.skills if s not in skills_hit]
    role_hit = any(
        _words(role) and _words(role) <= _words(job.title) for role in profile.target_roles
    )

    skill_ratio = len(skills_hit) / len(profile.skills) if profile.skills else 0.0
    score = round(skill_ratio * 70 + (30 if role_hit else 0))

    strengths = [f"Mentions {s}" for s in skills_hit[:3]]
    if role_hit:
        strengths.insert(0, "Title matches a target role")
    return Match(
        job_id=job.id,
        score=max(0, min(100, score)),
        summary=(
            f"Keyword estimate: {len(skills_hit)} of {len(profile.skills)} skills found. "
            "Add GEMINI_API_KEY for a real AI score."
        ),
        strengths=strengths[:4],
        gaps=[f"No mention of {s}" for s in skills_missing[:4]],
        method="keyword",
        created_at=now(),
    )
