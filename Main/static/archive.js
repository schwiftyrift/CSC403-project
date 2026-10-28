import { $, api, humanSize, say } from "./utils.js";
const statusE1 = $("status");

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
$("refreshHistory").onclick = () => loadHistory().catch(error => say(statusE1, error.message, "error"));
$("moreHistory").onclick = () => loadHistory(true).catch(error => say(statusE1, error.message, "error"));