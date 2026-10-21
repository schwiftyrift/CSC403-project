// Transcript page: plays the upload and highlights the sentence being spoken.
// Clicking a sentence (or pressing Enter on it) jumps the audio to that moment.
// Opened as /transcribe.html?job=<job_id> from the upload page.

const $ = (id) => document.getElementById(id);
const player = $("player"), list = $("segments"), statusEl = $("transcriptStatus");
const jobId = new URLSearchParams(location.search).get("job");
let segments = [], rows = [], active = -1;

function say(text, kind = "") { statusEl.textContent = text; statusEl.className = kind; }

// 75.4 -> "1:15", 3725 -> "1:02:05"
function clock(seconds) {
  const h = Math.floor(seconds / 3600), m = Math.floor(seconds / 60) % 60, s = Math.floor(seconds % 60);
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return (h ? h + ":" : "") + mm + ":" + String(s).padStart(2, "0");
}

function render() {
  list.replaceChildren();
  rows = segments.map((seg, i) => {
    const row = document.createElement("p");
    row.className = "segment";
    row.tabIndex = 0;
    row.setAttribute("role", "button");
    row.setAttribute("aria-label", "Play from " + clock(seg.start));
    const time = document.createElement("span");
    time.className = "time";
    time.textContent = clock(seg.start);
    const text = document.createElement("span");
    text.textContent = seg.text;
    row.append(time, text);
    row.addEventListener("click", () => {
      if (window.getSelection().toString()) return;  // let people select text without jumping
      seek(i);
    });
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); seek(i); }
    });
    list.append(row);
    return row;
  });
}

function seek(i) {
  player.currentTime = segments[i].start;
  player.play();
  highlight(i);
}

function highlight(i) {
  if (i === active) return;
  if (active >= 0) { rows[active].classList.remove("active"); rows[active].removeAttribute("aria-current"); }
  active = i;
  if (i < 0) return;
  rows[i].classList.add("active");
  rows[i].setAttribute("aria-current", "true");
  if (!player.paused) rows[i].scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// The sentence being spoken is the last one that has started by now.
player.addEventListener("timeupdate", () => {
  const t = player.currentTime;
  let i = segments.length - 1;
  while (i >= 0 && segments[i].start > t) i--;
  highlight(i);
});

async function load() {
  if (!jobId) { player.hidden = true; say("No file selected. Upload a file on the Home page first.", "error"); return; }
  player.src = "/jobs/" + encodeURIComponent(jobId) + "/media";
  say("Loading transcript...");
  let res, body = {};
  try {
    res = await fetch("/jobs/" + encodeURIComponent(jobId) + "/transcript");
    body = await res.json();
  } catch (_) {
    say("Could not reach the server. Refresh to try again.", "error");
    return;
  }
  if (res.ok) {
    segments = body.segments;
    render();
    say(segments.length ? "" : "The transcript is empty. No speech was found in this file.");
  } else if (body.error === "transcript not ready") {
    say("The transcript isn't ready yet. You can still play the recording. Refresh in a moment.");
  } else {
    player.hidden = true;
    say("Error: " + (body.error || "request failed (" + res.status + ")"), "error");
  }
}

load();
