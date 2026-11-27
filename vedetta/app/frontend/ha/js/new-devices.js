// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
import { COMPACT, LANG, REDUCED, api, esc, icon, ipKey, nowSec, t } from "./core.js";
import { S, snack } from "./core-ui.js";
import { schedule } from "./live.js";
import { paintNewDot } from "./net-gauge.js";

// ---------------------------------------------------- new devices
// The list is not a card of its own: it is a panel of the network card (filters.js puts it between the badges and the brands),
// so the card grows downwards when there is something to add and the log under it follows.
export var newEl = document.createElement("div");
newEl.id = "card-new";
newEl.className = "nd-panel";
newEl.hidden = true;
// Rows of the card: the devices found by the last scan (S.found, with
// Add) and the never-seen MACs detected on the network (S.newDevices); no duplicates by IP.
// The rows being added (S.adding) stay in the card until "Close", even when the server no longer lists them as new.
// A device not heard for 15 minutes is asleep: the list shows only the devices that answer now (the user, 17/11, in place of P7
// decision 3A that kept them with "seen 9 h ago"). The server still remembers them for 7 days; they come back as soon as they answer.
const ASLEEP_S = 900;
function asleep(d) { return !!(d.lastSeen && nowSec() - d.lastSeen > ASLEEP_S); }
// A device the app saw by itself that the card would show: not closed with «Cancel», answering now.
function shownNew(d) { return !S.dismissedNew[String(d.mac || d.ip).toUpperCase()] && !asleep({ lastSeen: d.last_seen }); }
// The +N on the ring: the rows of the card still to be decided, whatever brought them (a search, or the app by itself); not the ones being
// added or added (they stay green until "Close"). The user, 17/11: it counted 5 devices gone for days (touching it showed nothing), not
// the one a search had found, and then still counted it after it was added.
export function newWaitingCount() {
  const ad = S.adding;
  return newRows().filter(function (r) { return !(ad && r.ip && ad.ips[r.ip]); }).length;
}
function newRows() {
  const seen = {}, rows = [];
  // The same device appears only once: by IP or by MAC.
  function keys(d) {
    const k = [];
    if (d.ip) k.push("i:" + d.ip);
    if (d.mac) k.push("m:" + String(d.mac).toUpperCase());
    return k;
  }
  function take(row) {
    const k = keys(row);
    if (k.some(function (x) { return seen[x]; })) return;
    k.forEach(function (x) { seen[x] = true; });
    rows.push(row);
  }
  S.found.forEach(function (h) {
    if (asleep({ lastSeen: h.last_seen })) return;
    take({ src: "found", ip: h.ip, mac: h.mac, name: h.hostname || "", lastSeen: h.last_seen });
  });
  // Never-seen MACs detected on the network are added only after a completed scan.
  const list = (S.scanDone || S.newReady) ? S.newDevices.devices : [];
  list.forEach(function (d) {
    if (!shownNew(d)) return;     // closed with "Cancel" (it comes back only for a device not seen before), or not answering now
    take({ src: "new", ip: d.ip, mac: d.mac, name: d.hostname || "", lastSeen: d.last_seen, net: d.network });     // P11: "network" behind the router
  });
  const ad = S.adding;
  if (ad) Object.keys(ad.ips).forEach(function (ip) { if (ad.meta[ip]) take(ad.meta[ip]); });
  // In IP address order (those without a known one at the bottom).
  rows.sort(function (a, b) { return (a.ip ? ipKey(a.ip) : Infinity) - (b.ip ? ipKey(b.ip) : Infinity); });
  return rows;
}
// The ring in the icon of a row: it turns while the device is analysed, closes when it is saved and stays closed (green) once added.
// The tick is on the right, in place of "Cancel" (the user, 26/11: one spinner and one tick, not two).
function ndRing(state, fresh) {
  const c = '<circle class="tr" cx="16" cy="16" r="13"/>';
  if (state === "run") return '<svg class="nd-ring" viewBox="0 0 32 32" aria-hidden="true">' + c + '<circle class="sp" cx="16" cy="16" r="13"/></svg>';
  if (state === "save") return '<svg class="nd-ring" viewBox="0 0 32 32" aria-hidden="true">' + c + '<circle class="close" cx="16" cy="16" r="13"/></svg>';
  return '<svg class="nd-ring" viewBox="0 0 32 32" aria-hidden="true"><circle class="full' + (fresh ? " fresh" : "") + '" cx="16" cy="16" r="13"/></svg>';
}
function ndTick(fresh) {
  const label = esc(t("js.ha.new.added"));
  return '<span class="nd-tick" role="img" title="' + label + '" aria-label="' + label + '"><svg viewBox="0 0 32 32" aria-hidden="true"><path class="tick' + (fresh ? " fresh" : "") + '" d="M8 16.5l5 5 11-12"/></svg></span>';
}
// A button of the panel is a symbol: the words stay in the tooltip and for screen readers.
function sym(name, label, attrs, cls) {
  return '<button type="button" class="btn text rp nd-sym' + (cls ? " nd-" + cls : "") + '"' + (attrs || "") + ' title="' + esc(label) + '" aria-label="' + esc(label) + '">' + icon(name) + "</button>";
}
// Draws the panel again even if the markup is the same: a button turned off by hand (while a request runs) must come back.
function redrawNew() {
  newEl._markup = "";
  renderNew();
}

export function renderNew() {
  renderNewCard();
  paintNewDot();                                                              // the +N follows the card, every time it is drawn
}
function renderNewCard() {
  if (COMPACT) { newEl.hidden = true; return; }
  const list = newRows();
  if (!list.length) { newEl.hidden = true; newEl.innerHTML = ""; newEl._markup = ""; return; }
  const opening = newEl.hidden;      // the card appears now: it opens (below), instead of the page jumping to it
  newEl.hidden = false;
  const ad = S.adding;  // during the add: {ips, done (analysed), saved, skip (ip -> why not added), sending (add asked), meta, fresh, jobs, list, batch}
  let run = 0, analysed = 0, saved = 0, skipped = 0;
  if (ad) Object.keys(ad.ips).forEach(function (ip) { if (ad.saved[ip]) saved++; else if (ad.skip[ip]) skipped++; else if (ad.done[ip]) analysed++; else run++; });
  const active = run + analysed, total = run + analysed + saved + skipped, fin = !!ad && !active && saved + skipped > 0;
  const none = "<span></span>";
  const rows = list.map(function (d) {
    const state = ad && ad.ips[d.ip] ? (ad.saved[d.ip] ? "done" : ad.skip[d.ip] ? "skip" : ad.done[d.ip] ? "save" : "run") : "idle";
    const label = d.ip || d.mac;  // only IP and MAC: names are found later, by analyzing the device
    let cells;
    if (state === "idle") {
      // A device found by a search, or one behind the router (no MAC, or a MAC Home Assistant said), is ignored by the list of ignored devices.
      const ignAttrs = d.src === "found" || !d.mac || d.net
        ? ' data-ign-ip="' + esc(d.ip) + '" data-ign-mac="' + esc(d.mac || "") + '" data-ign-host="' + esc(d.name || "") + '"'
        : ' data-ignore-mac="' + esc(d.mac) + '"';
      const ignoreBtn = sym("eye-off", t("js.ha.new.ignore"), ignAttrs);
      cells = (d.ip ? sym("plus", t("js.ha.new.add_one"), ' data-add-ip="' + esc(d.ip) + '" data-add-host="' + esc(d.name || "") + '"', "ok") : none) + ignoreBtn;
    } else if (state === "skip") {
      cells = none + none;
    } else if (state === "done") {
      cells = none + ndTick(ad.fresh[d.ip] && Date.now() - ad.fresh[d.ip] < 900);
    } else {
      // One "Cancel" per row being added, also in a batch; off once the add is asked (a save cannot be called back).
      cells = none + sym("close", t("js.ha.cancel"), ' data-add-cancel="' + esc(d.ip) + '"' + (ad.sending[d.ip] ? " disabled" : ""));
    }
    const fresh = state === "done" && ad.fresh[d.ip] && Date.now() - ad.fresh[d.ip] < 900;
    const ic = state === "idle" ? icon("devices") : state === "skip" ? icon("alert-circle") : ndRing(state, fresh);
    // A row not added says why in place of its MAC (the reason is what the person needs now).
    const sub = state === "skip" ? '<span class="nd-why">' + esc(skipText(ad.skip[d.ip])) + "</span>" : esc(d.ip && d.mac ? d.mac : "");
    return '<div class="nd-row nd-' + state + '" data-ip="' + esc(d.ip || "") + '"><span class="nd-ic">' + ic + '</span><div class="nd-text"><div class="nd-name">' + esc(label) +
      '</div><div class="nd-sub">' + sub + '</div></div><div class="nd-actions">' + cells + "</div></div>";
  }).join("");
  let title, sub;
  if (active) { title = t("js.ha.new.run_title", { done: saved, total: total }); sub = t("js.ha.new.run_sub"); }
  else if (fin) {
    title = saved ? t("js.ha.new.added_title", { n: saved }) : t("js.ha.new.none_added");
    sub = skipped ? t("js.ha.new.not_added", { n: skipped }) : t("js.ha.new.added_sub");
  }
  else { title = S.found.length ? t("js.ha.new.found", { n: list.length }) : t("js.ha.new.title", { n: list.length }); sub = t("js.ha.new.hint"); }
  // The bar of the card: always two cells, "Add all" and "Cancel" (or "Close" when everything has ended), under the title.
  const free = list.filter(function (d) { return d.ip && !(ad && ad.ips[d.ip]); }).length;      // "Add all" from two devices on, found by a search or seen by the app
  const all = sym("plus", t("js.ha.new.add_all"), ' data-add-all="1"', "ok"), cancelBtn = sym("close", t("js.ha.cancel"), ' data-ignore-all="1"');
  let bar;
  if (active && ad.batch) bar = sym("plus", t("js.ha.new.add_all"), " disabled", "ok") + sym("close", t("js.ha.cancel"), ' data-add-cancel-all="1"');
  else if (active) bar = (free > 1 ? all : none) + none;                                    // added by hand: no "Cancel" on top
  else if (fin) bar = (free > 1 ? all : none) + sym("check", t("js.ha.new.close"), ' data-add-close="1"', "ok");
  else bar = (free > 1 ? all : none) + cancelBtn;
  const markup =
    '<div class="card-header"><span class="ch-ic ' + (fin && saved ? "ok" : "warn") + '">' + icon(fin && saved ? "check-circle" : fin ? "alert-circle" : "plus-circle") + '</span><div class="ch-text"><div class="ch-title small">' +
    esc(title) + '</div><div class="ch-sub">' + esc(sub) + "</div></div>" +
    '<div class="nd-bar-actions">' + bar + "</div></div>" +
    '<div class="nd-list">' + rows + "</div>";
  // The same markup again (the events of the network repeat the list): nothing is touched, or a button pressed at that moment
  // would be replaced between the press and the release and the click would be lost.
  if (markup === newEl._markup) return;
  newEl._markup = markup;
  newEl.innerHTML = markup;
  // Opening: the card grows from nothing to its height and what is under it (the log) slides down with it.
  if (opening && !REDUCED && newEl.animate) {
    var full = newEl.getBoundingClientRect().height;
    if (full > 0) newEl.animate([{ height: "0px", opacity: 0 }, { height: full + "px", opacity: 1 }], { duration: 280, easing: "ease-out" });
  }
}
// Why a device was not added (the reasons of POST /api/devices/add; "error" when the add itself did not answer).
const SKIP_KEYS = { exists: "js.ha.new.skip_exists", invalid: "js.ha.new.skip_invalid", off_limits: "js.ha.new.skip_off_limits" };
function skipText(reason) { return t(SKIP_KEYS[reason] || "js.ha.new.skip_error"); }
// The deep search sends a keep-alive line every 20 s (sse.with_keepalive): this long without a byte the stream is lost (a proxy that
// dropped it, an app put to sleep) and the page stops waiting for it, so "Add all" always ends (R8: a spinner turned for ever).
export const STALL_MS = 90000;
// Adding directly from here (in the HA mobile app a link to the classic
// dashboard would be blocked): associative search on the devices by recommended
// name and port, then a single save. Resolves to {results, stalled}.
function scanMany(ips, hosts, onResult, signal) {
  const hints = {}, NL = String.fromCharCode(10);
  ips.forEach(function (ip) { if (hosts[ip]) hints[ip] = hosts[ip]; });
  let results = [], complete = [], stalled = false, timer = null;
  const ctrl = window.AbortController ? new AbortController() : null;
  if (signal && ctrl) signal.addEventListener("abort", function () { ctrl.abort(); });
  function arm() {
    clearTimeout(timer);
    timer = setTimeout(function () { stalled = true; if (ctrl) ctrl.abort(); }, STALL_MS);
  }
  function settle() { clearTimeout(timer); return { results: complete.length ? complete : results, stalled: stalled }; }
  arm();
  function eat(line) {
    if (line.indexOf("data: ") !== 0) return;
    try {
      var ev = JSON.parse(line.slice(6));
      if (ev.type === "progress" && ev.result) { results.push(ev.result); if (onResult) onResult(ev.result); }
      else if (ev.type === "complete" && ev.results) complete = ev.results;
    } catch (err) { /* invalid row: ignored */ }
  }
  return fetch("/api/scan/deep", {
    method: "POST", headers: { "Content-Type": "application/json", "X-Lang": LANG },
    body: JSON.stringify({ ips: ips, hints: hints }), signal: ctrl ? ctrl.signal : signal
  }).then(function (r) {
    arm();
    // Stream reading: each completed device is reported immediately.
    if (!r.body || !r.body.getReader) {
      return r.text().then(function (txt) { txt.split(NL).forEach(eat); });
    }
    let reader = r.body.getReader(), dec = new TextDecoder(), buf = "";
    function pump() {
      return reader.read().then(function (x) {
        if (x.done) { buf.split(NL).forEach(eat); return; }
        arm();
        buf += dec.decode(x.value, { stream: true });
        const lines = buf.split(NL);
        buf = lines.pop();
        lines.forEach(eat);
        return pump();
      });
    }
    return pump();
  }).then(settle, settle);
}
function toDevice(ip, host, r) {
  return { ip: ip, name: (r && r.suggested_name) || host || ip, adapter: (r && r.adapter) || "generic",
    port: (r && r.suggested_port) || 80, scan_info: r && r.scan_info, name_source: r && r.name_source };
}
function afterAdd(ips) {
  // The rows added stay in the card (green) until "Close"; without the card (nothing in progress) they leave the list at once.
  if (!S.adding) S.found = S.found.filter(function (h) { return ips.indexOf(h.ip) < 0; });
  // The devices are already saved: a failed re-read must not reach the addition (it would undo rows that were added and
  // show an error); the list of new devices simply stays as it was until the next update from the server.
  return api("/api/new-devices").then(function (list) {
    if (Array.isArray(list)) S.newDevices = { count: list.length, devices: list, init: true };
  }, function () { /* see above: the next update brings the list */ }).then(function () {
    renderNew();
    S.dirty.net = true;
    schedule();
  });
}
function closeAdding() {
  const ad = S.adding;
  if (!ad) return;
  S.adding = null;
  // "Close" closes the card: the devices added are in the list, the others were not wanted now and a new scan finds them again
  S.found = [];
  S.scanDone = false;
  renderNew();
}
// The answer of POST /api/devices/add: the rows it made are saved, every other row says why it was not added.
function settleAdded(ad, ips, res) {
  const made = {}, why = {};
  (Array.isArray(res.added) ? res.added : []).forEach(function (d) { made[d.ip] = true; });
  (Array.isArray(res.skipped) ? res.skipped : []).forEach(function (s) { why[s.ip] = s.reason; });
  ips.forEach(function (ip) {
    if (made[ip]) { ad.saved[ip] = true; ad.fresh[ip] = Date.now(); }
    else ad.skip[ip] = why[ip] || "error";
  });
}
function addDevices(ips, hosts, mode) {
  // "Adding" state, shared among several parallel additions. Each row goes: analysed (ring turns) -> saved (ring closes into
  // a tick on the right). The other rows stay usable: each new addition starts at once with its own search (the server queues the heavy
  // jobs). Every row has its own "Cancel"; "batch" = started with "Add all": the bar also has a "Cancel" that stops them all.
  const ad = S.adding || (S.adding = { ips: {}, done: {}, saved: {}, skip: {}, sending: {}, meta: {}, fresh: {}, jobs: 0, list: [], batch: false });
  if (mode === "batch") ad.batch = true;
  ips = ips.filter(function (ip) { return !ad.ips[ip]; });
  if (!ips.length) { renderNew(); return; }
  const current = newRows();
  ips.forEach(function (ip) {
    const row = current.filter(function (r) { return r.ip === ip; })[0];
    ad.meta[ip] = row ? { src: row.src, ip: row.ip, mac: row.mac, name: row.name } : { src: "found", ip: ip };
    ad.ips[ip] = true;
  });
  ad.jobs++;
  // dropped: the rows of this job cancelled one by one (the search of the others goes on; these are never added).
  const job = { ips: ips, cancelled: false, dropAll: false, dropped: {}, ctrl: window.AbortController ? new AbortController() : null };
  ad.list.push(job);
  renderNew();
  function finish() {
    ad.jobs--;
    if (ad.jobs <= 0 && S.adding === ad) {
      ad.batch = false;
      if (!Object.keys(ad.saved).length && !Object.keys(ad.skip).length) S.adding = null;   // nothing was tried: the card goes back to how it was
      renderNew();                                             // otherwise it stays (green, or saying why) until "Close"
      // A device that the card itself brought (seen on the network, not chosen from a search) has no list to come back to:
      // when it is saved the card goes away by itself, after the tick has been seen.
      var savedIps = Object.keys(ad.saved);
      if (S.adding === ad && savedIps.length && !Object.keys(ad.skip).length && !S.found.length && savedIps.every(function (ip) { return ad.meta[ip] && ad.meta[ip].src === "new"; })) {
        setTimeout(function () { if (S.adding === ad && !ad.jobs) closeAdding(); }, 2200);
      }
    }
  }
  let use = ips;
  scanMany(ips, hosts, function (r) { if (ad.ips[r.ip] && !job.dropped[r.ip]) ad.done[r.ip] = true; renderNew(); }, job.ctrl && job.ctrl.signal).then(function (got) {
    const byIp = {};
    got.results.forEach(function (r) { byIp[r.ip] = r; });
    // The stream was lost: the searches still running are stopped on the server too; their devices are added with what is known.
    const lost = got.stalled ? ips.filter(function (ip) { return !byIp[ip]; }) : [];
    if (lost.length) api("/api/scan/cancel", { method: "POST", json: { ips: lost } }).catch(function () {});
    // Cancelled: only the devices whose analysis had already finished are kept (none, if that row was cancelled by hand).
    use = job.dropAll ? [] : (job.cancelled ? ips.filter(function (ip) { return byIp[ip]; }) : ips);
    use = use.filter(function (ip) { return ad.ips[ip] && !job.dropped[ip]; });
    use.forEach(function (ip) { ad.done[ip] = true; ad.sending[ip] = true; });
    renderNew();
    if (!use.length) return null;
    const devices = use.map(function (ip) { return toDevice(ip, hosts[ip], byIp[ip]); });
    return api("/api/devices/add", { method: "POST", json: { devices: devices } });
  }).then(function (res) {
    if (res) settleAdded(ad, use, res);
    finish();
    return res ? afterAdd(use) : null;
  }, function () {
    // The add did not answer (or failed): every row of this job says so, and the card ends with "Close" instead of turning on.
    use.forEach(function (ip) { if (ad.ips[ip] && !ad.saved[ip]) ad.skip[ip] = "error"; });
    finish();
    renderNew();
  });
}
newEl.addEventListener("click", function (e) {
  const add = e.target.closest("[data-add-ip]");
  if (add) {
    var hosts = {};
    hosts[add.dataset.addIp] = add.dataset.addHost;
    addDevices([add.dataset.addIp], hosts, "single");
    return;
  }
  const all = e.target.closest("[data-add-all]");
  if (all) {
    var map = {};
    const todo = newRows().filter(function (r) { return r.ip; });
    todo.forEach(function (r) { map[r.ip] = r.name || ""; });
    addDevices(todo.map(function (r) { return r.ip; }), map, "batch");  // those already in progress are skipped (and join the batch)
    return;
  }
  const rowCancel = e.target.closest("[data-add-cancel]");
  if (rowCancel && S.adding) {
    // "Cancel" on a row (alone or in a batch): that device goes back to how it was and is not added; the others go on.
    var ad1 = S.adding, ip1 = rowCancel.dataset.addCancel;
    if (ad1.sending[ip1] || ad1.saved[ip1]) return;                         // already being saved: too late (the button is off)
    var job1 = (ad1.list || []).filter(function (j) { return !j.cancelled && !j.dropped[ip1] && j.ips.indexOf(ip1) >= 0; })[0];
    var wasDone = !!ad1.done[ip1];
    delete ad1.ips[ip1]; delete ad1.done[ip1]; delete ad1.meta[ip1];
    if (job1) {
      job1.dropped[ip1] = true;
      if (job1.ips.every(function (ip) { return job1.dropped[ip]; })) { job1.dropAll = true; job1.cancelled = true; if (job1.ctrl) job1.ctrl.abort(); }
      if (!wasDone) api("/api/scan/cancel", { method: "POST", json: { ips: [ip1] } }).catch(function () {});
    }
    renderNew();
    return;
  }
  if (S.adding && e.target.closest("[data-add-cancel-all]")) {
    // "Cancel" in the bar, during "Add all": the analyses in progress are stopped (on the server too); the devices already
    // analysed are still added, the others go back to the list.
    var ad2 = S.adding, pending = [];
    (ad2.list || []).forEach(function (job) {
      if (job.cancelled) return;
      job.cancelled = true;
      job.ips.forEach(function (ip) { if (ad2.ips[ip] && !ad2.done[ip]) pending.push(ip); });
      if (job.ctrl) job.ctrl.abort();
    });
    pending.forEach(function (ip) { delete ad2.ips[ip]; delete ad2.meta[ip]; });
    ad2.batch = false;
    if (pending.length) api("/api/scan/cancel", { method: "POST", json: { ips: pending } }).catch(function () {});
    renderNew();
    return;
  }
  if (e.target.closest("[data-add-close]")) { closeAdding(); return; }
  const ign = e.target.closest("[data-ign-ip]");
  if (ign) {
    ign.disabled = true;
    api("/api/ignored/hosts", { method: "POST", json: { hosts: [{ ip: ign.dataset.ignIp, mac: ign.dataset.ignMac || null, hostname: ign.dataset.ignHost || null }] } })
      .then(function () {
        S.found = S.found.filter(function (h) { return h.ip !== ign.dataset.ignIp; });
        // The app may have seen the same device by itself: it must not come back as a "seen" row (the second press of the eye).
        S.dismissedNew[String(ign.dataset.ignMac || ign.dataset.ignIp).toUpperCase()] = true;
        redrawNew();
        S.dirty.net = true;                                                   // the +N on the ring follows the card
        schedule();
      }).catch(function () {
        ign.disabled = false;
        redrawNew();
        snack(t("js.ha.toast.error"), { kind: "error" });
      });
    return;
  }
  const ia = e.target.closest("[data-ignore-all]");
  if (ia) {
    // Cancel: closes the list of this scan; the devices are not ignored
    // and a new scan finds them again.
    // Cancel closes what the card shows. With the list of a search on screen it closes only that list: the devices the app saw by
    // itself stay and are the second card (a second Cancel closes it). Without a list it closes the card until something new
    // appears: the devices seen on the network are remembered as dismissed.
    if (!S.found.length) newRows().forEach(function (r) { if (r.src === "new") S.dismissedNew[String(r.mac || r.ip).toUpperCase()] = true; });
    S.found = [];
    S.scanDone = false;
    renderNew();
    S.dirty.net = true;                                                       // the +N on the ring follows the card
    schedule();
    return;
  }
  const b = e.target.closest("[data-ignore-mac]");
  if (!b) return;
  var mac = b.dataset.ignoreMac;
  b.disabled = true;
  api("/api/new-devices/ignore", { method: "POST", json: mac === "*" ? {} : { macs: [mac] } }).then(function (list) {
    if (Array.isArray(list)) S.newDevices = { count: list.length, devices: list, init: true };
    S.dismissedNew[String(mac).toUpperCase()] = true;
    redrawNew();
    S.dirty.net = true;
    schedule();
  }).catch(function () {
    b.disabled = false;
    redrawNew();
    snack(t("js.ha.toast.error"), { kind: "error" });
  });
});
