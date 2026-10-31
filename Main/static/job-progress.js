// Shows transcription progress and milestone notifications on every page.
// Self-contained so any page can include it with one script tag.
(async () => {
  const ACTIVE_POLL_MS = 3000;
  const IDLE_POLL_MS = 30000; // keep checking so uploads from another tab or device appear
  const MAX_RETRY_MS = 60000;
  const TOAST_MS = 6000;
  const MAX_TOASTS = 2;
  const MAX_ROWS = 3;
  const MAX_CARDS = 2;
  const MAX_NAME = 60;
  const RANK = {queued: 1, started: 2, halfway: 3, finished: 4};

  let user;
  try {
    const response = await fetch("/auth/me");
    if (!response.ok) return; // signed out: nothing to show
    user = await response.json();
  } catch (_) {
    return;
  }

  const SEEN_KEY = `jobMilestones:${user.id}`; // per user, because accounts can share a browser
  const COLLAPSED_KEY = "jobProgressCollapsed";
  let memorySeen = null; // replaces localStorage when the browser blocks it
  let baselinePending = true;
  let latestJobs = [];
  let finishedKey = null;
  let collapsed = false;
  let stopped = false, polling = false, pollAgain = false, timer = null, failures = 0;
  try { collapsed = localStorage.getItem(COLLAPSED_KEY) === "1"; } catch (_) {}

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text; // filenames are untrusted: never use innerHTML here
    return node;
  }

  const root = element("aside");
  root.id = "jobProgress";
  root.setAttribute("aria-label", "Transcription progress");
  const toasts = element("div", "job-stack");
  const finished = element("div", "job-stack");
  for (const region of [toasts, finished]) {
    region.setAttribute("role", "status");
    region.setAttribute("aria-live", "polite");
  }
  const finishedMore = element("div", "job-card job-more");
  finishedMore.hidden = true;
  const finishedMoreText = element("span");
  const dismissAll = element("button", "secondary", "Dismiss all");
  dismissAll.type = "button";
  finishedMore.append(finishedMoreText, dismissAll);
  const panel = element("section", "job-card job-panel");
  panel.hidden = true;
  const header = element("div", "job-panel-header");
  const title = element("strong");
  const toggle = element("button", "secondary");
  toggle.type = "button";
  header.append(title, toggle);
  const rows = element("div");
  const more = element("a", "job-link");
  more.href = "/history.html";
  const note = element("p", "job-detail"); // not a live region: reading out every update would be constant noise
  panel.append(header, rows, more, note);
  // The panel comes first: if the stack ever has to scroll, live progress stays in view.
  root.append(panel, finished, finishedMore, toasts);
  document.body.append(root);
  // Reserve room at the bottom of the page, so content can always be scrolled out from under the stack.
  new ResizeObserver(() => {
    document.body.style.paddingBottom = root.offsetHeight ? `${root.offsetHeight + 16}px` : "";
  }).observe(root);

  const isActive = (job) => job.status === "queued" || job.status === "processing";
  const shortName = (name) => name.length > MAX_NAME ? `${name.slice(0, MAX_NAME - 3)}...` : name;

  function readSeen() {
    if (memorySeen) return memorySeen;
    try {
      return JSON.parse(localStorage.getItem(SEEN_KEY) || "{}") || {};
    } catch (error) {
      if (error instanceof SyntaxError) return {}; // corrupted value: start over
      memorySeen = {}; // storage is blocked
      return memorySeen;
    }
  }

  function writeSeen(seen) {
    if (memorySeen) { memorySeen = seen; return; }
    try { localStorage.setItem(SEEN_KEY, JSON.stringify(seen)); } catch (_) { memorySeen = seen; }
  }

  function milestoneOf(job) {
    if (!isActive(job)) return "finished";
    if (job.stage === "queued") return "queued";
    return job.percent !== null && job.percent >= 50 ? "halfway" : "started";
  }

  function showToast(text) {
    const toast = element("div", "job-card", text);
    toasts.append(toast);
    while (toasts.children.length > MAX_TOASTS) toasts.firstElementChild.remove();
    setTimeout(() => toast.remove(), TOAST_MS);
  }

  function announceMilestones(jobs) {
    const seen = readSeen();
    // Without storage every page load looks new, so only announce changes seen after the first poll.
    const baseline = baselinePending && memorySeen !== null;
    baselinePending = false;
    const next = {}; // jobs that left the response are dropped, so storage can't grow forever
    for (const job of jobs) {
      const entry = seen[job.job_id] || {rank: 0, dismissed: false};
      const milestone = milestoneOf(job);
      if (RANK[milestone] > entry.rank) {
        entry.rank = RANK[milestone];
        if (baseline) entry.dismissed = milestone === "finished";
        else if (milestone === "queued") showToast(`"${shortName(job.filename)}" uploaded. It will be transcribed automatically.`);
        else if (milestone === "started") showToast(`Started transcribing "${shortName(job.filename)}".`);
        else if (milestone === "halfway") showToast(`"${shortName(job.filename)}" is halfway transcribed.`);
      }
      next[job.job_id] = entry;
    }
    writeSeen(next);
  }

  function formatEta(seconds) {
    if (seconds === 0) return "Almost done";
    if (seconds < 60) return "Less than a minute left";
    const minutes = Math.ceil(seconds / 60);
    if (minutes < 60) return `About ${minutes} min left`;
    return `About ${Math.floor(minutes / 60)} hr ${minutes % 60} min left`;
  }

  function describe(job) {
    if (job.stage === "queued") {
      if (!job.jobs_ahead) return ["Waiting to start", ""];
      return [`Waiting in line: ${job.jobs_ahead} ${job.jobs_ahead === 1 ? "job" : "jobs"} ahead of yours`, ""];
    }
    const label = job.percent !== null ? `Transcribing: ${job.percent}%` : job.stage === "preparing" ? "Preparing the audio..." : "Transcribing...";
    if (job.stalled) return [label, "Taking longer than usual. It will continue automatically."];
    if (job.stage === "preparing") return [label, ""];
    return [label, job.eta_seconds !== null ? formatEta(job.eta_seconds) : "Estimating time left..."];
  }

  function activeRow(job) {
    const row = element("div", "job-row");
    const [label, detail] = describe(job);
    const bar = element("progress", "show"); // style.css hides any progress without "show"
    bar.max = 100;
    bar.setAttribute("aria-label", `Transcription progress for ${job.filename}`);
    // Leaving value unset gives an animated, indeterminate bar for when no percent is known yet.
    if (job.stage === "queued") bar.value = 0;
    else if (job.percent !== null) bar.value = job.percent;
    const name = element("div", "job-name", shortName(job.filename));
    name.title = job.filename;
    row.append(name, bar, element("div", "job-detail", label));
    if (detail) row.append(element("div", "job-detail", detail));
    return row;
  }

  function finishedCard(job) {
    const failed = job.status === "failed";
    const card = element("div", failed ? "job-card job-failed" : "job-card job-done");
    // Failed files must be deleted first, because duplicate detection blocks re-uploading them.
    card.append(element("p", "", failed
      ? `Could not transcribe "${shortName(job.filename)}". The file may be damaged or have no audio. Delete it under Your uploads, then upload it again.`
      : `Transcript ready: "${shortName(job.filename)}".`));
    const link = element("a", "job-link", "Go to Your uploads");
    link.href = "/history.html";
    const dismiss = element("button", "secondary", "Dismiss");
    dismiss.type = "button";
    dismiss.setAttribute("aria-label", `Dismiss the notification for ${job.filename}`);
    dismiss.addEventListener("click", () => {
      const seen = readSeen();
      seen[job.job_id] = {rank: RANK.finished, dismissed: true};
      writeSeen(seen);
      renderFinished();
      const nextButton = finished.querySelector("button");
      if (nextButton) nextButton.focus();
    });
    card.append(link, dismiss);
    return card;
  }

  function renderFinished() {
    const seen = readSeen();
    const jobs = latestJobs.filter(job => !isActive(job) && seen[job.job_id] && !seen[job.job_id].dismissed);
    const extra = jobs.length - MAX_CARDS;
    finishedMore.hidden = extra <= 0;
    finishedMoreText.textContent = `And ${extra} more finished`;
    // Rebuild only when the set changes, so a poll can't take keyboard focus off a Dismiss button.
    const key = jobs.slice(0, MAX_CARDS).map(job => job.job_id).join();
    if (key === finishedKey) return;
    finishedKey = key;
    finished.replaceChildren(...jobs.slice(0, MAX_CARDS).map(finishedCard));
  }

  dismissAll.addEventListener("click", () => {
    const seen = readSeen();
    for (const job of latestJobs) {
      if (!isActive(job)) seen[job.job_id] = {rank: RANK.finished, dismissed: true};
    }
    writeSeen(seen);
    renderFinished();
  });

  function render() {
    const active = latestJobs.filter(isActive);
    panel.hidden = active.length === 0;
    title.textContent = active.length === 1 ? "Transcribing 1 file" : `Transcribing ${active.length} files`;
    toggle.textContent = collapsed ? "Show" : "Hide";
    toggle.setAttribute("aria-expanded", String(!collapsed));
    rows.hidden = collapsed;
    rows.replaceChildren(...active.slice(0, MAX_ROWS).map(activeRow));
    const hiddenCount = active.length - MAX_ROWS;
    more.hidden = collapsed || hiddenCount <= 0;
    more.textContent = `And ${hiddenCount} more under Your uploads`;
    note.hidden = failures === 0;
    note.textContent = "Can't reach the server. Trying again...";
    renderFinished();
  }

  toggle.addEventListener("click", () => {
    collapsed = !collapsed;
    try { localStorage.setItem(COLLAPSED_KEY, collapsed ? "1" : "0"); } catch (_) {}
    render();
  });

  async function poll() {
    clearTimeout(timer);
    if (stopped || document.hidden) return; // a visibilitychange restarts this when the tab returns
    if (polling) { pollAgain = true; return; }
    polling = true;
    let delay;
    try {
      const response = await fetch("/jobs/activity");
      if (response.status === 401) { // the session ended
        stopped = true;
        root.remove();
        return;
      }
      if (!response.ok) throw new Error(`Request failed (${response.status})`);
      const body = await response.json(); // a proxy error page lands in the catch below
      failures = 0;
      latestJobs = body.jobs;
      // Hidden tabs don't claim milestones, or the toast would appear where nobody can see it.
      if (!document.hidden) announceMilestones(latestJobs);
      render();
      window.dispatchEvent(new CustomEvent("jobs:update", {detail: latestJobs}));
      delay = latestJobs.some(isActive) ? ACTIVE_POLL_MS : IDLE_POLL_MS;
    } catch (_) {
      failures += 1;
      delay = Math.min(ACTIVE_POLL_MS * 2 ** failures, MAX_RETRY_MS);
      render();
    } finally {
      polling = false;
    }
    if (stopped) return;
    if (pollAgain) { pollAgain = false; poll(); return; }
    timer = setTimeout(poll, delay);
  }

  window.addEventListener("jobs:refresh", poll);
  document.addEventListener("visibilitychange", poll);
  window.addEventListener("pageshow", (event) => { if (event.persisted) poll(); }); // back/forward cache
  window.addEventListener("storage", (event) => { if (event.key === SEEN_KEY) renderFinished(); }); // dismissed in another tab
  poll();
})();
