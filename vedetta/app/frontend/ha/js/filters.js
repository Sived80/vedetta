import { $, REDUCED, api, esc, icon, t } from "./core.js";
import { S, animateNumber, renderLive, snack } from "./core-ui.js";
import { syncDeepBusy, updateDeepBadge } from "./deep.js";
import { newEl, renderNew } from "./new-devices.js";
import { schedule } from "./live.js";
import { bindGauge, gaugeHTML, paintCycle, paintGauge, paintNewDot } from "./net-gauge.js";
import { logoHTML, movingIcon } from "./net-icons.js";
import { mountTile, paintTile, sampleCycle, tileHTMLShell } from "./net-rotator.js";

// ------------------------------------------------------------ filters
// Chosen from the badges of the "Network" card (All, Online, Offline, Mobile) and from the segments of its circle (type).
export function matches(d) {
  const f = S.filter;
  if (f.status === "online" && !d.online) return false;
  if (f.status === "offline" && d.online) return false;
  if (f.status === "mobile" && !d.is_mobile) return false;
  if (f.type && d.type !== f.type) return false;
  if (f.q && d._hay.indexOf(f.q) < 0) return false;
  return true;
}
function counts() {
  const c = { total: S.list.length, online: 0, offline: 0, mobile: 0, types: {} };
  S.list.forEach(function (d) {
    if (d.online) c.online++; else c.offline++;
    if (d.is_mobile) c.mobile++;
    c.types[d.type] = (c.types[d.type] || 0) + 1;
  });
  return c;
}
function setFilter(kind, value) {
  if (kind === "status") S.filter.status = value;
  else S.filter.type = S.filter.type === value ? null : value;
  S.dirty.layout = true;
  S.dirty.net = true;
  schedule();
}

// ---------------------------------------------------------- "Network" card
export var netEl = $("card-network");
var FALLBACK_VERSION = "0.8.0";
function versionText() { return "v" + String(window.VEDETTA_VERSION || S.version || FALLBACK_VERSION).replace(/^v/i, ""); }

// Search, real-time status and settings: nodes created only once (with their
// handlers) and moved into the network card. If the card is rebuilt (resync
// after a service restart or a roles change) they must be put in a safe place first, otherwise they
// would vanish with the old content and the buttons would stop responding.
var NET_PARTS = null;
var BADGES = ["all", "online", "offline", "mobile"];
function headerHTML() {
  return '<div class="card-header"><div class="ch-title">' + logoHTML() + '<span id="net-title">Vedetta<sup id="net-ver">' + esc(versionText()) + "</sup></span></div>" +
    '<div class="card-tools" id="card-tools">' +
    '<button type="button" class="icon-btn touch rp" id="btn-refresh" title="' + esc(t("js.ha.refresh")) + '" aria-label="' + esc(t("js.ha.refresh")) + '">' +
    movingIcon("refresh", "spin-g") + "</button></div></div>";
}
function scanButtonsHTML() {
  return '<div class="split"><button type="button" class="btn outlined rp" id="btn-scan">' + icon("magnify") + "<span>" + esc(t("js.ha.scan")) + "</span></button>" +
    '<button type="button" class="btn outlined rp split-more" id="btn-deepmenu" aria-haspopup="true" aria-expanded="false" aria-label="' + esc(t("js.ha.deep.title")) + '">' + icon("chevron-down") + "</button></div>";
}
function badgesHTML() {
  return BADGES.map(function (k) {
    return '<button type="button" class="badge rp touch" data-badge="' + k + '">' + esc(t("js.ha.badge." + k)) + " <em>0</em></button>";
  }).join("");
}
export function buildNetwork() {
  if (!NET_PARTS) NET_PARTS = { live: $("live"), wrap: document.querySelector(".menu-wrap"), search: $("search-box") };
  const stash = document.createDocumentFragment();
  [NET_PARTS.live, NET_PARTS.wrap, NET_PARTS.search].forEach(function (n) { if (n) stash.appendChild(n); });
  netEl.innerHTML = headerHTML() +
    '<div class="card-content">' +
    '<div class="search-row" id="search-row"></div>' +
    '<div class="hero-row"><div class="gauge-col"><div class="gauge" id="gauge" role="group">' + gaugeHTML() + '</div><div class="gauge-side">' + scanButtonsHTML() + '</div></div>' +
    '<div class="tile-col" id="tile-col">' + tileHTMLShell() + '</div></div>' +
    '<div class="badges" id="badges">' + badgesHTML() + '</div>' +
    '<div class="brands" id="brands"></div></div>';
  // The devices to add open between the badges and the brands (the panel survives the rebuild of the card).
  netEl.querySelector(".card-content").insertBefore(newEl, $("brands"));
  // Search, real-time status and settings live inside this card: the already created
  // nodes (with their handlers) are moved here from the hidden container.
  const tools = $("card-tools");
  tools.insertBefore(NET_PARTS.live, tools.firstChild);
  tools.appendChild(NET_PARTS.wrap);
  $("search-row").appendChild(NET_PARTS.search);
  const holder = $("toolbar");
  if (holder) holder.remove();
  $("btn-refresh").addEventListener("click", doRefresh);
  $("btn-scan").addEventListener("click", doScan);
  $("newdot").addEventListener("click", showNewDevices);
  bindGauge($("gauge"), function (type) { setFilter("type", type); });
  $("badges").addEventListener("click", function (e) {
    const b = e.target.closest(".badge");
    if (b) setFilter("status", S.filter.status === b.dataset.badge ? "all" : b.dataset.badge);
  });
  mountTile();
  // Brands: the list opens on hover (CSS) and, on touch screens, with a tap on the block (.expanded).
  $("brands").addEventListener("click", function () { this.classList.toggle("expanded"); });
}

// The "+N" dot leads to the card of the new devices.
function showNewDevices() {
  const card = newEl;
  if (!card.hidden && card.scrollIntoView) card.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "nearest" });
}

function paintBadges(c) {
  const values = { all: c.total, online: c.online, offline: c.offline, mobile: c.mobile };
  Array.prototype.forEach.call($("badges").children, function (b) {
    const k = b.dataset.badge;
    animateNumber(b.querySelector("em"), values[k]);
    b.classList.toggle("on", S.filter.status === k);
    b.setAttribute("aria-pressed", String(S.filter.status === k));
  });
}
export function updateNetwork() {
  if (!$("gauge")) return;
  const c = counts();
  updateDeepBadge();
  paintGauge(c);
  paintNewDot();
  paintBadges(c);
  paintTile(false);
  renderBrands();
}

var BRAND_COLORS = 8;
// Short and honest text for those without a known brand: what is really known, i.e.
// the MAC manufacturer and its role (chip, board, virtual machine).
export function chipText(d) {
  if (d.brand) return d.brand;
  if (d.vendor_role === "private") return t("js.ha.chip.private");
  if (!d.vendor) return "";
  const role = d.vendor_role === "component" || d.vendor_role === "virtual" || d.vendor_role === "dual" ? d.vendor_role : "brand";
  return t("js.ha.chip." + role, { vendor: d.vendor });
}
// MAC manufacturers of devices without a brand (tooltip of the "Unknown" entry).
export function batteryTitle(d) {
  return t("js.ha.battery.yes") + (d.battery_source ? " · " + t("js.ha.battery.src_" + d.battery_source) : "");
}
function renderBrands() {
  const el = $("brands");
  if (!el) return;
  const map = {};
  S.list.forEach(function (d) {
    // Brand of the PRODUCT, never the network card manufacturer (an
    // Espressif chip is not a brand). Those without a known brand do not appear.
    if (!d.brand) return;
    map[d.brand] = (map[d.brand] || 0) + 1;
  });
  const rows = Object.keys(map).map(function (k) { return { name: k, n: map[k] }; });
  rows.sort(function (a, b) { return b.n - a.n || a.name.localeCompare(b.name); });
  const shown = rows.slice(0, BRAND_COLORS);
  const rest = rows.slice(BRAND_COLORS).reduce(function (s, r) { return s + r.n; }, 0);
  if (rest) shown.push({ name: "\u0000other", n: rest });
  const total = rows.length;
  const sig = JSON.stringify(shown);
  if (el._sig === sig) return;
  el._sig = sig;
  if (!total) { el.innerHTML = ""; return; }
  let bar = "", legend = "";
  shown.forEach(function (r, i) {
    const label = r.name === "\u0000other" ? t("js.ha.brands.other") : r.name;
    const cls = r.name === "\u0000other" ? "c-other" : "c" + (i + 1);
    const tip = label + ": " + r.n;
    bar += '<i class="' + cls + '" style="flex-grow:' + r.n + '" title="' + esc(tip) + '"></i>';
    legend += '<li title="' + esc(tip) + '"><span class="dot ' + cls + '"></span><span class="b-name">' + esc(label) + '</span><span class="b-n">' + r.n + "</span></li>";
  });
  el.innerHTML = '<div class="brands-title">' + esc(t("js.ha.brands.title")) + '</div><div class="brand-bar">' + bar + "</div><ul class=\"brands-list\">" + legend + "</ul>";
}

// Search state: the circle's ring (see net-gauge.js), the real-time pill and the buttons.
export function updateScan() {
  const scanBtn = $("btn-scan");
  if (!scanBtn) return;
  syncDeepBusy();
  if (sampleCycle()) paintTile(false);
  paintCycle();
  renderLive();
  $("btn-refresh").classList.toggle("spinning", S.refreshing);
  const scanning = S.activity.search || S.scanBusy;
  scanBtn.disabled = scanning;
  scanBtn.classList.toggle("busy", scanning);
  document.querySelectorAll(".empty-ic.scan").forEach(function (b) {
    b.disabled = scanning;
    b.classList.toggle("busy", scanning);
  });
}

function doRefresh() {
  if (S.refreshing) return;
  S.refreshing = true;
  S.refreshStart = Date.now();
  S.changedSince = 0;
  S.poll.nextAt = Date.now();
  updateScan();
  api("/api/refresh", { method: "POST" }).catch(function () {
    S.refreshing = false;
    updateScan();
    snack(t("js.ha.toast.refresh_failed"), { kind: "error" });
  });
  setTimeout(function () { if (S.refreshing) { S.refreshing = false; updateScan(); } }, 15000);
}
export function refreshDone() {
  if (!S.refreshing) return;
  const wait = Math.max(0, 700 - (Date.now() - S.refreshStart));
  const changed = S.changedSince;
  setTimeout(function () {
    if (!S.refreshing) return;
    S.refreshing = false;
    updateScan();
    if (changed) snack(t("js.ha.toast.refresh_changes", { n: changed }), { kind: "success", ms: 3200 });
  }, wait);
}

export function doScan() {
  if (S.scanBusy || S.activity.search) return;
  S.scanBusy = true;
  updateScan();
  api("/api/scan/quick", { method: "POST" }).then(function (list) {
    // An address appears only once in the acquisition list.
    const once = {};
    S.found = (Array.isArray(list) ? list : []).filter(function (h) {
      if (!h.ip || once[h.ip]) return false;
      once[h.ip] = true;
      return true;
    });
    const n = S.found.length;
    S.scanned = true;
    S.scanDone = true;
    S.dismissedNew = {};      // a search the user asks for shows again what the app had seen by itself
    try { localStorage.setItem("vedetta-ha-scanned", "1"); } catch (err) { /* ignore */ }
    renderNew();
    snack(n === 0 ? t("js.ha.toast.scan_none") : t("js.ha.toast.scan_found", { n: n }), { kind: "success" });
    // No scrolling: the card opens where it is, under the network card, and pushes the rest down (see renderNew).
  }).catch(function () {
    snack(t("js.ha.toast.scan_failed"), { kind: "error" });
  }).then(function () {
    S.scanBusy = false;
    updateScan();
  });
}
