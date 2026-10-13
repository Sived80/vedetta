import { $, api, esc, icon, t } from "./core.js";
import { S, raiseSnacks, snack, snacksEl } from "./core-ui.js";
import { guidedInput, guidedKey, menuBtn } from "./core-menu.js";
import { flash } from "./tile.js";

// ------------------------------------------------- ignored devices
// Two origins: "Ignore" on a device found by a search (an entry of the list: MAC, IP or name) and "Ignore" on a device found on the network (its MAC).
// Each row has a menu (three dots) with Restore and Forget. Both work with a countdown: the pressed item becomes "Undo" with a colour sliding
// across it for 5 s; only Undo stops it; leaving the menu, the sheet or the window lets it run to the end, and it ends with a notice (no Undo).
// Rows are independent (a countdown each); the two group buttons below are locked while any countdown runs, and lock the rows while theirs does.
var ignDlg = $("ignored");
var IGN_UNDO_MS = 5000;
export var ign = { rows: [], kind: "mac", pend: {}, bulk: null, menu: null, menuBtn: null, ui: null };

function ignRowsFrom(g) {
  const rows = [];
  g.items.forEach(function (it) {
    rows.push({ id: "i" + it.id, api: { id: it.id }, source: "search", kind: it.kind, title: it.label || it.value,
      ip: it.kind === "ip" ? it.value : "", mac: it.kind === "mac" ? it.value : "", name: it.kind === "name" ? it.value : "", vendor: "" });
  });
  g.macs.forEach(function (m) {
    rows.push({ id: "m" + m.mac, api: { mac: m.mac }, source: "network", kind: "mac", title: m.hostname || m.vendor || m.ip || m.mac,
      ip: m.ip || "", mac: m.mac, name: m.hostname || "", vendor: m.vendor || "" });
  });
  return rows;
}
function ignIds(r) {
  let a = [r.ip, r.mac].filter(function (x) { return x && x !== r.title; });
  if (!a.length && r.vendor && r.vendor !== r.title) a = [r.vendor];
  if (!a.length) a = [t("js.ha.ign.kind_" + r.kind)];
  return a.join(" · ");
}
function ignRowHtml(r) {
  const net = r.source === "network", where = t(net ? "js.ha.ign.from_network" : "js.ha.ign.from_search"), ids = ignIds(r);
  const full = r.title + "\n" + [r.ip, r.mac, r.vendor].filter(Boolean).join(" · ") + " · " + where;
  return '<div class="ig-item" data-id="' + esc(r.id) + '"><div class="nd-row" title="' + esc(full) + '"><span class="nd-ic">' + icon("eye-off") + "</span>" +
    '<div class="nd-text"><div class="nd-name" title="' + esc(r.title) + '">' + esc(r.title) + '</div><div class="nd-sub"><span class="ids" title="' + esc(ids) + '">' + esc(ids) +
    '</span><span class="org" title="' + esc(where) + '">' + icon(net ? "lan" : "magnify") + '<span class="vh">' + esc(where) + "</span></span></div></div>" +
    '<div class="nd-actions"><button type="button" class="icon-btn rp" data-ign="more" aria-haspopup="menu" aria-expanded="false" aria-label="' + esc(t("js.ha.ign.more")) +
    '" title="' + esc(t("js.ha.ign.more")) + '">' + icon("dots-vertical") + "</button></div></div></div>";
}
function ignBuild() {
  ign.rows = ignRowsFrom(S.ign);
  ign.pend = {}; ign.bulk = null; ign.menu = null; ign.menuBtn = null;
  const kinds = ["mac", "ip", "name"].map(function (k) {
    return '<button type="button" class="pill" data-ign-kind="' + k + '" aria-pressed="' + (k === ign.kind) + '">' + esc(t(k === "name" ? "js.ha.ign.pill_name" : "js.ha.ign.kind_" + k)) + "</button>";
  }).join("");
  ignDlg.innerHTML = '<div class="mi"><div class="mi-header"><button type="button" class="icon-btn touch rp" data-ign="close" aria-label="' + esc(t("js.ha.more.close")) + '">' + icon("close") + "</button>" +
    '<div class="mi-titles"><h2 class="mi-title" id="ignored-title">' + esc(t("js.ha.menu.ignored")) + '</h2><div class="mi-sub">' + esc(t("js.ha.ign.sub")) + "</div></div>" +
    '<button type="button" class="icon-btn ig-add-btn rp" data-ign="toggle-add" aria-expanded="false" aria-controls="ig-add" title="' + esc(t("js.ha.ign.add")) + '" aria-label="' + esc(t("js.ha.ign.add")) + '">' + icon("plus") + "</button></div>" +
    '<div class="ig-body"><div class="ig-scroll" tabindex="-1"><div class="ig-inner">' +
    '<div class="ig-addwrap" id="ig-add"><div><form class="ig-add" novalidate><div class="ig-kinds" role="group" aria-label="' + esc(t("js.ha.ign.kind_label")) + '">' + kinds + "</div>" +
    '<div class="ig-line"><input class="ig-field" autocomplete="off" autocapitalize="off" spellcheck="false" aria-describedby="ig-err"><button type="submit" class="btn filled rp">' + esc(t("js.ha.ign.go")) + "</button></div>" +
    '<div class="ig-err hint" id="ig-err" aria-live="polite"></div></form></div></div>' +
    '<div class="ig-list">' + ign.rows.map(ignRowHtml).join("") + "</div>" +
    '<div class="ig-empty"><div class="empty-ic">' + icon("eye-off") + "</div><h3>" + esc(t("js.ha.ign.empty")) + "</h3></div></div></div></div>" +
    '<div class="mi-actions"><button type="button" class="btn text ig-all rp" data-ign="all" data-bulk="restore">' + esc(t("js.ha.ign.restore_all")) +
    '</button><button type="button" class="btn text ig-all danger rp" data-ign="all" data-bulk="forget">' + esc(t("js.ha.ign.forget_all")) + "</button></div>" +
    '<div class="vh" role="status" aria-live="polite" id="ig-live"></div></div>';
  ign.ui = { scroll: ignDlg.querySelector(".ig-scroll"), list: ignDlg.querySelector(".ig-list"), empty: ignDlg.querySelector(".ig-empty"), addWrap: ignDlg.querySelector(".ig-addwrap"),
    field: ignDlg.querySelector(".ig-field"), err: ignDlg.querySelector(".ig-err"), addBtn: ignDlg.querySelector(".ig-add-btn"), all: ignDlg.querySelectorAll(".ig-all"), live: ignDlg.querySelector("#ig-live") };
  ignSetKind(ign.kind);
  ignRefresh();
}
function ignBar() { if (ign.ui) ignDlg.style.setProperty("--ig-sb", (ign.ui.scroll.offsetWidth - ign.ui.scroll.clientWidth) + "px"); }   // the + sits above the dots: the right edge follows the scroll bar
function ignRefresh() {
  const n = ign.rows.length;
  [].forEach.call(ign.ui.all, function (b) { b.hidden = !(n >= 2 || (ign.bulk && n >= 1)); });
  ign.ui.empty.classList.toggle("on", n === 0 && !ign.ui.list.querySelector(".ig-item"));
  ignBar();
}
function ignSay(s) { const l = ign.ui && ign.ui.live; if (!l) return; l.textContent = ""; setTimeout(function () { l.textContent = s; }, 30); }
function ignRow(id) { return ign.rows.find(function (r) { return r.id === id; }) || null; }
function ignEl(id) { return ign.ui.list.querySelector('.ig-item[data-id="' + id + '"]'); }

// --- rows fold away and open
function ignCollapse(el, done) {
  let fin = false;
  function end() { if (fin) return; fin = true; if (el.parentNode) el.parentNode.removeChild(el); if (done) done(); }
  el.style.height = el.offsetHeight + "px";
  void el.offsetHeight;
  el.classList.add("out");
  el.addEventListener("transitionend", function (e) { if (e.propertyName === "height") end(); });
  setTimeout(end, 320);
}
function ignExpand(el) {
  el.style.height = "0px"; el.classList.add("out"); void el.offsetHeight;
  el.classList.remove("out"); el.style.height = "60px";
  let f = false;
  function end() { if (f) return; f = true; el.style.height = ""; }
  el.addEventListener("transitionend", end); setTimeout(end, 320);
}
function ignInsert(r, flash) {
  const tmp = document.createElement("div"); tmp.innerHTML = ignRowHtml(r);
  const el = tmp.firstChild; ign.ui.list.insertBefore(el, ign.ui.list.firstChild);
  if (flash) el.firstChild.classList.add("fresh");
  ignExpand(el);
}
function ignDrop(id) {                 // the row leaves the list (the server is asked by the caller)
  const i = ign.rows.map(function (r) { return r.id; }).indexOf(id); if (i < 0) return null;
  var r = ign.rows.splice(i, 1)[0], el = ignEl(id);
  if (el) ignCollapse(el, ignRefresh);
  ignRefresh();
  return r;
}

// --- what the server is asked
function ignCall(r, kind) {
  if (kind === "restore") {
    return r.api.id ? api("/api/ignored/" + encodeURIComponent(r.api.id), { method: "DELETE" }).then(function (x) { S.ign.items = (x && x.items) || []; })
      : api("/api/new-devices/unignore", { method: "POST", json: { mac: r.api.mac } }).then(function (x) { S.ign.macs = Array.isArray(x) ? x : []; });
  }
  return api("/api/ignored/forget", { method: "POST", json: r.api }).then(function (x) { S.ign.items = (x && x.items) || []; S.ign.macs = (x && x.macs) || []; });
}
function ignFailed() {
  snack(t("js.ha.toast.error"), { kind: "error" });
  Promise.all([api("/api/ignored"), api("/api/new-devices/ignored")]).then(function (res) {
    S.ign = { items: (res[0] && res[0].items) || [], macs: Array.isArray(res[1]) ? res[1] : [] };
    if (ignDlg.open) ignBuild();
  }).catch(function () { /* the next opening reads it again */ });
}

// --- ROWS: a countdown each
function ignInner(kind) { return "<span>" + esc(t(kind === "restore" ? "js.ha.ign.restore" : "js.ha.ign.forget")) + "</span>" + icon(kind === "restore" ? "eye" : "delete-outline"); }
function ignCounting(elapsed) { return '<span class="fill" style="animation-delay:-' + Math.round(elapsed) + 'ms"></span><span>' + esc(t("js.ha.cancel")) + "</span>" + icon("undo"); }
function ignPaint(item, elapsed) { item.classList.add("counting"); item.innerHTML = ignCounting(elapsed); }
function ignMenuRow() { return ign.menuBtn ? ign.menuBtn.closest(".ig-item").getAttribute("data-id") : null; }
function ignRowsBusy() { return Object.keys(ign.pend).length > 0; }
// what is on and what is off: the group buttons (off while any row or the other group runs), the open menu (off during a group; otherwise,
// if this row has a countdown, only its Undo is on)
function ignLock() {
  const rb = ignRowsBusy();
  if (ign.ui) [].forEach.call(ign.ui.all, function (x) { if ((rb || ign.bulk) && !x.classList.contains("counting")) x.setAttribute("aria-disabled", "true"); else x.removeAttribute("aria-disabled"); });
  if (ign.menu) {
    var mine = ign.pend[ignMenuRow()];
    [].forEach.call(ign.menu.querySelectorAll(".menu-item"), function (x) {
      if (!x.classList.contains("counting") && (ign.bulk || mine)) x.setAttribute("aria-disabled", "true"); else x.removeAttribute("aria-disabled");
    });
  }
}
function ignFinishRow(id, silent) {
  const f = ign.pend[id]; if (!f) return;
  delete ign.pend[id]; clearTimeout(f.timer);
  const el = ignEl(id), next = el && (el.nextElementSibling || el.previousElementSibling);
  if (ignMenuRow() === id) ignCloseMenu(false);
  const r = ignDrop(id); ignLock(); if (!r) return;
  ignCall(r, f.kind).catch(ignFailed);
  const said = t(f.kind === "restore" ? "js.ha.ign.restored" : "js.ha.ign.forgot") + ": " + r.title;
  if (!silent) {
    snack(said); ignSay(said);
    var fb = next && next.querySelector('[data-ign="more"]');
    if (!ign.menu) (fb || ign.ui.addBtn).focus();
  }
}
function ignFinishAllRows(silent) { Object.keys(ign.pend).forEach(function (id) { ignFinishRow(id, silent); }); }
function ignCancelRow(id) {
  const f = ign.pend[id]; if (!f) return;
  delete ign.pend[id]; clearTimeout(f.timer);
  const it = ign.menu && ignMenuRow() === id && ign.menu.querySelector(".menu-item.counting");
  if (it) { it.classList.remove("counting"); it.innerHTML = ignInner(f.kind); it.focus(); }
  ignLock();
}
function ignStartRow(item) {
  const id = item.getAttribute("data-id"), kind = item.getAttribute("data-do");
  if (ign.bulk || ign.pend[id]) return;
  ignPaint(item, 0); item.focus();
  ignSay(t(kind === "restore" ? "js.ha.ign.restored" : "js.ha.ign.forgot") + ". " + t("js.ha.cancel") + "?");
  ign.pend[id] = { kind: kind, start: Date.now(), timer: setTimeout(function () { ignFinishRow(id, false); }, IGN_UNDO_MS) };
  ignLock();
}

// --- GROUP: "Restore all" / "Forget all"
function ignBulkLabel(kind) { return t(kind === "restore" ? "js.ha.ign.restore_all" : "js.ha.ign.forget_all"); }
function ignBulkReset() {
  [].forEach.call(ign.ui.all, function (b) { b.classList.remove("counting"); b.innerHTML = esc(ignBulkLabel(b.getAttribute("data-bulk"))); });
}
function ignFinishBulk(silent) {
  const f = ign.bulk; if (!f) return;
  ign.bulk = null; clearTimeout(f.timer);
  const rows = ign.rows.slice(), n = rows.length;
  rows.forEach(function (r) { ignDrop(r.id); });
  ignBulkReset(); ignLock();
  rows.reduce(function (p, r) { return p.then(function () { return ignCall(r, f.kind); }); }, Promise.resolve()).catch(ignFailed);
  if (!silent && n) { var said = t(f.kind === "restore" ? "js.ha.ign.restored_n" : "js.ha.ign.forgot_n", { n: n }); snack(said); ignSay(said); ign.ui.addBtn.focus(); }
}
function ignCancelBulk() {
  const f = ign.bulk; if (!f) return;
  ign.bulk = null; clearTimeout(f.timer);
  ignBulkReset(); ignLock();
}
function ignStartBulk(btn) {
  if (ign.bulk || ignRowsBusy()) return;
  const kind = btn.getAttribute("data-bulk");
  btn.classList.add("counting"); btn.innerHTML = '<span class="fill"></span><span>' + esc(t("js.ha.cancel")) + "</span>" + icon("undo");
  ignSay(ignBulkLabel(kind) + ". " + t("js.ha.cancel") + "?");
  ign.bulk = { kind: kind, timer: setTimeout(function () { ignFinishBulk(false); }, IGN_UNDO_MS) };
  ignLock();
}

// --- the menu of a row
function ignCloseMenu(refocus) {
  if (!ign.menu) return;
  const b = ign.menuBtn;
  ign.menu.parentNode.removeChild(ign.menu); ign.menu = null; ign.menuBtn = null;
  if (b) { b.setAttribute("aria-expanded", "false"); if (refocus) b.focus(); }
}
function ignOpenMenu(btn) {
  ignCloseMenu(false);
  const id = btn.closest(".ig-item").getAttribute("data-id"), m = document.createElement("div");
  m.className = "menu ig-menu"; m.setAttribute("role", "menu"); m.setAttribute("aria-label", t("js.ha.ign.more"));
  m.innerHTML = '<button type="button" class="menu-item" role="menuitem" tabindex="-1" data-id="' + esc(id) + '" data-do="restore">' + ignInner("restore") + "</button>" +
    '<button type="button" class="menu-item danger" role="menuitem" tabindex="-1" data-id="' + esc(id) + '" data-do="forget">' + ignInner("forget") + "</button>";
  ignDlg.appendChild(m); ign.menu = m; ign.menuBtn = btn; btn.setAttribute("aria-expanded", "true");
  const f = ign.pend[id];
  if (f) ignPaint(m.querySelector('[data-do="' + f.kind + '"]'), Date.now() - f.start);
  ignLock();
  const r = btn.getBoundingClientRect(), mw = m.offsetWidth, mh = m.offsetHeight, vw = window.innerWidth, vh = window.innerHeight;
  let left = Math.max(8, Math.min(r.right - mw, vw - mw - 8)), top = r.bottom + 4;
  if (top + mh > vh - 8) top = Math.max(8, r.top - mh - 4);
  m.style.left = left + "px"; m.style.top = top + "px"; m.style.right = "auto"; m.style.transformOrigin = "top right";
  const first = m.querySelector(".counting") || m.querySelector(".menu-item"); first.focus();
}

// --- add by hand
function ignHint() { return ign.kind === "mac" ? t("js.ha.ign.hint_mac") : ign.kind === "ip" ? t("js.ha.ign.hint_ip") : ""; }
function ignErr(msg) {
  const u = ign.ui; u.err.textContent = msg || ignHint(); u.err.classList.toggle("hint", !msg);
  if (msg) u.field.setAttribute("aria-invalid", "true"); else u.field.removeAttribute("aria-invalid");
}
function ignSetKind(k) {
  const u = ign.ui; ign.kind = k;
  [].forEach.call(ignDlg.querySelectorAll(".ig-kinds .pill"), function (p) { p.setAttribute("aria-pressed", p.getAttribute("data-ign-kind") === k); });
  u.field.placeholder = t("js.ha.ign.ph_" + k); u.field.setAttribute("aria-label", t(k === "name" ? "js.ha.ign.pill_name" : "js.ha.ign.kind_" + k));
  u.field.inputMode = k === "ip" ? "decimal" : "text"; u.field.value = ""; ignErr("");
}
function ignToggleAdd(open) {
  const u = ign.ui; open = open === undefined ? !u.addWrap.classList.contains("open") : open;
  u.addWrap.classList.toggle("open", open); u.addBtn.setAttribute("aria-expanded", String(open));
  if (open) { u.scroll.scrollTop = 0; setTimeout(function () { u.field.focus({ preventScroll: true }); }, 60); } else { ignErr(""); u.field.value = ""; }
}
function ignSubmit() {
  let u = ign.ui, v = u.field.value.trim(), kind = ign.kind, value;
  if (kind === "mac") {
    var h = v.replace(/[:\-.]/g, "");
    if (!/^[0-9a-fA-F]{12}$/.test(h)) return ignErr(t("js.ha.ign.err_mac"));
    value = h.toUpperCase().match(/../g).join(":");
  } else if (kind === "ip") {
    var p = v.split(".");
    if (p.length !== 4 || !p.every(function (x) { return /^\d{1,3}$/.test(x) && +x <= 255; })) return ignErr(t("js.ha.ign.err_ip"));
    value = p.map(Number).join(".");
  } else {
    if (!v) return ignErr(t("js.ha.ign.err_name"));
    value = v;
  }
  const dup = ign.rows.some(function (r) { return r.source === "search" && r.kind === kind && ((r.mac || r.ip || r.name) + "").toLowerCase() === value.toLowerCase(); });
  if (dup) return ignErr(t("js.ha.ign.err_dup"));
  const before = {}; S.ign.items.forEach(function (x) { before[x.id] = 1; });
  api("/api/ignored", { method: "POST", json: { kind: kind, value: value, label: value } }).then(function (res) {
    S.ign.items = (res && res.items) || [];
    const added = S.ign.items.filter(function (x) { return !before[x.id]; })[0];
    ignToggleAdd(false);
    if (!added) return;
    const row = ignRowsFrom({ items: [added], macs: [] })[0];
    ign.rows.unshift(row); ignInsert(row, true); ignRefresh(); u.scroll.scrollTop = 0; u.addBtn.focus();
    ignSay(t("js.ha.ign.add") + ": " + row.title);
  }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); });
}

// --- opening and closing
export function openIgnored() {
  Promise.all([api("/api/ignored"), api("/api/new-devices/ignored")]).then(function (res) {
    S.ign = { items: (res[0] && res[0].items) || [], macs: Array.isArray(res[1]) ? res[1] : [] };
    ignBuild();
    if (!ignDlg.open) {
      if (typeof ignDlg.showModal === "function") ignDlg.showModal(); else ignDlg.setAttribute("open", "");
      if (snacksEl.children.length) raiseSnacks();
    }
    ignBar();
  }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); });
}
function closeIgnored() {
  ignFinishAllRows(true); ignFinishBulk(true); ignCloseMenu(false);        // what is counting ends in silence
  if (ignDlg.open && typeof ignDlg.close === "function") ignDlg.close(); else ignDlg.removeAttribute("open");
}
ignDlg.addEventListener("click", function (e) {
  if (e.target === ignDlg) return closeIgnored();
  const kb = e.target.closest("[data-ign-kind]");
  if (kb) { ignSetKind(kb.getAttribute("data-ign-kind")); ign.ui.field.focus(); return; }
  const mi = e.target.closest(".ig-menu .menu-item");
  if (mi) {
    if (mi.getAttribute("aria-disabled") === "true") return;
    if (mi.classList.contains("counting")) { ignCancelRow(mi.getAttribute("data-id")); return; }
    ignStartRow(mi);
    return;
  }
  const b = e.target.closest("[data-ign]"); if (!b) return;
  const a = b.getAttribute("data-ign");
  if (a === "close") closeIgnored();
  else if (a === "toggle-add") ignToggleAdd();
  else if (a === "more") { if (ign.menuBtn === b) ignCloseMenu(true); else ignOpenMenu(b); }
  else if (a === "all") {
    if (b.classList.contains("counting")) ignCancelBulk();
    else if (b.getAttribute("aria-disabled") !== "true") ignStartBulk(b);
  }
});
ignDlg.addEventListener("submit", function (e) { e.preventDefault(); ignSubmit(); });
ignDlg.addEventListener("input", function (e) { if (ign.ui && e.target === ign.ui.field) { guidedInput(ign.ui.field, ign.kind); ignErr(""); } });
ignDlg.addEventListener("keydown", function (e) {
  if (ign.ui && e.target === ign.ui.field && guidedKey(e, ign.ui.field, ign.kind)) { ignErr(""); return; }
  const b = e.target.closest && e.target.closest('[data-ign="more"]');
  if (b && (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ")) { e.preventDefault(); e.stopPropagation(); ignOpenMenu(b); return; }
  if (ign.menu && ign.menu.contains(e.target)) {
    var items = [].slice.call(ign.menu.querySelectorAll(".menu-item")), k = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); items[(k + 1) % items.length].focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[(k - 1 + items.length) % items.length].focus(); }
    else if (e.key === "Home") { e.preventDefault(); items[0].focus(); }
    else if (e.key === "End") { e.preventDefault(); items[items.length - 1].focus(); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); ignCloseMenu(true); }
    else if (e.key === "Tab") { ignCloseMenu(true); e.preventDefault(); }
    return;
  }
  if (e.key === "Escape" && ign.ui && ign.ui.addWrap.classList.contains("open")) { e.preventDefault(); e.stopPropagation(); ignToggleAdd(false); ign.ui.addBtn.focus(); }
});
ignDlg.addEventListener("cancel", function (e) {
  if (ign.menu) { e.preventDefault(); ignCloseMenu(true); }
  else if (ign.ui && ign.ui.addWrap.classList.contains("open")) { e.preventDefault(); ignToggleAdd(false); ign.ui.addBtn.focus(); }
  else { ignFinishAllRows(true); ignFinishBulk(true); }
});
document.addEventListener("pointerdown", function (e) { if (ign.menu && !ign.menu.contains(e.target) && !e.target.closest('[data-ign="more"]')) ignCloseMenu(false); }, true);
ignDlg.addEventListener("scroll", function () { if (ign.menu) ignCloseMenu(false); }, true);
window.addEventListener("resize", function () { if (ign.menu) ignCloseMenu(false); ignBar(); });

