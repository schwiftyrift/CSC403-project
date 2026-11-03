// Synced transcript player (US-17): plays an upload above its transcript, highlights the
// sentence being spoken, and jumps the audio when a sentence is clicked (or Enter is pressed).
//
// Usage, once the page knows which job it is showing:
//   import { showTranscript } from "./transcript-player.js";
//   showTranscript(containerElement, jobId);
// It resolves to true once the player is shown. It resolves to false, leaving the container
// untouched, when the job has no timestamps (transcribed before they were saved) or they
// could not be loaded, so the page keeps showing the plain transcript text.

// 75.4 -> "1:15", 3725 -> "1:02:05"
function clock(seconds) {
  const h = Math.floor(seconds / 3600), m = Math.floor(seconds / 60) % 60, s = Math.floor(seconds % 60);
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return (h ? h + ":" : "") + mm + ":" + String(s).padStart(2, "0");
}

export async function showTranscript(container, jobId) {
  let segments;
  try {
    const response = await fetch(`/jobs/${encodeURIComponent(jobId)}/segments`);
    if (!response.ok) return false;
    segments = (await response.json()).segments;
  } catch (_) {
    return false;
  }
  if (!segments.length) return false;

  const player = document.createElement("audio");
  player.className = "transcript-audio";
  player.controls = true;
  player.preload = "metadata";
  player.src = `/jobs/${encodeURIComponent(jobId)}/media`;
  const list = document.createElement("div");
  list.className = "segments";
  let active = -1;

  const rows = segments.map((segment, i) => {
    const row = document.createElement("p");
    row.className = "segment";
    row.tabIndex = 0;
    row.setAttribute("role", "button");
    row.setAttribute("aria-label", `Play from ${clock(segment.start)}: ${segment.text}`);
    const time = document.createElement("span");
    time.className = "time";
    time.textContent = clock(segment.start);
    const text = document.createElement("span");
    text.textContent = segment.text;
    row.append(time, text);
    row.addEventListener("click", () => {
      if (window.getSelection().toString()) return; // let people select text without jumping
      seek(i);
    });
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); seek(i); }
    });
    return row;
  });

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
    let i = segments.length - 1;
    while (i >= 0 && segments[i].start > player.currentTime) i--;
    highlight(i);
  });

  list.append(...rows);
  container.replaceChildren(player, list);
  return true;
}
