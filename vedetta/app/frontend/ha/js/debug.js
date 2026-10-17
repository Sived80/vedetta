import { ROOT, dlg, t } from "./core.js";
import { S, snack } from "./core-ui.js";
import { updateTile } from "./tile.js";
import { miAttrs, miDebug } from "./more-attrs.js";

// Origin and reliability of brand and name: data for analysis, not for the user. Enabled with
// 3 consecutive taps on the logo or the name in the title of the network card (or ?debug=1); while enabled a fixed
// "DEBUG" badge stays always visible. The API returns this data in any case.
export let DEBUG = /[?&]debug=1/.test(location.search) || (function () { try { return localStorage.getItem("vedetta-debug") === "1"; } catch (e) { return false; } })();
export function showDebugBadge() {
  ROOT.toggleAttribute("data-debug", DEBUG);
  let b = document.getElementById("debug-badge");
  if (DEBUG && !b) {
    b = document.createElement("div");
    b.id = "debug-badge"; b.setAttribute("role", "status");
    b.textContent = t("js.ha.debug.badge");
    document.body.appendChild(b);
  } else if (!DEBUG && b) { b.remove(); }
}
function setDebug(on) {
  DEBUG = !!on;
  ROOT.toggleAttribute("data-debug", DEBUG);
  try { localStorage.setItem("vedetta-debug", DEBUG ? "1" : "0"); } catch (e) { /* ignore */ }
  showDebugBadge();
  snack(t(DEBUG ? "js.ha.debug.on" : "js.ha.debug.off"), { kind: DEBUG ? "warning" : "success", ms: 3500 });
  S.tiles.forEach(function (el, id) { updateTile(id); });
  const od = S.open && S.devices.get(S.open);
  if (od && dlg.open && S.mi.view === "main") { miAttrs(od); miDebug(od); }
}
// 3 consecutive taps (within 2 s) on the logo or the name of the network card (.ch-title: since the header with the logo there is no .ch-text). Like Android's "build number":
// from the second tap a notice says how many are left, so it is clear the gesture was understood.
// In the capture phase (no other handler can stop the event) and with touch-action on the title
// (no double-tap zoom). From the keyboard: Ctrl+Shift+D.
var tapTimes = [];
function debugTap(e) {
  const el = e.target && e.target.closest ? e.target.closest("#card-network .card-header .ch-title") : null;
  if (!el) return;
  const now = Date.now();
  tapTimes = tapTimes.filter(function (x) { return now - x < 2000; });
  tapTimes.push(now);
  if (tapTimes.length >= 3) { tapTimes = []; setDebug(!DEBUG); }
  else if (tapTimes.length === 2) snack(t(DEBUG ? "js.ha.debug.more_off" : "js.ha.debug.more_on"), { ms: 1500 });
}
document.addEventListener("click", debugTap, true);
document.addEventListener("keydown", function (e) {
  if (e.ctrlKey && e.shiftKey && (e.key === "D" || e.key === "d")) { e.preventDefault(); setDebug(!DEBUG); }
});
