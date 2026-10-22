const form = document.getElementById("loginContainer");
const password = document.getElementById("password");
const showPassword = document.getElementById("showPassword");
const accountStatus = document.getElementById("accountStatus");

showPassword.addEventListener("click", () => {
  const visible = password.type === "password";
  password.type = visible ? "text" : "password";
  showPassword.textContent = visible ? "Hide" : "Show";
  showPassword.setAttribute("aria-pressed", String(visible));
});

form.addEventListener("submit", async event => {
  event.preventDefault();
  const buttons = form.querySelectorAll("button");
  buttons.forEach(button => button.disabled = true);
  accountStatus.className = "";
  accountStatus.textContent = "Signing in...";
  try {
    const action = event.submitter?.id === "register" ? "register" : "login";
    const response = await fetch(`/auth/${action}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({email: document.getElementById("email").value, password: password.value})
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "Unable to sign in");
    password.value = "";
    window.location.replace("/");
  } catch (error) {
    accountStatus.textContent = error.message;
    accountStatus.className = "error";
  } finally {
    buttons.forEach(button => button.disabled = false);
  }
});
