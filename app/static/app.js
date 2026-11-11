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
