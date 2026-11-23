"""Pydantic models: the JSON shapes the API sends and receives."""
from typing import Literal

from pydantic import BaseModel, Field

JobSource = Literal["serpapi", "jsearch"]


class Job(BaseModel):
    """A job listing, normalized so SerpApi and JSearch look the same."""

    id: str  # our own stable id (hash of source + external_id)
    source: JobSource
    external_id: str
    title: str
    company: str = ""
    location: str = ""
    description: str = ""
    apply_url: str = ""
    employment_type: str = ""
    is_remote: bool = False
    salary: str = ""
    posted_at: str = ""
    fetched_at: str = ""


class Match(BaseModel):
    """How well a job fits Eric's profile."""

    job_id: str
    score: int = Field(ge=0, le=100)
    summary: str = ""
    strengths: list[str] = []
    gaps: list[str] = []
    method: Literal["gemini", "keyword"]
    created_at: str = ""


class JobWithMatch(Job):
    """A job plus its match score (if scored yet) and saved status."""

    match: Match | None = None
    saved: bool = False
    saved_note: str = ""


class SearchResponse(BaseModel):
    source: JobSource
    query: str
    location: str
    jobs: list[JobWithMatch]
    # Pass this back as ?page_token=... to get the next page. None = no more.
    next_page_token: str | None = None


class Experience(BaseModel):
    title: str = ""
    company: str = ""
    start: str = ""
    end: str = ""
    summary: str = ""


class Profile(BaseModel):
    """Eric's profile, built from his resume plus follow-up answers."""

    name: str = ""
    headline: str = ""
    location: str = ""
    target_roles: list[str] = []
    skills: list[str] = []
    experience: list[Experience] = []
    education: list[str] = []
    years_experience: float | None = None
    preferences: list[str] = []  # e.g. "Remote only", "Full-time", "$70k+"
    notes: str = ""

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "name": "Eric",
                "headline": "Warehouse lead with 5 years of experience",
                "location": "Austin, TX",
                "target_roles": ["Warehouse Supervisor", "Inventory Analyst"],
                "skills": ["Forklift", "Inventory management", "Excel", "Team leadership"],
                "experience": [{"title": "Warehouse Lead", "company": "Acme Logistics",
                                "start": "2020", "end": "2025", "summary": "Led a team of 8"}],
                "education": ["High school diploma", "OSHA 10"],
                "years_experience": 5,
                "preferences": ["Full-time", "On-site OK", "$55k+"],
                "notes": "",
            }]
        }
    }

    def is_empty(self) -> bool:
        return not (self.skills or self.target_roles or self.experience or self.headline)


class ProfileResponse(BaseModel):
    profile: Profile
    has_resume: bool = False
    follow_up_questions: list[str] = []
    updated_at: str = ""


class ResumeTextRequest(BaseModel):
    text: str = Field(
        min_length=20,
        examples=["Eric Example\nWarehouse Lead, Acme Logistics (2020-2025)\n- Led a team of 8\n- Forklift certified"],
    )


class AnswersRequest(BaseModel):
    """Answers to follow-up questions: {"question text": "Eric's answer"}."""

    answers: dict[str, str] = Field(
        min_length=1,
        examples=[{"Are you open to remote work?": "On-site or hybrid is fine", "What salary are you looking for?": "$55k+"}],
    )


class MatchRequest(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=20, examples=[["3f2a9c1b7d4e8a60"]])
    force: bool = False  # True = re-score even if a cached score exists


class MatchResponse(BaseModel):
    matches: list[Match]


class SaveRequest(BaseModel):
    note: str = Field("", examples=["Apply Monday"])
