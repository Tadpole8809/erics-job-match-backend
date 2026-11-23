// Built-in test page for Eric's Job Match. Plain JavaScript, no build step.
// Every call goes through api(), which makes this a handy reference for the real frontend.

const $ = (sel) => document.querySelector(sel);
const LIST_FIELDS = ["target_roles", "skills", "preferences", "education"];

let currentProfile = null;
let searchState = { jobs: [], nextToken: null, params: null };

// ---------- passcode ----------
// The passcode is remembered on this device so Eric only types it once.

const PASSCODE_KEY = "jobmatch-passcode";

function getPasscode() {
  try { return localStorage.getItem(PASSCODE_KEY) || ""; } catch { return ""; }
}
function setPasscode(value) {
  try {
    if (value) localStorage.setItem(PASSCODE_KEY, value);
    else localStorage.removeItem(PASSCODE_KEY);
  } catch { /* private mode: it just won't be remembered */ }
}

class LockedError extends Error {}

function showLock(message) {
  $("#lock").hidden = false;
  $("#lock-error").hidden = !message;
  $("#lock-error").textContent = message || "";
  setTimeout(() => $("#lock-input").focus(), 50);
}

$("#lock-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  setPasscode($("#lock-input").value.trim());
  $("#lock-input").value = "";
  await start();
});

// ---------- helpers ----------

async function api(method, path, body) {
  const opts = { method, headers: {} };
  const passcode = getPasscode();
  if (passcode) opts.headers["X-App-Passcode"] = passcode;
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let resp;
  try {
    resp = await fetch(path, opts);
  } catch {
    throw new Error("Can't reach the server. Check that it's running and that you're connected.");
  }
  const data = await resp.json().catch(() => ({}));
  if (resp.status === 401) {
    setPasscode("");
    showLock(passcode ? "That passcode didn't work. Try again." : "");
    throw new LockedError("Passcode required.");
  }
  if (!resp.ok) {
    let msg = data.detail || `Request failed (${resp.status})`;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join("; ");
    throw new Error(msg);
  }
  return data;
}

function esc(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

let toastTimer;
function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = "toast" + (isError ? " error" : "");
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), isError ? 6000 : 2500);
}

// Disable a button and show a working label while an async task runs.
async function busy(button, label, task) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = label;
  try {
    return await task();
  } catch (err) {
    if (!(err instanceof LockedError)) toast(err.message, true);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

const splitList = (text) => text.split(",").map((s) => s.trim()).filter(Boolean);

// ---------- tabs ----------

function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) => (p.hidden = p.id !== `tab-${name}`));
  if (name === "jobs") loadJobs();
}
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));

// ---------- key status ----------

async function loadHealth() {
  try {
    const { keys } = await api("GET", "/health");
    const labels = { gemini: "Gemini", jsearch: "JSearch", serpapi: "SerpApi" };
    $("#keys").innerHTML = Object.entries(labels)
      .map(([k, label]) => `<span class="key ${keys[k] ? "on" : ""}">${keys[k] ? "✓" : "✗"} ${label}</span>`)
      .join("");
  } catch {
    $("#keys").innerHTML = `<span class="key">Server not reachable</span>`;
  }
}

// ---------- profile ----------

function fillProfile(resp) {
  currentProfile = resp.profile;
  const form = $("#profile-form");
  for (const [key, value] of Object.entries(resp.profile)) {
    const field = form.elements[key];
    if (!field) continue;
    field.value = Array.isArray(value) ? value.join(", ") : value ?? "";
  }
  const exp = resp.profile.experience || [];
  $("#experience").innerHTML = exp.length
    ? "<h3>Experience (from resume)</h3>" +
      exp.map((e) => `<div class="exp"><strong>${esc(e.title)}</strong>${e.company ? " · " + esc(e.company) : ""}
        <span class="muted">${esc([e.start, e.end].filter(Boolean).join(" – "))}</span>
        ${e.summary ? `<div class="muted">${esc(e.summary)}</div>` : ""}</div>`).join("")
    : "";
  renderQuestions(resp.follow_up_questions || []);
  renderRoleChips();
}

function renderQuestions(questions) {
  $("#questions-card").hidden = questions.length === 0;
  $("#questions").innerHTML = questions
    .map((q, i) => `<div class="question"><label>${esc(q)}
        <input data-question="${esc(q)}" id="answer-${i}" placeholder="Type an answer, or leave blank to skip"></label></div>`)
    .join("");
}

function renderRoleChips() {
  const roles = currentProfile?.target_roles || [];
  $("#role-chips").innerHTML = roles.length
    ? `<span class="hint">Quick search:</span>` +
      roles.map((r) => `<button type="button" class="chip" data-role="${esc(r)}">${esc(r)}</button>`).join("")
    : "";
}

$("#role-chips").addEventListener("click", (e) => {
  const role = e.target.dataset?.role;
  if (!role) return;
  $("#q").value = role;
  if (!$("#location").value && currentProfile?.location) $("#location").value = currentProfile.location;
  $("#search-form").requestSubmit();
});

$("#resume-file-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const file = $("#resume-file").files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  busy(e.submitter, "Reading resume…", async () => {
    fillProfile(await api("POST", "/profile/resume", form));
    toast("Resume read. Check the questions below.");
  });
});

$("#resume-text-form").addEventListener("submit", (e) => {
  e.preventDefault();
  busy(e.submitter, "Reading resume…", async () => {
    fillProfile(await api("POST", "/profile/resume-text", { text: $("#resume-text").value }));
    toast("Resume read. Check the questions below.");
  });
});

$("#answers-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const answers = {};
  document.querySelectorAll("[data-question]").forEach((input) => {
    if (input.value.trim()) answers[input.dataset.question] = input.value.trim();
  });
  if (Object.keys(answers).length === 0) return toast("Answer at least one question first.", true);
  busy(e.submitter, "Updating profile…", async () => {
    fillProfile(await api("POST", "/profile/answers", { answers }));
    toast("Profile updated.");
  });
});

$("#profile-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const form = e.target.elements;
  const profile = { ...(currentProfile || {}) };
  for (const key of ["name", "location", "headline", "notes"]) profile[key] = form[key].value.trim();
  for (const key of LIST_FIELDS) profile[key] = splitList(form[key].value);
  profile.years_experience = form.years_experience.value === "" ? null : Number(form.years_experience.value);
  busy(e.submitter, "Saving…", async () => {
    fillProfile(await api("POST", "/profile", profile));
    toast("Profile saved.");
  });
});

// ---------- job cards ----------

function scoreBadge(match) {
  if (!match) return "";
  const level = match.score >= 70 ? "good" : match.score >= 45 ? "ok" : "low";
  return `<div class="score ${level}" title="${match.method === "keyword" ? "Keyword estimate" : "Gemini score"}">
    ${match.score}<small>${match.method === "keyword" ? "est." : "match"}</small></div>`;
}

function jobCard(job) {
  const meta = [job.company, job.location, job.is_remote ? "Remote" : "", job.employment_type, job.salary]
    .filter(Boolean).map(esc).join(" · ");
  const m = job.match;
  const matchHtml = m
    ? `<p class="match-text">${esc(m.summary)}</p>
       ${m.strengths.length ? `<ul class="match-list">${m.strengths.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}
       ${m.gaps.length ? `<ul class="match-list gaps">${m.gaps.map((g) => `<li>${esc(g)}</li>`).join("")}</ul>` : ""}`
    : "";
  return `<article class="job" data-id="${esc(job.id)}">
    <div class="job-head">
      <div><div class="job-title">${esc(job.title)}</div><div class="job-meta">${meta}</div>
        ${job.posted_at ? `<div class="job-meta">Posted ${esc(job.posted_at.slice(0, 10))}</div>` : ""}</div>
      ${scoreBadge(m)}
    </div>
    ${matchHtml}
    <div class="job-actions">
      <button class="small secondary" data-action="score">${m ? "Re-score" : "Score match"}</button>
      <button class="small secondary" data-action="save">${job.saved ? "★ Saved" : "☆ Save"}</button>
      ${job.apply_url ? `<a href="${esc(job.apply_url)}" target="_blank" rel="noopener">Apply ↗</a>` : ""}
    </div>
    ${job.description ? `<details><summary>Description</summary><p>${esc(job.description)}</p></details>` : ""}
  </article>`;
}

function renderList(container, jobs, emptyText) {
  container.innerHTML = jobs.length ? jobs.map(jobCard).join("") : `<div class="empty">${emptyText}</div>`;
}

// One click handler for score/save buttons in both result lists.
async function handleJobAction(e, jobs, rerender) {
  const button = e.target.closest("button[data-action]");
  if (!button) return;
  const id = button.closest(".job").dataset.id;
  const job = jobs.find((j) => j.id === id);
  if (!job) return;

  if (button.dataset.action === "score") {
    await busy(button, "Scoring…", async () => {
      const { matches } = await api("POST", "/match", { job_ids: [id], force: Boolean(job.match) });
      job.match = matches[0];
      rerender();
    });
  } else {
    await busy(button, "…", async () => {
      if (job.saved) {
        await api("DELETE", `/saved/${id}`);
        job.saved = false;
      } else {
        Object.assign(job, await api("POST", `/saved/${id}`, {}));
      }
      rerender();
    });
  }
}

// ---------- search ----------

function renderSearch() {
  renderList($("#search-results"), searchState.jobs, "No jobs found. Try different words or a wider location.");
  $("#search-bar").hidden = searchState.jobs.length === 0;
  $("#search-count").textContent = `${searchState.jobs.length} jobs`;
  $("#load-more").hidden = !searchState.nextToken;
}

async function runSearch(append) {
  const params = new URLSearchParams(searchState.params);
  if (append && searchState.nextToken) params.set("page_token", searchState.nextToken);
  const data = await api("GET", `/search?${params}`);
  searchState.jobs = append ? searchState.jobs.concat(data.jobs) : data.jobs;
  searchState.nextToken = data.next_page_token;
  renderSearch();
}

$("#search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  searchState.params = { q: $("#q").value.trim(), location: $("#location").value.trim(), source: $("#source").value };
  const button = e.submitter || $("#search-form button[type=submit]");
  busy(button, "Searching…", () => runSearch(false));
});

$("#load-more").addEventListener("click", (e) => busy(e.target, "Loading…", () => runSearch(true)));
$("#search-results").addEventListener("click", (e) => handleJobAction(e, searchState.jobs, renderSearch));

$("#score-all").addEventListener("click", (e) => {
  const unscored = searchState.jobs.filter((j) => !j.match).map((j) => j.id);
  if (unscored.length === 0) return toast("Everything here is already scored.");
  busy(e.target, "Scoring…", async () => {
    // The API takes up to 20 jobs per call.
    for (let i = 0; i < unscored.length; i += 20) {
      const { matches } = await api("POST", "/match", { job_ids: unscored.slice(i, i + 20) });
      for (const m of matches) {
        const job = searchState.jobs.find((j) => j.id === m.job_id);
        if (job) job.match = m;
      }
      renderSearch();
    }
    searchState.jobs.sort((a, b) => (b.match?.score ?? -1) - (a.match?.score ?? -1));
    renderSearch();
  });
});

// ---------- stored jobs ----------

let storedJobs = [];
function renderStored() {
  renderList($("#jobs-results"), storedJobs, "No jobs yet. Run a search first.");
}

async function loadJobs() {
  const params = new URLSearchParams({
    q: $("#jobs-filter").value.trim(),
    sort: $("#jobs-sort").value,
    saved: $("#jobs-saved").checked,
    limit: 100,
  });
  try {
    storedJobs = await api("GET", `/jobs?${params}`);
    renderStored();
  } catch (err) {
    if (!(err instanceof LockedError)) toast(err.message, true);
  }
}

let filterTimer;
$("#jobs-filter").addEventListener("input", () => {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(loadJobs, 250);
});
$("#jobs-sort").addEventListener("change", loadJobs);
$("#jobs-saved").addEventListener("change", loadJobs);
$("#jobs-results").addEventListener("click", (e) => handleJobAction(e, storedJobs, renderStored));

// ---------- start ----------

async function start() {
  loadHealth();
  try {
    fillProfile(await api("GET", "/profile"));
    $("#lock").hidden = true;
  } catch (err) {
    if (!(err instanceof LockedError)) toast(err.message, true);
  }
}

start();

// Lets the app open instantly from the Home Screen. Needs HTTPS (or localhost).
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
