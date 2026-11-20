import { $, api, esc, fmtStamp, icon, t } from "./core.js";
import { S } from "./core-ui.js";

// ------------------------------------------------- "Last 30 days" in the card
// How the device comes and goes (a strip of 30 days and its class), the quality of its link over 7 days in one line, and the changes
// of its name and brand (closed, opened with a tap). Three answers of the server, asked together when the card opens, kept a minute.
var CLASS_KEYS = { once: "js.ha.month.once", occasional: "js.ha.month.occasional", recurring: "js.ha.month.recurring", stable: "js.ha.month.stable", observing: "js.ha.month.observing" };
var LEVEL_KEYS = { normal: "js.ha.month.lv_normal", high: "js.ha.month.lv_high", anomalous: "js.ha.month.lv_anomalous" };
var TREND_KEYS = { rising: "js.ha.month.tr_rising", falling: "js.ha.month.tr_falling", stable: "js.ha.month.tr_stable" };
var FIELD_KEYS = { name: "js.ha.month.f_name", brand: "js.ha.month.f_brand" };
var cache = {}, openChanges = false;

export function loadMonth() {
  const id = S.open, box = $("mi-month");
  if (!box) return;
  const hit = cache[id];
  if (hit && Date.now() - hit.at < 60000) return paintMonth(hit);
  const enc = encodeURIComponent(id);
  Promise.all([api("/api/ha/recurrence/" + enc), api("/api/ha/quality/" + enc), api("/api/ha/identity/" + enc)]).then(function (r) {
    cache[id] = { at: Date.now(), rec: r[0], q: r[1], changes: (r[2] && r[2].changes) || [] };
    if (S.open === id) paintMonth(cache[id]);
  }).catch(function () { const b = $("mi-month"); if (b) b.hidden = true; });
}

function strip(rec) {
  return '<div class="mm-strip" role="img" aria-label="' + esc(t("js.ha.month.days", { n: rec.active_days, of: rec.history_days })) + '">' +
    rec.strip.map(function (on) { return '<i class="' + (on ? "on" : "") + '"></i>'; }).join("") + "</div>";
}

function hours(s) { return s >= 3600 ? Math.floor(s / 3600) + " h" : Math.max(1, Math.floor(s / 60)) + " min"; }

function qualityLine(q) {
  const parts = [];
  if (q.median_ms != null) parts.push(t("js.ha.month.typical", { ms: Math.round(q.median_ms) }));
  if (LEVEL_KEYS[q.level]) parts.push(t(LEVEL_KEYS[q.level]));
  if (TREND_KEYS[q.trend]) parts.push(t(TREND_KEYS[q.trend]));
  if (q.changes_24h) parts.push(t("js.ha.month.changes", { n: q.changes_24h }));
  if (q.longest_outage_s) parts.push(t("js.ha.month.outage", { t: hours(q.longest_outage_s) }));
  return parts.length ? '<div class="mm-quality' + (q.level === "anomalous" ? " warn" : "") + '">' + esc(parts.join(" · ")) + "</div>" : "";
}

function changesHtml(list) {
  if (!list.length) return "";
  const rows = list.map(function (c) {
    return '<li><span class="mm-when">' + esc(fmtStamp(c.ts, true)) + "</span><span>" + esc(t(FIELD_KEYS[c.field] || "js.ha.month.f_name")) + ": " +
      esc(c.old || "–") + " → " + esc(c.new || "–") + "</span></li>";
  }).join("");
  return '<button type="button" class="mm-more rp" data-mm="changes" aria-expanded="' + openChanges + '"><span>' + esc(t("js.ha.month.renames", { n: list.length })) + "</span>" +
    icon("chevron-down") + "</button>" + '<ul class="mm-changes"' + (openChanges ? "" : " hidden") + ">" + rows + "</ul>";
}

function paintMonth(m) {
  const box = $("mi-month");
  if (!box) return;
  const rec = m.rec || {}, cls = CLASS_KEYS[rec.class];
  box.hidden = false;
  box.innerHTML = '<div class="mi-sec-head"><h3>' + esc(t("js.ha.month.title")) + "</h3>" +
    (cls ? '<span class="mm-class" data-c="' + esc(rec.class) + '">' + esc(t(cls)) + "</span>" : "") + "</div>" +
    (rec.strip ? strip(rec) + '<div class="mm-sub">' + esc(t("js.ha.month.days", { n: rec.active_days, of: rec.history_days })) + "</div>" : "") +
    qualityLine(m.q || {}) + changesHtml(m.changes || []);
}

document.addEventListener("click", function (e) {
  const b = e.target.closest('[data-mm="changes"]');
  if (!b) return;
  openChanges = !openChanges;
  b.setAttribute("aria-expanded", String(openChanges));
  const ul = b.nextElementSibling;
  if (ul) ul.hidden = !openChanges;
});
