// Visual line: drag an operation chip onto another station to prepare a move.
(function () {
  "use strict";
  var floor = document.querySelector(".line-floor.is-editable");
  var form = document.querySelector("[data-move-form]");
  if (!floor || !form) return;
  var work = form.querySelector("#work");
  var target = form.querySelector("#to_station");
  var dragged = null;
  floor.addEventListener("dragstart", function (event) {
    var chip = event.target.closest(".op-chip");
    if (!chip) return;
    dragged = chip;
    chip.classList.add("is-dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", chip.dataset.from + ":" + chip.dataset.op);
  });
  floor.addEventListener("dragend", function () {
    if (dragged) dragged.classList.remove("is-dragging");
    floor.querySelectorAll(".is-target").forEach(function (n) { n.classList.remove("is-target"); });
  });
  floor.addEventListener("dragover", function (event) {
    var tile = event.target.closest(".station-tile");
    if (!tile || !dragged) return;
    event.preventDefault();
    floor.querySelectorAll(".is-target").forEach(function (n) { if (n !== tile) n.classList.remove("is-target"); });
    tile.classList.add("is-target");
  });
  floor.addEventListener("drop", function (event) {
    var tile = event.target.closest(".station-tile");
    if (!tile || !dragged) return;
    event.preventDefault();
    if (tile.dataset.station === dragged.dataset.from) return;
    work.value = dragged.dataset.from + ":" + dragged.dataset.op;
    target.value = tile.dataset.station;
    form.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
    form.querySelector("button[type=submit]").focus({ preventScroll: true });
  });
  // Keyboard and touch: pressing a chip selects it as the work to move.
  floor.addEventListener("click", function (event) {
    var chip = event.target.closest(".op-chip");
    if (!chip) return;
    work.value = chip.dataset.from + ":" + chip.dataset.op;
    target.focus();
  });
})();
