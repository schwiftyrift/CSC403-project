const API_URL = "/jobs";
const ALLOWED = [".mp3", ".wav", ".m4a", ".mp4", ".mov"];
const MAX_MB = 500;
// -----------------------------------------------------------------------------

const $ = (id) => document.getElementById(id);
const drop = $("drop"), input = $("file"), chosen = $("chosen"), bar = $("bar");
const go = $("go"), statusEl = $("status"), result = $("result");
let selected = null;
let signedIn = false;

function say(text, kind = "") { statusEl.textContent = text; statusEl.className = kind; }

function humanSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 ** 2) return (bytes / 1024).toFixed(1) + " KB";
  if (bytes < 1024 ** 3) return (bytes / 1024 ** 2).toFixed(1) + " MB";
  return (bytes / 1024 ** 3).toFixed(2) + " GB";
}

function setFile(file) {
  result.className = ""; result.textContent = "";
  bar.className = ""; bar.value = 0;
  const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
  if (!ALLOWED.includes(ext)) { clearFile(); say("Unsupported file type. Use " + ALLOWED.join(", ") + ".", "error"); return; }
  if (file.size > MAX_MB * 1024 * 1024) { clearFile(); say("File is larger than " + MAX_MB + " MB.", "error"); return; }
  selected = file;
  $("name").textContent = file.name;
  $("size").textContent = humanSize(file.size);
  chosen.classList.add("show");
  go.disabled = !signedIn;
  say("");
}

function clearFile() {
  selected = null; input.value = "";
  chosen.classList.remove("show");
  go.disabled = true;
}

input.addEventListener("change", () => { if (input.files[0]) setFile(input.files[0]); });
$("clear").addEventListener("click", () => { clearFile(); say(""); result.className = ""; bar.className = ""; });

// Drag and drop
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => {
  const files = e.dataTransfer.files;
  if (files.length > 1) say("Only one file at a time. Using the first one.", "error");
  if (files[0]) setFile(files[0]);
});
// Stop the browser from opening a file that is dropped outside the box
["dragover", "drop"].forEach((ev) => window.addEventListener(ev, (e) => e.preventDefault()));

go.addEventListener("click", () => {
  if (!selected || !signedIn) return;
  const form = new FormData();
  form.append("file", selected);
  const xhr = new XMLHttpRequest();
  xhr.open("POST", API_URL);
  go.disabled = true; bar.className = "show"; bar.value = 0; result.className = ""; say("Uploading...");

  xhr.upload.onprogress = (e) => { if (e.lengthComputable) bar.value = (e.loaded / e.total) * 100; };
  xhr.onload = () => {
    let body = {};
    try { body = JSON.parse(xhr.responseText); } catch (_) {}
    if (xhr.status >= 200 && xhr.status < 300) {
      say("Upload complete.", "ok");
      loadHistory().catch(e => say(e.message, "error"));
      result.textContent = `${body.filename} saved to your account.`; result.className = "show";
    } else {
      if (xhr.status === 401) setAccount(null);
      say("Error: " + (body.error || "request failed (" + xhr.status + ")"), "error");
    }
    go.disabled = !signedIn;
  };
  xhr.onerror = () => { say("Could not reach the server.", "error"); go.disabled = !signedIn; };
  xhr.send(form);
});

const menuButton = document.getElementById("menuButton");
const sideBar = document.getElementById("sidebar");

menuButton.addEventListener("click", () => {
  sideBar.classList.toggle("open");
  menuButton.classList.toggle("open");

  const isOpen = sideBar.classList.contains("open");

  menuButton.setAttribute("aria-expanded", isOpen);
});
async function api(url, options = {}) {
  const response = await fetch(url, options);
  const body = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    if (response.status === 401) setAccount(null);
    throw new Error(body.error || "Request failed");
  }
  return body;
}
function setAccount(user) {
  signedIn = Boolean(user);
  $("accountStatus").textContent = user ? `Signed in as ${user.email}` : "Sign in to upload files and view your history.";
  $("loginLink").hidden = signedIn;
  $("logout").hidden = !signedIn;
  $("history").hidden = !signedIn;
  go.disabled = !signedIn || !selected;
  if (!signedIn) { $("historyList").replaceChildren(); result.textContent = ""; }
}
$("logout").addEventListener("click", async () => {
  try { await api("/auth/logout", {method: "POST"}); setAccount(null); window.location.replace("/login.html"); }
  catch (error) { say(error.message, "error"); }
});
let historyOffset = 0;
async function loadHistory(append = false) {
  if (!append) { historyOffset = 0; $("historyList").replaceChildren(); }
  const jobs = await api(`/jobs?limit=50&offset=${historyOffset}`);
  historyOffset += jobs.length;
  $("moreHistory").hidden = jobs.length < 50;
  if (!append && !jobs.length) $("historyList").textContent = "No uploads yet.";
  for (const job of jobs) {
    const article = document.createElement("article");
    const title = document.createElement("h3"); title.textContent = job.filename;
    const link = document.createElement("a"); link.href = `/jobs/${job.job_id}/file`; link.textContent = "Download file";
    const details = document.createElement("p");
    details.textContent = `${humanSize(job.size_bytes)} - Uploaded ${new Date(job.uploaded_at * 1000).toLocaleString()}`;
    article.append(title, details, link);
    $("historyList").append(article);
  }
}
$("refreshHistory").onclick = () => loadHistory().catch(error => say(error.message, "error"));
$("moreHistory").onclick = () => loadHistory(true).catch(error => say(error.message, "error"));
setAccount(null);
api("/auth/me").then(async user => { setAccount(user); await loadHistory(); }).catch(error => {
  if (signedIn) say(error.message, "error");
});
