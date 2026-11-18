export const defaults = {general: [], lecture: [], video: [], notes: []};
export const labels = {summary: "Summary", topics: "Important topics", study_guide: "Study guide", captions: "Video captions"};

export function outputControls(container, changed = () => {}) {
  const fieldset = document.createElement("fieldset");
  const legend = document.createElement("legend"); legend.textContent = "Additional outputs (plain transcript always included)";
  fieldset.append(legend);
  const checks = {};
  for (const [value, text] of Object.entries(labels)) {
    const line = document.createElement("label");
    const check = document.createElement("input"); check.type = "checkbox"; check.value = value;
    line.append(check, document.createTextNode(" " + text + " "));
    fieldset.append(line); checks[value] = check;
    check.addEventListener("change", () => changed(get()));
  }
  const hint = document.createElement("p");
  hint.textContent = "Select additional outputs, then click Generate selected outputs. Saved results remain available. Text outputs download as TXT or DOCX; video captions download as SRT or VTT.";
  function get() { return {content_type: "general", formats: Object.keys(checks).filter(key => checks[key].checked)}; }
  function set(data) {
    for (const [key, check] of Object.entries(checks)) check.checked = data.formats.includes(key);
  }
  container.append(fieldset, hint);
  return {get, set};
}
