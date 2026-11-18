import "./utils.js";

$("logout").addEventListener("click", async () => {
  try { await api("/auth/logout", {method: "POST"}); window.location.replace("/login.html"); }
  catch (error) { say(error.message, "error"); }
});
