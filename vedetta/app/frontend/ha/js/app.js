import { POLL_WATCHDOG_MS, redirecting } from "./core.js";
import { S, buildToolbar } from "./core-ui.js";
import { showDebugBadge } from "./debug.js";
import { updateScan } from "./filters.js";
import { fetchHist, fetchLog } from "./log.js";
import { connect, load, tick } from "./live.js";

function start() {
  buildToolbar();
  showDebugBadge();
  load();
  setInterval(updateScan, 1000);
  // Log open: reloads by itself (more often at the detailed level, where
  // the service entries arrive continuously).
  setInterval(function () {
    if (S.log.open && !document.hidden) fetchLog();
  }, 6000);
  setInterval(tick, 30000);
  setInterval(fetchHist, 300000);
  // If the stream goes quiet (mobile network, standby): beyond the maximum interval between
  // two cycles with no event at all it is reopened from scratch.
  setInterval(function () {
    if (S.es && S.loaded && Date.now() - S.conn.last > POLL_WATCHDOG_MS) connect();
  }, 15000);
  window.addEventListener("pagehide", function () { if (S.es) { S.es.close(); S.es = null; } });
  window.addEventListener("pageshow", function (e) { if (e.persisted && S.loaded) connect(); });
  let hiddenAt = 0;
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") { hiddenAt = Date.now(); return; }
    if (!S.loaded) { load(); return; }                       // it was in error: retry immediately
    tick();
    // After more than 30 s in the background (mobile app, tab in standby) stream and session
    // may be dead: everything is resynced, without showing errors if not needed.
    if (hiddenAt && Date.now() - hiddenAt > 30000) load({ silent: true });
    else if (!S.es) connect();
  });
  // Tab open for a long time with no event (not even the heartbeats every 15 s): session or network
  // dropped without the browser noticing.
  setInterval(function () {
    if (S.loaded && !document.hidden && Date.now() - S.conn.last > 3 * POLL_WATCHDOG_MS) load({ silent: true });
  }, 60000);
}
if (!redirecting) start();
