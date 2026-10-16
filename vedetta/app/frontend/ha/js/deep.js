import { $, REDUCED, api, dlg, esc, t } from "./core.js";
import { S, snack } from "./core-ui.js";
import { closePopups } from "./core-menu.js";
import { fetchHist } from "./log.js";
import { movingIcon, radarIcon } from "./net-icons.js";

// ------------------------------------------------- deep search
// Advanced search: system, open services, web page. Slow. From the menu (all devices, or the ones never analysed) it starts
// as soon as the choice is made; on a single device the confirmation can be switched off. While one is running no other
// can start: the buttons are off until it is over (the network search is independent and stays available).
export var SKIP_DEEP_KEY = "vedetta-ha-skip-deep";
export function skipDeepConfirm() { try { return localStorage.getItem(SKIP_DEEP_KEY) === "1"; } catch (err) { return false; } }
// Devices never analyzed in depth: scanned_at is written only by the deep search ("Last deep search").
function deepPending() { return Array.from(S.devices.values()).filter(function (d) { return !d.scanned_at && !d.deep_empty_at; }); }
var deepFlying = new Set();       // the devices whose search THIS page started and whose request is still open (a second device is queued by the server, not dropped)
function deepBusy() { return deepFlying.size > 0; }               // the top buttons wait until every request of this page is over
export function deepOneBusy(id) { return !!id && (S.activity.rescanning.has(id) || deepFlying.has(id)); }   // a device already being searched cannot be started again
export function syncDeepBusy() {
  const busy = deepBusy(), btn = $("btn-deepmenu");
  if (btn) { btn.disabled = busy; btn.title = busy ? t("js.ha.deep.busy") : ""; }
  if (busy && deepMenuEl && !deepMenuEl.hidden) toggleDeepMenu(false);
  if (typeof dlg !== "undefined" && dlg) {
    var sheetBtn = dlg.querySelector('[data-act="deep"]');
    if (sheetBtn) { var one = deepOneBusy(S.open); sheetBtn.disabled = one; sheetBtn.title = one ? t("js.ha.deep.busy") : ""; }
  }
}
export function runDeep(ids) {
  const fresh = ids.filter(function (id) { return !deepOneBusy(id); });
  if (!fresh.length) { if (ids.length) snack(t("js.ha.deep.already"), { kind: "warning" }); return; }      // never in silence
  fresh.forEach(function (id) { deepFlying.add(id); });
  syncDeepBusy();
  api("/api/devices/rescan", { method: "POST", json: { ids: fresh } }).then(function () {
    snack(t("js.ha.deep.done"), { kind: "success" });
    fetchHist();
  }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); }).then(function () { fresh.forEach(function (id) { deepFlying.delete(id); }); syncDeepBusy(); });
}
export var deepMenuEl = $("deep-menu");
// The badge: how many devices were never analysed in depth. It is ONE element that changes place: on the corner of the arrow
// while the menu is closed, in the "to analyse" tile while it is open. While it moves it lives in <body>, fixed, so nothing it
// crosses (overflow, stacking order, the menu itself) can hide it, and it lands in exactly the place it was measured for.
var deepBadge = document.createElement("span");
deepBadge.id = "deep-badge"; deepBadge.className = "deep-badge"; deepBadge.dataset.at = "corner"; deepBadge.hidden = true;
var deepFlight = null, deepFlightId = 0;
function deepSplit() { return document.querySelector(".gauge-side .split"); }
export function updateDeepBadge() {
  const split = deepSplit();
  if (!split) return;
  const n = S.loaded ? deepPending().length : 0;
  // it lives in the arrow of the network card: when that card is rebuilt (return to the app, reload) the badge is put back
  if (deepBadge.dataset.at === "corner" && deepBadge.parentNode !== split) split.appendChild(deepBadge);
  else if (!deepBadge.parentNode) split.appendChild(deepBadge);
  deepBadge.textContent = n > 99 ? "99+" : String(n);
  deepBadge.hidden = n === 0;
  const label = t("js.ha.deep.badge", { n: n });
  deepBadge.setAttribute("aria-label", label);
  deepBadge.title = label;
  const btn = $("btn-deepmenu");
  if (btn) btn.setAttribute("aria-label", t("js.ha.deep.title") + (n ? " · " + label : ""));
  const tile = deepMenuEl.querySelector('[data-deep="pending"]');
  if (tile) {
    tile.disabled = n === 0;
    tile.querySelector(".dm-s").textContent = t(n ? "js.ha.deep.tile_pending_sub" : "js.ha.deep.tile_pending_done");
  }
}
function moveDeepBadge(toSlot) {
  const b = deepBadge, dest = toSlot ? deepMenuEl.querySelector(".dm-slot") : deepSplit();
  if (!dest) return;
  const first = b.getBoundingClientRect();           // where it is now (also when it is half way)
  if (deepFlight) { deepFlight.cancel(); deepFlight = null; }
  deepFlightId++;
  b.style.left = b.style.top = "";
  dest.appendChild(b);
  b.dataset.at = toSlot ? "slot" : "corner";
  if (b.hidden || REDUCED || !b.animate || !first.width) return;
  const last = b.getBoundingClientRect(), id = deepFlightId;
  document.body.appendChild(b);
  b.dataset.at = "fly";
  b.style.left = last.left + "px";
  b.style.top = last.top + "px";
  const anim = b.animate([{ transform: "translate(" + (first.left - last.left) + "px," + (first.top - last.top) + "px)" }, { transform: "translate(0px,0px)" }],
    { duration: 320, easing: "cubic-bezier(0.2, 0, 0, 1)" });
  deepFlight = anim;
  function land() {
    if (id !== deepFlightId) return;               // another move started: this one is not the last
    b.style.left = b.style.top = "";
    dest.appendChild(b);
    b.dataset.at = toSlot ? "slot" : "corner";
    deepFlight = null;
  }
  anim.onfinish = land;
  anim.oncancel = land;
}
deepBadge.addEventListener("click", function (e) {
  if (deepBadge.dataset.at !== "corner" || deepBusy()) return;
  e.stopPropagation();
  toggleDeepMenu(true);
});
// One row of the menu: coloured icon, title, one line of explanation and, on the right, what the row holds (the badge lands there).
function deepItem(mode, color, iconHTML, title, sub, enabled, tail) {
  return '<button type="button" class="dm-item rp" role="menuitem" data-deep="' + mode + '" style="--c:' + color + '"' + (enabled ? "" : " disabled") + ">" +
    '<span class="dm-ic">' + iconHTML + '</span><span class="dm-tx"><span class="dm-t">' + esc(title) + '</span><span class="dm-s">' + esc(sub) + "</span></span>" + tail + "</button>";
}
export function toggleDeepMenu(open) {
  if (open === undefined) open = deepMenuEl.hidden;
  if (open === !deepMenuEl.hidden) return;         // already so: the badge must not move twice
  if (open && deepBusy()) return;                  // one search at a time
  if (open) {
    closePopups("deep");
    if (deepMenuEl.contains(deepBadge)) deepSplit().appendChild(deepBadge);      // never lost with the old tiles
    var pending = deepPending().length;
    deepMenuEl.innerHTML = '<div class="dm-head">' + radarIcon() + esc(t("js.ha.deep.title")) + "</div>" +
      deepItem("all", "var(--primary-color)", radarIcon(), t("js.ha.deep.tile_all"), t("js.ha.deep.tile_all_sub"), true, "") +
      deepItem("pending", "var(--warning-color)", movingIcon("magnify", "lens"), t("js.ha.deep.tile_pending"),
        t(pending ? "js.ha.deep.tile_pending_sub" : "js.ha.deep.tile_pending_done"), pending > 0, '<span class="dm-slot"></span>') +
      '<p class="dm-foot">' + esc(t("js.ha.deep.note", { hour: "03:00" })) + "</p>";
    var btn = $("btn-deepmenu"), r = btn.getBoundingClientRect();
    deepMenuEl.hidden = false;
    (deepMenuEl.getAnimations ? deepMenuEl.getAnimations() : []).forEach(function (a) { a.finish(); });   // measure the final place, not the opening one
    var mw = deepMenuEl.offsetWidth || 288;
    var cx = r.left + r.width / 2;
    var targetLeft = Math.round(cx - mw / 2);
    var left = Math.max(8, Math.min(window.innerWidth - mw - 8, targetLeft));
    deepMenuEl.style.top = Math.round(r.bottom + 6) + "px";
    deepMenuEl.style.left = left + "px";
    deepMenuEl.style.right = "auto";
    moveDeepBadge(true);
  } else {
    moveDeepBadge(false);
    deepMenuEl.hidden = true;
  }
  const b2 = $("btn-deepmenu"); if (b2) b2.setAttribute("aria-expanded", String(open));
}
// The choice in the menu starts the search: no confirmation (the badge and the tiles already say what it will do).
function startDeepAll(mode) {
  if (deepBusy()) { snack(t("js.ha.deep.busy"), { kind: "warning" }); return; }
  const list = mode === "pending" ? deepPending() : S.list;
  if (!list.length) { snack(t(mode === "pending" ? "js.ha.deep.menu_pending_none" : "js.ha.deep.none"), { kind: "warning" }); return; }
  runDeep(list.map(function (d) { return d.id; }));
}
document.addEventListener("click", function (e) {
  if (e.target.closest("#btn-deepmenu")) { e.stopPropagation(); toggleDeepMenu(); }
});
deepMenuEl.addEventListener("click", function (e) {
  const item = e.target.closest("[data-deep]");
  if (!item || item.disabled) return;
  toggleDeepMenu(false);
  startDeepAll(item.dataset.deep);
});
document.addEventListener("click", function (e) {
  if (!deepMenuEl.hidden && !e.target.closest("#deep-menu") && !e.target.closest("#btn-deepmenu")) toggleDeepMenu(false);
});
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape" && !deepMenuEl.hidden) toggleDeepMenu(false);
});
window.addEventListener("resize", function () { if (!deepMenuEl.hidden) toggleDeepMenu(false); });
