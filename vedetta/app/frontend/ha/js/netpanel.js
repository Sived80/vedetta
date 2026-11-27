// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
import { $, api, esc, icon, t } from "./core.js";
import { raiseSnacks, snack, snacksEl } from "./core-ui.js";
import { ignoredEscape, leaveIgnored, mountIgnored, mountedIn, refreshIgnored } from "./ignored.js";

// ----------------------------------------------------------------- the panel «Networks» (v10)
// A view over the page (a dialog that fills the window): the networks Vedetta looks at, one row each (name, network, VLAN, state, devices,
// what Vedetta sees, a quick action, the gear), and a management panel on the right (full screen on a phone). «How to turn it on» is a
// screen of that panel. Everything comes from /api/networks: the server judges what each network gives (caps), the page only shows it.
// Switches only for ports and model, where the server gives one (decisions 1A and «A» of 13/11): a switch sends the touch it names.
// The focus stays on the control used and the panel does not jump: a redraw keeps the scroll and puts the focus back on the same control
// (or on the one that takes its place).
// The ignored devices are shown where they belong (ignored.js): those of a network in its panel, the others in «In every network» under the list.
var viewEl = $("netview");
var NP = { data: null, open: null, busy: false };
var CAPS = ["pres", "name", "mac", "port", "deep", "quiet", "stray"];
var CAP_ICON = { pres: icon("heart"), name: icon("card-account-details"), mac: icon("barcode"), port: icon("lan"), deep: icon("devices"), quiet: icon("ghost"), stray: icon("account-question") };
var SRC_ICON = { ved: icon("radar"), ha: icon("home-assistant"), router: icon("router") };
var STATE_CHIP = { on: "ok", "new": "warn", mute: "warn", paused: "off" };

function T(key, vars) { return t("js.networks." + key, vars); }
function capName(k) { return T("cap." + k); }
function nets() { return NP.data ? [NP.data.main].concat(NP.data.networks) : []; }
function find(id) { return nets().filter(function (n) { return n.id === id; })[0] || null; }
function isMain(n) { return n.id === NP.data.main.id; }
function direct(n) { return n.via.indexOf("direct") >= 0; }
function label(n) { return n.name || n.cidr; }
function netState(n) {
  if (n.state === "paused") return "paused";
  if (n.state === "proposed") return "new";
  return n.mute ? "mute" : "on";
}

// ---- the list
function legend() {
  function it(cls, ic, text) { return '<span class="np-it"><span class="np-ico ' + cls + '">' + ic + "</span>" + esc(text) + "</span>"; }
  return '<div class="np-legend"><div class="np-lg"><h3>' + esc(T("ui.sources")) + "</h3>" + ["ved", "ha", "router"].map(function (s) { return it("k-" + s, SRC_ICON[s], T("source." + s)); }).join("") +
    '</div><span class="np-sep"></span><div class="np-lg"><h3>' + esc(T("ui.missing")) + "</h3>" + it("np-lk", icon("help-circle-outline"), T("ui.can_on")) +
    it("np-sn", icon("clock-outline"), T("ui.soon")) + "</div></div>";
}
function bar(n, k) {
  const c = n.caps[k];
  if (c.state === "on") return '<i class="on k-' + c.source + '" title="' + esc(T("ui.bar_on", { cap: capName(k), src: T("source." + c.source) })) + '"></i>';
  if (c.state === "how") return '<i class="how" title="' + esc(T("ui.bar_how", { cap: capName(k) })) + '"></i>';
  return '<i title="' + esc(T(c.state === "soon" ? "ui.bar_soon" : "ui.bar_off", { cap: capName(k) })) + '"></i>';
}
function coverage(n) {
  const on = CAPS.filter(function (k) { return n.caps[k].state === "on"; }).length;
  return '<div class="np-cov"><div class="np-bars">' + CAPS.map(function (k) { return bar(n, k); }).join("") + "</div><span>" + esc(T("ui.of", { n: on, all: CAPS.length })) + "</span></div>";
}
// The quick action of a row: adopt a new network, pause or resume a written one; the main network has none.
function quickOf(n) {
  const st = netState(n);
  if (st === "new") return { act: "adopt", ic: icon("check"), cls: " go" };
  if (isMain(n)) return null;
  return st === "paused" ? { act: "resume", ic: icon("play"), cls: "" } : { act: "pause", ic: icon("pause"), cls: "" };
}
function quick(n) {
  const q = quickOf(n);
  if (!q) return '<span class="np-ph"></span>';
  const text = T("ui." + q.act);
  return '<button type="button" class="np-ib' + q.cls + '" data-np-act="' + esc(n.id + "|" + q.act) + '" title="' + esc(text) + '" aria-label="' + esc(text + " " + label(n)) + '">' + q.ic + "</button>";
}
function row(n) {
  const st = netState(n);
  const devs = st === "paused" ? "—" : T("ui.of", { n: n.on, all: n.cards });
  return '<div role="row" class="np-gr np-rw' + (st === "new" || st === "mute" ? " need" : "") + (st === "paused" ? " paused" : "") + '">' +
    '<div role="cell"><b class="np-nm">' + esc(label(n)) + '</b></div><div role="cell"><span class="np-mono">' + esc(n.cidr) + "</span></div>" +
    '<div role="cell" class="c-vlan"><span class="np-mono">' + esc(n.vlan || "—") + '</span></div><div role="cell" class="keep"><span class="np-chip ' + STATE_CHIP[st] + '">' +
    esc(T("ui.state_" + st)) + '</span></div><div role="cell">' + esc(devs) + '</div><div role="cell">' + coverage(n) + '</div><div role="cell" class="keep c-btn">' + quick(n) +
    '</div><div role="cell" class="keep c-btn"><button type="button" class="np-ib gear" data-np-open="' + esc(n.id) + '" title="' + esc(T("ui.manage")) + '" aria-label="' +
    esc(T("ui.manage_one", { name: label(n) })) + '">' + icon("cog") + "</button></div></div>";
}
function listHtml() {
  const cols = ["col_name", "col_net", "col_vlan", "col_state", "col_devices", "col_sees", "col_action", "manage"];
  const head = '<div role="row" class="np-gr np-hd">' + cols.map(function (c, i) { return '<div role="columnheader"' + (i === 2 ? ' class="c-vlan"' : "") + ">" + esc(T("ui." + c)) + "</div>"; }).join("") + "</div>";
  return '<div class="np-list"><div class="np-tw"><div class="np-grid" role="table" aria-label="' + esc(T("ui.title")) + '">' + head + nets().map(row).join("") + "</div></div></div>";
}
function viewHtml() {
  // Like every page and window of the app: the X first, on the left, then the title (the rule of the windows, 17/10).
  return '<div class="np-top"><button type="button" class="np-ib" id="np-x" title="' + esc(T("ui.close")) + '" aria-label="' + esc(T("ui.close")) + '">' + icon("close") +
    '</button><h2 id="netview-title">' + esc(T("ui.title")) + '</h2><span class="np-grow"></span><button type="button" class="np-btn" id="np-add">' + icon("plus") + esc(T("ui.add")) + '</button></div><div class="np-wrap">' + legend() + '<div id="np-rows">' + listHtml() + '</div><section class="ig-host np-allign" id="np-ign-all" aria-labelledby="ig-all-title"></section></div>' +
    '<div id="np-host"></div>';
}

// ---- the management panel: one network
function switchHtml(c, k) {
  return '<button type="button" class="np-sw k-' + (c.source || "ved") + '" role="switch" aria-checked="' + !!c.switch.on + '" data-np-tog="' + k + '" aria-label="' + esc(capName(k)) + '"></button>';
}
function capRight(n, k) {
  const c = n.caps[k];
  if (n.state === "paused") return '<span class="np-muted">' + esc(T("ui.paused")) + "</span>";
  // asked (switch on) but stopped (the router blocks the probes): the guide that unblocks it comes first, the switch stays beside it
  const how = c.state === "how" ? '<button type="button" class="np-how" data-np-how="' + k + '">' + esc(T("ui.how")) + icon("chevron-right") + "</button>" : "";
  if (c.switch && how) return '<span class="np-pair">' + how + switchHtml(c, k) + "</span>";      // one cell of the grid: the row keeps its three columns
  if (c.switch) return switchHtml(c, k);
  if (c.state === "soon") return '<span class="np-soon">' + icon("clock-outline") + esc(T("ui.soon")) + "</span>";
  return how;
}
function capRow(n, k) {
  const c = n.caps[k];
  const sub = c.source && c.state !== "how"
    ? '<span class="np-sub src k-' + c.source + '">' + SRC_ICON[c.source] + "<span>" + esc(T("source." + c.source) + " · " + T("by." + c.by)) + "</span></span>"
    : '<span class="np-sub"><span>' + esc(T("capd." + k)) + "</span></span>";
  return '<div class="np-cap"><span class="np-cic">' + CAP_ICON[k] + '</span><div class="np-mid"><b>' + esc(capName(k)) + "</b>" + sub + "</div>" + capRight(n, k) + "</div>";
}
function stateButtons(n) {
  const st = netState(n), out = [];
  if (st === "new") out.push('<button type="button" class="np-btn" data-np-pact="adopt">' + icon("check") + esc(T("ui.adopt_long")) + "</button>");
  if (!isMain(n) && st !== "new") {
    out.push(st === "paused" ? '<button type="button" class="np-btn flat" data-np-pact="resume">' + icon("play") + esc(T("ui.resume_long")) + "</button>"
      : '<button type="button" class="np-btn flat" data-np-pact="pause">' + icon("pause") + esc(T("ui.pause_long")) + "</button>");
  }
  return out.length ? '<section class="np-sec"><h4>' + esc(T("ui.sec_state")) + '</h4><div class="np-btns">' + out.join("") + "</div></section>" : "";
}
// «Delete this network»: the confirmation says what goes, counted by the server (GET .../purge) before anything is deleted.
// The main network is never deleted: its danger zone deletes its devices only, and Vedetta starts over there as at the first install.
var DANGER = { text: "js.networks.ui.danger_text", ask: "js.networks.ui.delete", title: "js.networks.ui.confirm_title", after: "js.networks.ui.confirm_text" };
var DANGER_MAIN = { text: "js.networks.ui.danger_main_text", ask: "js.networks.ui.delete_main", title: "js.networks.ui.confirm_main_title", after: "js.networks.ui.confirm_main_text" };
// the counts as the page's language writes numbers (33.000, 33,000), never a bare 33000
function countsText(c) {
  const out = {}, lang = document.documentElement.lang || undefined;
  Object.keys(c).forEach(function (k) { out[k] = typeof c[k] === "number" ? c[k].toLocaleString(lang) : c[k]; });
  return out;
}
function danger(n) {
  const c = NP.open.counts, k = isMain(n) ? DANGER_MAIN : DANGER;
  const body = NP.open.confirm
    ? '<div class="np-confirm" role="alert"><b>' + esc(t(k.title, { name: label(n) })) + "</b><span>" + esc(c ? T("ui.confirm_counts", countsText(c)) : T("ui.counting")) + "</span>" + (c && c.ignored ? "<span>" + esc(T("ui.confirm_ignored", c)) + "</span>" : "") + "<span>" +
      esc(t(k.after)) + '</span><div class="np-two"><button type="button" class="np-btn flat" data-np-pact="nodel">' + esc(T("ui.cancel")) +
      '</button><button type="button" class="np-btn red" data-np-pact="del"' + (c ? "" : " disabled") + ">" + esc(T("ui.delete_do")) + "</button></div></div>"
    : '<button type="button" class="np-btn ghost-red" data-np-pact="askdel">' + icon("delete-outline") + esc(t(k.ask)) + "</button>";
  return '<section class="np-sec"><h4>' + esc(T("ui.sec_danger")) + '</h4><div class="np-danger"><p>' + esc(t(k.text)) + "</p>" + body + "</div></section>";
}
function vlanField(n) {
  if (direct(n)) return "<dt>" + esc(T("ui.f_vlan")) + "</dt><dd>" + esc(n.vlan || "—") + (n.vlan ? ' <span class="np-muted">' + esc(T("ui.vlan_host")) + "</span>" : "") + "</dd>";
  return '<dt><label for="np-vlan">' + esc(T("ui.f_vlan")) + '</label></dt><dd><input id="np-vlan" class="np-in np-mono" inputmode="numeric" value="' + esc(n.vlan || "") + '"></dd>';
}
// A network behind the router (step P11): its devices are found by ping, and without a MAC an address that changes looks like a new device.
function routedNote(n) {
  return direct(n) ? "" : '<p class="np-muted np-routed">' + esc(T("ui.routed_note")) + "</p>";
}
function mainHtml(n) {
  const st = netState(n);
  return '<section class="np-sec"><h4>' + esc(T("ui.sec_net")) + '</h4><div class="np-field"><label for="np-name">' + esc(T("ui.f_name")) + '</label><input id="np-name" class="np-in" maxlength="32" value="' +
    esc(n.name || "") + '"></div><dl class="np-kv"><dt>' + esc(T("ui.f_address")) + '</dt><dd class="np-mono">' + esc(n.cidr) + "</dd>" + vlanField(n) + "<dt>" + esc(T("ui.f_link")) + "</dt><dd>" +
    esc(T(direct(n) ? "ui.link_direct" : "ui.link_routed")) + "</dd><dt>" + esc(T("ui.col_state")) + '</dt><dd><span class="np-chip ' + STATE_CHIP[st] + '">' + esc(T("ui.state_" + st)) +
    "</span></dd></dl>" + routedNote(n) + "</section>" + stateButtons(n) + '<section class="np-sec"><h4>' + esc(T("ui.sec_sees")) + '</h4><div class="np-caps">' +
    CAPS.map(function (k) { return capRow(n, k); }).join("") + "</div></section>" + '<section class="np-sec"><h4>' + esc(T("ui.sec_ignored")) +
    '</h4><div class="ig-host np-ign" id="np-ign-net"></div></section>' + danger(n);
}

// ---- «How to turn it on»: one card per way, an «OR» between them
function crumb(n, c) { return c === "net" ? (n.vlan ? T("ui.net_vlan", { n: n.vlan }) : label(n)) : T("where." + c); }
function wayWhat(w) {
  let what = esc(T("way." + w.id + ".what", { from: w.params.from || "?", to: w.params.to || "" }));
  if (w.id === "ha_inside" && w.params.vlan) what += " " + esc(T("ui.inside_vlan"));
  if (w.params.example) what += '<span class="np-ex">' + esc(T("ui.example", { cmd: "" })) + '<span class="np-exc">' + esc(w.params.example) + "</span></span>";
  return what;
}
function wayCard(n, w) {
  const pill = w.best ? '<span class="np-pill best">' + esc(T("ui.best")) + "</span>" : w.soon ? '<span class="np-pill soon">' + esc(T("ui.soon")) + "</span>" : "";
  const crumbs = '<div class="np-crumbs">' + w.where.map(function (c) { return "<span>" + esc(crumb(n, c)) + "</span>"; }).join("<i>›</i>") + "</div>";
  return '<article class="np-way' + (w.best ? " best" : "") + '"><div class="np-way-top"><span class="np-ico k-' + w.by + '">' + SRC_ICON[w.by] + '</span><div class="np-wt"><span class="np-by">' +
    esc(T("source." + w.by)) + "</span><b>" + esc(T("way." + w.id + ".title")) + "</b></div>" + pill + "</div>" +
    '<div class="np-wrow"><span>' + esc(T("ui.row_where")) + "</span><div>" + crumbs + "</div></div>" +
    '<div class="np-wrow"><span>' + esc(T("ui.row_what")) + "</span><div><span>" + wayWhat(w) + "</span></div></div>" +
    '<div class="np-wrow"><span>' + esc(T("ui.row_sec")) + "</span><div><span>" + esc(T("way." + w.id + ".sec")) + "</span></div></div>" +
    (w.id === "snmp" ? '<div class="np-snmp" id="np-snmp">' + snmpForm() + "</div>" : "") + "</article>";
}

// ---- the SNMP way: the router's address and the community, written here (the community never comes back from the server), «Try»
var SN = { router: "", set: false, msg: null, busy: false };
function snmpForm() {
  const msg = SN.msg ? '<div class="np-snmp-msg ' + (SN.msg.ok ? "ok" : "fail") + '">' + esc(SN.msg.text) + "</div>" : "";
  return '<label><span>' + esc(T("snmp.router")) + '</span><input id="np-snmp-router" inputmode="decimal" autocomplete="off" spellcheck="false" value="' + esc(SN.router) + '"></label>' +
    '<label><span>' + esc(T("snmp.community")) + '</span><input id="np-snmp-comm" type="password" autocomplete="off" placeholder="' + esc(SN.set ? T("snmp.kept") : "") + '"></label>' +
    '<div class="np-snmp-acts"><button type="button" class="btn text rp" data-np-snmp="try"' + (SN.busy ? " disabled" : "") + ">" + esc(T("snmp.try")) + "</button>" +
    '<button type="button" class="btn tonal rp" data-np-snmp="save"' + (SN.busy ? " disabled" : "") + ">" + esc(T("snmp.save")) + "</button></div>" + msg;
}
function snmpPaint() { const box = $("np-snmp"); if (box) box.innerHTML = snmpForm(); }
function snmpLoad() { api("/api/snmp").then(function (s) { SN.router = s.snmp_router || ""; SN.set = !!s.snmp_community_set; snmpPaint(); }).catch(function () {}); }
function snmpAct(what) {
  const r = $("np-snmp-router"), c = $("np-snmp-comm");
  if (r) SN.router = r.value.trim();
  SN.busy = true; SN.msg = null; snmpPaint();
  const body = { snmp_router: SN.router };
  if (c && c.value) body.snmp_community = c.value;
  const save = what === "save" || (c && c.value) ? api("/api/snmp", { method: "POST", json: body }) : Promise.resolve(null);
  save.then(function (s) {
    if (s) SN.set = !!s.snmp_community_set;
    return what === "try" ? api("/api/snmp/test", { method: "POST", json: {} }) : null;
  }).then(function (res) {
    if (res) SN.msg = res.ok ? { ok: true, text: T("snmp.ok", { n: res.rows }) } : { ok: false, text: res.error === "not_configured" ? T("snmp.off") : T("snmp.fail", { error: res.error || "" }) };
    else if (what === "save") snack(T("snmp.saved"), { kind: "success" });
  }).catch(function (err) {
    // a value the server refuses (400) is said in the page's language: the address of the router, or the community
    const refused = err && err.status === 400 ? (/community/.test(String(err.detail || "")) ? T("snmp.bad_community") : T("snmp.bad_router")) : "";
    SN.msg = { ok: false, text: refused || (err && err.message) || "" };
  })
    .then(function () { SN.busy = false; snmpPaint(); });
}
function guideHtml(n, k) {
  const or = '<div class="np-or" role="separator"><span>' + esc(T("ui.or")) + "</span></div>";
  return '<div class="np-lead"><div class="np-lt"><span class="np-cic">' + CAP_ICON[k] + "</span><h3>" + esc(T("ui.activate", { cap: capName(k) })) + "</h3></div><p>" + esc(T("how." + k + ".lead")) + "</p></div>" +
    '<div class="np-ways">' + n.caps[k].ways.map(function (w) { return wayCard(n, w); }).join(or) + '</div><div class="np-foot"><p>' + esc(T("ui.foot_done")) + "</p><p>" + esc(T("ui.foot_menus")) + "</p></div>";
}

// ---- «Add network»: «Try» first (the server pings each address once and judges what Vedetta would see, nothing saved), then «Add»
var LATER = { soon: "js.networks.ui.soon", off: "js.networks.ui.later_off", how: "js.networks.ui.later_how" };
function trialCap(r, k) {
  const c = r.caps[k];
  const sub = c.state === "on" ? '<span class="np-sub src k-' + c.source + '">' + SRC_ICON[c.source] + "<span>" + esc(T("source." + c.source) + " · " + T("by." + c.by)) + "</span></span>"
    : '<span class="np-sub"><span>' + esc(t(LATER[c.state] || LATER.how)) + "</span></span>";
  return '<div class="np-cap"><span class="np-cic">' + CAP_ICON[k] + '</span><div class="np-mid"><b>' + esc(capName(k)) + "</b>" + sub + "</div></div>";
}
function trialHtml(r) {
  const said = r.answer ? T("ui.test_answer", { n: r.answer, all: r.asked }) : T("ui.test_none");
  return '<section class="np-sec np-trial" role="status"><h4>' + esc(T("ui.test_sees")) + "</h4><p>" + esc(said) + "</p>" +
    (r.sample.length ? '<p class="np-muted np-mono">' + esc(r.sample.join(", ")) + "</p>" : "") + '<div class="np-caps">' + CAPS.map(function (k) { return trialCap(r, k); }).join("") + "</div></section>";
}
function addButtons(o) {
  const off = NP.busy ? " disabled" : "";
  if (!o.result) return '<button type="button" class="np-btn" data-np-pact="test"' + off + ">" + icon("radar") + esc(T("ui.test_do")) + "</button>";
  return '<div class="np-two"><button type="button" class="np-btn flat" data-np-pact="test"' + off + ">" + esc(T("ui.test_again")) + '</button><button type="button" class="np-btn" data-np-pact="try"' + off + ">" +
    icon("check") + esc(T("ui.add_do")) + "</button></div>";
}
function addHtml() {
  const o = NP.open, bad = o.tried && !cidrOk((o.cidr || "").trim());
  return '<section class="np-sec"><div class="np-field"><label for="np-a-name">' + esc(T("ui.f_name")) + '</label><input id="np-a-name" class="np-in" maxlength="32" placeholder="' +
    esc(T("ui.name_ph")) + '" value="' + esc(o.name || "") + '" data-np-af="name"></div><div class="np-field"><label for="np-a-cidr">' + esc(T("ui.f_cidr")) +
    '</label><input id="np-a-cidr" class="np-in np-mono' + (bad ? " bad" : "") + '" placeholder="192.168.30.0/24" value="' + esc(o.cidr || "") + '" data-np-af="cidr"><span class="np-hint' +
    (bad ? " bad" : "") + '">' + esc(T(bad ? "ui.cidr_bad" : "ui.cidr_hint")) + '</span></div><div class="np-field"><label for="np-a-vlan">' + esc(T("ui.f_vlan")) +
    '</label><input id="np-a-vlan" class="np-in np-mono" inputmode="numeric" value="' + esc(o.vlan || "") + '" data-np-af="vlan"><span class="np-hint">' + esc(T("ui.vlan_hint")) +
    '</span></div></section><p class="np-muted"' + (o.testing ? ' role="status">' + esc(T("ui.testing")) : ">" + esc(T("ui.add_note"))) + "</p>" + (o.result ? trialHtml(o.result) : "") +
    '<div class="np-btns">' + addButtons(o) + "</div>";
}
var CIDR = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\/(\d{1,2})$/;
function cidrOk(s) {
  const m = CIDR.exec(s || "");
  if (!m) return false;
  for (let i = 1; i < 5; i++) if (+m[i] > 255) return false;
  return +m[5] >= 22 && +m[5] <= 30;
}

function panelHtml() {
  const o = NP.open, n = o.add ? null : find(o.id);
  let title = T("ui.add"), body;
  if (o.add) body = addHtml();
  else if (o.guide) { title = label(n); body = guideHtml(n, o.guide); }
  else { title = label(n); body = mainHtml(n); }
  // One button on the left, as in the card of a device: the X closes; inside a guide the same X goes back one step.
  const lead = o.guide ? '<button type="button" class="np-ib" data-np-back="1" title="' + esc(T("ui.back")) + '" aria-label="' + esc(T("ui.back")) + '">'
    : '<button type="button" class="np-ib" data-np-close="1" title="' + esc(T("ui.close")) + '" aria-label="' + esc(T("ui.close")) + '">';
  return '<div class="np-scrim" data-np-close="1"></div><aside class="np-panel" role="dialog" aria-modal="true" aria-labelledby="np-ptitle"><div class="np-ptop">' + lead + icon("close") +
    '</button><h2 id="np-ptitle">' + esc(title) + '</h2></div><div class="np-pbody">' + body + "</div></aside>";
}

// ---- drawing without losing the place
var KEYS = ["data-np-tog", "data-np-how", "data-np-pact", "data-np-af", "data-np-back", "data-np-act", "data-np-open"];
var COUNTERPART = { '[data-np-pact="askdel"]': '[data-np-pact="nodel"]', '[data-np-pact="nodel"]': '[data-np-pact="askdel"]', '[data-np-pact="adopt"]': '[data-np-pact="pause"]',
  '[data-np-pact="pause"]': '[data-np-pact="resume"]', '[data-np-pact="resume"]': '[data-np-pact="pause"]' };
function focusKey(el) {
  if (!el || !viewEl.contains(el)) return null;
  for (let i = 0; i < KEYS.length; i++) if (el.hasAttribute(KEYS[i])) return "[" + KEYS[i] + '="' + el.getAttribute(KEYS[i]) + '"]';
  return el.id ? "#" + el.id : null;
}
function quickCounterpart(key) {
  // a quick action changes into another one (pause -> resume): the focus goes to the new button of the same row
  const m = /^\[data-np-act="(.*)\|(\w+)"\]$/.exec(key || "");
  return m ? viewEl.querySelector('[data-np-act^="' + m[1] + '|"]') : null;
}
function refocus(key) {
  const el = key && (viewEl.querySelector(key) || (COUNTERPART[key] && viewEl.querySelector(COUNTERPART[key])) || quickCounterpart(key));
  if (el) el.focus({ preventScroll: true });
}
function drawRows() {
  const key = focusKey(document.activeElement), rows = $("np-rows");
  if (!rows) return;
  rows.innerHTML = listHtml();
  if (!NP.open) refocus(key);
}
// ---- the ignored devices: an address in a network belongs to it (a MAC: its last known address); the rest is in every network
function ipNum(ip) {
  const p = String(ip || "").split(".");
  return p.length === 4 && p.every(function (x) { return /^\d{1,3}$/.test(x) && +x < 256; }) ? ((+p[0] * 256 + +p[1]) * 256 + +p[2]) * 256 + +p[3] : -1;
}
function inCidr(ip, cidr) {
  const m = /^(.+)\/(\d+)$/.exec(cidr || ""), a = ipNum(ip);
  if (!m || a < 0) return false;
  const size = Math.pow(2, 32 - +m[2]), base = ipNum(m[1]);
  return a >= base && a < base + size;
}
function ignoredOf(n) { return function (r) { return inCidr(r.ip, n.cidr); }; }
function ignoredElsewhere(r) { return !nets().some(function (n) { return inCidr(r.ip, n.cidr); }); }
function placeIgnored(again) {
  const box = $("np-ign-net"), all = $("np-ign-all");
  if (NP.open && box) mountIgnored(box, ignoredOf(find(NP.open.id)), false);
  else if (!NP.open && all && (again || mountedIn() !== all)) mountIgnored(all, ignoredElsewhere, true);
}
function render(opts) {
  opts = opts || {};
  const host = $("np-host");
  if (!host) return;
  if (!NP.open) { host.innerHTML = ""; placeIgnored(); return; }
  if (mountedIn() && host.contains(mountedIn())) leaveIgnored();
  const first = !host.querySelector(".np-panel"), pb = host.querySelector(".np-pbody");
  const top = opts.top != null ? opts.top : (pb ? pb.scrollTop : 0), key = opts.focus || focusKey(document.activeElement);
  host.innerHTML = panelHtml();
  if (first) host.querySelector(".np-panel").classList.add("enter");
  host.querySelector(".np-pbody").scrollTop = top;
  placeIgnored();
  refocus(key);
}
function show(data) {
  NP.data = data;
  if (NP.open && NP.open.id && !find(NP.open.id)) NP.open = null;
  drawRows();
  render();
}

// ---- talking to the server: every answer is the whole list
function failed(err) {
  NP.busy = false;
  const d = err && err.detail;
  snack(d && typeof d.message === "string" ? d.message : T("ui.failed"), { kind: "error" });
  render();
  runAfter();
}
function send(path, method, body) {
  NP.busy = true;
  return api(path, { method: method, json: body }).then(function (data) { NP.busy = false; show(data); runAfter(); return data; }, failed);
}
// A click that came while the server was busy (a name saved on leaving its field, then «Pause» at once) is done when the answer is drawn,
// never dropped (19/11 review). Only the last one waits; closing the panel or the view forgets it. It is done only where it was
// made: in the same panel, or in the list if no panel was open (a panel closed during a try leaves a click in the list to do).
function runAfter() {
  const next = NP.after;
  NP.after = null;
  if (next && !NP.busy && viewEl.open && next.open === NP.open) next.run(next.el);
}
function change(n, body) { return send("/api/networks/" + encodeURIComponent(n.id), "POST", body); }
var STATE_OF = { adopt: "confirmed", resume: "confirmed", pause: "paused" };

export function openNetPanel() {
  snmpLoad();
  Promise.all([api("/api/networks"), refreshIgnored()]).then(function (res) {
    NP.data = res[0];
    NP.open = null;
    leaveIgnored();
    viewEl.innerHTML = viewHtml();
    placeIgnored(true);
    if (!viewEl.open) {
      if (typeof viewEl.showModal === "function") viewEl.showModal(); else viewEl.setAttribute("open", "");
      if (snacksEl.children.length) raiseSnacks();
    }
    $("np-x").focus();
  }).catch(function () { snack(T("ui.load_failed"), { kind: "error" }); });
}
function closeView() {
  leaveIgnored();
  NP.open = null;
  NP.after = null;
  if (viewEl.open && typeof viewEl.close === "function") viewEl.close(); else viewEl.removeAttribute("open");
  viewEl.innerHTML = "";
}
function closePanel() {
  const id = NP.open && NP.open.id;
  NP.open = null;
  NP.after = null;
  render();
  const g = id && viewEl.querySelector('[data-np-open="' + id + '"]');
  if (g) g.focus();
}
function back() {
  const k = NP.open.guide;
  NP.open.guide = null;
  render({ top: NP.open.mainTop || 0, focus: '[data-np-how="' + k + '"]' });
}
function candidate(o) {
  o.nid = o.nid || "n" + Date.now().toString(36);
  const cidr = (o.cidr || "").trim(), name = (o.name || "").trim(), vlan = (o.vlan || "").trim();      // kept as typed, trimmed when sent
  return { id: o.nid, cidr: cidr, via: ["routed"], state: "confirmed", name: name || null, vlan: vlan ? Number(vlan) : null };
}
function written(o) {
  o.tried = true;
  if (cidrOk((o.cidr || "").trim())) return true;
  render({ focus: "#np-a-cidr" });
  return false;
}
function tryNet() {
  const o = NP.open;
  if (!written(o)) return;
  o.result = null;
  o.testing = NP.busy = true;
  render();
  api("/api/networks/test", { method: "POST", json: candidate(o), timeout: 90000 }).then(function (r) {
    o.testing = NP.busy = false;
    if (NP.open !== o) { runAfter(); return; }
    o.result = r;
    render({ focus: '[data-np-pact="try"]' });
    runAfter();
  }, function (err) { o.testing = false; failed(err); });
}
function tryAdd() {
  const o = NP.open;
  if (!written(o)) return;
  render();
  send("/api/networks", "POST", candidate(o)).then(function (data) { if (data) closePanel(); });
}
function purgePath(n) { return "/api/networks/" + encodeURIComponent(n.id) + "/purge"; }
function askPurge(n) {
  const o = NP.open;
  o.confirm = true;
  o.counts = null;
  render();
  // the count failed: the notice, and back to the «Delete» button (never stuck on «Counting…» with «Delete all» off)
  api(purgePath(n)).then(function (c) { if (NP.open === o && o.confirm) { o.counts = c; render(); } }, function (err) { o.confirm = false; failed(err); });
}
function panelAction(act) {
  const n = find(NP.open.id);
  if (act === "askdel") { askPurge(n); return; }
  if (act === "nodel") { NP.open.confirm = false; render(); return; }
  if (act === "del") { send(purgePath(n), "POST").then(function (data) { if (data) { closePanel(); refreshIgnored().then(function () { placeIgnored(true); }); } }); return; }
  change(n, { state: STATE_OF[act] });
}
function toggle(k) {
  const n = find(NP.open.id), sw = n.caps[k].switch;
  change(n, { touch: sw.on ? sw.touch_off : sw.touch_on });
}
function saveField(el) {
  const n = find(NP.open.id), value = el.value.trim();
  if (el.id === "np-name") {
    if (value === (n.name || "")) return;
    send(isMain(n) ? "/api/networks/main" : "/api/networks/" + encodeURIComponent(n.id), "POST", { name: value || null });
    return;
  }
  change(n, { vlan: value === "" ? null : Number(value) });
}
var CLICKS = [
  ["#np-x", function () { closeView(); }],
  ["#np-add", function () { NP.open = { add: true }; render({ focus: "#np-a-name" }); }],
  ["[data-np-open]", function (el) { NP.open = { id: el.dataset.npOpen }; render({ focus: '.np-ptop [data-np-close="1"]' }); }],
  ["[data-np-act]", function (el) { const p = el.dataset.npAct.split("|"); change(find(p[0]), { state: STATE_OF[p[1]] }); }],
  ["[data-np-close]", function () { closePanel(); }],
  ["[data-np-back]", function () { back(); }],
  ["[data-np-tog]", function (el) { toggle(el.dataset.npTog); }],
  ["[data-np-how]", function (el) { NP.open.mainTop = $("np-host").querySelector(".np-pbody").scrollTop; NP.open.guide = el.dataset.npHow; render({ top: 0, focus: '[data-np-back="1"]' }); }],
  ["[data-np-snmp]", function (el) { if (!SN.busy) snmpAct(el.dataset.npSnmp); }],
  ["[data-np-pact]", function (el) { const a = el.dataset.npPact; if (a === "try") tryAdd(); else if (a === "test") tryNet(); else panelAction(a); }],
];
// The ways out (the X of the view and of the panel, «back») work at once, also while the server is busy (a try takes up to half a minute).
const FREE = { "#np-x": 1, "[data-np-close]": 1, "[data-np-back]": 1 };
viewEl.addEventListener("click", function (e) {
  if (e.target === viewEl) return;
  for (let i = 0; i < CLICKS.length; i++) {
    const el = e.target.closest(CLICKS[i][0]);
    if (!el) continue;
    if (NP.busy && !FREE[CLICKS[i][0]]) NP.after = { run: CLICKS[i][1], el: el, open: NP.open };
    else CLICKS[i][1](el);
    return;
  }
});
viewEl.addEventListener("input", function (e) {
  const o = NP.open;
  if (!o || !e.target.dataset.npAf) return;
  o[e.target.dataset.npAf] = e.target.value;            // as typed: a redraw must not take a space away (trimmed in candidate())
  if (o.result) { o.result = null; render(); }      // a changed network is not the one tried: try it again
});
viewEl.addEventListener("change", function (e) { if (NP.open && (e.target.id === "np-name" || e.target.id === "np-vlan")) saveField(e.target); });
viewEl.addEventListener("keydown", function (e) {
  if (e.key === "Enter" && e.target.dataset && e.target.dataset.npAf && !NP.busy) { e.preventDefault(); if (NP.open.result) tryAdd(); else tryNet(); }
  if (e.key === "Tab") keepInPanel(e);
});
// The side panel says it is modal (aria-modal): Tab and Shift+Tab go round its own controls, never to the rows behind the shade (19/11 review).
function keepInPanel(e) {
  const panel = NP.open && viewEl.querySelector(".np-panel");
  if (!panel) return;
  const all = Array.from(panel.querySelectorAll("button:not([disabled]), input:not([disabled]), select, textarea, a[href], [tabindex]:not([tabindex='-1'])"))
    .filter(function (el) { return !el.closest("[hidden]"); });
  if (!all.length) return;
  const first = all[0], last = all[all.length - 1], at = document.activeElement;
  if (!panel.contains(at)) { e.preventDefault(); first.focus(); }
  else if (!e.shiftKey && at === last) { e.preventDefault(); first.focus(); }
  else if (e.shiftKey && at === first) { e.preventDefault(); last.focus(); }
}
// Escape: back from «How to turn it on», then the panel, then the view.
viewEl.addEventListener("cancel", function (e) {
  e.preventDefault();
  if (ignoredEscape()) return;
  if (!NP.open) closeView();
  else if (NP.open.guide) back();
  else closePanel();
});
