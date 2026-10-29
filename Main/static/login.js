import { $, api } from "./utils.js";

const form = $("loginContainer");
const password = $("password");
const showPassword = $("showPassword");
const accountStatus = $("accountStatus");

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
    
    await api(`/auth/${action}`, {
      method: "POST",
      headers:{
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        email: $("email").value,
        password: password.value
      })
    });
    
    password.value = "";
    window.location.replace("/");
  } catch (error) {
    accountStatus.textContent = error.message;
    accountStatus.className = "error";
  } finally {
    buttons.forEach(button => button.disabled = false);
  }
});
