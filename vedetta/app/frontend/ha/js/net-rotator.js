import { $, REDUCED, esc, icon, t } from "./core.js";
import { S } from "./core-ui.js";
import { deepOneBusy } from "./deep.js";

// ------------------------------------------------------------ rotating tile of the Network card
// One tile that shows, in turn, a datum of the network: LAN latency, gateway, recognised devices, Home Assistant link.
// A tile with no data to show is left out. It turns by itself, stops under the pointer, and a click goes to the next one.
var ROTATE_MS = 4200, FADE_MS = 160, MAX_LATENCY = 13, MAX_CYCLES = 8, SUBNET_HOSTS = 254;
var latency = [], cycles = [], lastNext = null;       // samples of this page: gateway latency (ms) and duration of the checks (s)
var shown = 0, hold = false, timer = 0;

function push(list, value, max) { list.push(value); if (list.length > max) list.shift(); }
function ms(v) { return v < 10 ? v.toFixed(1) : String(Math.round(v)); }

function gateway() {
  const by = S.roles.by_ip || {};
  const ip = Object.keys(by).find(function (k) { return by[k].gateway; });
  if (!ip) return null;
  return S.list.find(function (d) { return d.ip === ip; }) || { ip: ip, online: false };
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
  if (!gw || !gw.online || !latency.length) return null;
  const last = latency[latency.length - 1], lo = Math.min.apply(null, latency), hi = Math.max.apply(null, latency);
  const avg = latency.reduce(function (a, v) { return a + v; }, 0) / latency.length;
  const pct = hi > lo ? Math.max(4, (last - lo) / (hi - lo) * 100) : 100;
  const foot = '<div class="bar-leg"><span>' + esc(t("js.ha.tile.min")) + " <b>" + ms(lo) + ' ms</b></span><span>' + esc(t("js.ha.tile.max")) + " <b>" + ms(hi) + ' ms</b></span></div>' +
    '<div class="pbar"><i style="width:' + pct.toFixed(1) + '%"></i></div>';
  return {
    id: "latency",
    tip: t("js.ha.tile.latency_tip", { n: latency.length, min: ms(lo), max: ms(hi) }),
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
  const on = !!(S.mqtt && S.mqtt.active && S.mqtt.connected), last = cycles[cycles.length - 1], hosts = S.list.length;
  const broker = statBox(t("js.ha.tile.broker_mqtt"), esc(t(on ? "js.ha.tile.online" : "js.ha.tile.offline")), on ? "var(--success-color)" : "var(--error-color)", "tinted");
  const cycle = statBox(t("js.ha.tile.last_cycle"), last === undefined ? "–" : last.toFixed(1) + ' <span class="unit">s</span>');
  const foot = '<div class="bar-leg"><span>' + esc(t("js.ha.tile.mqtt_exposed")) + '</span><b>' + hosts + '</b></div>' +
    '<div class="pbar"><i style="width:100%"></i></div>';
  return {
    id: "mqtt",
    tip: t(on ? "js.ha.tile.mqtt_tip" : "js.ha.tile.mqtt_tip_off", { s: last === undefined ? "?" : last.toFixed(1) }),
    html: cardHTML("var(--orange-color)", "home-assistant", esc(t("js.ha.tile.mqtt")),
      '<div class="stat-grid-2">' + broker + cycle + "</div>", foot)
  };
}

function tiles() {
  const gw = gateway();
  return [latencyTile(gw), gatewayTile(gw), lensTile(), mqttTile()].filter(Boolean);
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
  const cur = list[shown % list.length], dots = el.querySelector(".t-dots");
  if (dots.children.length !== list.length) dots.innerHTML = list.map(function () { return "<i></i>"; }).join("");
  Array.prototype.forEach.call(dots.children, function (d, n) { d.classList.toggle("on", n === shown % list.length); });
  el.title = cur.tip;
  el.setAttribute("aria-label", cur.tip + " · " + t("js.ha.tile.next"));
  put(el.querySelector(".t-body"), cur, fade);
}

function advance() { shown++; paintTile(true); }
export function tileHTMLShell() {
  return '<button type="button" class="nettile rp" id="rot" hidden><div class="t-body"></div><div class="t-dots"></div></button>';
}
export function mountTile() {
  const el = $("rot");
  clearInterval(timer);
  hold = false;
  el.addEventListener("click", advance);
  el.addEventListener("mouseenter", function () { hold = true; });
  el.addEventListener("mouseleave", function () { hold = false; });
  el.addEventListener("focus", function () { hold = true; });
  el.addEventListener("blur", function () { hold = false; });
  if (!REDUCED) timer = setInterval(function () { if (!hold && !document.hidden) advance(); }, ROTATE_MS);
  paintTile(false);
}
