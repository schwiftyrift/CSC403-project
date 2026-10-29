import { $, api, humanSize, say } from "./utils.js";

const API_URL = "/jobs";
const ALLOWED = [".mp3", ".wav", ".m4a", ".mp4", ".mov"];
const MAX_MB = 500;
const drop = $("drop"), input = $("file"), chosen = $("chosen"), bar = $("bar");
const go = $("go"), statusEl = $("status"), result = $("result");
const transcribe = $("transcribe");

let selected = null;
let signedIn = false;

function setFile(file) {
  result.className = ""; result.textContent = "";
  bar.className = ""; bar.value = 0;
  const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
  if (!ALLOWED.includes(ext)) { clearFile(); say(statusEl, "Unsupported file type. Use " + ALLOWED.join(", ") + ".", "error"); return; }
  if (file.size > MAX_MB * 1024 * 1024) { clearFile(); say(statusEl, "File is larger than " + MAX_MB + " MB.", "error"); return; }
  selected = file;
  $("name").textContent = file.name;
  $("size").textContent = humanSize(file.size);
  chosen.classList.add("show");
  go.disabled = !signedIn;
  say(statusEl, "");
}

function clearFile() {
  selected = null; input.value = "";
  chosen.classList.remove("show");
  transcribe.classList.remove("show")
  go.disabled = true;
}

input.addEventListener("change", () => { if (input.files[0]) setFile(input.files[0]); });
$("clear").addEventListener("click", () => { clearFile(); say(statusEl, ""); result.className = ""; bar.className = ""; });


// Drag and drop
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => {
  const files = e.dataTransfer.files;
  if (files.length > 1) say(statusEl, "Only one file at a time. Using the first one.", "error");
  if (files[0]) setFile(files[0]);
});
// Stop the browser from opening a file that is dropped outside the box
["dragover", "drop"].forEach((ev) => window.addEventListener(ev, (e) => e.preventDefault()));

api("/auth/me")
    .then(user => {
        signedIn = setAccount(user);
        go.disabled = !selected;
    })
    .catch(() => {
        signedIn = setAccount(null);
        go.disabled = true;
    });

go.addEventListener("click", () => {
  if (!selected || !signedIn) return;
  const form = new FormData();
  form.append("file", selected);
  const xhr = new XMLHttpRequest();
  xhr.open("POST", API_URL);
  go.disabled = true; bar.className = "show"; bar.value = 0; result.className = ""; say(statusEl, "Uploading...");

  xhr.upload.onprogress = (e) => { if (e.lengthComputable) bar.value = (e.loaded / e.total) * 100; };
  xhr.onload = () => {
    let body = {};
    try { body = JSON.parse(xhr.responseText); } catch (_) {}
    if (xhr.status >= 200 && xhr.status < 300) {
        say(statusEl, "Upload complete.", "ok");
        transcribe.classList.add("show");
        result.textContent = `${body.filename} saved to your account.`; result.className = "show";
    } else {
        if (xhr.status === 401){
            signedIn = false;
            go.disabled = true;
        }
        say(statusEl, "Error: " + (body.error || "request failed (" + xhr.status + ")"), "error");
    }
    go.disabled = !signedIn || !selected;
  };
  xhr.onerror = () => { say(statusEl, "Could not reach the server.", "error"); go.disabled = !signedIn || !selected; };
  xhr.send(form);
});

transcribe.addEventListener("click", ()=> {
  window.location.href = "/transcribe.html";
});
