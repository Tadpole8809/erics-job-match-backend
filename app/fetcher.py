"""Fetch jobs from SerpApi (Google Jobs) or JSearch (RapidAPI) and normalize them.

Both APIs return different shapes; normalize_* turns each into our Job model.
"""
import hashlib

import httpx

from app import config
from app.db import now
from app.models import Job, JobSource

SERPAPI_URL = "https://serpapi.com/search.json"
JSEARCH_URL = "https://jsearch.p.rapidapi.com/search"
JSEARCH_HOST = "jsearch.p.rapidapi.com"
TIMEOUT_SECONDS = 30

# JSearch sends codes like "FULLTIME"; show them the way Google Jobs does.
EMPLOYMENT_TYPES = {
    "FULLTIME": "Full-time",
    "PARTTIME": "Part-time",
    "CONTRACTOR": "Contractor",
    "INTERN": "Internship",
}


class FetchError(Exception):
    """Something went wrong talking to a job API (missing key, bad key, rate limit...)."""


def make_job_id(source: str, external_id: str) -> str:
    return hashlib.sha1(f"{source}:{external_id}".encode()).hexdigest()[:16]


def pick_source(source: str) -> JobSource:
    """'auto' uses JSearch if its key is set, otherwise SerpApi."""
    if source in ("serpapi", "jsearch"):
        return source  # type: ignore[return-value]
    if config.jsearch_key():
        return "jsearch"
    if config.serpapi_key():
        return "serpapi"
    raise FetchError("No job API key set. Add SERPAPI_KEY or JSEARCH_KEY to .env.")


def search_jobs(
    query: str, location: str = "", source: str = "auto", page_token: str | None = None
) -> tuple[JobSource, list[Job], str | None]:
    """Returns (source used, jobs, next_page_token)."""
    chosen = pick_source(source)
    if chosen == "jsearch":
        jobs, next_token = fetch_jsearch(query, location, page_token)
    else:
        jobs, next_token = fetch_serpapi(query, location, page_token)
    return chosen, jobs, next_token


def _check_response(resp: httpx.Response, api_name: str) -> None:
    if resp.status_code in (401, 403):
        raise FetchError(f"{api_name} rejected the API key (HTTP {resp.status_code}). Check .env.")
    if resp.status_code == 429:
        raise FetchError(f"{api_name} rate limit or monthly quota reached. Try again later.")
    if resp.status_code >= 400:
        raise FetchError(f"{api_name} error (HTTP {resp.status_code}): {resp.text[:300]}")


# ---------- JSearch ----------

def fetch_jsearch(query: str, location: str, page_token: str | None) -> tuple[list[Job], str | None]:
    key = config.jsearch_key()
    if not key:
        raise FetchError("JSEARCH_KEY is not set in .env.")
    page = int(page_token) if page_token and page_token.isdigit() else 1
    full_query = f"{query} in {location}" if location else query
    try:
        resp = httpx.get(
            JSEARCH_URL,
            params={"query": full_query, "page": page, "num_pages": 1},
            headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": JSEARCH_HOST},
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise FetchError(f"Could not reach JSearch: {exc}") from exc
    _check_response(resp, "JSearch")
    results = resp.json().get("data") or []
    jobs = [normalize_jsearch(r) for r in results if r.get("job_id")]
    return jobs, (str(page + 1) if jobs else None)


def normalize_jsearch(r: dict) -> Job:
    location_parts = [r.get("job_city"), r.get("job_state"), r.get("job_country")]
    location = ", ".join(p for p in location_parts if p) or (r.get("job_location") or "")

    salary = r.get("job_salary") or ""
    if not salary and (r.get("job_min_salary") or r.get("job_max_salary")):
        low, high = r.get("job_min_salary"), r.get("job_max_salary")
        amount = f"{low:,.0f}-{high:,.0f}" if low and high else f"{(low or high):,.0f}"
        period = (r.get("job_salary_period") or "").lower()
        salary = f"${amount}" + (f" / {period}" if period else "")

    return Job(
        id=make_job_id("jsearch", r["job_id"]),
        source="jsearch",
        external_id=r["job_id"],
        title=r.get("job_title") or "Untitled",
        company=r.get("employer_name") or "",
        location=location,
        description=r.get("job_description") or "",
        apply_url=r.get("job_apply_link") or r.get("job_google_link") or "",
        employment_type=EMPLOYMENT_TYPES.get(r.get("job_employment_type") or "", r.get("job_employment_type") or ""),
        is_remote=bool(r.get("job_is_remote")),
        salary=str(salary),
        posted_at=r.get("job_posted_at_datetime_utc") or "",
        fetched_at=now(),
    )


# ---------- SerpApi (Google Jobs) ----------

def fetch_serpapi(query: str, location: str, page_token: str | None) -> tuple[list[Job], str | None]:
    key = config.serpapi_key()
    if not key:
        raise FetchError("SERPAPI_KEY is not set in .env.")
    params = {"engine": "google_jobs", "q": query, "api_key": key, "hl": "en"}
    if location:
        params["location"] = location
    if page_token:
        params["next_page_token"] = page_token
    try:
        resp = httpx.get(SERPAPI_URL, params=params, timeout=TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        raise FetchError(f"Could not reach SerpApi: {exc}") from exc
    _check_response(resp, "SerpApi")
    body = resp.json()
    if body.get("error"):
        # SerpApi reports "no results" as an error; treat it as an empty page.
        if "hasn't returned any results" in body["error"]:
            return [], None
        raise FetchError(f"SerpApi error: {body['error']}")
    jobs = [normalize_serpapi(r) for r in body.get("jobs_results") or [] if r.get("job_id")]
    next_token = (body.get("serpapi_pagination") or {}).get("next_page_token")
    return jobs, next_token


def normalize_serpapi(r: dict) -> Job:
    ext = r.get("detected_extensions") or {}
    apply_options = r.get("apply_options") or []
    apply_url = apply_options[0].get("link", "") if apply_options else r.get("share_link", "")
    location = r.get("location") or ""
    return Job(
        id=make_job_id("serpapi", r["job_id"]),
        source="serpapi",
        external_id=r["job_id"],
        title=r.get("title") or "Untitled",
        company=r.get("company_name") or "",
        location=location,
        description=r.get("description") or "",
        apply_url=apply_url,
        employment_type=ext.get("schedule_type") or "",
        is_remote=bool(ext.get("work_from_home")) or "remote" in location.lower(),
        salary=ext.get("salary") or "",
        posted_at=ext.get("posted_at") or "",
        fetched_at=now(),
    )
