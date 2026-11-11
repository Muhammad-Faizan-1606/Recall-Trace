/* Small progressive enhancements; every page works without this file. */
(function () {
  "use strict";

  // Ask before destructive actions (delete, archive, remove, revoke, reject).
  document.addEventListener("submit", function (event) {
    var button = event.submitter || event.target.querySelector("button[type=submit], button:not([type])");
    if (!button || !button.matches(".btn-outline-danger, .btn-danger")) return;
    var action = button.textContent.trim();
    if (!window.confirm(action + "?\n\nCheck this is the right record before continuing.")) {
      event.preventDefault();
    }
  });

  // Light/dark theme toggle, remembered in this browser.
  document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
    button.addEventListener("click", function () {
      var next = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
      document.documentElement.setAttribute("data-theme", next);
      document.documentElement.setAttribute("data-bs-theme", next);
      try { localStorage.setItem("recalltrace-theme", next); } catch (error) { /* ignore */ }
    });
  });

  // Slide-out sidebar on small screens.
  var sidebar = document.getElementById("sidebar");
  var backdrop = document.querySelector(".sidebar-backdrop");
  function setMenu(open) {
    if (!sidebar) return;
    document.body.classList.toggle("menu-open", open);
    if (backdrop) backdrop.hidden = !open;
    var opener = document.querySelector("[data-sidebar-open]");
    if (opener) opener.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) { var first = sidebar.querySelector("a, button"); if (first) first.focus(); }
  }
  document.querySelectorAll("[data-sidebar-open]").forEach(function (b) { b.addEventListener("click", function () { setMenu(true); }); });
  document.querySelectorAll("[data-sidebar-close]").forEach(function (b) { b.addEventListener("click", function () { setMenu(false); }); });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && document.body.classList.contains("menu-open")) setMenu(false);
    // "/" focuses the search box, as in many tools.
    if (event.key === "/" && !/input|textarea|select/i.test(document.activeElement.tagName)) {
      var search = document.getElementById("global-search");
      if (search) { event.preventDefault(); search.focus(); }
    }
  });

  // Quick filter for longer tables: hides rows that do not contain the typed text.
  document.querySelectorAll(".table-responsive").forEach(function (wrapper, index) {
    var table = wrapper.querySelector("table");
    var rows = table ? table.tBodies[0] && table.tBodies[0].rows : null;
    if (!rows || rows.length < 8) return;
    var label = document.createElement("label");
    label.className = "table-filter";
    var id = "table-filter-" + index;
    label.setAttribute("for", id);
    label.textContent = "Filter";
    var input = document.createElement("input");
    input.type = "search";
    input.id = id;
    input.className = "form-control form-control-sm";
    input.placeholder = "Type to filter " + rows.length + " rows";
    label.appendChild(input);
    wrapper.parentNode.insertBefore(label, wrapper);
    input.addEventListener("input", function () {
      var needle = input.value.trim().toLowerCase();
      Array.prototype.forEach.call(rows, function (row) {
        row.hidden = needle !== "" && row.textContent.toLowerCase().indexOf(needle) === -1;
      });
    });
  });
})();
