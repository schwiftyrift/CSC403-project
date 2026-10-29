// The new password is only saved when the form is submitted, so link scanners that open
// the emailed link (some email providers do) cannot use it up.
const form = document.getElementById("resetForm");
const statusEl = document.getElementById("accountStatus");
const button = document.getElementById("savePassword");
const password = document.getElementById("password");
const confirmPassword = document.getElementById("confirm");
const token = new URLSearchParams(window.location.search).get("token");

function say(text, kind = "") { statusEl.textContent = text; statusEl.className = kind; }
function offerNewLink() { document.getElementById("requestNew").hidden = false; }

if (!token) {
  button.disabled = true;
  say("This link is incomplete. Copy the whole link from the email, or request a new one.", "error");
  offerNewLink();
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  if (password.value !== confirmPassword.value) {
    say("The passwords don't match.", "error");
    return;
  }
  button.disabled = true;
  say("Saving...");
  try {
    const response = await fetch("/auth/password-reset", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token, password: password.value}),
    });
    const body = await response.json().catch(() => ({}));
    if (response.ok) {
      password.value = confirmPassword.value = "";
      say("Your password was changed. Taking you to Transcript Service...", "ok");
      setTimeout(() => window.location.replace("/"), 1500);
      return;
    }
    if (response.status >= 500) say("The service is having trouble right now. Try again in a few minutes.", "error");
    else {
      say(body.error && body.error.includes("reset link") ? body.error : "Passwords must be 12-128 characters.", "error");
      if (body.error && body.error.includes("reset link")) offerNewLink();
    }
  } catch (_) {
    say("Could not reach the server. Check your connection and try again.", "error");
  }
  button.disabled = false;
});
