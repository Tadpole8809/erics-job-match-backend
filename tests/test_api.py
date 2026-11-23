"""API tests. They use a temporary database and never call real APIs."""
import pytest
from fastapi.testclient import TestClient

from app import fetcher, gemini, main
from app.models import Profile

JSEARCH_SAMPLE = {
    "job_id": "abc123",
    "job_title": "Warehouse Supervisor",
    "employer_name": "Acme Logistics",
    "job_city": "Austin",
    "job_state": "TX",
    "job_country": "US",
    "job_description": "Lead a team of 10. Forklift certification and inventory management required.",
    "job_apply_link": "https://example.com/apply",
    "job_employment_type": "FULLTIME",
    "job_is_remote": False,
    "job_min_salary": 50000,
    "job_max_salary": 65000,
    "job_salary_period": "YEAR",
    "job_posted_at_datetime_utc": "2026-11-20T12:00:00Z",
}

SERPAPI_SAMPLE = {
    "job_id": "eyJqb2IiOiJ4In0=",
    "title": "Inventory Analyst",
    "company_name": "Globex",
    "location": "Anywhere",
    "description": "Excel and inventory management.",
    "detected_extensions": {"posted_at": "3 days ago", "schedule_type": "Full-time", "work_from_home": True},
    "apply_options": [{"title": "Globex Careers", "link": "https://globex.example/jobs/1"}],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    for key in ("SERPAPI_KEY", "JSEARCH_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(key, "")
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def fake_search(monkeypatch):
    def _search(query, location="", source="auto", page_token=None):
        jobs = [fetcher.normalize_jsearch(JSEARCH_SAMPLE), fetcher.normalize_serpapi(SERPAPI_SAMPLE)]
        return "jsearch", jobs, "2"

    monkeypatch.setattr(main.fetcher, "search_jobs", _search)


def test_health(client):
    body = client.get("/health").json()
    assert body["ok"] is True
    assert body["keys"] == {"serpapi": False, "jsearch": False, "gemini": False}


def test_test_page_is_served(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Eric's Job Match" in resp.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_normalizers():
    j = fetcher.normalize_jsearch(JSEARCH_SAMPLE)
    assert j.location == "Austin, TX, US"
    assert j.salary == "$50,000-65,000 / year"
    assert j.employment_type == "Full-time"
    assert j.id == fetcher.make_job_id("jsearch", "abc123")

    s = fetcher.normalize_serpapi(SERPAPI_SAMPLE)
    assert s.is_remote is True
    assert s.apply_url == "https://globex.example/jobs/1"
    assert s.employment_type == "Full-time"


def test_search_without_keys_gives_clear_error(client):
    resp = client.get("/search", params={"q": "supervisor"})
    assert resp.status_code == 502
    assert "SERPAPI_KEY or JSEARCH_KEY" in resp.json()["detail"]


def test_search_stores_jobs(client, fake_search):
    resp = client.get("/search", params={"q": "warehouse"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["jobs"]) == 2
    assert body["next_page_token"] == "2"

    stored = client.get("/jobs").json()
    assert {j["title"] for j in stored} == {"Warehouse Supervisor", "Inventory Analyst"}
    assert client.get("/jobs", params={"q": "globex"}).json()[0]["company"] == "Globex"


def test_match_requires_profile(client, fake_search):
    job_id = client.get("/search", params={"q": "x"}).json()["jobs"][0]["id"]
    resp = client.post("/match", json={"job_ids": [job_id]})
    assert resp.status_code == 400


def test_keyword_match_and_sort(client, fake_search):
    jobs = client.get("/search", params={"q": "x"}).json()["jobs"]
    profile = Profile(skills=["forklift", "inventory management", "Excel"], target_roles=["Warehouse Supervisor"])
    assert client.post("/profile", json=profile.model_dump()).status_code == 200

    resp = client.post("/match", json={"job_ids": [j["id"] for j in jobs]})
    assert resp.status_code == 200
    matches = {m["job_id"]: m for m in resp.json()["matches"]}
    warehouse = next(j for j in jobs if j["title"] == "Warehouse Supervisor")
    assert matches[warehouse["id"]]["method"] == "keyword"
    assert matches[warehouse["id"]]["score"] > 50

    ranked = client.get("/jobs", params={"sort": "score"}).json()
    assert ranked[0]["title"] == "Warehouse Supervisor"
    assert ranked[0]["match"]["score"] >= ranked[1]["match"]["score"]


def test_profile_change_clears_scores(client, fake_search):
    job_id = client.get("/search", params={"q": "x"}).json()["jobs"][0]["id"]
    client.post("/profile", json={"skills": ["forklift"]})
    client.post("/match", json={"job_ids": [job_id]})
    assert client.get(f"/jobs/{job_id}").json()["match"] is not None

    client.post("/profile", json={"skills": ["python"]})
    assert client.get(f"/jobs/{job_id}").json()["match"] is None


def test_save_and_unsave(client, fake_search):
    job_id = client.get("/search", params={"q": "x"}).json()["jobs"][0]["id"]
    resp = client.post(f"/saved/{job_id}", json={"note": "apply Monday"})
    assert resp.json()["saved"] is True
    assert resp.json()["saved_note"] == "apply Monday"
    assert len(client.get("/saved").json()) == 1

    assert client.delete(f"/saved/{job_id}").status_code == 200
    assert client.get("/saved").json() == []
    assert client.delete(f"/saved/{job_id}").status_code == 404
    assert client.post("/saved/nope").status_code == 404


def test_resume_flow_with_fake_gemini(client, monkeypatch):
    replies = iter([
        {
            "profile": {"name": "Eric", "skills": ["forklift"], "target_roles": ["Warehouse Lead"]},
            "follow_up_questions": ["Are you open to remote work?", "What salary are you looking for?"],
        },
        {
            "profile": {"name": "Eric", "skills": ["forklift"], "target_roles": ["Warehouse Lead"],
                        "preferences": ["On-site OK"]},
            "follow_up_questions": ["What salary are you looking for?"],
        },
    ])
    monkeypatch.setattr(gemini, "generate_json", lambda prompt: next(replies))

    resume = b"Eric Example\nWarehouse associate, 5 years. Forklift certified."
    resp = client.post("/profile/resume", files={"file": ("resume.txt", resume, "text/plain")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["has_resume"] is True
    assert len(body["follow_up_questions"]) == 2

    resp = client.post("/profile/answers", json={"answers": {"Are you open to remote work?": "On-site is fine"}})
    body = resp.json()
    assert body["profile"]["preferences"] == ["On-site OK"]
    assert body["follow_up_questions"] == ["What salary are you looking for?"]
    assert body["has_resume"] is True


def test_resume_without_gemini_key(client):
    resp = client.post("/profile/resume-text", json={"text": "A resume long enough to pass validation."})
    assert resp.status_code == 502
    assert "GEMINI_API_KEY" in resp.json()["detail"]


def test_bad_resume_file_type(client):
    resp = client.post("/profile/resume", files={"file": ("resume.docx", b"x" * 50, "application/octet-stream")})
    assert resp.status_code == 400
