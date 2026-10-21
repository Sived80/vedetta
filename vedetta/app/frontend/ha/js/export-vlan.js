import { api, esc, icon, t } from "./core.js";
import { DEBUG } from "./debug.js";

// ------------------------------------------------- an optional extra of the export for the developer (debug mode only)
// Only in the debug mode, only for the developer export, only while the server says the survey is on (info.survey). A check button: it asks the server whether Home Assistant
// has network trackers; found = green with the number, nothing found or Home Assistant not readable = back to the default and the step-by-step guide opens, with a first line that
// says the normal export works without this option. The state lives in X.vlan (X is the state of the export window, kept in export.js).
var VLAN_T = "js.ha.export.vlan.";
function vlanT(key, vars) { return t(VLAN_T + key, vars); }
function vlanTHas(key) { return t(VLAN_T + key) !== VLAN_T + key; }       // t() answers the key itself for a text that does not exist
var VLAN_GUIDE_STEPS = 5;

export function vlanInit() { return { state: "idle", n: 0, pop: false, guide: false, why: null }; }
export function vlanAvailable(X) { return !!(DEBUG && X.dest === "dev" && X.info && X.info.survey); }
export function vlanWanted(X) { return vlanAvailable(X) && X.vlan.state === "ok"; }

function vlanButton(v) {
  const busy = v.state === "busy", ok = v.state === "ok";
  const main = busy ? vlanT("btn_busy") : ok ? vlanT("btn_ok", { n: v.n }) : vlanT("btn_idle");
  const sub = busy ? "" : ok ? vlanT("btn_ok_sub") : vlanT("btn_idle_sub");
  return '<button type="button" class="xv-chk" data-xp="vlan" data-state="' + v.state + '" aria-pressed="' + ok + '"' + (busy ? ' aria-busy="true"' : "") + ">" +
    (busy ? '<span class="xv-spin" aria-hidden="true"></span>' : icon(ok ? "check-circle" : "check-circle-outline")) +
    '<span class="xv-ct"><span>' + esc(main) + "</span>" + (sub ? "<small>" + esc(sub) + "</small>" : "") + "</span></button>";
}

function vlanStep(n) {
  return '<div class="xv-stp"><span class="xv-n">' + n + "</span><div><b>" + esc(vlanT("pop_s" + n + "_t")) + '</b><span class="xv-d">' + esc(vlanT("pop_s" + n + "_d")) + "</span></div></div>";
}

function vlanPop() {
  return '<div class="xv-pop" role="note"><h3>' + esc(vlanT("pop_title")) + '</h3><div class="xv-grp"><div class="xv-gh">' + icon("home") + esc(vlanT("pop_group")) + "</div>" +
    vlanStep(1) + vlanStep(2) + vlanStep(3) + '</div><div class="xv-all">' + icon("lock") + "<span>" + esc(vlanT("pop_masked")) + "</span></div>" +
    '<div class="xv-pf"><button type="button" class="btn text" data-xp="vlanguide">' + esc(vlanT("pop_guide")) + icon("chevron-right", "s") + "</button></div></div>";
}

export function vlanSection(X) {
  if (!vlanAvailable(X)) return "";
  const v = X.vlan, label = esc(vlanT("info_label"));
  return '<div class="xv-adv"><div class="xv-advh"><b>' + esc(vlanT("adv_title")) + "</b>" + esc(vlanT("adv_text")) + '</div><div class="xv-opt">' + vlanButton(v) +
    '<button type="button" class="xv-i" data-xp="vlaninfo" aria-expanded="' + v.pop + '" aria-label="' + label + '" title="' + label + '">' + icon("information-outline") + "</button></div>" +
    (v.pop ? vlanPop() : "") + "</div>";
}

function vlanMistakes(n) {
  let out = "";
  for (var k = 1; vlanTHas("s" + n + "_b" + k + "_s"); k++) out += "<li><b>" + esc(vlanT("s" + n + "_b" + k + "_s")) + "</b><span>" + esc(vlanT("s" + n + "_b" + k + "_r")) + "</span></li>";
  return out ? '<div class="xv-bad"><b>' + esc(vlanT("g_bad")) + "</b><ul>" + out + "</ul></div>" : "";
}

function vlanGuideStep(n) {
  return '<section class="xv-gs"><div class="xv-gn">' + n + "</div><div><h4>" + esc(vlanT("s" + n + "_t")) + "</h4>" +
    '<div class="xv-row"><span class="xv-lbl">' + esc(vlanT("g_where")) + "</span><code>" + esc(vlanT("s" + n + "_where")) + "</code></div>" +
    '<div class="xv-row"><span class="xv-lbl">' + esc(vlanT("g_todo")) + "</span><span>" + esc(vlanT("s" + n + "_todo")) + "</span></div>" +
    '<div class="xv-row"><span class="xv-lbl see">' + esc(vlanT("g_see")) + "</span><span>" + esc(vlanT("s" + n + "_see")) + "</span></div>" + vlanMistakes(n) + "</div></section>";
}

// what the person reads first when the check found nothing: nothing is wrong, the normal export works without this option
function vlanBanner(why) {
  if (why !== "none" && why !== "noha") return "";
  return '<div class="xv-banner" role="status">' + icon("information-outline") + "<div><span>" + esc(vlanT("why_" + why)) + "</span><small>" + esc(vlanT("notneeded") + " " + vlanT("why_" + why + "_sub")) + "</small></div></div>";
}

export function vlanGuide(X) {
  if (!vlanAvailable(X) || !X.vlan.guide) return "";
  let steps = "";
  for (var n = 1; n <= VLAN_GUIDE_STEPS; n++) steps += vlanGuideStep(n);
  let ready = "";
  for (var r = 1; r <= 3; r++) ready += "<div>" + icon("check") + "<span>" + esc(vlanT("ready_" + r)) + "</span></div>";
  return '<div class="xv-guide" role="dialog" aria-labelledby="xv-gtitle"><div class="xv-gt"><h3 id="xv-gtitle">' + esc(vlanT("g_title")) + '</h3><button type="button" class="xv-x" data-xp="vlanclose">' + esc(vlanT("g_close")) + "</button></div>" +
    '<div class="xv-gb">' + vlanBanner(X.vlan.why) + '<p class="xv-lead">' + esc(vlanT("g_lead")) + "</p>" + steps +
    '<div class="xv-ready"><b>' + esc(vlanT("ready_title")) + "</b>" + ready + '</div><div class="xv-gf"><button type="button" class="btn filled" data-xp="vlandone">' + esc(vlanT("g_done")) + "</button></div></div></div>";
}

// the check: asks the server, then the button is green (found) or default with the guide open; never blocks the export, which does not wait for it
function vlanCheck(X, redraw) {
  const v = X.vlan;
  if (v.state === "busy") return;
  if (v.state === "ok") { v.state = "idle"; return; }
  v.state = "busy";
  function done(state, n) {
    if (X.vlan !== v) return;
    v.state = state === "ok" ? "ok" : "idle";
    v.n = state === "ok" ? n : 0;
    if (state !== "ok") { v.guide = true; v.why = state === "none" ? "none" : "noha"; }
    redraw();
    const el = document.querySelector(state === "ok" ? '#exportdlg [data-xp="vlan"]' : '#exportdlg [data-xp="vlanclose"]');
    if (el) el.focus();
  }
  api("/api/export/survey/check", { method: "POST" }).then(function (r) { done(r && r.state, r && r.clients); }).catch(function () { done("noha", 0); });
}

// a click on one of the data-xp="vlan..." elements: true when it was one of ours (the caller redraws)
export function vlanClick(X, act, redraw) {
  if (act === "vlan") vlanCheck(X, redraw);
  else if (act === "vlaninfo") X.vlan.pop = !X.vlan.pop;
  else if (act === "vlanguide") { X.vlan.guide = true; X.vlan.why = null; X.vlan.pop = false; }
  else if (act === "vlanclose" || act === "vlandone") X.vlan.guide = false;
  else return false;
  return true;
}

// Escape closes the guide first, then the small panel, and only then the window itself
export function vlanEscape(X) {
  if (!X || !X.vlan) return false;
  if (X.vlan.guide) { X.vlan.guide = false; return true; }
  if (X.vlan.pop) { X.vlan.pop = false; return true; }
  return false;
}
