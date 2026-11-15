// Sewing floor: the cutting buffer, every sewing line as a conveyor with its bundles, and the
// Sewn dock. Drag a bundle (or pick it with Enter / a tap, then choose a place) to issue it to
// a line, move it to another line or mark it sewn. The server applies the same rules as the
// bundle forms. Used on the factory map and the shop floor page.
(function () {
  "use strict";
  var REFRESH_MS = 15000;
  function text(tag, value, cls) { var n = document.createElement(tag); n.textContent = value; if (cls) n.className = cls; return n; }
  function fetchJSON(url) {
    return fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }
  var floorSection = document.querySelector(".floor-section");
  var linesNode = document.querySelector("[data-lines]");
  var pile = document.querySelector('[data-pile="buffer"]');
  var toast = document.querySelector("[data-toast]");
  var siteId = null, canMove = false, dragging = null, picked = null;

  function say(message, bad) {
    if (!toast) return;
    toast.textContent = message; toast.className = "floor-toast is-shown" + (bad ? " is-bad" : "");
    window.clearTimeout(say.timer); say.timer = window.setTimeout(function () { toast.className = "floor-toast"; }, 4200);
  }
  function boxNode(b, from) {
    var n = document.createElement("button");
    var c = b.client;
    n.type = "button"; n.className = "bundle-box" + (c ? " has-client" : "");
    n.setAttribute("data-id", b.id); n.setAttribute("data-version", b.version); n.setAttribute("data-from", from);
    var about = (c ? c.client + ", " : "") + "bundle " + b.number + ", size " + b.size + ", " + b.pieces + " pieces";
    n.setAttribute("aria-label", about + (canMove ? ". Enter to pick up." : ""));
    n.title = (c ? c.client + "\n" : "") + b.number + " · " + b.order + (b.style ? " · " + b.style : "") +
      (b.colour ? " · " + b.colour : "") + "\nSize " + b.size + " · " + b.pieces + " pcs";
    if (c) {
      // Colours come from the server as #rrggbb; set through the CSSOM (allowed by the CSP).
      n.style.setProperty("--client", c.colour);
      n.style.setProperty("--client-ink", c.ink);
      var label = document.createElement("span"); label.className = "box-label"; label.setAttribute("aria-hidden", "true");
      if (c.logo) {
        var img = document.createElement("img");
        img.src = c.logo; img.alt = ""; img.width = 16; img.height = 16; img.loading = "lazy"; img.draggable = false;
        label.appendChild(img);
      }
      label.appendChild(text("span", c.short));
      n.appendChild(label);
    }
    n.appendChild(text("span", b.size, "box-size"));
    n.appendChild(text("span", b.pieces + " pcs", "box-pcs"));
    if (!canMove) n.disabled = true;
    return n;
  }
  function renderFloor(data) {
    canMove = !!data.can_move;
    floorSection.classList.toggle("can-move", canMove);
    pile.textContent = "";
    if (!data.buffer.length) pile.appendChild(text("p", "Nothing waiting at cutting.", "fine-print"));
    data.buffer.forEach(function (b) { pile.appendChild(boxNode(b, "buffer")); });
    linesNode.textContent = "";
    data.lines.forEach(function (line) {
      var li = document.createElement("li");
      li.className = "floor-line drop-zone" + (line.down ? " has-down" : "");
      li.setAttribute("data-drop", "line"); li.setAttribute("data-line", line.id); li.tabIndex = 0;
      li.setAttribute("aria-label", line.name + " " + line.code + ": " + line.bundles.length + " bundles" + (canMove ? ". Enter to drop a picked bundle here." : ""));
      var head = document.createElement("div"); head.className = "line-head";
      head.appendChild(text("strong", line.code));
      head.appendChild(text("span", line.style || "no style", "fine-print"));
      var lights = document.createElement("span"); lights.className = "line-lights"; lights.setAttribute("aria-hidden", "true");
      var total = Math.min(14, line.running + line.idle + line.down);
      for (var i = 0; i < total; i += 1) {
        var cls = i < line.down ? "l-down" : (i < line.down + line.idle ? "l-idle" : "l-run");
        lights.appendChild(text("i", "", cls));
      }
      head.appendChild(lights);
      head.appendChild(text("span", (line.good ? line.good.toLocaleString() + " good" : "no output yet") + (line.efficiency !== null ? " · " + line.efficiency + "%" : ""), "line-figures"));
      li.appendChild(head);
      var belt = document.createElement("div"); belt.className = "line-belt";
      if (!line.bundles.length) belt.appendChild(text("span", "Empty: drop work here", "belt-empty"));
      line.bundles.forEach(function (b) { belt.appendChild(boxNode(b, "line:" + line.id)); });
      li.appendChild(belt);
      li.appendChild(text("span", line.pieces_on_line + " pcs waiting", "line-wip"));
      linesNode.appendChild(li);
    });
  }
  function refreshFloor() {
    if (!floorSection || !siteId || dragging || document.hidden) return;
    fetchJSON(floorSection.getAttribute("data-floor-source") + "?site=" + encodeURIComponent(siteId))
      .then(renderFloor).catch(function () { say("Could not load the sewing floor; retrying.", true); });
  }
  function move(box, zone) {
    var from = box.getAttribute("data-from");
    var target = zone.getAttribute("data-drop");
    var step = null, lineId = null;
    if (target === "line") {
      lineId = zone.getAttribute("data-line");
      if (from === "buffer") step = "issue";
      else if (from !== "line:" + lineId) step = "transfer";
    } else if (target === "sewn" && from.indexOf("line:") === 0) step = "sewn";
    if (!step) { say(target === "sewn" ? "Only bundles on a line can be marked sewn." : "Drop the bundle on a different line.", true); return; }
    box.classList.add("is-busy");
    fetch(floorSection.getAttribute("data-move-base") + box.getAttribute("data-id"), {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": floorSection.getAttribute("data-csrf") },
      body: JSON.stringify({ step: step, line_id: lineId, version: box.getAttribute("data-version") })
    }).then(function (r) { return r.json().then(function (body) { return { ok: r.ok, body: body }; }); })
      .then(function (res) {
        say(res.ok ? res.body.message : (res.body.error || "That move was refused."), !res.ok);
        refreshFloor(); window.dispatchEvent(new Event("factory:changed"));
      }).catch(function () { say("The move did not reach the server; nothing changed.", true); box.classList.remove("is-busy"); });
  }

  // Pointer dragging works for mouse, pen and touch.
  function zoneAt(x, y) { var n = document.elementFromPoint(x, y); return n ? n.closest(".drop-zone") : null; }
  function clearTargets() { document.querySelectorAll(".drop-zone.is-target").forEach(function (z) { z.classList.remove("is-target"); }); }
  if (floorSection) {
    floorSection.addEventListener("pointerdown", function (event) {
      var box = event.target.closest(".bundle-box");
      if (!box || !canMove || box.disabled) return;
      dragging = { box: box, x: event.clientX, y: event.clientY, ghost: null, id: event.pointerId };
    });
    document.addEventListener("pointermove", function (event) {
      if (!dragging || event.pointerId !== dragging.id) return;
      if (!dragging.ghost) {
        if (Math.abs(event.clientX - dragging.x) + Math.abs(event.clientY - dragging.y) < 6) return;
        dragging.ghost = dragging.box.cloneNode(true); dragging.ghost.className = "bundle-box is-ghost";
        document.body.appendChild(dragging.ghost); dragging.box.classList.add("is-lifted");
        cancelPick();
      }
      event.preventDefault();
      dragging.ghost.style.transform = "translate(" + (event.clientX - 22) + "px," + (event.clientY - 22) + "px) rotate(-6deg)";
      clearTargets(); var zone = zoneAt(event.clientX, event.clientY); if (zone) zone.classList.add("is-target");
    }, { passive: false });
    document.addEventListener("pointerup", function (event) {
      if (!dragging || event.pointerId !== dragging.id) return;
      var d = dragging; dragging = null; clearTargets();
      if (!d.ghost) { pick(d.box); return; }
      d.ghost.remove(); d.box.classList.remove("is-lifted");
      var zone = zoneAt(event.clientX, event.clientY);
      if (zone) move(d.box, zone);
    });
    document.addEventListener("pointercancel", function () {
      if (dragging && dragging.ghost) { dragging.ghost.remove(); dragging.box.classList.remove("is-lifted"); }
      dragging = null; clearTargets();
    });
    // Keyboard and tap-tap: pick a bundle, then choose a line or the Sewn dock.
    floorSection.addEventListener("keydown", function (event) {
      if (event.key !== "Enter" && event.key !== " ") return;
      var box = event.target.closest(".bundle-box");
      if (box) { event.preventDefault(); pick(box); return; }
      var zone = event.target.closest(".drop-zone");
      if (zone && picked) { event.preventDefault(); var p = picked; cancelPick(); move(p, zone); }
    });
    floorSection.addEventListener("click", function (event) {
      if (!picked || event.target.closest(".bundle-box")) return;
      var zone = event.target.closest(".drop-zone");
      if (zone) { var p = picked; cancelPick(); move(p, zone); }
    });
    // Site tabs.
    document.querySelectorAll("[data-site-tabs] a").forEach(function (tab, index) {
      if (index === 0) siteId = tab.getAttribute("data-site");
      tab.addEventListener("click", function (event) {
        event.preventDefault();
        document.querySelectorAll("[data-site-tabs] a").forEach(function (t) { t.removeAttribute("aria-current"); });
        tab.setAttribute("aria-current", "page");
        siteId = tab.getAttribute("data-site"); refreshFloor();
      });
    });
  }
  function pick(box) {
    if (!canMove) return;
    if (picked === box) { cancelPick(); return; }
    cancelPick(); picked = box; box.classList.add("is-picked"); box.setAttribute("aria-pressed", "true");
    floorSection.classList.add("is-picking");
    say("Bundle picked up: choose a line or Sewn. Escape to cancel.");
  }
  function cancelPick() {
    if (!picked) return;
    picked.classList.remove("is-picked"); picked.removeAttribute("aria-pressed"); picked = null;
    if (floorSection) floorSection.classList.remove("is-picking");
  }


  if (!floorSection) return;
  refreshFloor();
  window.setInterval(refreshFloor, REFRESH_MS);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refreshFloor(); });
})();
