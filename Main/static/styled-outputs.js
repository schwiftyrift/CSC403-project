import { $, api } from "./utils.js";
import { labels, outputControls } from "./output-controls.js";

const initialized = new WeakSet();

export async function setupOutputs(jobId, transcriptText) {
  if (initialized.has(transcriptText)) return;
  initialized.add(transcriptText);
  const base = `/jobs/${encodeURIComponent(jobId)}`;
  const status = $("outputStatus"), panel = $("outputPanel");
  let outputs = [], busy = false, timer, stopped = false, downloading = false, downloadFormat = "";
  const controls = outputControls($("outputSelections"), () => { status.textContent = ""; render(); });
  $("styledOutputs").hidden = false;

  function render() {
    const formats = controls.get().formats;
    if (!formats.includes(downloadFormat)) downloadFormat = formats[0] || "";
    const output = outputs.find(item => item.format === downloadFormat);
    $("downloadChoice").hidden = formats.length < 2;
    const select = $("downloadOutput");
    if ([...select.options].map(option => option.value).join() !== formats.join()) {
      select.replaceChildren();
      for (const format of formats) {
        const option = document.createElement("option");
        option.value = format; option.textContent = labels[format]; select.append(option);
      }
    }
    select.value = downloadFormat;
    select.disabled = busy || downloading;
    panel.hidden = formats.length === 0;
    panel.textContent = formats.map(format => {
      const item = outputs.find(item => item.format === format);
      const message = !item ? "Not generated yet."
        : item.status === "done" ? "Saved — ready to download."
        : item.status === "failed" ? item.error : `Output ${item.status}…`;
      return `${labels[format]}: ${message}`;
    }).join("\n");
    $("generateOutputs").disabled = busy || formats.length === 0;
    for (const id of ["downloadTxt", "downloadDocx"]) {
      $(id).disabled = busy || downloading || output?.status !== "done";
      const extension = downloadFormat === "captions" ? (id === "downloadTxt" ? "srt" : "vtt") : (id === "downloadTxt" ? "txt" : "docx");
      $(id).textContent = `Download .${extension}`;
      $(id).setAttribute("aria-label", `Download .${extension}${downloadFormat ? ` of ${labels[downloadFormat]}` : ""}`);
    }
    $("retryOutput").hidden = !["done", "failed"].includes(output?.status);
    $("retryOutput").disabled = busy || downloading;
    $("retryOutput").textContent = output?.status === "failed" ? "Retry" : "Regenerate";
    $("retryOutput").setAttribute("aria-label", `${output?.status === "failed" ? "Retry" : "Regenerate"} ${labels[downloadFormat] || "output"}`);
  }

  async function refresh() {
    clearTimeout(timer);
    try {
      const updated = await api(base + "/outputs");
      if (JSON.stringify(updated) !== JSON.stringify(outputs)) { outputs = updated; render(); }
    } catch (error) { status.textContent = error.message; }
    if (!stopped) timer = setTimeout(refresh, 4000);
  }

  async function requestOutputs(formats) {
    if (busy || !formats.length) return;
    busy = true; render();
    try {
      await api(base + "/output-preferences", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(controls.get())});
      for (const format of formats) await api(`${base}/outputs/${format}`, {method: "POST"});
      status.textContent = "Generation requested. Check the status below; you can leave this page and return later.";
    } catch (error) { status.textContent = error.message; }
    finally { busy = false; render(); await refresh(); }
  }

  async function download(extension) {
    const format = downloadFormat;
    if (busy || downloading || outputs.find(item => item.format === format)?.status !== "done") return;
    downloading = true; render();
    try {
      const response = await fetch(`${base}/outputs/${format}/download/${extension}`);
      if (!response.ok) throw new Error((await response.json()).error || "Download failed.");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `${$("transcriptFilename").textContent.replace(/\.[^.]+$/, "")}-${format}.${extension}`;
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      status.textContent = `Downloaded ${labels[format]} as .${extension}.`;
    } catch (error) { status.textContent = error.message; }
    finally { downloading = false; render(); }
  }

  $("generateOutputs").addEventListener("click", () => requestOutputs(controls.get().formats));
  $("downloadOutput").addEventListener("change", event => { downloadFormat = event.target.value; render(); });
  $("downloadTxt").addEventListener("click", () => download(downloadFormat === "captions" ? "srt" : "txt"));
  $("downloadDocx").addEventListener("click", () => download(downloadFormat === "captions" ? "vtt" : "docx"));
  $("retryOutput").addEventListener("click", () => requestOutputs([downloadFormat]));
  window.addEventListener("pagehide", () => { stopped = true; clearTimeout(timer); }, {once: true});
  render();
  await refresh();
}
