// Confirms the token from the emailed link. The confirmation is a POST sent by this script, so
// link scanners that only download the page (some email providers do) cannot use the link up.
const statusEl = document.getElementById("status");
const RESULTS = {
  verified: "Your email is verified. Thanks!",
  already_verified: "Your email was already verified. You're all set.",
};

function show(text, kind) {
  statusEl.textContent = text;
  statusEl.className = kind;
  document.getElementById("continueLink").hidden = false;
}

async function verify() {
  const token = new URLSearchParams(window.location.search).get("token");
  if (!token) {
    show("This link is incomplete. Copy the whole link from the email, or log in and use Resend to get a new one.", "error");
    return;
  }
  try {
    const response = await fetch("/auth/verify", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token}),
    });
    const body = await response.json().catch(() => ({}));
    if (response.ok) show(RESULTS[body.status] || RESULTS.verified, "ok");
    else if (response.status >= 500) show("The service is having trouble right now. Reload this page in a few minutes to try again.", "error");
    else show(body.error || "This link could not be used. Log in and use Resend to get a new one.", "error");
  } catch (_) {
    show("Could not reach the server. Check your connection, then reload this page to try again.", "error");
  }
}

verify();
