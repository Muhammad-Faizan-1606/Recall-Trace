/* Apply the saved theme before the page paints (dark is the default). */
(function () {
  try {
    var saved = localStorage.getItem("recalltrace-theme");
    if (saved === "light" || saved === "dark") {
      document.documentElement.setAttribute("data-theme", saved);
      document.documentElement.setAttribute("data-bs-theme", saved);
    }
  } catch (error) {
    /* Storage unavailable: keep the default theme. */
  }
})();
