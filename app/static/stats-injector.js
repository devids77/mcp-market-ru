/**
 * MCP Market Russia — live stats injector.
 * Replaces nodes [data-stat="companies|projects|tools|regions"] with values
 * from /api/dashboard/stats. Falls back to hardcoded text on any failure.
 */
(function () {
  "use strict";
  var ENDPOINT = "/api/dashboard/stats";
  var CACHE_KEY = "mcp_stats_v1";
  var TTL_MS = 5 * 60 * 1000;
  var FMT = new Intl.NumberFormat("ru-RU");

  function apply(stats) {
    if (!stats || typeof stats !== "object") return;
    var nodes = document.querySelectorAll("[data-stat]");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var val = stats[el.getAttribute("data-stat")];
      if (typeof val !== "number" || !isFinite(val)) continue;
      el.textContent = el.getAttribute("data-stat-format") === "raw"
        ? String(val) : FMT.format(val);
    }
  }
  function readCache() {
    try {
      var p = JSON.parse(sessionStorage.getItem(CACHE_KEY) || "null");
      return p && (Date.now() - p.t) < TTL_MS ? p.d : null;
    } catch (e) { return null; }
  }
  function writeCache(d) {
    try { sessionStorage.setItem(CACHE_KEY, JSON.stringify({ t: Date.now(), d: d })); }
    catch (e) {}
  }
  function load() {
    var c = readCache();
    if (c) { apply(c); return; }
    fetch(ENDPOINT, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) { writeCache(d); apply(d); } })
      .catch(function () {});
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load, { once: true });
  } else { load(); }
})();
