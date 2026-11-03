import { $, api } from "./utils.js"
import { showTranscript } from "./transcript-player.js";

const transcriptFilename = $("transcriptFilename");
const transcriptStatus = $("transcriptStatus");
const transcriptText = $("transcriptText");
api("/transcripts/latest")
    .then(data => {
        transcriptFilename.textContent = data.filename;
        transcriptText.textContent = data.text;
        transcriptStatus.textContent = "";
        showTranscript(transcriptText, data.job_id); // swaps in the player when the transcript has timestamps
    })
    .catch(error => {
        transcriptStatus.textContent = error.message;
        transcriptText.textContent = "";
    });