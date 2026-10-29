export const $ = (id) => document.getElementById(id);
let signedIn = false;


export function humanSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 ** 2) return (bytes / 1024).toFixed(1) + " KB";
  if (bytes < 1024 ** 3) return (bytes / 1024 ** 2).toFixed(1) + " MB";
  return (bytes / 1024 ** 3).toFixed(2) + " GB";
}

export async function api(url, options = {}) {
  const response = await fetch(url, options);
  const body = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    throw new Error(body.error || "Request failed");
  }
  return body;
}

const menuButton = document.getElementById("menuButton");
const sideBar = document.getElementById("sidebar");

if (menuButton && sideBar){
    menuButton.addEventListener("click", () => {
      sideBar.classList.toggle("open");
      menuButton.classList.toggle("open");
    
      const isOpen = sideBar.classList.contains("open");
    
      menuButton.setAttribute("aria-expanded", isOpen);
    });
}
const logoutButton = $("logout");
if (logoutButton){
    logoutButton.addEventListener("click", async () => {
      try { await api("/auth/logout", {method: "POST"}); window.location.replace("/login.html"); }
      catch (error) { 
            console.error(error)
       }
    });
}

export function say(element, text, kind = "") {
  if (!element) return;
  element.textContent = text;
  element.className = kind;
}

export function setAccount(user) {
  const signedIn = Boolean(user);

  const accountStatus = $("accountStatus");
  const loginLink = $("loginLink");
  const logout = $("logout");
  const history = $("history");

  if (accountStatus){
    accountStatus.textContent = signedIn ? `Signed in as ${user.email}` : "Sign in to upload files and view your history";
  }

  if (loginLink) {
    loginLink.hidden = signedIn;
  }

  if (logout) {
    logout.hidden = !signedIn;
  }

  if (history) {
    history.hidden = !signedIn;
  }

  return signedIn;
}