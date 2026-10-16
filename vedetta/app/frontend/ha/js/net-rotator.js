import { $, REDUCED, esc, icon, t } from "./core.js";
import { S } from "./core-ui.js";
import { bars, donut, spark } from "./net-charts.js";

// ------------------------------------------------------------ rotating tile of the Network card
// One 48 px tile that shows, in turn, a datum of the network: LAN latency, gateway, recognised devices, Home Assistant link.
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

function tileHTML(label, value, extra, graph) {
  return '<div class="t-txt"><span class="t-l">' + label + '</span><span class="t-v">' + value + (extra || "") + '</span></div><div class="t-g">' + graph + "</div>";
}
function stateDot(ok) { return '<span class="sd ' + (ok ? "ok" : "err") + '"></span>'; }

function latencyTile(gw) {
  if (!gw || !gw.online || !latency.length) return null;
  const last = latency[latency.length - 1], lo = Math.min.apply(null, latency), hi = Math.max.apply(null, latency), many = latency.length > 1;
  function chip(cls, key, v) { return '<span class="mm ' + cls + '"><u>' + esc(t("js.ha.tile." + key)) + "</u>" + ms(v) + "</span>"; }
  return {
    id: "latency",
    tip: t("js.ha.tile.latency_tip", { n: latency.length, min: ms(lo), max: ms(hi) }),
    html: tileHTML(esc(t("js.ha.tile.latency")), '<span class="t-n">' + ms(last) + " ms</span>", many ? chip("min", "min", lo) + chip("max", "max", hi) : "",
      many ? '<span class="sp-n">' + spark(latency, 32, 24) + '</span><span class="sp-w">' + spark(latency, 72, 24) + "</span>" : "")
  };
}

function gatewayTile(gw) {
  const m = gw && /^(\d+\.\d+\.\d+)\.\d+$/.exec(gw.ip || "");
  if (!m) return null;
  const used = S.list.filter(function (d) { return d.ip && d.ip.indexOf(m[1] + ".") === 0; }).length, free = Math.max(0, SUBNET_HOSTS - used);
  const subnet = m[1] + ".0/24";
  return {
    id: "gateway",
    tip: t(gw.online ? "js.ha.tile.gateway_tip" : "js.ha.tile.gateway_tip_off", { subnet: subnet, used: used, free: free }),
    html: tileHTML(stateDot(gw.online) + esc(t("js.ha.tile.gateway")), '<span class="t-n">' + esc(gw.ip) + "</span>", "",
      '<span class="gw-ic">' + icon("router-wireless") + '</span><div class="gw-bar"><span class="gw-t"><b>' + used + "</b> " + esc(t("js.ha.tile.used")) +
      '<span class="gw-f"> · ' + esc(t("js.ha.tile.free", { n: free })) + '</span></span><div class="pbar"><i style="width:' + Math.max(0, Math.min(100, used / SUBNET_HOSTS * 100)).toFixed(1) + '%"></i></div></div>')
  };
}

// Recognised = the cards that are not under analysis (S.analysis keeps only the unidentified ones).
function lensTile() {
  const total = S.list.length;
  if (!total) return null;
  const waiting = S.list.filter(function (d) { return S.analysis[d.id]; }).length, ok = total - waiting, pct = Math.round(ok / total * 100);
  return {
    id: "lens",
    tip: t("js.ha.tile.lens_tip", { ok: ok, total: total, pct: pct, wait: waiting }),
    html: tileHTML(esc(t("js.ha.tile.lens")), '<span class="t-n">' + ok + " / " + total + '</span><span class="xs">' + pct + '%</span><span class="x">' + esc(t("js.ha.tile.recognised")) + "</span>", "", donut(ok, total))
  };
}

function mqttTile() {
  if (!S.mqtt || !S.mqtt.active) return null;
  const on = !!S.mqtt.connected, last = cycles[cycles.length - 1];
  const value = last === undefined ? esc(t(on ? "js.ha.tile.connected" : "js.ha.tile.disconnected")) : esc(t("js.ha.tile.cycle", { s: last.toFixed(1) }));
  return {
    id: "mqtt",
    tip: t(on ? "js.ha.tile.mqtt_tip" : "js.ha.tile.mqtt_tip_off", { s: last === undefined ? "–" : last.toFixed(1) }),
    html: tileHTML(stateDot(on) + esc(t("js.ha.tile.mqtt")), '<span class="t-n">' + value + "</span>", last === undefined ? "" : '<span class="x">' + esc(t(on ? "js.ha.tile.connected" : "js.ha.tile.disconnected")) + "</span>",
      bars(cycles, 40, 22))
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
