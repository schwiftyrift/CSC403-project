export const defaults = {general: [], lecture: ["summary", "topics"], video: [], notes: ["study_guide"]};
export const labels = {summary: "Summary", topics: "Important topics", study_guide: "Study guide"};

export function outputControls(container, changed = () => {}) {
  const label = document.createElement("label");
  label.textContent = "Content type ";
  const select = document.createElement("select");
  for (const [value, text] of Object.entries({general: "General transcription", lecture: "Lecture", video: "Video captions", notes: "Notes"})) {
    const option = document.createElement("option");
    option.value = value; option.textContent = text; select.append(option);
  }
  label.append(select);
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
  hint.textContent = "Video captions use the existing SRT and VTT downloads in Your uploads. Study outputs are generated in English.";
  select.addEventListener("change", () => {
    for (const [key, check] of Object.entries(checks)) check.checked = defaults[select.value].includes(key);
    changed(get());
  });
  function get() { return {content_type: select.value, formats: Object.keys(checks).filter(key => checks[key].checked)}; }
  function set(data) {
    select.value = data.content_type;
    for (const [key, check] of Object.entries(checks)) check.checked = data.formats.includes(key);
  }
  container.append(label, fieldset, hint);
  return {get, set};
}
