//Show password
const password = document.getElementById("password");
const showPassword = document.getElementById("showPassword");

showPassword.addEventListener("click", () => {
  if (password.type === "password") {
    password.type = "text";
    showPassword.textContent = "Hide";
  } else {
    password.type = "password";
    showPassword.textContent = "Show";
  }
});

const loginButton = document.getElementById("loginButton");

loginButton.addEventListener("click", () => {
  window.location.href = "/";
});
