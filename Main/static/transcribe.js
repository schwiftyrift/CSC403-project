import { $, api } from "./utils.js"

const transcriptFilename = $("transcriptFilename");
const transcriptStatus = $("transcriptStatus");
const transcriptText = $("transcriptText");
api("/transcripts/latest")
    .then(data => {
        transcriptFilename.textContent = data.filename;
        transcriptText.textContent = data.text;
        transcriptStatus.textContent = "";
    })
    .catch(error => {
        transcriptStatus.textContent = error.message;
        transcriptText.textContent = "";
    });