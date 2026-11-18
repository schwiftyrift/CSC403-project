import { $, api } from "./utils.js"
import { showTranscript } from "./transcript-player.js";
import { setupOutputs } from "./styled-outputs.js";

// Opened as /transcribe.html?job=<job_id> from "View transcript" in Your uploads, or with no
// job to show the newest transcript. A job that is still being transcribed shows its progress
// and loads by itself when it finishes (job-progress.js on this page sends "jobs:update").

const transcriptFilename = $("transcriptFilename");
const transcriptStatus = $("transcriptStatus");
const transcriptText = $("transcriptText");
const jobId = new URLSearchParams(location.search).get("job");
const WAITING = {queued: "Waiting to be transcribed. The transcript will appear here when it's ready.",
                 processing: "Transcribing. The transcript will appear here when it's ready."};
let loaded = false;

// A message, optionally followed by a link that tells the user what to do next.
function say(text, kind = "", link = null) {
  transcriptStatus.className = kind;
  transcriptStatus.textContent = text;
  if (link) {
    const a = document.createElement("a");
    a.href = link.href;
    a.textContent = link.text;
    transcriptStatus.append(" ", a);
  }
}

const UPLOADS = {href: "/history.html", text: "Go to Your uploads"};

function fail(error) {
  if (error.status === 401) { window.location.replace("/login.html"); return; }
  transcriptText.textContent = "";
  // fetch throws a TypeError when the server cannot be reached at all.
  if (error instanceof TypeError) say("Could not reach the server. Check your connection and refresh the page.", "error");
  else if (error.status === 404 && jobId) say("This upload wasn't found. It may have been deleted.", "error", UPLOADS);
  else if (error.status === 400 && jobId) say("This link doesn't point to an upload. Open the transcript from Your uploads instead.", "error", UPLOADS);
  else if (error.status === 404) say("You don't have any finished transcripts yet.", "", {href: "/upload.html", text: "Upload a file"});
  else say(error.message, "error");
}

async function showTranscriptOf(url) {
  if (loaded) return;
  loaded = true; // set before the request, so a second "jobs:update" can't load it twice
  const data = await api(url);
  transcriptFilename.textContent = data.filename;
  document.title = `${data.filename} - Transcript Service`;
  transcriptText.textContent = data.text;
  $("plainTranscriptText").textContent = data.text;
  say(data.text.trim() ? "" : "No speech was found in this recording.");
  // Keep a readable plain copy when the player replaces the original text with timed sentences.
  showTranscript(transcriptText, data.job_id).then(shown => {
    $("plainTranscriptSection").hidden = !shown || !data.text.trim();
  });
  setupOutputs(data.job_id, transcriptText);
}

function showStatus(job) {
  if (job.status === "failed") {
    say("Transcription failed. You can retry it from Your uploads.", "error", UPLOADS);
  } else if (job.status === "processing" && job.percent != null) {
    say(`Transcribing: ${job.percent}%. The transcript will appear here when it's ready.`);
  } else {
    say(WAITING[job.status] || `Status: ${job.status}`);
  }
}

async function load() {
  if (!jobId) return showTranscriptOf("/transcripts/latest");
  const job = await api(`/jobs/${encodeURIComponent(jobId)}`);
  transcriptFilename.textContent = job.filename;
  if (job.status === "done") return showTranscriptOf(`/jobs/${encodeURIComponent(jobId)}/transcript`);
  showStatus(job);
}

window.addEventListener("jobs:update", (event) => {
  const job = jobId && !loaded && event.detail.find(j => j.job_id === jobId);
  if (!job) return;
  if (job.status === "done") showTranscriptOf(`/jobs/${encodeURIComponent(jobId)}/transcript`).catch(fail);
  else showStatus(job);
});

load().catch(fail);
