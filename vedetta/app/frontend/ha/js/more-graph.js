import { $, LANG, api, dlg, esc, fmtClock, fmtStamp, icon, t } from "./core.js";
import { S } from "./core-ui.js";
import { span } from "./core-menu.js";
import { closeMore, miHero } from "./more-info.js";
import { miActions, miAttrs, miDebug } from "./more-attrs.js";

export function updateMore() {
  if (!S.open || !dlg.open || S.mi.view !== "main") return;
  const d = S.devices.get(S.open);
  if (!d) return closeMore();
  const title = $("more-title");
  if (title && title.textContent !== d.name) title.textContent = d.name;
  miHero(d);
  miAttrs(d);
  miDebug(d);
  miActions(d);
}

// History chart: a single segmented band (online / offline / no data)
// like the HA history bar, with tooltip on hover or touch.
export function loadGraph() {
  const id = S.open, hours = S.mi.range;
  const cached = S.mi.win[hours];
  if (cached && Date.now() - cached.at < 30000) { S.mi.token++; return paintGraph(cached.data, hours); }
  const graph = $("mi-graph");
  if (graph && !cached) graph.innerHTML = '<div class="skeleton sk-graph"></div>';
  const token = ++S.mi.token;
  api("/api/ha/history/" + encodeURIComponent(id) + "?hours=" + hours).then(function (data) {
    if (token !== S.mi.token || S.open !== id) return;
    S.mi.win[hours] = { at: Date.now(), data: data };
    if (hours === S.mi.range) paintGraph(data, hours);
  }).catch(function () {
    if (token !== S.mi.token) return;
    const g = $("mi-graph");
    if (g) g.innerHTML = '<div class="graph-msg">' + esc(t("js.ha.more.history_failed")) + "</div>";
  });
}

// Timeline strokes: online/offline segments plus the "no data" gaps,
// clipped to the window. No intermediate state.
function bucketsFor(win) {
  const segs = win.segments.slice().sort(function (x, y) { return x.from - y.from; });
  let out = [], cur = win.from;
  segs.forEach(function (s) {
    const a = Math.max(s.from, win.from), b = Math.min(s.to, win.to);
    if (b <= a) return;
    if (a > cur) out.push({ a: cur, b: a, st: "nodata" });
    out.push({ a: a, b: b, st: s.online ? "on" : "off" });
    cur = Math.max(cur, b);
  });
  if (cur < win.to) out.push({ a: cur, b: win.to, st: "nodata" });
  return out;
}

// Small line chart (SVG) of the response time: series already reduced by the
// server to ~120 points [ts, ms]. Empty if there is no data.
function latencyChart(lat) {
  const pts = lat && lat.points ? lat.points : [];
  if (pts.length < 2) return "";
  const W = 300, H = 56, pad = 3, span = Math.max(1, lat.to - lat.from);
  let max = 1;
  pts.forEach(function (p) { if (p[1] > max) max = p[1]; });
  const line = pts.map(function (p, i) {
    const x = (p[0] - lat.from) / span * W, y = H - pad - p[1] / max * (H - 2 * pad);
    return (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
  }).join(" ");
  const lastX = ((pts[pts.length - 1][0] - lat.from) / span * W).toFixed(1), firstX = ((pts[0][0] - lat.from) / span * W).toFixed(1);
  const area = line + " L" + lastX + " " + H + " L" + firstX + " " + H + " Z";
  return '<div class="lat-chart"><div class="lat-head"><span>' + esc(t("js.ha.more.latency_title")) + "</span><span>" +
    esc(t("js.ha.more.latency_stats", { avg: Math.round(lat.avg), max: Math.round(lat.max) })) + "</span></div>" +
    '<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" role="img" aria-label="' + esc(t("js.ha.more.latency_aria")) + '">' +
    '<path class="lat-area" d="' + area + '"></path><path class="lat-line" d="' + line + '"></path></svg></div>';
}

function paintGraph(win, hours) {
  const el = $("mi-graph");
  if (!el) return;
  const latHtml = latencyChart(win.latency);
  if (!win.segments || !win.segments.length) {
    el.innerHTML = '<div class="graph-msg">' + icon("history") + "<span>" + esc(t("js.ha.more.nodata")) + "</span></div>" + latHtml;
    return;
  }
  const from = win.from, to = win.to, span = to - from, longRange = hours > 24;
  const outages = win.segments.filter(function (s) { return !s.online; }).length;
  const label = { on: t("js.ha.more.tip_online_seg"), off: t("js.ha.more.tip_offline_seg"), nodata: t("js.ha.more.nodata") };
  const strip = bucketsFor(win).map(function (b) {
    const left = (b.a - from) / span * 100, w = Math.max(0.4, (b.b - b.a) / span * 100);
    const tip = label[b.st] + "\n" + fmtStamp(b.a, longRange) + " – " + fmtStamp(b.b, longRange);
    return '<i class="' + b.st + '" style="left:' + left.toFixed(2) + "%;width:" + w.toFixed(2) + '%" data-tip="' + esc(tip) + '"></i>';
  }).join("");
  const ticks = [];
  if (!longRange) { for (var h = 0; h <= 24; h += 6) ticks.push(h === 24 ? t("js.ha.more.now") : fmtClock(from + h * 3600)); }
  else {
    for (var d = 0; d < 7; d++) ticks.push(new Date((from + d * 86400) * 1000).toLocaleDateString(LANG, { weekday: "short" }));
    ticks.push(t("js.ha.more.now"));
  }
  const pct = win.online_pct;
  el.innerHTML =
    '<div class="stats">' +
    '<div class="stat"><span class="stat-v">' + outages + '</span><span class="stat-l">' + esc(t("js.ha.more.outages", { n: outages })) + "</span></div></div>" +
    '<div class="chart" role="img" aria-label="' + esc(t("js.ha.more.chart_aria")) + '">' +
      '<div class="tl">' + strip + "</div>" +
      '<div class="axis">' + ticks.map(function (x) { return "<span>" + esc(x) + "</span>"; }).join("") + "</div>" +
      '<div class="tip" id="tip" hidden></div></div>' + latHtml;
}

// Single chart tooltip.
var tipTimer = null;
function tipFor(e) {
  const chart = e.target.closest ? e.target.closest(".chart") : null;
  if (!chart) {
    var stray = dlg.querySelector(".tip");
    if (stray && !stray.hidden && e.pointerType !== "touch") stray.hidden = true;
    return;
  }
  const tip = chart.querySelector(".tip");
  const target = e.target.closest("[data-tip]");
  if (!target) { tip.hidden = true; return; }
  tip.textContent = target.dataset.tip;
  tip.hidden = false;
  const cr = chart.getBoundingClientRect();
  let x = e.clientX - cr.left;
  const w = tip.offsetWidth;
  x = Math.max(w / 2 + 4, Math.min(cr.width - w / 2 - 4, x));
  tip.style.left = x + "px";
  clearTimeout(tipTimer);
  if (e.pointerType === "touch") tipTimer = setTimeout(function () { tip.hidden = true; }, 1800);
}
dlg.addEventListener("pointermove", tipFor);
dlg.addEventListener("pointerdown", tipFor);
dlg.addEventListener("pointerleave", function (e) {
  const tip = dlg.querySelector(".tip");
  if (tip && e.pointerType !== "touch") tip.hidden = true;
});

