const $ = (id) => document.getElementById(id);
let user = null;

function say(el, text, kind = "") { el.textContent = text; el.className = kind; }

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (response.status === 401) {
    window.location.replace("/login.html");
    throw new Error("Please log in again.");
  }
  if (!response.ok) {
    throw new Error(response.status >= 500 && !body.error ? "The service is having trouble right now. Try again in a few minutes."
      : body.error || "Request failed (" + response.status + ")");
  }
  return body;
}

$("changePassword").addEventListener("submit", async event => {
  event.preventDefault();
  const status = $("passwordStatus");
  if ($("newPassword").value !== $("confirmPassword").value) {
    say(status, "The new passwords don't match.", "error");
    return;
  }
  $("savePassword").disabled = true;
  say(status, "Saving...");
  try {
    await api("/auth/password", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({current_password: $("currentPassword").value, new_password: $("newPassword").value}),
    });
    $("changePassword").reset();
    say(status, "Password changed. Your other devices were signed out.", "ok");
  } catch (error) {
    say(status, error.message.startsWith("invalid request") ? "New passwords must be 12-128 characters." : error.message, "error");
  }
  $("savePassword").disabled = false;
});

$("emailResetLink").addEventListener("click", async () => {
  const status = $("resetStatus");
  $("emailResetLink").disabled = true;
  say(status, "Sending...");
  try {
    await api("/auth/password-reset-email", {method: "POST"});
    say(status, `Sent. Check ${user.email}, including the spam folder.`, "ok");
  } catch (error) {
    say(status, error.message, "error");
  }
  $("emailResetLink").disabled = false;
});

const menuButton = $("menuButton");
const sideBar = $("sidebar");
menuButton.addEventListener("click", () => {
  sideBar.classList.toggle("open");
  menuButton.classList.toggle("open");
  menuButton.setAttribute("aria-expanded", sideBar.classList.contains("open"));
});

$("logout").addEventListener("click", async () => {
  try { await api("/auth/logout", {method: "POST"}); window.location.replace("/login.html"); }
  catch (error) { say($("signedInAs"), error.message, "error"); }
});

api("/auth/me").then(me => {
  user = me;
  $("signedInAs").textContent = `Signed in as ${me.email}`;
  $("passwordCard").hidden = false;
  $("resetCard").hidden = false;
}).catch(error => say($("signedInAs"), error.message, "error"));
