// ---- Settings ---------------------------------------------------------------
// Set API_URL to your upload endpoint (for example "/api/jobs") to send the file
// to a real server. Leave it empty to run in demo mode, which uploads nothing and
// just shows what was chosen.
const API_URL = "/jobs";
const ALLOWED = [".mp3", ".wav", ".m4a", ".mp4", ".mov"];
const MAX_MB = 500;
// -----------------------------------------------------------------------------

const $ = (id) => document.getElementById(id);
const drop = $("drop"), input = $("file"), chosen = $("chosen"), bar = $("bar");
const go = $("go"), statusEl = $("status"), result = $("result");
let selected = null;

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
  go.disabled = false;
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
  if (!selected) return;
  if (!API_URL) {  // demo mode
    result.textContent = JSON.stringify({ mode: "demo (nothing uploaded)", filename: selected.name, size: humanSize(selected.size), type: selected.type || "unknown" }, null, 2);
    result.className = "show";
    say("Demo mode: file chosen but not sent. Set API_URL in script.js to upload for real.", "ok");
    return;
  }

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
      result.textContent = JSON.stringify(body, null, 2); result.className = "show";
    } else {
      say("Error: " + (body.error || "request failed (" + xhr.status + ")"), "error");
    }
    go.disabled = false;
  };
  xhr.onerror = () => { say("Could not reach the server.", "error"); go.disabled = false; };
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