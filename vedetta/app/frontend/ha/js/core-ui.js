import { $, REDUCED, debounce, esc, icon, params, t } from "./core.js";
import { layout } from "./tile.js";
import { connect, schedule } from "./live.js";

// ------------------------------------------------------------------ state
export var S = {
  devices: new Map(),
  starHint: false,        // the server says the one-time star invitation may appear
  starMenu: false,        // it is in the menu that is open now
  update: null,           // what the summary says about a newer version of this add-on: {available, installed, latest} (null: not known)
  list: [],               // devices in IP order
  rev: 0,
  loaded: false,
  loadTries: 0,
  filter: { q: (params.get("q") || "").toLowerCase(), status: "all", type: null },
  poll: { known: false, interval: 30000, nextAt: 0 },
  activity: { search: false, rescanning: new Set() },
  dismissedNew: {},          // devices seen on the network that the user closed with "Cancel" (by MAC): the card does not come back for them
  newDevices: { count: 0, devices: [], init: false },
  refreshing: false,
  refreshStart: 0,
  changedSince: 0,
  scanBusy: false,
  hist: new Map(),        // id -> {from,to,segments,online_pct} (last 24 h)
  log: { events: [], limit: 30, ids: null, open: false, q: "",
         level: (function () { try { var v = localStorage.getItem("vedetta-ha-loglevel"); return v === "normal" || v === "detail" ? v : "min"; } catch (e) { return "min"; } })() },
  open: null,             // device shown in the "More info" dialog
  mi: { range: 24, view: "main", win: {}, token: 0 },
  conn: { ok: false, everOk: false, retryAt: 3000, last: 0 },
  es: null,
  retryTimer: null,
  tiles: new Map(),       // id -> tile element (reused across redraws)
  groups: {},
  chipsSig: "",
  scanned: (function () { try { return localStorage.getItem("vedetta-ha-scanned") === "1"; } catch (err) { return false; } })(),
  scanDone: false,  // true only after a scan completed in this page
  roles: { by_ip: {}, via: {}, names: {} },  // who does what on the network (roles.py)
  analysis: {},           // card id -> {state, reasons, badges} for the cards that are not identified (ha/analysis_view.py); a missing card is identified
  adding: null,           // add in progress: {ips, done}
  found: [],              // devices found by the last scan and not yet added
  missLimit: 3,           // consecutive failed checks before going offline (shared setting)
  dirty: { ids: new Set(), layout: false, net: false, more: false },
  flushQueued: false,
  gauge: 0
};

// ---------------------------------------------------------------- toast
// Snackbar at the bottom as in HA: text, optional action, disappears on its own.
export var snacksEl = $("snacks");
// The modal dialog sits in the browser's "top layer" and would cover the toasts:
// the container is a manual popover, brought back to the top every time.
export function raiseSnacks() {
  try {
    if (typeof snacksEl.showPopover !== "function") return;
    if (snacksEl.matches(":popover-open")) snacksEl.hidePopover();
    snacksEl.showPopover();
  } catch (err) { /* without the popover the toasts stay under the open dialog */ }
}
export function snack(message, opts) {
  opts = opts || {};
  const el = document.createElement("div");
  el.className = "snack" + (opts.kind ? " " + opts.kind : "");
  el.setAttribute("role", opts.kind === "error" ? "alert" : "status");
  const ic = opts.kind === "error" ? "alert-circle" : (opts.kind === "warning" ? "alert" : "");
  el.innerHTML = (ic ? '<span class="snack-icon">' + icon(ic) + "</span>" : "") +
    '<span class="snack-text">' + esc(message) + "</span>";
  let timer = null;
  function close() {
    clearTimeout(timer);
    el.classList.remove("show");
    setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 260);
  }
  if (opts.action) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "snack-action rp";
    b.textContent = opts.action.text;
    b.addEventListener("click", function () { close(); opts.action.fn(); });
    el.appendChild(b);
  }
  snacksEl.appendChild(el);
  while (snacksEl.children.length > 3) snacksEl.removeChild(snacksEl.firstChild);
  raiseSnacks();
  requestAnimationFrame(function () { el.classList.add("show"); });
  timer = setTimeout(close, opts.ms || (opts.kind === "error" ? 6000 : 4200));
  el.addEventListener("click", function (e) { if (!e.target.closest(".snack-action")) close(); });
}

// ------------------------------------------------------------- ripple
// Touch ripple as in HA components (mwc-ripple): a single delegation.
document.addEventListener("pointerdown", function (e) {
  if (REDUCED || e.button > 0) return;
  const host = e.target.closest ? e.target.closest(".rp") : null;
  if (!host || host.disabled || host.getAttribute("aria-disabled") === "true") return;
  const rect = host.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height) * 2;
  const wave = document.createElement("span");
  wave.className = "wave";
  wave.style.width = wave.style.height = size + "px";
  wave.style.left = (e.clientX - rect.left - size / 2) + "px";
  wave.style.top = (e.clientY - rect.top - size / 2) + "px";
  host.appendChild(wave);
  wave.addEventListener("animationend", function () { if (wave.parentNode) wave.parentNode.removeChild(wave); });
  setTimeout(function () { if (wave.parentNode) wave.parentNode.removeChild(wave); }, 900);
}, { passive: true });

// Counters that scroll toward the new value.
export function animateNumber(el, to) {
  if (!el) return;
  const from = el._v == null ? 0 : el._v;
  el._v = to;
  if (REDUCED || from === to) { el.textContent = String(to); return; }
  const start = performance.now(), dur = 450;
  cancelAnimationFrame(el._raf || 0);
  (function step(now) {
    const p = Math.min(1, (now - start) / dur);
    const e = 1 - Math.pow(1 - p, 3);
    el.textContent = String(Math.round(from + (to - from) * e));
    if (p < 1) el._raf = requestAnimationFrame(step);
  })(start);
}

// ---------------------------------------------------------------- bar
export var searchEl = $("search"), searchClear = $("search-clear");
export function buildToolbar() {
  $("search-icon").innerHTML = icon("magnify");
  searchEl.placeholder = t("js.ha.search");
  searchEl.setAttribute("aria-label", t("js.ha.search"));
  searchEl.value = params.get("q") || "";
  searchClear.innerHTML = icon("close");
  searchClear.title = t("js.ha.search_clear");
  searchClear.setAttribute("aria-label", t("js.ha.search_clear"));
  searchClear.hidden = !searchEl.value;
  $("btn-menu").innerHTML = icon("dots-vertical");
  $("btn-menu").title = t("js.ha.menu");
  $("btn-menu").setAttribute("aria-label", t("js.ha.menu"));
  $("btn-menu").classList.add("rp");
  searchClear.classList.add("rp");
  setConn(null);
}

var applySearch = debounce(function () {
  S.filter.q = searchEl.value.trim().toLowerCase();
  searchClear.hidden = !searchEl.value;
  S.dirty.layout = true;
  S.dirty.net = true;
  schedule();
}, 90);
searchEl.addEventListener("input", applySearch);
searchEl.addEventListener("keydown", function (e) {
  if (e.key === "Escape" && searchEl.value) { searchEl.value = ""; applySearch(); }
});
searchClear.addEventListener("click", function () { searchEl.value = ""; applySearch(); searchEl.focus(); });

// "Real time" dot and banner if the stream drops.
var bannerEl = $("banner");
// Pause of the periodic check: left = ms remaining (null = no expiry).
export function pauseLeft() {
  if (!S.poll.paused) return null;
  return S.poll.pausedAt == null ? Infinity : Math.max(0, S.poll.pausedAt - Date.now());
}
export function fmtLeft(ms) {
  const m = Math.ceil(ms / 60000);
  return m < 60 ? m + " min" : Math.floor(m / 60) + " h" + (m % 60 ? " " + (m % 60) + " min" : "");
}
// A single pill for the status: real time / paused / disconnected. Clickable.
export function renderLive() {
  const live = $("live"), text = $("live-text");
  if (!live) return;
  const ok = S.link === undefined ? null : S.link, left = pauseLeft();
  const paused = ok === true && S.poll.paused;
  live.classList.toggle("ok", ok === true && !paused);
  live.classList.toggle("paused", paused);
  // LED: blinking orange = timed pause; blinking red = stopped until
  // resumed; solid red = connection lost (class "bad").
  live.classList.toggle("timed", paused && left !== Infinity);
  live.classList.toggle("forever", paused && left === Infinity);
  live.classList.toggle("bad", ok === false);
  const label = ok === false ? t("js.ha.live.offline") : ok !== true ? t("js.ha.live.connecting")
    : paused ? (left === Infinity ? t("js.ha.pause.live") : t("js.ha.pause.live_left", { left: fmtLeft(left) })) : t("js.ha.live");
  if (text.textContent !== label) text.textContent = label;
  const title = paused ? t("js.ha.pause.resume_title") : t("js.ha.pause.title");
  if (live.title !== title) { live.title = title; live.setAttribute("aria-label", label + ". " + title); }
}
export function setConn(ok) {
  S.link = ok;
  renderLive();
  if (ok === true) {
    bannerEl.hidden = true;
    S.conn.everOk = true;
  } else if (ok === false) {
    bannerEl.hidden = false;
    bannerEl.innerHTML = icon("alert") + '<span class="banner-text">' + esc(t("js.ha.banner.lost")) + "</span>" +
      '<button type="button" class="btn text rp" id="banner-retry">' + esc(t("js.ha.banner.retry")) + "</button>";
    $("banner-retry").addEventListener("click", function () { connect(); });
  }
  S.conn.ok = ok === true;
}

