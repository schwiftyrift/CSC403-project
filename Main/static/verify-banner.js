// Reminds signed-in users with an unverified email, with a button to send the link again.
// Self-contained so any page can include it with one script tag.
(async () => {
  let user;
  try {
    const response = await fetch("/auth/me");
    if (!response.ok) return; // signed out: nothing to show
    user = await response.json();
  } catch (_) {
    return;
  }
  if (user.email_verified !== false) return;

  const banner = document.createElement("section");
  banner.className = "card";
  banner.id = "verifyBanner";
  const text = document.createElement("p");
  text.textContent = `Please verify your email address. We sent a link to ${user.email}. If you can't find it, check your spam folder.`;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary";
  button.textContent = "Resend verification email";
  const status = document.createElement("p");
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");

  button.addEventListener("click", async () => {
    button.disabled = true;
    status.className = "";
    status.textContent = "Sending...";
    try {
      const response = await fetch("/auth/verification-email", {method: "POST"});
      const body = await response.json().catch(() => ({}));
      if (response.status === 409) { banner.remove(); return; } // verified in the meantime
      status.textContent = response.ok ? `Sent. Check ${user.email}, including the spam folder.`
        : body.error || "Could not send the email. Try again in a few minutes.";
      status.className = response.ok ? "ok" : "error";
    } catch (_) {
      status.textContent = "Could not reach the server. Try again in a few minutes.";
      status.className = "error";
    }
    button.disabled = false;
  });

  banner.append(text, button, status);
  const anchor = document.querySelector("main .sub") || document.querySelector("main h1");
  if (anchor) anchor.after(banner);
  else document.body.prepend(banner);
})();
