/* Apply the theme before the page paints: the saved choice, else the system setting. */
(function () {
  var theme = "light";
  try {
    var saved = localStorage.getItem("recalltrace-theme");
    if (saved === "light" || saved === "dark") {
      theme = saved;
    } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
      theme = "dark";
    }
  } catch (error) {
    /* Storage unavailable: fall back to light. */
  }
  document.documentElement.setAttribute("data-theme", theme);
  document.documentElement.setAttribute("data-bs-theme", theme);
})();
