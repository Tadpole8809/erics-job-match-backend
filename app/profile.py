"""Profile flow: read Eric's resume, extract a profile, then ask follow-up questions.

1. analyze_resume(text)      -> profile + follow-up questions about gaps
2. apply_answers(...)        -> updated profile + any remaining questions
"""
import io
import json

from pydantic import ValidationError

from app import gemini
from app.models import Profile

MAX_RESUME_CHARS = 15000

PROFILE_SHAPE = """{
  "name": "", "headline": "", "location": "",
  "target_roles": [], "skills": [],
  "experience": [{"title": "", "company": "", "start": "", "end": "", "summary": ""}],
  "education": [], "years_experience": null, "preferences": [], "notes": ""
}"""

RESUME_PROMPT = """You are helping a job seeker build a profile used to match him to jobs.

Read his resume below and extract a profile. Then write 3 to 6 short, friendly
follow-up questions about important things the resume doesn't make clear, such
as: what roles he wants next, remote/hybrid/on-site, willingness to relocate,
salary expectations, full-time vs contract, and skills he has but didn't list.
Only ask about things that are actually missing or unclear.

For target_roles, infer reasonable roles from his experience if he didn't state any.
Use "preferences" for short statements like "Remote only" or "Full-time".

Reply with JSON only, in exactly this shape:
{{"profile": {shape}, "follow_up_questions": ["..."]}}

Resume:
{resume}
"""

ANSWERS_PROMPT = """You are updating a job seeker's profile with his answers to follow-up questions.

Current profile (JSON):
{profile}

Questions and his answers:
{answers}

Questions he hasn't answered yet:
{remaining}

Merge the answers into the profile (add target roles, skills, preferences,
notes, etc.). Keep everything already in the profile unless an answer changes it.
Then list any follow-up questions that still matter: the unanswered ones above,
plus at most 2 new ones if an answer raised something important. It's fine to
return an empty list.

Reply with JSON only, in exactly this shape:
{{"profile": {shape}, "follow_up_questions": ["..."]}}
"""


class ProfileError(Exception):
    pass


def extract_text(filename: str, data: bytes) -> str:
    """Get plain text from an uploaded resume (.pdf, .txt or .md)."""
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            raise ProfileError(f"Couldn't read that PDF: {exc}") from exc
    elif name.endswith((".txt", ".md")):
        text = data.decode("utf-8", errors="replace")
    else:
        raise ProfileError("Upload the resume as a .pdf or .txt file (or paste the text).")
    text = text.strip()
    if len(text) < 20:
        raise ProfileError("Couldn't find any text in that file. If it's a scanned PDF, paste the text instead.")
    return text


def _parse(data: dict) -> tuple[Profile, list[str]]:
    try:
        profile = Profile.model_validate(data.get("profile") or {})
    except ValidationError as exc:
        raise ProfileError(f"Gemini returned a profile in an unexpected format: {exc}") from exc
    questions = [str(q) for q in data.get("follow_up_questions") or [] if str(q).strip()]
    return profile, questions


def analyze_resume(resume_text: str) -> tuple[Profile, list[str]]:
    prompt = RESUME_PROMPT.format(shape=PROFILE_SHAPE, resume=resume_text[:MAX_RESUME_CHARS])
    try:
        return _parse(gemini.generate_json(prompt))
    except gemini.GeminiError as exc:
        raise ProfileError(str(exc)) from exc


def apply_answers(
    profile: Profile, open_questions: list[str], answers: dict[str, str]
) -> tuple[Profile, list[str]]:
    answered = {q: a for q, a in answers.items() if a.strip()}
    remaining = [q for q in open_questions if q not in answered]
    prompt = ANSWERS_PROMPT.format(
        shape=PROFILE_SHAPE,
        profile=profile.model_dump_json(indent=2),
        answers=json.dumps(answered, indent=2),
        remaining=json.dumps(remaining, indent=2),
    )
    try:
        return _parse(gemini.generate_json(prompt))
    except gemini.GeminiError as exc:
        raise ProfileError(str(exc)) from exc
