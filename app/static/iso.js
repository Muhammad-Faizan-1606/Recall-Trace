// Factory map: an isometric 3D factory with live work flowing between departments, and an
// interactive sewing floor where bundles are dragged between the cutting buffer and lines.
// Figures come from the server (recorded data) every 15 seconds; nothing here is simulated.
(function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  var REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var REFRESH_MS = 15000;
  var stage = document.querySelector(".iso-stage");
  var svg = document.querySelector("[data-iso-scene]");
  var stamp = document.querySelector("[data-map-updated]");
  if (!stage || !svg) return;

  // ---------- Geometry ----------
  var U = 22, OX = 0, OY = 0, COS = Math.cos(Math.PI / 6), SIN = Math.sin(Math.PI / 6);
  function P(x, y, z) { return [OX + (x - y) * U * COS, OY + (x + y) * U * SIN - (z || 0) * U]; }
  function pts(list) { return list.map(function (p) { return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(" "); }
  function el(name, attrs, parent) {
    var node = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(node);
    return node;
  }

  // Footprint (x, y), size (w, d) and height (h) of each building, in process order.
  var ORDER = ["yarn", "knitting", "dyeing", "finishing", "cutting", "sewing", "packing", "shipped"];
  var LAYOUT = {
    yarn: { x: 0, y: 0, w: 3, d: 3, h: 2.2 },
    knitting: { x: 7.5, y: 0, w: 4.5, d: 4, h: 2.6 },
    dyeing: { x: 16.5, y: 0, w: 4, d: 4, h: 3.4 },
    finishing: { x: 25, y: 0.5, w: 4.5, d: 3, h: 2.4 },
    cutting: { x: 25.5, y: 12, w: 4, d: 3, h: 2.2 },
    sewing: { x: 14, y: 11.5, w: 6.5, d: 5, h: 2.6 },
    packing: { x: 6.5, y: 12, w: 3.5, d: 3, h: 2.2 },
    shipped: { x: 0, y: 12.3, w: 3, d: 2.4, h: 1.7 }
  };
  var TITLES = { yarn: "Yarn store", knitting: "Knitting", dyeing: "Dyeing", finishing: "Finishing", cutting: "Cutting", sewing: "Sewing", packing: "Packing", shipped: "Dispatch" };
  var layers = {};
  ["ground", "conveyors", "particles", "buildings", "labels"].forEach(function (n) { layers[n] = svg.querySelector('[data-layer="' + n + '"]'); });

  // Ground plate under the campus.
  (function ground() {
    var g = layers.ground;
    el("polygon", { "class": "iso-ground", points: pts([P(-3, -2), P(31.5, -2), P(31.5, 18.5), P(-3, 18.5)]) }, g);
    for (var i = -3; i <= 31.5; i += 2) el("line", { "class": "iso-grid", x1: P(i, -2)[0], y1: P(i, -2)[1], x2: P(i, 18.5)[0], y2: P(i, 18.5)[1] }, g);
    for (var j = -2; j <= 18.5; j += 2) el("line", { "class": "iso-grid", x1: P(-3, j)[0], y1: P(-3, j)[1], x2: P(31.5, j)[0], y2: P(31.5, j)[1] }, g);
  })();

  // Conveyor routes between consecutive buildings, along the ground.
  function route(a, b) {
    var A = LAYOUT[a], B = LAYOUT[b];
    if (a === "finishing") {
      var mx = A.x + A.w / 2, ex = B.x + B.w / 2;
      return [[mx, A.y + A.d], [mx, (A.y + A.d + B.y) / 2], [ex, (A.y + A.d + B.y) / 2], [ex, B.y]];
    }
    var forward = B.x > A.x;
    var sx = forward ? A.x + A.w : A.x, ex2 = forward ? B.x : B.x + B.w;
    var sy = A.y + A.d / 2, ey = B.y + B.d / 2, mid = (sx + ex2) / 2;
    return [[sx, sy], [mid, sy], [mid, ey], [ex2, ey]];
  }
  var conveyors = {};
  for (var i = 0; i < ORDER.length - 1; i += 1) {
    var from = ORDER[i], to = ORDER[i + 1];
    var path = route(from, to).map(function (p) { return P(p[0], p[1], 0.05); });
    var d = "M" + path.map(function (p) { return p[0].toFixed(1) + " " + p[1].toFixed(1); }).join(" L");
    el("path", { "class": "iso-belt", d: d }, layers.conveyors);
    var lane = el("path", { "class": "iso-lane", d: d }, layers.conveyors);
    conveyors[from] = { path: lane, length: 0, dots: [], amount: "", moving: false };
  }

  // Buildings: three shaded faces, a status roof, machine lights and a label.
  var buildings = {};
  ORDER.slice().sort(function (a, b) { return (LAYOUT[a].x + LAYOUT[a].y) - (LAYOUT[b].x + LAYOUT[b].y); }).forEach(function (key) {
    var b = LAYOUT[key], x = b.x, y = b.y, w = b.w, d = b.d, h = b.h;
    var g = el("g", { "class": "iso-building", tabindex: "0", role: "button", "data-key": key, "aria-label": TITLES[key] + ": open details" }, layers.buildings);
    el("polygon", { "class": "iso-shadow", points: pts([P(x + 0.3, y + 0.3), P(x + w + 0.6, y + 0.3), P(x + w + 0.6, y + d + 0.6), P(x + 0.3, y + d + 0.6)]) }, g);
    el("polygon", { "class": "face-left", points: pts([P(x, y + d, 0), P(x + w, y + d, 0), P(x + w, y + d, h), P(x, y + d, h)]) }, g);
    el("polygon", { "class": "face-right", points: pts([P(x + w, y, 0), P(x + w, y + d, 0), P(x + w, y + d, h), P(x + w, y, h)]) }, g);
    var roof = el("polygon", { "class": "face-top", points: pts([P(x, y, h), P(x + w, y, h), P(x + w, y + d, h), P(x, y + d, h)]) }, g);
    // Doors and windows give each block a sense of scale.
    el("polygon", { "class": "iso-door", points: pts([P(x + w * 0.4, y + d, 0), P(x + w * 0.6, y + d, 0), P(x + w * 0.6, y + d, h * 0.45), P(x + w * 0.4, y + d, h * 0.45)]) }, g);
    for (var k = 0; k < Math.floor(w); k += 1) {
      el("polygon", { "class": "iso-window", points: pts([P(x + k + 0.25, y + d, h * 0.62), P(x + k + 0.75, y + d, h * 0.62), P(x + k + 0.75, y + d, h * 0.82), P(x + k + 0.25, y + d, h * 0.82)]) }, g);
    }
    // Roof details by department.
    if (key === "dyeing") {
      [[0.9, 0.9], [2.1, 0.9], [0.9, 2.2], [2.1, 2.2]].forEach(function (o) {
        var c = P(x + o[0] + 0.4, y + o[1] + 0.4, h + 0.35);
        el("ellipse", { "class": "iso-vessel", cx: c[0], cy: c[1], rx: 11, ry: 6 }, g);
      });
      var chimney = P(x + w - 0.7, y + 0.5, h);
      el("rect", { "class": "iso-chimney", x: chimney[0] - 4, y: chimney[1] - 26, width: 8, height: 26, rx: 2 }, g);
      buildings.chimney = [chimney[0], chimney[1] - 28];
    } else if (key === "sewing") {
      for (var r = 0; r < 4; r += 1) {
        el("polygon", { "class": "iso-saw", points: pts([P(x + 0.5 + r * 1.5, y + 0.3, h), P(x + 1.6 + r * 1.5, y + 0.3, h), P(x + 0.5 + r * 1.5, y + 0.3, h + 0.6)]) }, g);
        el("polygon", { "class": "iso-saw-side", points: pts([P(x + 0.5 + r * 1.5, y + 0.3, h + 0.6), P(x + 0.5 + r * 1.5, y + d - 0.3, h + 0.6), P(x + 1.6 + r * 1.5, y + d - 0.3, h), P(x + 1.6 + r * 1.5, y + 0.3, h)]) }, g);
      }
    } else if (key === "shipped") {
      var t = P(x - 1.6, y + 0.4, 0);
      el("polygon", { "class": "iso-truck", points: pts([P(x - 2.4, y + 0.4, 0), P(x - 0.6, y + 0.4, 0), P(x - 0.6, y + 2, 0), P(x - 2.4, y + 2, 0)]) }, g);
      el("polygon", { "class": "iso-truck-box", points: pts([P(x - 2.4, y + 2, 0), P(x - 0.6, y + 2, 0), P(x - 0.6, y + 2, 1.3), P(x - 2.4, y + 2, 1.3)]) }, g);
      el("polygon", { "class": "iso-truck-top", points: pts([P(x - 2.4, y + 0.4, 1.3), P(x - 0.6, y + 0.4, 1.3), P(x - 0.6, y + 2, 1.3), P(x - 2.4, y + 2, 1.3)]) }, g);
      el("polygon", { "class": "iso-truck-box", points: pts([P(x - 0.6, y + 0.4, 0), P(x - 0.6, y + 2, 0), P(x - 0.6, y + 2, 1.3), P(x - 0.6, y + 0.4, 1.3)]) }, g);
      void t;
    }
    var lights = el("g", { "class": "iso-lights" }, g);
    var top = P(x + w / 2, y + d / 2, h + (key === "dyeing" ? 1.6 : 1.2));
    var label = el("g", { "class": "iso-label", transform: "translate(" + top[0].toFixed(1) + " " + top[1].toFixed(1) + ")" }, layers.labels);
    el("rect", { "class": "iso-label-bg", x: -64, y: -40, width: 128, height: 46, rx: 12 }, label);
    var dot = el("circle", { "class": "iso-state", cx: -50, cy: -26, r: 5 }, label);
    var name = el("text", { "class": "iso-name", x: -40, y: -22 }, label);
    name.textContent = TITLES[key];
    var figure = el("text", { "class": "iso-figure", x: -52, y: -3 }, label);
    buildings[key] = { group: g, roof: roof, lights: lights, label: label, dot: dot, figure: figure, box: b };
  });

  // Fit the drawing in the viewBox.
  (function fit() {
    var box = svg.getBBox();
    svg.setAttribute("viewBox", [box.x - 20, box.y - 30, box.width + 40, box.height + 50].map(function (v) { return v.toFixed(0); }).join(" "));
  })();
  Object.keys(conveyors).forEach(function (key) { conveyors[key].length = conveyors[key].path.getTotalLength(); });

  // Machine lights on the right-hand wall: up to 12, in proportion to running, idle and down.
  function drawLights(key, s) {
    var b = buildings[key]; if (!b) return;
    while (b.lights.firstChild) b.lights.removeChild(b.lights.firstChild);
    var total = s.running + s.idle + s.down;
    if (!total) return;
    var n = Math.min(12, total), down = s.down ? Math.max(1, Math.round(s.down / total * n)) : 0;
    var idle = s.idle ? Math.max(1, Math.round(s.idle / total * n)) : 0;
    var box = b.box, cols = Math.ceil(n / 2);
    for (var i = 0; i < n; i += 1) {
      var col = i % cols, row = Math.floor(i / cols);
      var p = P(box.x + box.w, box.y + 0.4 + (box.d - 0.8) * (col + 0.5) / cols, box.h * (0.3 + row * 0.25));
      var cls = i < down ? "light-down" : (i < down + idle ? "light-idle" : "light-run");
      el("circle", { "class": "iso-light " + cls, cx: p[0].toFixed(1), cy: p[1].toFixed(1), r: 3.4 }, b.lights);
    }
  }

  // ---------- Live data ----------
  var stations = {};
  function applyScene(data) {
    data.stations.forEach(function (s) {
      stations[s.key] = s;
      var b = buildings[s.key]; if (!b) return;
      b.roof.setAttribute("class", "face-top roof-" + s.state);
      b.dot.setAttribute("class", "iso-state state-" + s.state);
      b.figure.textContent = s.figure;
      b.group.setAttribute("aria-label", TITLES[s.key] + ": " + s.figure + " " + s.note + ". Open details.");
      drawLights(s.key, s);
    });
    data.flows.forEach(function (f) {
      var c = conveyors[f.source]; if (!c) return;
      c.amount = f.amount + " " + f.label;
      c.moving = !!f.moving;
      c.path.setAttribute("class", "iso-lane" + (f.moving ? " is-moving" : ""));
      var want = f.moving ? 5 : 0;
      while (c.dots.length < want) {
        c.dots.push({ t: c.dots.length / want, node: el("circle", { "class": "iso-dot", r: 4 }, layers.particles) });
      }
      while (c.dots.length > want) { var gone = c.dots.pop(); gone.node.remove(); }
      c.dots.forEach(function (dot, index) { dot.t = index / Math.max(1, want); });
    });
    smoke(stations.dyeing && stations.dyeing.figure !== "0");
    updateCards(data);
    if (openKey) showPanel(openKey);
  }

  // The department cards below the scene carry the same figures.
  function updateCards(data) {
    data.stations.forEach(function (s) {
      var item = document.querySelector('.factory-map [data-station="' + s.key + '"]');
      if (!item) return;
      ["figure", "note", "running", "idle", "down"].forEach(function (field) {
        var node = item.querySelector('[data-field="' + field + '"]');
        if (node && s[field] !== undefined && s[field] !== null) node.textContent = s[field];
      });
      if (s.load !== null) {
        var load = item.querySelector('[data-field="load"]'); if (load) load.textContent = Math.round(s.load);
        var bar = item.querySelector('[data-field="loadbar"]'); if (bar) bar.className = "load-bar lb-" + Math.min(20, Math.round(s.load / 100 * 14));
      }
      item.className = item.className.replace(/state-\w+/, "state-" + s.state);
    });
    data.flows.forEach(function (f) {
      var flow = document.querySelector('.factory-map [data-flow="' + f.source + '"]');
      if (!flow) return;
      var amount = flow.querySelector('[data-field="amount"]'); if (amount) amount.textContent = f.amount;
      flow.classList.toggle("is-moving", !!f.moving);
    });
  }

  // Smoke from the dye house chimney while batches are in the vessels.
  var puffs = [];
  function smoke(on) {
    if (!buildings.chimney) return;
    if (on && !puffs.length) {
      for (var i = 0; i < 4; i += 1) puffs.push({ t: i / 4, node: el("circle", { "class": "iso-smoke", r: 6 }, layers.labels) });
    } else if (!on) { puffs.forEach(function (p) { p.node.remove(); }); puffs = []; }
  }

  // ---------- Animation ----------
  var last = 0;
  function frame(now) {
    var dt = last ? Math.min(0.05, (now - last) / 1000) : 0; last = now;
    Object.keys(conveyors).forEach(function (key) {
      var c = conveyors[key];
      c.dots.forEach(function (dot) {
        if (!REDUCED) dot.t = (dot.t + dt * 0.12) % 1;
        var p = c.path.getPointAtLength(dot.t * c.length);
        dot.node.setAttribute("cx", p.x.toFixed(1)); dot.node.setAttribute("cy", p.y.toFixed(1));
      });
    });
    puffs.forEach(function (puff) {
      if (!REDUCED) puff.t = (puff.t + dt * 0.25) % 1;
      var base = buildings.chimney;
      puff.node.setAttribute("cx", (base[0] + puff.t * 18).toFixed(1));
      puff.node.setAttribute("cy", (base[1] - puff.t * 42).toFixed(1));
      puff.node.setAttribute("r", (5 + puff.t * 9).toFixed(1));
      puff.node.setAttribute("opacity", (0.55 * (1 - puff.t)).toFixed(2));
    });
    if (!REDUCED) window.requestAnimationFrame(frame);
  }

  // ---------- Details panel ----------
  var panel = document.querySelector("[data-iso-panel]");
  var panelBody = document.querySelector("[data-iso-panel-body]");
  var openKey = null;
  var DRILL = { knitting: 1, dyeing: 1, finishing: 1, cutting: 1, sewing: 1, packing: 1 };
  function text(tag, value, cls) { var n = document.createElement(tag); n.textContent = value; if (cls) n.className = cls; return n; }
  function showPanel(key) {
    var s = stations[key]; if (!s || !panel) return;
    openKey = key;
    panelBody.textContent = "";
    panelBody.appendChild(text("p", TITLES[key], "iso-panel-kicker"));
    panelBody.appendChild(text("p", s.figure, "iso-panel-figure"));
    panelBody.appendChild(text("p", s.note, "iso-panel-note"));
    if (s.running + s.idle + s.down) {
      var machines = document.createElement("p"); machines.className = "map-machines";
      [["m-run", s.running, " running"], ["m-idle", s.idle, " idle"], ["m-down", s.down, " down"]].forEach(function (m) {
        machines.appendChild(text("span", String(m[1]), m[0])); machines.appendChild(document.createTextNode(m[2]));
      });
      panelBody.appendChild(machines);
    }
    if (s.load !== null) panelBody.appendChild(text("p", Math.round(s.load) + "% of today's capacity booked", "fine-print"));
    var c = conveyors[key];
    if (c && c.amount) panelBody.appendChild(text("p", "Next: " + c.amount, "fine-print"));
    var links = document.createElement("p"); links.className = "iso-panel-links";
    if (DRILL[key]) {
      var a = document.createElement("a"); a.className = "btn btn-sm btn-primary";
      a.href = stage.getAttribute("data-station-base") + "/" + key; a.textContent = "See every machine";
      links.appendChild(a);
    }
    if (key === "sewing" && document.querySelector(".floor-section")) {
      var f = document.createElement("a"); f.className = "btn btn-sm btn-outline-secondary"; f.href = "#floor-heading"; f.textContent = "Move bundles between lines";
      links.appendChild(f);
    }
    if (links.childNodes.length) panelBody.appendChild(links);
    panel.hidden = false;
    Object.keys(buildings).forEach(function (k) { if (buildings[k].group) buildings[k].group.classList.toggle("is-selected", k === key); });
  }
  function hidePanel() {
    openKey = null; if (panel) panel.hidden = true;
    Object.keys(buildings).forEach(function (k) { if (buildings[k].group) buildings[k].group.classList.remove("is-selected"); });
  }
  layers.buildings.addEventListener("click", function (event) {
    var g = event.target.closest(".iso-building"); if (g) showPanel(g.getAttribute("data-key"));
  });
  layers.buildings.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    var g = event.target.closest(".iso-building"); if (!g) return;
    event.preventDefault(); showPanel(g.getAttribute("data-key"));
  });
  var close = document.querySelector("[data-iso-close]");
  if (close) close.addEventListener("click", hidePanel);
  document.addEventListener("keydown", function (event) { if (event.key === "Escape") { hidePanel(); cancelPick(); } });

  function fetchJSON(url) {
    return fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }
  function refreshScene() {
    if (document.hidden) return;
    fetchJSON(stage.getAttribute("data-map-source")).then(function (data) {
      applyScene(data);
      if (stamp) stamp.textContent = "Live · updated " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    }).catch(function () { if (stamp) stamp.textContent = "Offline · will retry"; });
  }

  // ---------- Sewing floor: drag bundles ----------
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
    n.type = "button"; n.className = "bundle-box";
    n.setAttribute("data-id", b.id); n.setAttribute("data-version", b.version); n.setAttribute("data-from", from);
    n.setAttribute("aria-label", "Bundle " + b.number + ", size " + b.size + ", " + b.pieces + " pieces" + (canMove ? ". Enter to pick up." : ""));
    n.title = b.number + " · " + b.order + " · size " + b.size + " · " + b.pieces + " pcs";
    n.appendChild(text("span", b.size, "box-size"));
    n.appendChild(text("span", String(b.pieces), "box-pcs"));
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
        refreshFloor(); refreshScene();
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

  refreshScene();
  refreshFloor();
  window.setInterval(function () { refreshScene(); refreshFloor(); }, REFRESH_MS);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) { refreshScene(); refreshFloor(); } });
  window.requestAnimationFrame(frame);
})();
