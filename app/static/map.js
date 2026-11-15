// Live factory map: refresh the figures every 30 seconds from the JSON feed.
(function () {
  "use strict";
  var map = document.querySelector("[data-map-source]");
  if (!map) return;
  var stamp = document.querySelector("[data-map-updated]");
  function setText(scope, field, value) {
    var node = scope.querySelector('[data-field="' + field + '"]');
    if (node && value !== undefined && value !== null) node.textContent = value;
  }
  function apply(data) {
    data.stations.forEach(function (s) {
      var item = map.querySelector('[data-station="' + s.key + '"]');
      if (!item) return;
      ["figure", "note", "running", "idle", "down"].forEach(function (field) { setText(item, field, s[field]); });
      if (s.load !== null) {
        setText(item, "load", Math.round(s.load));
        var bar = item.querySelector('[data-field="loadbar"]');
        if (bar) bar.className = "load-bar lb-" + Math.min(20, Math.round(s.load / 100 * 14));
      }
      item.className = item.className.replace(/state-\w+/, "state-" + s.state);
    });
    data.flows.forEach(function (f) {
      var flow = map.querySelector('[data-flow="' + f.source + '"]');
      if (!flow) return;
      setText(flow, "amount", f.amount);
      flow.classList.toggle("is-moving", !!f.moving);
    });
    if (stamp) {
      var now = new Date();
      stamp.textContent = "Live · updated " + now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
  }
  function refresh() {
    if (document.hidden) return;
    fetch(map.getAttribute("data-map-source"), { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { if (data) apply(data); })
      .catch(function () { if (stamp) stamp.textContent = "Offline · will retry"; });
  }
  window.setInterval(refresh, 30000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
})();
