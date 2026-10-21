// Sidebar menu, shared by every page that has #menuButton and #sidebar.
const menuButton = document.getElementById("menuButton");
const sideBar = document.getElementById("sidebar");

menuButton.addEventListener("click", () => {
  sideBar.classList.toggle("open");
  menuButton.classList.toggle("open");

  const isOpen = sideBar.classList.contains("open");

  menuButton.setAttribute("aria-expanded", isOpen);
});
