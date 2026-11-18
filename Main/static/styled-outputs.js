import { $, api } from "./utils.js";
import { labels, outputControls } from "./output-controls.js";

export async function setupOutputs(jobId, transcriptText) {
  const base = `/jobs/${encodeURIComponent(jobId)}`;
  const status = $("outputStatus"), tabs = $("outputTabs"), panel = $("outputPanel"), actions = $("outputActions");
  let active = "plain", outputs = [], busy = false, timer, stopped = false;
  const controls = outputControls($("outputSelections"));
  $("styledOutputs").hidden = false;
  try { controls.set(await api(base + "/output-preferences")); }
  catch (error) { status.textContent = error.message; }
  for (const [format, label] of Object.entries({plain: "Plain transcript", ...labels})) {
    const button = document.createElement("button");
    button.type = "button"; button.role = "tab"; button.id = `output-tab-${format}`;
    button.textContent = label; button.setAttribute("aria-controls", "outputPanel");
    button.addEventListener("click", () => { active = format; render(); });
    button.addEventListener("keydown", event => {
      const buttons = [...tabs.children]; let next = buttons.indexOf(button);
      if (event.key === "ArrowRight") next = (next + 1) % buttons.length;
      else if (event.key === "ArrowLeft") next = (next + buttons.length - 1) % buttons.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = buttons.length - 1;
      else return;
      event.preventDefault(); buttons[next].click(); buttons[next].focus();
    });
    tabs.append(button);
  }
  // Place the additive tabs before the existing player; keep the original player mounted.
  transcriptText.before(tabs);
  function render() {
    [...tabs.children].forEach((button, index) => {
      const selected = Object.keys({plain: "", ...labels})[index] === active;
      button.setAttribute("aria-selected", String(selected)); button.tabIndex = selected ? 0 : -1;
    });
    transcriptText.hidden = active !== "plain";
    transcriptText.setAttribute("role", "tabpanel");
    transcriptText.setAttribute("aria-labelledby", "output-tab-plain");
    tabs.children[0].setAttribute("aria-controls", "transcriptText");
    panel.hidden = active === "plain";
    panel.setAttribute("aria-labelledby", `output-tab-${active}`);
    actions.replaceChildren();
    if (active === "plain") return;
    const output = outputs.find(item => item.format === active);
    panel.style.whiteSpace = "pre-wrap";
    panel.textContent = output?.text || "No output generated yet. Select this format and click Generate selected outputs.";
    if (output && output.status !== "done") panel.textContent = (output.text ? output.text + "\n\n" : "") + (output.status === "failed" ? output.error : `Output ${output.status}…`);
    const retry = document.createElement("button"); retry.type = "button";
    retry.textContent = output?.status === "failed" ? "Retry" : output?.status === "done" ? "Regenerate" : "Generate";
    retry.disabled = busy || ["queued", "generating"].includes(output?.status);
    retry.addEventListener("click", () => requestOutputs([active])); actions.append(retry);
    if (output?.status === "done") {
      for (const extension of ["txt", "docx"]) {
        const button = document.createElement("button"); button.type = "button"; button.textContent = `Download .${extension}`;
        button.addEventListener("click", async () => {
          button.disabled = true;
          try {
            const response = await fetch(`${base}/outputs/${active}/download/${extension}`);
            if (!response.ok) throw new Error((await response.json()).error || "Download failed.");
            const url = URL.createObjectURL(await response.blob());
            const link = document.createElement("a"); link.href = url; link.download = `${$("transcriptFilename").textContent.replace(/\.[^.]+$/, "")}-${active}.${extension}`;
            link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
          } catch (error) { status.textContent = error.message; }
          finally { button.disabled = false; }
        }); actions.append(button);
      }
    }
  }
  async function refresh() {
    clearTimeout(timer);
    try {
      const updated = await api(base + "/outputs");
      if (JSON.stringify(updated) !== JSON.stringify(outputs)) { outputs = updated; render(); }
    }
    catch (error) { status.textContent = error.message; }
    if (!stopped) timer = setTimeout(refresh, 4000);
  }
  async function requestOutputs(formats) {
    if (busy) return;
    busy = true; $("generateOutputs").disabled = true;
    try {
      await api(base + "/output-preferences", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(controls.get())});
      for (const format of formats) await api(`${base}/outputs/${format}`, {method: "POST"});
      status.textContent = formats.length ? "Outputs queued. You can leave this page and return later." : "Preferences saved. Plain transcript and caption downloads remain available.";
      if (formats.length) active = formats[0];
    } catch (error) { status.textContent = error.message; }
    finally { busy = false; $("generateOutputs").disabled = false; render(); await refresh(); }
  }
  $("generateOutputs").addEventListener("click", () => requestOutputs(controls.get().formats));
  window.addEventListener("pagehide", () => { stopped = true; clearTimeout(timer); }, {once: true});
  render();
  await refresh();
}
