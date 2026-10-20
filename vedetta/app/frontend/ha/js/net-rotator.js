import { $, REDUCED, ago, api, esc, icon, t } from "./core.js";
import { S } from "./core-ui.js";
import { deepOneBusy } from "./deep.js";

// ------------------------------------------------------------ rotating tile of the Network card
// One tile that shows, in turn, a datum of the network: LAN latency, gateway, recognised devices, Home Assistant link.
// A tile with no data to show is left out. It turns by itself, stops under the pointer, and a click goes to the next one.
var ROTATE_MS = 4200, ATTENTION_HOLD_MS = 12000, FADE_MS = 160, MAX_LATENCY = 13, MAX_CYCLES = 8, SUBNET_HOSTS = 254;
var latency = [], cycles = [], lastNext = null;       // samples of this page: gateway latency (ms) and duration of the checks (s)
var shown = 0, hold = false, timer = 0;
// One more tile that another part of the page offers (the network health, only in the debug mode): `extra()` returns {id, tip, html, open(el), attention} or null. A tile with `open` does that when
// it is clicked instead of passing to the next. When `attention` becomes something new the carousel goes to the tile and stays on it for a while.
var extra = null, seenAttention = "", holdUntil = 0, current = null;
export function setExtraTile(fn) { extra = fn; seenAttention = ""; }

// The latency of the gateway over the last hour, from the history of the app (the average of each minute, to a tenth of a millisecond). The value
// of the card is rounded to whole milliseconds (a LAN answers in less than one: it was always "1.0 ms"); the history is not.
var gwHist = { id: null, at: 0, busy: false, series: null };
function refreshGatewayHistory(gw) {
  if (!gw || !gw.id || gwHist.busy) return;
  if (gwHist.id === gw.id && Date.now() - gwHist.at < 60000) return;
  gwHist.busy = true;
  gwHist.id = gw.id;
  api("/api/ha/history/" + encodeURIComponent(gw.id) + "?hours=1").then(function (x) {
    const lat = x && x.latency;
    gwHist.series = lat && lat.points && lat.points.length ? lat : null;
  }).catch(function () { gwHist.series = null; }).then(function () {
    gwHist.busy = false;
    gwHist.at = Date.now();
    paintTile(false);
  });
}
function push(list, value, max) { list.push(value); if (list.length > max) list.shift(); }
function ms(v) { return v < 10 ? v.toFixed(1) : String(Math.round(v)); }

function gateway() {
  const by = S.roles.by_ip || {};
  const ip = Object.keys(by).find(function (k) { return by[k].gateway; });
  if (!ip) return null;
  return S.list.find(function (d) { return d.ip === ip; }) || { ip: ip, online: false };
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
    const took = first ? 0 : (Date.now() - lastNext) / 1000, gw = gateway();
    if (took > 0 && took * 1000 < S.poll.interval) push(cycles, took, MAX_CYCLES);
    if (gw && gw.online && gw.latency_ms != null) push(latency, gw.latency_ms, MAX_LATENCY);
  }
  lastNext = next;
  return taken;
}

function cardHTML(color, iconName, label, midHTML, footHTML) {
  return '<div class="t-card" style="--c:' + color + '">' +
    '<div class="t-head"><span class="t-ic">' + icon(iconName) + '</span><span class="t-l">' + label + '</span></div>' +
    '<div class="t-mid">' + midHTML + '</div>' +
    '<div class="t-foot">' + (footHTML || '') + '</div>' +
  '</div>';
}
// KPI box of the middle of a tile: small label above, value below (value is already escaped).
function statBox(label, value, color, boxCls) {
  return '<div class="stat-box' + (boxCls ? " " + boxCls : "") + '"' + (color ? ' style="--sc:' + color + '"' : "") + '><span class="stat-box-lbl">' + esc(label) + "</span>" +
    '<span class="stat-box-val">' + value + "</span></div>";
}

function latencyTile(gw) {
  const hist = gw && gwHist.id === gw.id && gwHist.series ? gwHist.series.points.map(function (p) { return p[1]; }) : null;
  const samples = hist || latency;
  if (!gw || !gw.online || !samples.length) return null;
  const last = samples[samples.length - 1], lo = Math.min.apply(null, samples), hi = Math.max.apply(null, samples);
  const avg = samples.reduce(function (a, v) { return a + v; }, 0) / samples.length;
  const pct = hi > lo ? Math.max(4, (last - lo) / (hi - lo) * 100) : 100;
  const foot = '<div class="bar-leg"><span>' + esc(t("js.ha.tile.min")) + " <b>" + ms(lo) + ' ms</b></span><span>' + esc(t("js.ha.tile.max")) + " <b>" + ms(hi) + ' ms</b></span></div>' +
    '<div class="pbar"><i style="width:' + pct.toFixed(1) + '%"></i></div>';
  return {
    id: "latency",
    tip: t("js.ha.tile.latency_tip", { n: samples.length, min: ms(lo), max: ms(hi) }),
    html: cardHTML("var(--primary-color)", "wifi-arrow-up-down", esc(t("js.ha.tile.latency")),
      '<div class="stat-grid-2">' +
        statBox(t("js.ha.tile.current"), ms(last) + ' <span class="unit">ms</span>', "var(--primary-color)") +
        statBox(t("js.ha.tile.avg_lan"), ms(avg) + ' <span class="unit">ms</span>') +
      "</div>",
      foot)
  };
}

function gatewayTile(gw) {
  const m = gw && /^(\d+\.\d+\.\d+)\.\d+$/.exec(gw.ip || "");
  if (!m) return null;
  const used = S.list.filter(function (d) { return d.ip && d.ip.indexOf(m[1] + ".") === 0; }).length, free = Math.max(0, SUBNET_HOSTS - used);
  const subnet = m[1] + ".0/24";
  const pct = Math.max(0, Math.min(100, used / SUBNET_HOSTS * 100)).toFixed(1);
  const foot = '<div class="bar-leg"><span><b>' + used + '</b> ' + esc(t("js.ha.tile.used")) + '</span><span>' + esc(t("js.ha.tile.free", { n: free })) + '</span></div>' +
    '<div class="pbar"><i style="width:' + pct + '%"></i></div>';
  return {
    id: "gateway",
    tip: t(gw.online ? "js.ha.tile.gateway_tip" : "js.ha.tile.gateway_tip_off", { subnet: subnet, used: used, free: free }),
    html: cardHTML("var(--teal-color)", "router-wireless", esc(t("js.ha.tile.gateway")),
      '<div class="t-v"><span class="t-n mono' + (gw.online ? "" : " gw-off") + '">' + esc(gw.ip) + '</span></div>' +
      '<div class="gw-net"><span class="gw-sub">' + esc(subnet) + '</span>' + (gw.online ? '<span class="gw-state">' + esc(t("js.ha.tile.net_active")) + '</span>' : "") + '</div>',
      foot)
  };
}

// Connection to the internet, in the style of the gateway tile: the public IP, how it is reached (direct, CGNAT, double NAT), the hops to the outside.
// Each of the two checks can be switched off in the add-on options (S.external): what is off says so instead of a value.
function internetTile() {
  const ext = S.external, net = S.roles && S.roles.internet;
  const ipOn = !ext || ext.public_ip.on, pathOn = !ext || ext.path.on;
  if (!ipOn && !pathOn) {
    return {
      id: "internet",
      tip: t("js.ha.tile.internet_tip_off"),
      html: cardHTML("var(--info-color)", "earth", esc(t("js.ha.tile.internet")),
        '<div class="t-v"><span class="t-n mono gw-off">' + esc(t("js.ha.tile.off")) + '</span></div>' +
        '<div class="gw-net"><span class="gw-sub">' + esc(t("js.ha.tile.net_all_off")) + '</span><span class="gw-state gw-off">' + esc(t("js.ha.tile.no_checks")) + '</span></div>',
        '<div class="bar-leg"><span>' + esc(t("js.ha.tile.hops", { n: "–" })) + '</span><span>–</span></div><div class="pbar"><i style="width:0%"></i></div>')
    };
  }
  if (!net) return null;
  const hops = (net.hops || []).length, reachable = ipOn ? !!net.public_ip : hops > 0;
  const kind = t(!pathOn ? "js.ha.tile.net_path_off" : net.cgnat ? "js.ha.tile.net_cgnat" : net.double_nat ? "js.ha.tile.net_double" : "js.ha.tile.net_direct");
  const pct = pathOn ? Math.max(0, Math.min(100, hops / 5 * 100)).toFixed(1) : "0";
  const foot = '<div class="bar-leg"><span>' + esc(t("js.ha.tile.hops", { n: pathOn ? hops : "–" })) + '</span><span>' + esc(t("js.ha.tile.checked", { ago: net.ts ? ago(net.ts) : "-" })) + '</span></div>' +
    '<div class="pbar"><i style="width:' + pct + '%"></i></div>';
  return {
    id: "internet",
    tip: t("js.ha.tile.internet_tip", { kind: kind, hops: pathOn ? hops : "–" }),
    html: cardHTML("var(--info-color)", "earth", esc(t("js.ha.tile.internet")),
      '<div class="t-v"><span class="t-n mono' + (ipOn && net.public_ip ? "" : " gw-off") + '">' + esc(ipOn ? net.public_ip || "–" : t("js.ha.tile.off")) + '</span></div>' +
      '<div class="gw-net"><span class="gw-sub">' + esc(kind) + '</span><span class="gw-state' + (reachable ? "" : " gw-off") + '">' + esc(t(reachable ? "js.ha.tile.online" : "js.ha.tile.offline")) + '</span></div>',
      foot)
  };
}

// The three functions that reach the internet and whether each is on: three boxes as in the latency tile, label on the left and On or Off on the right.
function extRow(on, labelKey) {
  return statBox(t(labelKey), esc(t(on ? "js.ha.tile.on" : "js.ha.tile.off")), on ? "var(--success-color)" : "var(--secondary-text-color)", "tinted");
}
function externalTile() {
  const ext = S.external;
  if (!ext) return null;
  const rows = [[ext.public_ip.on, "js.ha.tile.ext_public_ip"], [ext.path.on, "js.ha.tile.ext_path"], [ext.mac_database.on, "js.ha.tile.ext_mac"]];
  const n = rows.filter(function (r) { return r[0]; }).length;
  return {
    id: "external",
    tip: t("js.ha.tile.external_tip", { n: n, total: rows.length }),
    html: cardHTML("var(--teal-color)", "toggle-switch", esc(t("js.ha.tile.external")),
      '<div class="stat-grid-2">' + rows.map(function (r) { return extRow(r[0], r[1]); }).join("") + "</div>")
  };
}

// One labelled bar of the "recognised devices" tile: count and label above, share shown by the bar.
function lensRow(n, total, labelKey, color) {
  const pct = total ? n / total * 100 : 0;
  return '<div class="bar-row" style="--bc:' + color + '"><div class="bar-leg"><span><b>' + n + '</b> ' + esc(t(labelKey)) + '</span></div>' +
    '<div class="pbar"><i style="width:' + pct.toFixed(1) + '%"></i></div></div>';
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
  // Devices whose deep search is running right now.
  const deepCount = devices.filter(function (d) { return deepOneBusy(d.id); }).length;
  const ok = total - analysing - waiting, pct = Math.round(ok / total * 100);
  return {
    id: "lens",
    tip: t("js.ha.tile.lens_tip", { ok: ok, total: total, pct: pct, wait: analysing + waiting }),
    html: cardHTML("var(--purple-color)", "magnify", esc(t("js.ha.tile.lens")),
      '<div class="t-bars">' +
        lensRow(ok, total, "js.ha.tile.identified", "var(--purple-color)") +
        lensRow(analysing, total, "js.ha.tile.analyzing", "var(--primary-color)") +
        lensRow(deepCount, total, "js.ha.deep.title", "var(--warning-color)") +
      "</div>",
      "")
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
  const foot = '<div class="bar-leg"><span>' + esc(t("js.ha.tile.mqtt_exposed")) + '</span><b>' + (on ? shared : "–") + '</b></div>' +
    '<div class="pbar"><i style="width:' + (on && total ? (shared / total * 100).toFixed(1) : 0) + '%"></i></div>';
  return {
    id: "mqtt",
    tip: t(on ? "js.ha.tile.mqtt_tip" : configured ? "js.ha.tile.mqtt_tip_off" : "js.ha.tile.mqtt_tip_none", { s: last === undefined ? "?" : last.toFixed(1) }),
    html: cardHTML("var(--orange-color)", "home-assistant", esc(t("js.ha.tile.mqtt")),
      '<div class="stat-grid-2">' + broker + cycle + "</div>", foot)
  };
}

function tiles() {
  const gw = gateway();
  refreshGatewayHistory(gw);
  const own = extra ? extra() : null, list = [latencyTile(gw), gatewayTile(gw), internetTile(), externalTile(), lensTile(), mqttTile()].filter(Boolean);
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
function onTileClick() { if (current && current.open) current.open($("rot")); else advance(); }
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
