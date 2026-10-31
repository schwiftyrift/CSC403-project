const PAGE_SIZE = 50;
const VIEW_KEY = "historyView";
const STATUS_TEXT = {queued: "Waiting to be transcribed", processing: "Transcribing", done: "Transcript ready", failed: "Transcription failed"};
// -----------------------------------------------------------------------------

const $ = (id) => document.getElementById(id);
const list = $("historyList"), statusEl = $("status");
let offset = 0;
let loadId = 0;

function say(text, kind = "") { statusEl.textContent = text; statusEl.className = kind; }

function humanSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 ** 2) return (bytes / 1024).toFixed(1) + " KB";
  if (bytes < 1024 ** 3) return (bytes / 1024 ** 2).toFixed(1) + " MB";
  return (bytes / 1024 ** 3).toFixed(2) + " GB";
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const body = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (response.status === 401) {
    window.location.replace("/login.html");
    throw new Error("Please log in again.");
  }
  if (!response.ok) {
    const error = new Error(body.error || "Request failed (" + response.status + ")");
    error.status = response.status;
    throw error;
  }
  return body;
}

function updateEmptyState() {
  const empty = !list.querySelector("article");
  $("emptyHistory").hidden = !empty;
  $("deleteAll").disabled = empty;
}

function transcriptButton(job) {
  const transcript = document.createElement("button");
  transcript.type = "button"; transcript.className = "secondary transcript-download"; transcript.textContent = "Download transcript";
  transcript.setAttribute("aria-label", `Download the transcript of ${job.filename} as a text file`);
  transcript.addEventListener("click", () => downloadTranscript(job, transcript));
  return transcript;
}

function render(job) {
  const article = document.createElement("article");
  article.dataset.jobId = job.job_id;
  const title = document.createElement("h3"); title.textContent = job.filename;
  const details = document.createElement("p");
  details.textContent = `${humanSize(job.size_bytes)} - Uploaded ${new Date(job.uploaded_at * 1000).toLocaleString()}`;
  const status = document.createElement("p"); status.className = "job-status"; status.textContent = STATUS_TEXT[job.status] || job.status;
  const actions = document.createElement("div"); actions.className = "actions";
  const link = document.createElement("a"); link.href = `/jobs/${job.job_id}/file`; link.textContent = "Download";
  link.setAttribute("aria-label", `Download ${job.filename}`);
  const remove = document.createElement("button");
  remove.type = "button"; remove.className = "danger"; remove.textContent = "Delete";
  remove.setAttribute("aria-label", `Delete ${job.filename}`);
  remove.addEventListener("click", () => deleteOne(job, article, remove));
  actions.append(link);
  if (job.transcript_ready) {
    actions.append(transcriptButton(job));
  }
  actions.append(remove);
  article.append(title, details, status, actions);
  return article;
}

async function loadHistory(append = false) {
  const request = ++loadId;
  const jobs = await api(`/jobs?limit=${PAGE_SIZE}&offset=${append ? offset : 0}`);
  if (request !== loadId) return; // a newer load replaced this one
  if (!append) { offset = 0; list.replaceChildren(); }
  offset += jobs.length;
  list.append(...jobs.map(render));
  $("moreHistory").hidden = jobs.length < PAGE_SIZE;
  $("history").hidden = false;
  updateEmptyState();
}

// Fetched rather than linked so a failure shows a message here instead of a raw error page.
async function downloadTranscript(job, button) {
  button.disabled = true;
  say(`Preparing the transcript of ${job.filename}...`);
  try {
    const response = await fetch(`/jobs/${job.job_id}/transcript.txt`);
    if (response.status === 401) { window.location.replace("/login.html"); return; }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(response.status >= 500
        ? "The transcript service is down right now. Try again in a few minutes."
        : (body.error || `The download failed (${response.status}). Try again.`));
    }
    const url = URL.createObjectURL(await response.blob());
    const save = document.createElement("a");
    save.href = url;
    save.download = job.filename.replace(/\.[^.]+$/, "") + ".txt";
    save.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    say(`Downloaded the transcript of ${job.filename}.`, "ok");
  } catch (error) {
    // fetch throws a TypeError when the server cannot be reached at all.
    say(error instanceof TypeError ? "Could not reach the server. Check your connection and try again." : error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function deleteOne(job, article, button) {
  if (!confirm(`Permanently delete "${job.filename}" and its transcript? This cannot be undone.`)) return;
  button.disabled = true;
  try {
    await api(`/jobs/${job.job_id}`, {method: "DELETE"});
    say(`Deleted ${job.filename}.`, "ok");
  } catch (error) {
    // 404 means it is already gone (for example, deleted in another tab).
    if (error.status !== 404) { button.disabled = false; say(error.message, "error"); return; }
    say(`${job.filename} was already deleted.`, "ok");
  }
  const next = article.nextElementSibling || article.previousElementSibling;
  article.remove();
  offset -= 1; // keep "Load more" from skipping an item
  (next ? next.querySelector("button") : $("refreshHistory")).focus();
  if (!list.querySelector("article")) await loadHistory().catch(error => say(error.message, "error"));
  updateEmptyState();
}

$("deleteAll").addEventListener("click", async () => {
  if (!confirm("Permanently delete ALL of your uploads and transcripts, including ones not shown on this page? This cannot be undone.")) return;
  $("deleteAll").disabled = true;
  try {
    await api("/jobs", {method: "DELETE"});
    say("All uploads deleted.", "ok");
  } catch (error) {
    say(error.message, "error");
  }
  // Reload either way: after a partial failure (409) the remaining files are still listed.
  await loadHistory().catch(error => say(error.message, "error"));
  $("refreshHistory").focus();
});

function setView(view) {
  const grid = view === "grid";
  list.className = grid ? "grid-view" : "list-view";
  $("listView").setAttribute("aria-pressed", String(!grid));
  $("gridView").setAttribute("aria-pressed", String(grid));
  try { localStorage.setItem(VIEW_KEY, grid ? "grid" : "list"); } catch (_) {}
}
$("listView").addEventListener("click", () => setView("list"));
$("gridView").addEventListener("click", () => setView("grid"));
let savedView = "list";
try { savedView = localStorage.getItem(VIEW_KEY) || "list"; } catch (_) {}
setView(savedView);

$("refreshHistory").addEventListener("click", () => { say(""); loadHistory().catch(error => say(error.message, "error")); });
$("moreHistory").addEventListener("click", () => loadHistory(true).catch(error => say(error.message, "error")));

const menuButton = $("menuButton");
const sideBar = $("sidebar");
menuButton.addEventListener("click", () => {
  sideBar.classList.toggle("open");
  menuButton.classList.toggle("open");
  menuButton.setAttribute("aria-expanded", sideBar.classList.contains("open"));
});

$("logout").addEventListener("click", async () => {
  try { await api("/auth/logout", {method: "POST"}); window.location.replace("/login.html"); }
  catch (error) { say(error.message, "error"); }
});

// Update rows in place: reloading the list would lose "Load more" pages and keyboard focus.
window.addEventListener("jobs:update", (event) => {
  for (const job of event.detail) {
    const article = list.querySelector(`article[data-job-id="${job.job_id}"]`);
    if (!article) continue;
    article.querySelector(".job-status").textContent = job.percent !== null && job.status === "processing"
      ? `Transcribing: ${job.percent}%` : STATUS_TEXT[job.status] || job.status;
    if (job.status === "done" && !article.querySelector(".transcript-download")) {
      article.querySelector(".actions").insertBefore(transcriptButton(job), article.querySelector(".danger"));
    }
  }
});

api("/auth/me").then(() => loadHistory()).catch(error => say(error.message, "error"));
