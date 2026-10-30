import { LANG, REDUCED, api, esc, icon, t, typeIcon } from "./core.js";
import { S, snack } from "./core-ui.js";
import { load } from "./live.js";

// ------------------------------------------- networks seen by Home Assistant
// The panel of the network card where the user turns on the reading of the clients Home Assistant sees (a router integration) on networks Vedetta does not scan,
// reads them, chooses which to adopt and adopts them. An adopted client is a card like the others (it comes with the devices); this panel only chooses and adopts.
// It opens from the menu and closes by itself, bottom to top, when the adoption is done.
export var netsEl = document.createElement("div");
netsEl.id = "card-nets";
netsEl.className = "nd-panel";
netsEl.hidden = true;
var netsInfo = null;                        // the last answer of /api/ha/networks
var netsSel = {};                           // MACs ticked in the list
var netsBusy = "";                          // "read" while Home Assistant is asked, "adopt" while the adoption runs
var netsLoadTimer = null;

// How many clients can be adopted now (the number next to the menu entry); 0 while the function is off.
export function netsCount() { return netsInfo && netsInfo.enabled ? netsInfo.candidates.length : 0; }

function netsClock(ts) {
  return new Date(ts * 1000).toLocaleTimeString(LANG, { hour: "2-digit", minute: "2-digit" });
}
function netsNetworks(list) {
  // The networks in the order Home Assistant lists them (the server sent the clients in that order), the clients without an address last.
  const order = [], by = {};
  list.forEach(function (c) {
    const key = c.net || "";
    if (!by[key]) { by[key] = []; order.push(key); }
    by[key].push(c);
  });
  return order.sort(function (a, b) { return (a === "") - (b === ""); }).map(function (key) { return { net: key, list: by[key] }; });
}
function netsStateText(c) { return c.online === true ? t("js.ha.nets.on") : c.online === false ? t("js.ha.nets.off") : t("js.ha.nets.unknown"); }
function netsRow(c) {
  const name = c.name || c.host || c.mac.toUpperCase();
  return '<div class="rv-row"><input type="checkbox" data-nets-m="' + esc(c.mac) + '"' + (netsSel[c.mac] ? " checked" : "") + ' aria-label="' + esc(name) + '">' +
    '<span class="rv-ic' + (c.online === false ? " off" : "") + '">' + icon(typeIcon(c.type)) + '</span><div class="nd-text"><div class="nd-name">' + esc(name) +
    '</div><div class="nd-sub">' + esc((c.ip || t("js.ha.nets.no_ip_row")) + " · " + c.mac.toUpperCase() + " · " + netsStateText(c)) + "</div></div></div>";
}
function netsGroup(g) {
  const on = g.list.filter(function (c) { return c.online === true; }).length;
  const label = g.net ? g.net : t("js.ha.nets.no_ip");
  const other = g.net && !g.list.some(function (c) { return c.same_net; }) ? " · " + t("js.ha.nets.other_net") : "";
  return '<div class="rv-net"><b>' + esc(label) + '</b><span class="sp"></span><button type="button" class="btn text rp rv-all" data-nets-all="' + esc(g.net) + '">' + esc(t("js.ha.nets.select_all")) + "</button>" +
    "<span>" + esc(t("js.ha.nets.net_sum", { n: g.list.length, on: on }) + other) + "</span></div>" + g.list.map(netsRow).join("");
}
function netsBody(info) {
  if (!info.enabled) return "";
  const read = info.read_at ? t("js.ha.nets.read_at", { time: netsClock(info.read_at), n: info.candidates.length }) : t("js.ha.nets.never");
  let html = '<div class="rv-bar top"><span>' + esc(info.error ? t("js.ha.nets.error") : read) + '</span><span class="sp"></span><button type="button" class="btn filled rp" id="nets-read"' +
    (netsBusy ? " disabled" : "") + ">" + esc(netsBusy === "read" ? t("js.ha.nets.reading") : t("js.ha.nets.read")) + "</button></div>";
  if (info.read_at && !info.candidates.length) return html + '<div class="rv-empty">' + esc(t("js.ha.nets.empty")) + "</div>";
  html += netsNetworks(info.candidates).map(netsGroup).join("");
  const n = info.candidates.filter(function (c) { return netsSel[c.mac]; }).length;
  if (info.candidates.length) {
    html += '<div class="rv-bar"><span>' + esc(t("js.ha.nets.selected", { n: n })) + '</span><span class="sp"></span><button type="button" class="btn filled rp" id="nets-adopt"' +
      (n && !netsBusy ? "" : " disabled") + ">" + esc(t("js.ha.nets.adopt")) + "</button></div>";
  }
  return html;
}
export function renderNets() {
  if (netsEl.hidden || !netsInfo) return;
  const info = netsInfo;
  const intro = info.available
    ? '<ul class="rv-note"><li>' + [t("js.ha.nets.n1"), t("js.ha.nets.n2"), t("js.ha.nets.n3"), t("js.ha.nets.n4")].map(esc).join("</li><li>") + "</li></ul>"
    : '<div class="rv-empty">' + esc(t("js.ha.nets.unavailable")) + "</div>";
  netsEl.innerHTML = '<div class="card-header"><span class="ch-ic ok">' + icon("lan") + '</span><div class="ch-text"><div class="ch-title small">' + esc(t("js.ha.nets.title")) +
    '</div><div class="ch-sub">' + esc(t("js.ha.nets.sub")) + "</div></div>" +
    (info.available ? '<button type="button" class="rv-switch' + (info.enabled ? " on" : "") + '" id="nets-switch" role="switch" aria-checked="' + info.enabled + '" aria-label="' + esc(t("js.ha.nets.switch")) + '"></button>' : "") +
    // The way out, as in the panel of the devices found: a plain icon button, the word only in the tooltip and for screen readers.
    '<button type="button" class="btn text rp nd-sym rv-close" id="nets-close" title="' + esc(t("js.ha.new.close")) + '" aria-label="' + esc(t("js.ha.new.close")) + '">' + icon("close") + "</button>" +
    "</div>" + intro + netsBody(info);
}
function netsAsk(path, body) {
  return api(path, { method: "POST", json: body || {} }).then(function (info) { netsInfo = info; return info; });
}
// Refreshes what is known (the number in the menu, the panel if it is open). Silent when Home Assistant is not there.
export function netsRefresh() {
  return api("/api/ha/networks").then(function (info) { netsInfo = info; renderNets(); }).catch(function () { /* the function is extra: nothing to say */ });
}
// A reading finished or a device changed: the cards come again with the devices, the panel with its list.
export function netsChanged() {
  clearTimeout(netsLoadTimer);
  netsLoadTimer = setTimeout(function () { if (S.loaded) load({ silent: true }); netsRefresh(); }, 150);
}
export function openNets() {
  const opening = netsEl.hidden;
  netsEl.hidden = false;
  netsSel = {};
  netsBusy = "";
  (netsInfo ? Promise.resolve() : netsRefresh()).then(function () {
    renderNets();
    if (opening && !REDUCED && netsEl.animate) {
      const full = netsEl.getBoundingClientRect().height;
      if (full > 0) netsEl.animate([{ height: "0px", opacity: 0 }, { height: full + "px", opacity: 1 }], { duration: 280, easing: "ease-out" });
    }
    if (netsEl.scrollIntoView) netsEl.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "nearest" });
  });
  netsRefresh();
}
// Closes from the bottom up (the height goes to nothing from the bottom edge), then hides the panel.
export function closeNets() {
  if (netsEl.hidden) return;
  const done = function () { netsEl.hidden = true; netsEl.style.overflow = ""; netsEl.innerHTML = ""; };
  if (REDUCED || !netsEl.animate) { done(); return; }
  const h = netsEl.getBoundingClientRect().height;
  netsEl.style.overflow = "hidden";
  netsEl.animate([{ height: h + "px", opacity: 1 }, { height: "0px", opacity: 0 }], { duration: 420, easing: "ease-in" }).onfinish = done;
}
function netsFail() { snack(t("js.ha.nets.failed"), { kind: "error" }); netsBusy = ""; renderNets(); }
netsEl.addEventListener("click", function (e) {
  if (e.target.closest("#nets-close")) { closeNets(); return; }
  if (e.target.closest("#nets-switch")) {
    const turnOn = !netsInfo.enabled;
    netsAsk("/api/ha/networks/enabled", { enabled: turnOn }).then(function (info) {
      renderNets();
      if (turnOn && !info.read_at) { netsBusy = "read"; renderNets(); netsAsk("/api/ha/networks/read").then(function () { netsBusy = ""; renderNets(); netsChanged(); }).catch(netsFail); }
      else netsChanged();
    }).catch(netsFail);
    return;
  }
  if (e.target.closest("#nets-read")) {
    netsBusy = "read"; renderNets();
    netsAsk("/api/ha/networks/read").then(function () { netsBusy = ""; renderNets(); netsChanged(); }).catch(netsFail);
    return;
  }
  const all = e.target.closest("[data-nets-all]");
  if (all) {
    netsInfo.candidates.forEach(function (c) { if ((c.net || "") === all.dataset.netsAll) netsSel[c.mac] = true; });
    renderNets();
    return;
  }
  if (e.target.closest("#nets-adopt")) {
    const macs = Object.keys(netsSel).filter(function (m) { return netsSel[m]; });
    if (!macs.length) return;
    netsBusy = "adopt"; renderNets();
    netsAsk("/api/ha/networks/adopt", { macs: macs }).then(function (info) {
      netsSel = {};
      netsBusy = "";
      snack(t("js.ha.nets.adopted", { n: info.done }), { kind: "success", ms: 4000 });
      if (S.loaded) load({ silent: true });
      renderNets();
      setTimeout(closeNets, 900);       // the cards are there: the panel closes by itself
    }).catch(netsFail);
  }
});
netsEl.addEventListener("change", function (e) {
  const box = e.target.closest("[data-nets-m]");
  if (!box) return;
  netsSel[box.dataset.netsM] = box.checked;
  renderNets();
});
