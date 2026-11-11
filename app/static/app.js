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

  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var root = document.documentElement;

  // Light/dark theme toggle, remembered in this browser. Where supported, the new
  // theme spreads out from the button as a circle.
  function applyTheme(next) {
    root.setAttribute("data-theme", next);
    root.setAttribute("data-bs-theme", next);
    try { localStorage.setItem("recalltrace-theme", next); } catch (error) { /* ignore */ }
  }
  document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
    button.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      if (!document.startViewTransition || reduceMotion) { applyTheme(next); return; }
      var box = button.getBoundingClientRect();
      var x = box.left + box.width / 2, y = box.top + box.height / 2;
      var radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
      root.classList.add("theme-switching");
      var transition = document.startViewTransition(function () { applyTheme(next); });
      transition.ready.then(function () {
        root.animate(
          { clipPath: ["circle(0px at " + x + "px " + y + "px)", "circle(" + radius + "px at " + x + "px " + y + "px)"] },
          { duration: 560, easing: "cubic-bezier(.16, 1, .3, 1)", pseudoElement: "::view-transition-new(root)" }
        );
      });
      transition.finished.then(function () { root.classList.remove("theme-switching"); });
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

  // The floating top bar gains depth once the page scrolls.
  var topbar = document.querySelector(".topbar");
  if (topbar) {
    var onScroll = function () { topbar.classList.toggle("is-scrolled", window.scrollY > 8); };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  // Whole table rows open their record when the first cell holds the record link.
  document.querySelectorAll(".table-responsive tbody tr").forEach(function (row) {
    var first = row.cells[0] && row.cells[0].querySelector("a[href]");
    if (!first || row.querySelector("form, button, input, select, textarea")) return;
    row.setAttribute("data-href", first.getAttribute("href"));
    row.addEventListener("click", function (event) {
      if (event.target.closest("a, button, input, select, textarea, summary, label")) return;
      if (window.getSelection && String(window.getSelection())) return;
      window.location.href = row.getAttribute("data-href");
    });
  });

  // Flash messages: a close button, and success notes leave on their own.
  document.querySelectorAll(".content > .alert").forEach(function (alert) {
    var close = document.createElement("button");
    close.type = "button";
    close.className = "alert-close";
    close.setAttribute("aria-label", "Dismiss message");
    close.textContent = "\u00d7";
    alert.appendChild(close);
    function dismiss() {
      alert.classList.add("is-leaving");
      window.setTimeout(function () { alert.remove(); }, reduceMotion ? 0 : 300);
    }
    close.addEventListener("click", dismiss);
    if (alert.classList.contains("alert-success")) window.setTimeout(dismiss, 6000);
  });

  if (reduceMotion) return;

  // Key figures count up once when the page opens.
  document.querySelectorAll(".facts dd").forEach(function (cell) {
    var target = cell.querySelector("a") || cell;
    var value = parseInt(target.textContent.trim(), 10);
    if (!(value > 0) || String(value) !== target.textContent.trim()) return;
    var start = null;
    target.textContent = "0";
    function step(time) {
      if (start === null) start = time;
      var progress = Math.min(1, (time - start) / 800);
      target.textContent = String(Math.round(value * (1 - Math.pow(1 - progress, 3))));
      if (progress < 1) window.requestAnimationFrame(step);
    }
    window.requestAnimationFrame(step);
  });

  // Blocks that start below the fold rise into view as they are reached.
  if ("IntersectionObserver" in window) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) { entry.target.classList.add("is-in"); observer.unobserve(entry.target); }
      });
    }, { rootMargin: "0px 0px -8% 0px" });
    document.querySelectorAll(".section, .split .rail > *, .directory > *, .result-groups > *, .facts, .feature").forEach(function (block) {
      if (block.getBoundingClientRect().top > window.innerHeight) {
        block.classList.add("reveal");
        observer.observe(block);
      }
    });    // Safety net: anything still waiting appears once the reader reaches the end.
    function revealRest() {
      if (window.scrollY + window.innerHeight < document.documentElement.scrollHeight - 40) return;
      document.querySelectorAll(".reveal:not(.is-in)").forEach(function (block) { block.classList.add("is-in"); });
    }
    window.addEventListener("scroll", revealRest, { passive: true });
    window.addEventListener("beforeprint", function () {
      document.querySelectorAll(".reveal").forEach(function (block) { block.classList.add("is-in"); });
    });
  }
})();
