import { $, BASE, COMPACT, COMPACT_LIMIT, I, REDUCED, TYPE_ORDER, analysisText, canOpen, canWake, devIcon, esc, icon, ipKey, logoTint, logoVar, nowSec, reloadHost, stateText, t, typeIcon, typeLabel, typePlural } from "./core.js";
import { S, searchClear, searchEl } from "./core-ui.js";
import { span } from "./core-menu.js";
import { DEBUG } from "./debug.js";
import { batteryTitle, chipText, doScan, matches } from "./filters.js";
import { openMore } from "./more-info.js";
import { openExternal, wakeDevice } from "./more-edit.js";
import { load, schedule } from "./live.js";

// ----------------------------------------------------------------- tile
export var groupsEl = $("groups");

export function prepare(d) {
  d.type = I.typeIcon[d.type] ? d.type : "generic";
  d._hay = [d.name, d.ip, d.mac, d.brand, d.vendor, d.title, typeLabel(d.type), typePlural(d.type)]
    .filter(Boolean).join(" ").toLowerCase();
  return d;
}
export function rebuildList() {
  S.list = Array.from(S.devices.values()).sort(function (a, b) { return ipKey(a.ip) - ipKey(b.ip) || a.name.localeCompare(b.name); });
}

function createTile(d, index) {
  const el = document.createElement("div");
  el.className = "tile rp";
  el.setAttribute("role", "button");
  el.tabIndex = 0;
  el.dataset.id = d.id;
  el.style.animationDelay = Math.min(index || 0, 14) * 22 + "ms";
  el.innerHTML =
    '<span class="brand-big" aria-hidden="true" hidden><i></i></span>' +
    '<span class="tile-icon"><span class="ic"></span><span class="ring"></span><span class="tile-flag" hidden>' + icon("flag") + "</span>" +
    '<span class="tile-mark tr" role="img" hidden></span><span class="tile-mark br" role="img" hidden></span></span>' +
    '<span class="tile-body"><span class="tile-name"></span><span class="tile-ip"></span><span class="tile-state"></span><span class="tile-sub"><span class="tile-sub-txt"></span><span class="tile-batt" role="img" style="display:inline-flex;vertical-align:-2px;margin-left:.35em;opacity:.65"></span></span></span>' +
    '<button type="button" class="icon-btn small tile-open touch rp" title="' + esc(t("js.ha.act.open")) + '" aria-label="' + esc(t("js.ha.act.open")) + '">' + icon("open-in-new") + "</button>" +
    '<button type="button" class="icon-btn small tile-wake touch rp" hidden>' + icon("power") + "</button>" +
    '<span class="hbar" role="img"></span>';
  el._r = {
    big: el.querySelector(".brand-big"), box: el.querySelector(".tile-icon"), ic: el.querySelector(".ic"), name: el.querySelector(".tile-name"), ip: el.querySelector(".tile-ip"), subRow: el.querySelector(".tile-sub"), state: el.querySelector(".tile-state"),
    sub: el.querySelector(".tile-sub-txt"), batt: el.querySelector(".tile-batt"), flag: el.querySelector(".tile-flag"), markTR: el.querySelector(".tile-mark.tr"), markBR: el.querySelector(".tile-mark.br"), wake: el.querySelector(".tile-wake"), open: el.querySelector(".tile-open"), hbar: el.querySelector(".hbar")
  };
  el._r.wake.title = t("js.ha.act.wake");
  el._r.wake.setAttribute("aria-label", t("js.ha.act.wake"));
  S.tiles.set(d.id, el);
  return el;
}

// Network roles (gateway, DHCP, DNS, router, AP, repeater) and the repeater it goes through.
function roleText(ip) {
  const rr = (S.roles.by_ip || {})[ip];
  return rr ? Object.keys(rr).map(function (k) { return t("js.ha.role." + k); }).join(" \u00b7 ") : "";
}
export function viaText(ip, short) {
  const v = (S.roles.via || {})[ip];
  if (!v) return "";
  if (!v.ip) return short ? t("js.ha.via.short", { name: t("js.ha.role.repeater").toLowerCase() }) : t("js.ha.via.unknown", { mac: v.mac });
  var name = v.name || v.ip;
  return short ? t("js.ha.via.short", { name: name }) : name + " (" + v.ip + ")";
}
// Signs on the corners of the icon, from the server's choice (analysis/badges.py): a lens when the card is under analysis, a clock while it settles. Never colour alone: a shape and a text too.
// The words of the state (analisi in corso...) are NOT on the tile: they live in the head of the open card, beside online/offline (more-info.js); here only the sign on the icon and, for the screen reader, the aria-label.
var MARKS = { analysing: ["magnify", "js.ha.an.analysing.tip"], settling: ["clock-outline", "js.ha.an.settling.tip"], unresolved: ["help-circle-outline", "js.ha.an.unresolved.tip"] };
function paintMarks(r, info) {
  const by = {};
  ((info && info.badges) || []).forEach(function (b) { if (MARKS[b.id]) by[b.corner] = b.id; });
  [["top_right", r.markTR], ["bottom_right", r.markBR]].forEach(function (c) {
    const id = by[c[0]], el = c[1];
    if (el._id === (id || "")) return;
    el._id = id || "";
    el.hidden = !id;
    el.className = "tile-mark " + (c[0] === "top_right" ? "tr" : "br") + (id ? " " + id : "");
    el.innerHTML = id ? icon(MARKS[id][0]) : "";
    const tip = id ? t(MARKS[id][1]) : "";
    el.title = tip;
    if (tip) el.setAttribute("aria-label", tip); else el.removeAttribute("aria-label");
  });
}
export function updateTile(id) {
  const d = S.devices.get(id), el = S.tiles.get(id);
  if (!d || !el) return;
  const r = el._r;
  el.classList.toggle("online", d.online);
  el.classList.toggle("offline", !d.online);
  el.dataset.type = d.type;
  el.classList.toggle("scanning", S.activity.rescanning.has(id));
  if (el._type !== d.type + "|" + d.icon) { el._type = d.type + "|" + d.icon; r.ic.innerHTML = icon(devIcon(d)); }
  if (el._logo !== (d.logo || "")) {
    el._logo = d.logo || "";
    r.big.hidden = !el._logo;
    r.box.classList.toggle("has-logo", !!el._logo);    // used by the list view: the logo replaces the icon in the circle
    if (el._logo) {
      r.big.style.setProperty("--logo", logoVar(d));
      r.box.style.setProperty("--logo", logoVar(d));
      r.box.style.setProperty("--bc", logoTint(d));
    } else {
      r.big.style.removeProperty("--logo");
      r.box.style.removeProperty("--logo");
      r.box.style.removeProperty("--bc");
    }
  }
  if (r.name.textContent !== d.name) r.name.textContent = d.name;
  // a device flagged for the report is recognisable from outside: a small flag on its icon
  r.flag.hidden = !d.focus;
  r.flag.title = d.focus ? t("js.ha.focus.edit") : "";
  el.classList.toggle("flagged", !!d.focus);
  paintMarks(r, S.analysis[id]);
  const st = stateText(d), anText = analysisText(S.analysis[id]);
  if (r.state.textContent !== st) r.state.textContent = st;
  const chip = [roleText(d.ip), viaText(d.ip, true), chipText(d)].filter(Boolean).join(" \u00b7 ");
  // Order: name, IP (in full), status and latency, other information (role, brand/chip, battery).
  if (r.ip.textContent !== d.ip) r.ip.textContent = d.ip;
  if (r.sub.textContent !== chip) r.sub.textContent = chip;
  // Battery: discreet icon only if the device is certainly battery-powered.
  const bt = DEBUG && d.battery === "yes" ? batteryTitle(d) : "";
  if (r.batt._t !== bt) {
    r.batt._t = bt;
    r.batt.innerHTML = bt ? icon("battery") : "";
    r.batt.title = bt;
    if (bt) r.batt.setAttribute("aria-label", bt); else r.batt.removeAttribute("aria-label");
    var sv = r.batt.firstChild;
    if (sv && sv.style) { sv.style.width = "14px"; sv.style.height = "14px"; }
  }
  r.subRow.hidden = !chip && !bt;
  r.open.style.display = canOpen(d) ? "" : "none";
  r.open.classList.toggle("off", !d.online);
  r.open.setAttribute("aria-disabled", d.online ? "false" : "true");
  r.wake.hidden = !canWake(d);
  el.setAttribute("aria-label", d.name + ", " + st + (anText ? ", " + anText : ""));
  renderHbar(id);
}

// Mini bar of the last 24 h (like the HA history bar): sliding window
// ending now, clipped segments; with no data it stays empty.
export function renderHbar(id) {
  const el = S.tiles.get(id);
  if (!el) return;
  const bar = el._r.hbar, h = S.hist.get(id);
  let html = "", title = "";
  if (h && h.segments.length) {
    var to = nowSec(), from = to - 86400, span = 86400;
    h.segments.forEach(function (s, i) {
      const end = (i === h.segments.length - 1 && s.to >= h.to - 5) ? to : s.to;
      const a = Math.max(s.from, from), b = Math.min(end, to);
      if (b <= a) return;
      html += '<i class="' + (s.online ? "on" : "off") + '" style="left:' + ((a - from) / span * 100).toFixed(2) +
        "%;width:" + Math.max(0.6, (b - a) / span * 100).toFixed(2) + '%"></i>';
    });
    title = t("js.ha.hbar_title");
  }
  if (bar._html !== html) { bar._html = html; bar.innerHTML = html; }
  bar.title = title;
  bar.classList.toggle("nodata", !html);
  bar.setAttribute("aria-label", title || t("js.ha.more.nodata"));
}

export function reconcile(parent, nodes) {
  let ref = parent.firstChild;
  nodes.forEach(function (n) {
    if (n === ref) ref = ref.nextSibling;
    else parent.insertBefore(n, ref);
  });
  while (ref) {
    var next = ref.nextSibling;
    parent.removeChild(ref);
    ref = next;
  }
}

export function emptyState(kind) {
  const el = document.createElement("div");
  el.className = "ha-card empty-state";
  if (kind === "none") {
    var busyNow = S.activity.search || S.scanBusy;
    el.innerHTML = '<button type="button" class="empty-ic scan rp' + (busyNow ? " busy" : "") + '" data-empty="scan" title="' + esc(t("js.ha.scan")) +
      '" aria-label="' + esc(t("js.ha.scan")) + '"' + (busyNow ? " disabled" : "") + ">" + icon("magnify") + "</button><h3>" +
      esc(t("js.ha.empty.title")) + "</h3><p>" + esc(t("js.ha.empty.text")) + "</p>";
  } else if (kind === "nomatch") {
    el.innerHTML = '<div class="empty-ic">' + icon("magnify") + "</div><h3>" + esc(t("js.ha.nomatch.title")) + "</h3><p>" +
      esc(t("js.ha.nomatch.text")) + '</p><div class="btn-row center"><button type="button" class="btn tonal rp" data-empty="clear">' +
      esc(t("js.ha.nomatch.clear")) + "</button></div>";
  } else {
    el.innerHTML = '<div class="empty-ic err">' + icon("alert-circle") + "</div><h3>" + esc(t("js.ha.error.title")) + "</h3><p>" +
      esc(S.lastErr && (S.lastErr.status === 401 || S.lastErr.status === 403) ? t("js.ha.error.session") : t("js.ha.error.text")) +
      '</p><div class="btn-row center"><button type="button" class="btn filled rp" data-empty="retry">' + esc(t("js.ha.error.retry")) +
      '</button><button type="button" class="btn text rp" data-empty="reload">' + esc(t("js.ha.error.reload")) + "</button></div>";
  }
  return el;
}

export function layout() {
  if (!S.loaded) return;
  const visible = S.list.filter(matches);
  if (COMPACT) return layoutCompact(visible);
  const nodes = [];
  TYPE_ORDER.forEach(function (type) {
    const items = visible.filter(function (d) { return d.type === type; });
    let g = S.groups[type];
    if (!g) {
      var sec = document.createElement("section");
      sec.className = "group";
      sec.dataset.type = type;
      sec.innerHTML = '<div class="heading"><span class="hd-ic">' + icon(typeIcon(type)) + '</span><h2 class="hd-title"></h2>' +
        '<span class="hd-count"></span><span class="hd-sub"></span></div><div class="tiles"></div>';
      g = S.groups[type] = { el: sec, grid: sec.querySelector(".tiles"), title: sec.querySelector(".hd-title"),
        count: sec.querySelector(".hd-count"), sub: sec.querySelector(".hd-sub") };
      g.title.textContent = typePlural(type);
    }
    if (!items.length) return;
    const online = items.filter(function (d) { return d.online; }).length;
    g.count.textContent = String(items.length);
    g.sub.textContent = online === items.length ? "" : t("js.ha.group.online", { n: online });
    const tiles = items.map(function (d, i) {
      const el = S.tiles.get(d.id) || createTile(d, i);
      return el;
    });
    reconcile(g.grid, tiles);
    items.forEach(function (d) { updateTile(d.id); });
    nodes.push(g.el);
  });
  if (!nodes.length) nodes.push(emptyState(S.list.length ? "nomatch" : "none"));
  reconcile(groupsEl, nodes);
}

// Compact mode: a single card with a short list (offline first).
function layoutCompact(visible) {
  const rank = function (d) { return d.online ? 2 : (d.is_mobile ? 1 : 0); };
  const sorted = visible.slice().sort(function (a, b) { return rank(a) - rank(b) || a.name.localeCompare(b.name); });
  const shown = sorted.slice(0, COMPACT_LIMIT);
  const card = document.createElement("div");
  card.className = "ha-card compact-list";
  const full = new URLSearchParams(location.search);
  full.delete("compact");
  full.delete("limit");
  let html = '<div class="card-header slim"><div class="ch-title">' + esc(t("js.ha.devices")) + "</div></div><div class=\"crows\">";
  if (!shown.length) html += '<div class="crow-empty">' + esc(t("js.ha.empty.title")) + "</div>";
  shown.forEach(function (d) {
    html += '<div class="crow rp ' + (d.online ? "online" : "offline") + '" data-type="' + esc(d.type) + '" role="button" tabindex="0" data-id="' + esc(d.id) + '">' +
      (d.logo
        ? '<span class="tile-icon has-logo" style="--logo:' + esc(logoVar(d)) + ";--bc:" + logoTint(d) + '"><span class="ic"></span></span>'
        : '<span class="tile-icon"><span class="ic">' + icon(devIcon(d)) + "</span></span>") +
      '<span class="crow-body"><span class="tile-name">' + esc(d.name) + '</span><span class="tile-state">' + esc(stateText(d)) + "</span></span></div>";
  });
  html += "</div>";
  if (sorted.length > shown.length) {
    html += '<a class="crow-more rp" href="' + BASE + '/ha?' + esc(full.toString()) + '" target="_blank" rel="noopener">' +
      esc(t("js.ha.compact.more", { n: sorted.length - shown.length })) + icon("open-in-new") + "</a>";
  }
  card.innerHTML = html;
  reconcile(groupsEl, [card]);
}

groupsEl.addEventListener("click", function (e) {
  const opn = e.target.closest(".tile-open");
  if (opn) {
    e.stopPropagation();
    var od = S.devices.get(opn.closest(".tile").dataset.id);
    // When offline the button is grey and does nothing.
    if (od && od.online) openExternal(od.url || "http://" + od.ip + (od.port && od.port !== 80 ? ":" + od.port : ""));
    return;
  }
  const wake = e.target.closest(".tile-wake");
  if (wake) {
    e.stopPropagation();
    var wid = wake.closest(".tile").dataset.id;
    return wakeDevice(wid);
  }
  const empty = e.target.closest("[data-empty]");
  if (empty) {
    if (empty.dataset.empty === "scan") doScan();
    else if (empty.dataset.empty === "retry") {
      // Visible feedback: button busy; if it fails again the whole page is reloaded.
      empty.disabled = true;
      empty.textContent = t("js.ha.error.retrying");
      load().then(function () { if (!S.loaded && S.loadFails >= 2) reloadHost(true); });
    }
    else if (empty.dataset.empty === "reload") reloadHost(true);
    else clearFilters();
    return;
  }
  const host = e.target.closest("[data-id]");
  if (host) openMore(host.dataset.id);
});
groupsEl.addEventListener("keydown", function (e) {
  if ((e.key === "Enter" || e.key === " ") && e.target.dataset && e.target.dataset.id) {
    e.preventDefault();
    openMore(e.target.dataset.id);
  }
});
function clearFilters() {
  S.filter.status = "all";
  S.filter.type = null;
  S.filter.q = "";
  searchEl.value = "";
  searchClear.hidden = true;
  S.dirty.layout = true;
  S.dirty.net = true;
  schedule();
}

export function flash(id, kind) {
  const el = S.tiles.get(id);
  if (!el || REDUCED) return;
  const ic = el.querySelector(".tile-icon");
  ic.classList.remove("flash-on", "flash-off");
  void ic.offsetWidth;
  ic.classList.add(kind === "on" ? "flash-on" : "flash-off");
}

