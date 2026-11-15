// Planning board: filter orders, drag an order card to another priority lane, or change its
// sewing lines. Every change is previewed first (nothing saved), then applied on request by
// the same planning service as the order screen, which re-plans every open order.
(function () {
  "use strict";
  var lanes = document.querySelector("[data-plan-lanes]");
  if (!lanes) return;
  var base = lanes.getAttribute("data-preview-base");
  var csrf = lanes.getAttribute("data-csrf");
  var canPlan = lanes.classList.contains("can-plan");
  var drawer = document.querySelector("[data-plan-drawer]");
  var drawerTitle = drawer.querySelector("[data-drawer-title]");
  var drawerBody = drawer.querySelector("[data-drawer-body]");
  var applyButton = drawer.querySelector("[data-drawer-apply]");
  var toast = document.querySelector("[data-plan-toast]");
  var pending = null, dragging = null, picked = null;
  var LANES = { 1: "most urgent", 2: "high", 3: "normal", 4: "low", 5: "fill-in" };

  function say(message, bad) {
    toast.textContent = message;
    toast.className = "floor-toast is-shown" + (bad ? " is-bad" : "");
    window.clearTimeout(say.timer);
    say.timer = window.setTimeout(function () { toast.className = "floor-toast"; }, 4200);
  }
  function el(tag, text, cls) {
    var n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  }

  // ---------- Filters: client, text and late only ----------
  var search = document.querySelector("[data-plan-search]");
  var late = document.querySelector("[data-plan-late]");
  var client = "";
  function filter() {
    var words = (search && search.value || "").trim().toLowerCase();
    var lateOnly = late && late.checked;
    document.querySelectorAll(".plan-card, [data-plan-row]").forEach(function (n) {
      var show = (!client || n.getAttribute("data-client") === client) &&
        (!words || n.getAttribute("data-text").indexOf(words) !== -1) &&
        (!lateOnly || n.getAttribute("data-late") === "1");
      n.hidden = !show;
    });
    document.querySelectorAll(".plan-lane").forEach(function (lane) {
      var visible = lane.querySelectorAll(".plan-card:not([hidden])").length;
      lane.querySelector(".count-pill").textContent = visible;
    });
  }
  document.querySelectorAll("[data-plan-client]").forEach(function (b) {
    b.addEventListener("click", function () {
      client = b.getAttribute("data-plan-client");
      document.querySelectorAll("[data-plan-client]").forEach(function (o) {
        var on = o === b;
        o.classList.toggle("is-on", on);
        o.setAttribute("aria-pressed", on ? "true" : "false");
      });
      filter();
    });
  });
  if (search) search.addEventListener("input", filter);
  if (late) late.addEventListener("change", filter);

  // ---------- Preview, then apply ----------
  function preview(card, priority, lines) {
    var url = base + card.getAttribute("data-order") + "/preview.json?priority=" + priority + "&lines=" + lines;
    card.classList.add("is-busy");
    fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { return r.json().then(function (body) { return { ok: r.ok, body: body }; }); })
      .then(function (res) {
        card.classList.remove("is-busy");
        if (!res.ok) { say(res.body.error || "Could not preview that change.", true); return; }
        showDrawer(card, res.body);
      })
      .catch(function () { card.classList.remove("is-busy"); say("Could not reach the server; try again.", true); });
  }
  function showDrawer(card, p) {
    pending = { card: card, priority: p.priority, lines: p.lines, version: p.version };
    drawerTitle.textContent = p.reference + ": " + LANES[p.priority] + ", " + p.lines + " line" + (p.lines !== 1 ? "s" : "");
    drawerBody.textContent = "";
    var finish = el("p");
    if (p.finish_text) {
      finish.appendChild(document.createTextNode("Finishes "));
      finish.appendChild(el("strong", p.finish_text));
      if (p.was_text && p.was_text !== p.finish_text) finish.appendChild(document.createTextNode(" (now " + p.was_text + ")"));
      finish.appendChild(document.createTextNode(". "));
      finish.appendChild(el("span", p.slack < 0 ? (-p.slack) + " days late" : p.slack + " days spare", p.slack < 0 ? "tag tag-bad" : "tag tag-good"));
    } else {
      finish.textContent = "This change leaves the order without a complete plan.";
    }
    drawerBody.appendChild(finish);
    drawerBody.appendChild(el("p", p.newly_late.length ?
      "Other orders that would become late: " + p.newly_late.join(", ") + "." :
      "No other order becomes late.", p.newly_late.length ? "plan-warning" : "fine-print"));
    drawer.hidden = false;
    applyButton.focus();
  }
  function closeDrawer() {
    drawer.hidden = true;
    if (pending && pending.card) pending.card.focus();
    pending = null;
  }
  drawer.querySelector("[data-drawer-cancel]").addEventListener("click", closeDrawer);
  applyButton.addEventListener("click", function () {
    if (!pending) return;
    applyButton.disabled = true;
    fetch(base + pending.card.getAttribute("data-order") + "/change", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify({ priority: pending.priority, lines: pending.lines, version: pending.version })
    })
      .then(function (r) { return r.json().then(function (body) { return { ok: r.ok, body: body }; }); })
      .then(function (res) {
        applyButton.disabled = false;
        if (!res.ok) { say(res.body.error || "The change was refused.", true); closeDrawer(); return; }
        window.location.reload();
      })
      .catch(function () { applyButton.disabled = false; say("Could not reach the server; try again.", true); });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      if (!drawer.hidden) closeDrawer();
      if (picked) { picked.classList.remove("is-picked"); picked = null; say("Move cancelled."); }
    }
  });

  if (!canPlan) return;

  // ---------- Sewing lines stepper ----------
  lanes.addEventListener("click", function (e) {
    var step = e.target.closest("[data-lines-step]");
    if (!step) return;
    var card = step.closest(".plan-card");
    var lines = Number(card.getAttribute("data-lines")) + Number(step.getAttribute("data-lines-step"));
    if (lines < 1 || lines > 20) return;
    preview(card, card.getAttribute("data-priority"), lines);
  });

  function dropOn(card, lane) {
    if (!lane) return;
    var priority = lane.getAttribute("data-lane");
    if (priority === card.getAttribute("data-priority")) { say("That order is already in this lane."); return; }
    preview(card, priority, card.getAttribute("data-lines"));
  }
  function movable(card) { return card && !card.classList.contains("is-fixed"); }

  // ---------- Drag with mouse, pen or touch ----------
  lanes.addEventListener("pointerdown", function (e) {
    var card = e.target.closest(".plan-card");
    if (!movable(card) || e.button > 0 || e.target.closest("a, button, form")) return;
    // On touch screens drag by the grip, so the page still scrolls normally.
    if (e.pointerType === "touch" && !e.target.closest(".plan-grip")) return;
    dragging = { card: card, x: e.clientX, y: e.clientY, moved: false, ghost: null, over: null };
  });
  document.addEventListener("pointermove", function (e) {
    if (!dragging) return;
    if (!dragging.moved) {
      if (Math.abs(e.clientX - dragging.x) + Math.abs(e.clientY - dragging.y) < 6) return;
      dragging.moved = true;
      var box = dragging.card.getBoundingClientRect();
      dragging.ghost = dragging.card.cloneNode(true);
      dragging.ghost.className = "plan-card is-ghost";
      dragging.ghost.style.width = box.width + "px";
      dragging.dx = e.clientX - box.left; dragging.dy = e.clientY - box.top;
      document.body.appendChild(dragging.ghost);
      dragging.card.classList.add("is-lifted");
      lanes.classList.add("is-dragging");
    }
    e.preventDefault();
    dragging.ghost.style.transform = "translate(" + (e.clientX - dragging.dx) + "px," + (e.clientY - dragging.dy) + "px) rotate(-2deg)";
    var under = document.elementFromPoint(e.clientX, e.clientY);
    var lane = under && under.closest(".plan-lane");
    if (dragging.over && dragging.over !== lane) dragging.over.classList.remove("is-target");
    if (lane) lane.classList.add("is-target");
    dragging.over = lane;
  });
  function endDrag() {
    if (!dragging) return;
    var d = dragging; dragging = null;
    if (!d.moved) return;
    d.ghost.remove();
    d.card.classList.remove("is-lifted");
    lanes.classList.remove("is-dragging");
    if (d.over) d.over.classList.remove("is-target");
    dropOn(d.card, d.over);
  }
  document.addEventListener("pointerup", endDrag);
  document.addEventListener("pointercancel", function () {
    if (!dragging) return;
    if (dragging.ghost) dragging.ghost.remove();
    dragging.card.classList.remove("is-lifted");
    lanes.classList.remove("is-dragging");
    dragging = null;
  });

  // ---------- Keyboard and tap: pick a card, then choose a lane ----------
  lanes.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    if (e.target.closest("a, button, input")) return;
    var card = e.target.closest(".plan-card");
    var lane = e.target.closest(".plan-lane");
    if (card && e.target === card && movable(card)) {
      e.preventDefault();
      if (picked) picked.classList.remove("is-picked");
      picked = card; card.classList.add("is-picked");
      say("Picked " + card.querySelector(".plan-card-title a").textContent + ". Move to a lane and press Enter.");
    } else if (lane && e.target === lane && picked) {
      e.preventDefault();
      var chosen = picked; picked.classList.remove("is-picked"); picked = null;
      dropOn(chosen, lane);
    }
  });
})();
