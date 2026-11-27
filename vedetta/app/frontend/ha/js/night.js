// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
import { $, COMPACT, api, esc, icon, t } from "./core.js";

// ------------------------------------------------- "Last 12 hours": the summary card
// Only when there is something to say (new devices, returns after a long absence, devices gone silent) and only the changes of the
// window (the server decides, analysis/digest.py). The X hides it until something else happens: the list of what it said is kept in
// this browser and compared with the next answer. Read at the start and every 30 minutes.
var el = $("card-night");
var KEY = "vedetta-night-seen";
var last = null;

function said(d) {
  return [].concat(d.new.map(function (i) { return "n:" + i; }), d.back.map(function (b) { return "b:" + b.id + ":" + Math.round(b.at); }),
    d.silent.map(function (i) { return "s:" + i; })).sort().join("|");
}
function seen() { try { return localStorage.getItem(KEY) || ""; } catch (e) { return ""; } }
function days(s) { return Math.max(1, Math.floor(s / 86400)); }
function names(d, ids) { return ids.map(function (i) { return d.labels[i] || i; }).join(", "); }
function line(ic, text) { return '<li><span class="ng-ic">' + icon(ic) + "</span><span>" + esc(text) + "</span></li>"; }

function paint(d) {
  last = d;
  const sig = said(d);
  if (COMPACT || d.first_window || !sig || sig === seen()) { el.hidden = true; el.innerHTML = ""; return; }
  const rows = [];
  if (d.new.length) rows.push(line("plus-circle", t(d.new.length === 1 ? "js.ha.night.new_one" : "js.ha.night.new", { n: d.new.length, names: names(d, d.new) })));
  d.back.forEach(function (b) { rows.push(line("history", t("js.ha.night.back", { name: d.labels[b.id] || b.id, days: days(b.away_s), n: days(b.away_s) }))); });
  if (d.silent.length) rows.push(line("ghost", t(d.silent.length === 1 ? "js.ha.night.silent_one" : "js.ha.night.silent", { n: d.silent.length, names: names(d, d.silent) })));
  el.innerHTML = '<div class="ng-head"><h2>' + esc(t("js.ha.night.title")) + '</h2><button type="button" class="icon-btn small touch rp" data-night="close" aria-label="' +
    esc(t("js.ha.night.hide")) + '" title="' + esc(t("js.ha.night.hide")) + '">' + icon("close") + '</button></div><ul class="ng-list">' + rows.join("") + "</ul>";
  el.hidden = false;
}
export function loadNight() {
  if (!el || COMPACT) return;
  api("/api/ha/digest?hours=12").then(paint).catch(function () {});
}
if (el) {
  el.addEventListener("click", function (e) {
    if (!e.target.closest('[data-night="close"]') || !last) return;
    try { localStorage.setItem(KEY, said(last)); } catch (err) { /* ignore */ }
    el.hidden = true;
  });
  loadNight();
  setInterval(loadNight, 30 * 60 * 1000);
}
