const form = document.getElementById("forgotForm");
const statusEl = document.getElementById("accountStatus");
const button = document.getElementById("sendLink");

function say(text, kind = "") { statusEl.textContent = text; statusEl.className = kind; }

form.addEventListener("submit", async event => {
  event.preventDefault();
  button.disabled = true;
  say("Sending...");
  try {
    const response = await fetch("/auth/password-reset-request", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({email: document.getElementById("email").value}),
    });
    const body = await response.json().catch(() => ({}));
    if (response.ok) say(body.message, "ok");
    else if (response.status >= 500) say("The service is having trouble right now. Try again in a few minutes.", "error");
    else say("Enter a valid email address.", "error");
  } catch (_) {
    say("Could not reach the server. Check your connection and try again.", "error");
  } finally {
    button.disabled = false;
  }
});
