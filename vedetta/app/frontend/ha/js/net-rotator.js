// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
import { $, REDUCED, ago, api, esc, icon, t } from "./core.js";
import { S } from "./core-ui.js";
import { openHaHelp } from "./ha-help.js";

// ------------------------------------------------------------ rotating tile of the Network card
// One tile that shows, in turn, a datum: one tile per network (its gateway's latency in the main one), internet, the outside functions,
// recognised devices, Home Assistant.
// A tile with no data to show is left out. It turns by itself, stops under the pointer, and a click goes to the next one.
var ROTATE_MS = 4200, ATTENTION_HOLD_MS = 12000, FADE_MS = 160, MAX_CYCLES = 8;
var cycles = [], lastNext = null;                    // samples of this page: duration of the checks (s)
var shown = 0, hold = false, timer = 0;
var toggleShared = null;                              // set by filters.js: shows only the devices shared with Home Assistant, or all again (Discussion #17)
export function onSharedFilter(fn) { toggleShared = fn; }
var openNetworks = null;                              // set by core-menu.js, which owns the Networks panel: the button of a proposed or paused network's tile
export function onOpenNetworks(fn) { openNetworks = fn; }
// One more tile that another part of the page offers (the network health, only in the debug mode): `extra()` returns {id, tip, html, open(el), attention} or null. A tile with `open` does that only when
// its `[data-open]` part is clicked; any other click passes to the next tile. When `attention` becomes something new the carousel goes to the tile and stays on it for a while.
var extra = null, seenAttention = "", holdUntil = 0, current = null;
export function setExtraTile(fn) { extra = fn; seenAttention = ""; }

function push(list, value, max) { list.push(value); if (list.length > max) list.shift(); }
function ms(v) { return v < 10 ? v.toFixed(1) : String(Math.round(v)); }

// The gateway's card, or null: without a card (a fresh install, nothing added yet) its state is not known, and not knowing is not "down"
// (Discussion #63).
function gateway() {
  const by = S.roles.by_ip || {};
  const ip = Object.keys(by).find(function (k) { return by[k].gateway; });
  if (!ip) return null;
  return S.list.find(function (d) { return d.ip === ip; }) || null;
}

// The latency of the gateway now, as the tile says it (tenths below 10 ms), or null while it does not answer; the health screen shows it.
export function gatewayLatencyText() {
  const gw = gateway();
  return gw && gw.online && gw.latency_ms != null ? ms(gw.latency_ms) : null;
}

// Called at every update of the scan state. A later "next check" means the previous one has just ended: that is the moment to sample.
// Returns true when a sample was taken (the tile has new numbers).
export function sampleCycle() {
  if (!S.poll.known) return false;
  const next = S.poll.nextAt, first = lastNext === null, taken = first || next > lastNext + 1000;
  if (taken) {
    const took = first ? 0 : (Date.now() - lastNext) / 1000;
    if (took > 0 && took * 1000 < S.poll.interval) push(cycles, took, MAX_CYCLES);
  }
  lastNext = next;
  return taken;
}

// Every tile has the same places (decided 20/11, the layout of the health tile): the icon on the first row (the dots of the carousel on its
// right), the name on a row of its own, two boxes (label on the left, value on the right; the first one tinted in the colour of the tile)
// and the foot: a legend with its bar, or a button in the place of both. Values are escaped by the caller.
function cardHTML(color, iconName, name, b1, b2, foot) {
  return '<div class="t-card" style="--c:' + color + '">' +
    '<div class="t-head"><span class="t-ic">' + icon(iconName) + "</span></div>" +
    '<div class="t-name">' + name + "</div>" +
    '<div class="t-mid"><div class="stat-grid-2">' + b1 + b2 + "</div></div>" +
    '<div class="t-foot">' + (foot || "") + "</div>" +
  "</div>";
}
// KPI box of the middle of a tile: label on the left, value on the right (value is already escaped).
function statBox(label, value, color, boxCls) {
  return '<div class="stat-box' + (boxCls ? " " + boxCls : "") + '"' + (color ? ' style="--sc:' + color + '"' : "") + '><span class="stat-box-lbl">' + esc(label) + "</span>" +
    '<span class="stat-box-val">' + value + "</span></div>";
}
function tileLegend(left, right, pct, color) {
  return '<div class="bar-leg"><span>' + left + "</span><span>" + right + "</span></div>" +
    '<div class="pbar"><i style="width:' + Math.max(0, Math.min(100, pct || 0)).toFixed(1) + "%" + (color ? ";background:" + color : "") + '"></i></div>';
}
// A button in the place of the legend and its bar, as the one of the health tile ("Open"): the click on it calls the tile's `open`.
function goButton(label) { return '<span class="hs-go" data-open>' + esc(label) + icon("chevron-right") + "</span>"; }

// ------------------------------------------------------------ one tile per network
// The networks are read from the panel's own answer (GET /api/networks: name, subnet, VLAN, state, cards, cards on now, "silent"), at most
// once a minute and never twice at a time; the gateway's latency comes from its card. Nothing else is asked for these tiles.
var NET_EVERY_MS = 60000;
var NET_COLORS = ["var(--primary-color)", "var(--orange-color)", "var(--purple-color)", "var(--teal-color)", "var(--pink-color, #e91e63)", "var(--indigo-color, #3f51b5)"];
var tileNets = { rows: null, at: 0, busy: false };   // the page is one bundle: names unique across the modules (netpanel.js has nets and legend)
function refreshNetworks() {
  if (tileNets.busy || Date.now() - tileNets.at < NET_EVERY_MS) return;
  tileNets.busy = true;
  api("/api/networks").then(function (x) {
    tileNets.rows = x && x.main ? [x.main].concat((x.networks || []).filter(function (n) { return n && n.fits !== false; })) : null;
  }).catch(function () { /* keep the last answer */ }).then(function () {
    tileNets.busy = false;
    tileNets.at = Date.now();
    paintTile(false);
  });
}
function gatewayBox(gw) {
  if (!gw) return statBox(t("js.ha.tile.gateway"), "–");
  if (!gw.online) return statBox(t("js.ha.tile.gateway"), esc(t("js.ha.tile.net_gw_down")), "var(--error-color)", "tinted");
  return statBox(t("js.ha.tile.gateway"), gw.latency_ms == null ? "–" : ms(gw.latency_ms) + ' <span class="unit">ms</span>');
}
function netFoot(n, cards, on, color) {
  if (n.state === "proposed" || n.state === "paused") return goButton(t("js.ha.tile.net_open"));
  return tileLegend(esc(n.cidr), esc(t("js.ha.tile.net_off", { n: cards - on })), cards ? on / cards * 100 : 0, color);
}
function netBoxes(n, i, cards, on, color) {
  const count = on + " / " + cards;
  if (n.state === "proposed") return [statBox(t("js.ha.tile.net_proposed"), esc(t("js.ha.tile.net_cards", { n: cards })), "var(--info-color)", "tinted"), statBox(t("js.ha.tile.net_on"), count)];
  const b2 = i === 0 ? gatewayBox(gateway()) : statBox(t("js.ha.tile.net_vlan"), n.vlan ? esc(String(n.vlan)) : "–");
  if (n.state === "paused") return [statBox(t("js.ha.tile.net_paused"), "–", "var(--secondary-text-color)", "tinted"), b2];
  if (n.mute) return [statBox(t("js.ha.tile.net_mute"), esc(t("js.ha.tile.net_mute_val")), "var(--error-color)", "tinted"), b2];
  return [statBox(t("js.ha.tile.net_on"), count, color, "tinted"), b2];
}
function netTile(n, i) {
  if (!n || !n.cidr) return null;
  const color = NET_COLORS[i % NET_COLORS.length], cards = n.cards || 0, on = Math.min(n.on || 0, cards);
  const name = n.state === "proposed" ? n.cidr : n.name || n.cidr, boxes = netBoxes(n, i, cards, on, color);
  const button = n.state === "proposed" || n.state === "paused";
  return {
    id: "net-" + (n.id || n.cidr),
    open: button && openNetworks ? function () { openNetworks(); } : null,
    tip: t("js.ha.tile.net_tip", { name: name, on: on, cards: cards }),
    html: cardHTML(color, "router-wireless", esc(name), boxes[0], boxes[1], netFoot(n, cards, on, color))
  };
}
function netTiles() {
  refreshNetworks();
  return (tileNets.rows || []).map(function (n, i) { return safe(function () { return netTile(n, i); }); });
}

// ------------------------------------------------------------ the other tiles
// The public IP that could not be read (scan/internet.py: public_ip_status): the short text of the box, the whole sentence (tooltip, gateway's card).
export const IP_MISS = { redirected: ["js.ha.tile.ip_redirected", "js.ha.net.ip_redirected"], no_reply: ["js.ha.tile.ip_no_reply", "js.ha.net.ip_no_reply"] };
// Connection to the internet: the public IP, how it is reached (direct, CGNAT, double NAT), the hops to the outside.
// Each of the two checks can be switched off in the add-on options (S.external): what is off says so instead of a value.
function internetTile() {
  const ext = S.external, net = S.roles && S.roles.internet;
  const ipOn = !ext || ext.public_ip.on, pathOn = !ext || ext.path.on;
  const name = esc(t("js.ha.tile.internet")), color = "var(--info-color)";
  if (!ipOn && !pathOn) {
    return {
      id: "internet",
      tip: t("js.ha.tile.internet_tip_off"),
      html: cardHTML(color, "earth", name, statBox(t("js.ha.tile.ext_public_ip"), esc(t("js.ha.tile.off")), "var(--secondary-text-color)", "tinted"),
        statBox(t("js.ha.tile.connection"), esc(t("js.ha.tile.net_all_off"))), tileLegend(esc(t("js.ha.tile.hops", { n: "–" })), esc(t("js.ha.tile.no_checks")), 0))
    };
  }
  if (!net) return null;
  // no address: "redirected" (the network answers the DNS in place of OpenDNS) or "no_reply" (tried again) is said, not "–"; the path decides online
  const hops = (net.hops || []).length, miss = ipOn && !net.public_ip ? IP_MISS[net.public_ip_status] : null;
  const reachable = ipOn && !!net.public_ip || (pathOn || !ipOn) && hops > 0;
  const kind = t(!pathOn ? "js.ha.tile.net_path_off" : net.cgnat ? "js.ha.tile.net_cgnat" : net.double_nat ? "js.ha.tile.net_double" : net.maybe_double_nat ? "js.ha.tile.net_maybe_double" : "js.ha.tile.net_direct");
  const ip = !ipOn ? t("js.ha.tile.off") : net.public_ip || (miss ? t(miss[0]) : "–");
  const b1 = statBox(t("js.ha.tile.ext_public_ip"), esc(ip), miss ? "var(--warning-color)" : reachable ? color : "var(--error-color)", "tinted");
  // in the box the label already says "Connection": the direct case is one word there (the tooltip keeps the whole text)
  const direct = pathOn && !net.cgnat && !net.double_nat && !net.maybe_double_nat;
  const b2 = statBox(t("js.ha.tile.connection"), esc(direct ? t("js.ha.tile.net_direct_short") : kind));
  const foot = tileLegend(esc(t("js.ha.tile.hops", { n: pathOn ? hops : "–" })) + " · " + esc(t(reachable ? "js.ha.tile.online" : "js.ha.tile.offline")),
    esc(t("js.ha.tile.checked", { ago: net.ts ? ago(net.ts) : "-" })), pathOn ? hops / 5 * 100 : 0, color);
  const tip = t("js.ha.tile.internet_tip", { kind: kind, hops: pathOn ? hops : "–" }) + (miss ? " · " + t(miss[1]) : "");
  return { id: "internet", tip: tip, html: cardHTML(color, "earth", name, b1, b2, foot) };
}

// The app's Configuration page in Home Assistant, where the three functions are switched on and off: asked of the host (as the Updates page,
// update.js), only inside Home Assistant and when the server knows the slug of the app.
function settingsOpener(ext) {
  if (window.parent === window || !ext.app_slug) return null;
  return function () { window.parent.postMessage({ type: "home-assistant/navigate", path: "/hassio/addon/" + ext.app_slug + "/config" }, "*"); };
}
// The three functions that reach the internet: how many are on, and which ones are off; the foot is the button to their settings when it can open them.
function externalTile() {
  const ext = S.external;
  if (!ext) return null;
  const rows = [[ext.public_ip.on, "js.ha.tile.ext_public_ip"], [ext.path.on, "js.ha.tile.ext_path"], [ext.mac_database.on, "js.ha.tile.ext_mac"]];
  const n = rows.filter(function (r) { return r[0]; }).length, off = rows.filter(function (r) { return !r[0]; }).map(function (r) { return t(r[1]); });
  const color = "var(--teal-color)";
  const b1 = statBox(t("js.ha.tile.ext_on_lbl"), esc(t("js.ha.tile.ext_count", { n: n, total: rows.length })), n ? "var(--success-color)" : "var(--secondary-text-color)", "tinted");
  const b2 = statBox(t("js.ha.tile.ext_off_lbl"), off.length ? esc(off.join(", ")) : "–");
  const onNames = rows.filter(function (r) { return r[0]; }).map(function (r) { return t(r[1]); }).join(", ");      // the legend: the ones that are on
  const settings = settingsOpener(ext);
  return {
    id: "external",
    open: settings,
    tip: t("js.ha.tile.external_tip", { n: n, total: rows.length }),
    html: cardHTML(color, "toggle-switch", esc(t("js.ha.tile.external")), b1, b2, settings ? goButton(t("js.ha.tile.ext_settings")) : tileLegend(esc(onNames), "", n / rows.length * 100, color))
  };
}

function lensTile() {
  const devices = Array.from(S.devices.values());
  const total = devices.length;
  if (!total) return null;
  // A card missing from S.analysis is identified; "analysing" is the state under analysis, everything else not yet identified waits.
  let analysing = 0, waiting = 0;
  devices.forEach(function (d) {
    const info = S.analysis[d.id];
    if (!info) return;
    if (info.state === "analysing") analysing++; else waiting++;
  });
  const ok = total - analysing - waiting, pct = Math.round(ok / total * 100), color = "var(--purple-color)";
  return {
    id: "lens",
    tip: t("js.ha.tile.lens_tip", { ok: ok, total: total, pct: pct, wait: analysing + waiting }),
    html: cardHTML(color, "magnify", esc(t("js.ha.tile.lens")),
      statBox(t("js.ha.tile.identified"), ok + " / " + total, color, "tinted"), statBox(t("js.ha.tile.analyzing"), String(analysing)),
      tileLegend(pct + "%", esc(t("js.ha.tile.waiting", { n: waiting })), pct, color))
  };
}

function mqttTile() {
  // Three states: connected; configured but the broker does not answer (a fault: red); not configured (not a fault: grey). "Exposed" = the devices
  // shared with Home Assistant (the switch of each card), counted only while the broker is connected: otherwise nothing is exposed.
  const on = !!(S.mqtt && S.mqtt.active && S.mqtt.connected), configured = !!(S.mqtt && S.mqtt.active), last = cycles[cycles.length - 1];
  const shared = S.list.filter(function (d) { return d.ha_share; }).length, total = S.list.length;
  const broker = statBox(t("js.ha.tile.broker_mqtt"), esc(t(on ? "js.ha.tile.online" : configured ? "js.ha.tile.offline" : "js.ha.tile.not_configured")),
    on ? "var(--success-color)" : configured ? "var(--error-color)" : "var(--secondary-text-color)", "tinted");
  const cycle = statBox(t("js.ha.tile.last_cycle"), last === undefined ? "–" : last.toFixed(1) + ' <span class="unit">s</span>');
  // "Exposed N" is also a filter (Discussion #17): a tap shows only the shared devices, another tap (or "All") shows all again
  const can = on && shared > 0, active = can && S.filter.shared;
  const foot = '<div class="bar-leg' + (can ? " t-filter" : "") + (active ? " on" : "") + '"' + (can ? ' data-open="1" title="' + esc(t(active ? "js.ha.tile.mqtt_filter_off" : "js.ha.tile.mqtt_filter")) + '"' : "") +
    '><span>' + esc(t("js.ha.tile.mqtt_exposed")) + '</span><b>' + (on ? shared : "–") + '</b></div>' +
    '<div class="pbar"><i style="width:' + (on && total ? (shared / total * 100).toFixed(1) : 0) + '%"></i></div>';
  return {
    id: "mqtt",
    tip: t(on ? "js.ha.tile.mqtt_tip" : configured ? "js.ha.tile.mqtt_tip_off" : "js.ha.tile.mqtt_tip_none", { s: last === undefined ? "?" : last.toFixed(1) }),
    open: can && toggleShared ? function () { toggleShared(); paintTile(false); } : null,
    html: cardHTML("var(--orange-color)", "home-assistant", esc(t("js.ha.tile.mqtt")), broker, cycle, foot)
  };
}

// Docker only (S.haLink from the summary): whether Home Assistant is connected. Green with its devices; grey when it is not configured, red
// when it refuses the token or does not answer; the foot opens the window that explains how to connect it (ha-help.js).
var HA_STATE = { no_url: "js.ha.tile.ha_not_configured", no_token: "js.ha.tile.ha_not_configured", refused: "js.ha.tile.ha_refused",
  unreachable: "js.ha.tile.ha_unreachable" };
function haTile() {
  const link = S.haLink;
  if (!link) return null;
  const on = !!link.connected, fault = link.problem === "refused" || link.problem === "unreachable";
  const color = on ? "var(--success-color)" : fault ? "var(--error-color)" : "var(--secondary-text-color)";
  const state = statBox(t("js.ha.tile.ha_state"), esc(t(on ? "js.ha.tile.ha_connected" : HA_STATE[link.problem] || "js.ha.tile.ha_not_configured")), color, "tinted");
  const count = statBox(t("js.ha.tile.ha_devices"), on ? String(link.devices) : "–");
  const foot = on ? tileLegend(esc(t("js.ha.tile.ha_read", { ago: link.at ? ago(link.at) : "–" })), "", 100, color) : goButton(t("js.ha.tile.ha_how"));
  return {
    id: "ha",
    open: on ? null : function () { openHaHelp(); },
    tip: t(on ? "js.ha.tile.ha_tip_on" : "js.ha.tile.ha_tip_off"),
    html: cardHTML("var(--primary-color)", "home-assistant", esc(t("js.ha.tile.ha")), state, count, foot)
  };
}

// One tile that fails (a field missing, an answer of an unexpected shape) is left out: the others are still shown.
function safe(make) { try { return make(); } catch (err) { return null; } }
function tiles() {
  const own = extra ? safe(extra) : null;
  const list = netTiles().concat([haTile, internetTile, externalTile, lensTile, mqttTile].map(safe)).filter(Boolean);
  return own ? list.concat([own]) : list;
}

// The new content replaces the old one with a short fade; a refresh of the same tile (new numbers) is written at once.
function put(body, tile, fade) {
  if (body._html === tile.html) return;
  const swap = fade && body._id !== tile.id && !REDUCED;
  body._id = tile.id;
  body._html = tile.html;
  if (!swap) { body.innerHTML = tile.html; return; }
  body.classList.add("out");
  setTimeout(function () {
    body.innerHTML = tile.html;
    body.classList.remove("out");
    body.classList.add("pre");
    void body.offsetWidth;
    body.classList.remove("pre");
  }, FADE_MS);
}
export function paintTile(fade) {
  const el = $("rot");
  if (!el) return;
  const list = tiles(), row = el.parentElement;
  el.hidden = !list.length;
  row.classList.toggle("solo", !list.length);
  if (!list.length) return;
  const own = list[list.length - 1];
  if (own && own.attention !== undefined) {
    if (own.attention && own.attention !== seenAttention) { shown = list.length - 1; holdUntil = Date.now() + ATTENTION_HOLD_MS; fade = true; }
    seenAttention = own.attention;
  }
  const cur = current = list[shown % list.length], dots = el.querySelector(".t-dots");
  paintDots(dots, cur, own);
  el.title = cur.tip;
  el.setAttribute("aria-label", cur.tip + " · " + t("js.ha.tile.next"));
  put(el.querySelector(".t-body"), cur, fade);
}

// The two segments: the bar starts again at each new tile; the dot shows that the tile of the page asks for attention, in its colour.
function paintDots(dots, cur, own) {
  if (!dots.children.length) dots.innerHTML = '<i class="bar"></i><i class="dot"></i>';
  const bar = dots.children[0], dot = dots.children[1], alert = !!(own && own.attention);
  dot.classList.toggle("alert", alert);
  if (alert) dots.style.setProperty("--ac", own.color);
  if (dots._id === cur.id) return;
  dots._id = cur.id;
  dots.style.setProperty("--ms", ROTATE_MS + "ms");
  bar.classList.remove("run"); void bar.offsetWidth; bar.classList.add("run");
}
function advance() { shown++; paintTile(true); }
function onTileClick(e) { if (current && current.open && e.target.closest("[data-open]")) current.open($("rot")); else advance(); }
export function tileHTMLShell() {
  return '<button type="button" class="nettile" id="rot" hidden><div class="t-body"></div><div class="t-dots"></div></button>';
}
export function mountTile() {
  const el = $("rot");
  clearInterval(timer);
  hold = false;
  el.addEventListener("click", onTileClick);
  el.addEventListener("mouseenter", function () { hold = true; });
  el.addEventListener("mouseleave", function () { hold = false; });
  el.addEventListener("focus", function () { hold = true; });
  el.addEventListener("blur", function () { hold = false; });
  if (!REDUCED) timer = setInterval(function () { if (!hold && !document.hidden && Date.now() >= holdUntil) advance(); }, ROTATE_MS);
  paintTile(false);
}
