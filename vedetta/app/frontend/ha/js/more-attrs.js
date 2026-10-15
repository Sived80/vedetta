import { $, ago, api, canOpen, esc, fmtStamp, fmtUptime, icon, t, typeLabel } from "./core.js";
import { S } from "./core-ui.js";
import { DEBUG } from "./debug.js";
import { deepOneBusy } from "./deep.js";
import { batteryTitle, chipText } from "./filters.js";
import { viaText } from "./tile.js";
import { EV_KEYS, dbgFetch, evApply, evRowCells } from "./more-evidence.js";

export function miDebug(d) {
  const el = $("mi-debug");
  if (!el) return;
  if (!DEBUG) { el.innerHTML = ""; return; }
  function fmt(o) {
    return Object.keys(o || {}).map(function (k) { return k + " " + o[k]; }).join(", ") || "-";
  }
  function draw(x) {
    if (!x) return;
    const rows = [
      [t("js.ha.dbg.type"), (x.type.manual ? x.type.chosen + " (" + t("js.ha.type.manual") + ")" : x.type.chosen) + " | " + fmt(x.type.scores) + " | min " + x.type.min_score],
      [t("js.ha.dbg.kinds"), fmt(x.type.kinds)],
      [t("js.ha.dbg.evidence"), (x.type.evidence || []).map(function (e) {
        return e.group + ": " + e.source + " [" + e.family + "] " + e.pts + (e.counted ? "" : " (ripetuto)");
      }).join("; ") || "-"],
      [t("js.ha.dbg.name"), (x.name.shown || "-") + " | " + (x.name.source || "-") + (x.name.placeholder ? " | placeholder" : "")],
      [t("js.ha.dbg.candidates"), x.name.candidates.map(function (c) { return c.source + ": " + c.raw + (c.cleaned === c.raw ? "" : " -> " + (c.cleaned || "x")); }).join("; ") || "-"],
      [t("js.ha.dbg.brand"), (x.brand.brand || "-") + " | " + (x.brand.source || "-") + " / " + (x.brand.evidence || "-") + " / " + (x.brand.confidence || "-") +
        " | " + (x.brand.vendor || "-") + " (" + (x.brand.vendor_role || "-") + ")" + (x.brand.manual ? " | manual" : "")],
      [t("js.ha.dbg.mobile"), String(x.mobile.is_mobile) + " | mode " + (x.mobile.mode === undefined || x.mobile.mode === null ? "auto" : x.mobile.mode) +
        " | private MAC " + x.mobile.private_mac + " | DHCP " + (x.mobile.dhcp_os_family || "-") + " | churn " + x.mobile.churn_7d +
        " | battery " + (x.mobile.battery || "-") + "/" + (x.mobile.battery_source || "-")],
      [t("js.ha.dbg.dhcp"), fmt(x.dhcp)],
      [t("js.ha.dbg.roles"), (x.roles.roles.join(", ") || "-") + " | UPnP " + (x.roles.upnp_types.join(", ") || "-")],
      [t("js.ha.dbg.scan"), fmt(x.scan)],
      ["WoL", x.wol.ok ? "ok" : "-"]
    ];
    el.innerHTML = '<section class="mi-section dbg"><div class="mi-sec-head"><h3>' + esc(t("js.ha.debug.badge")) + "</h3></div><dl class=\"attr-list\">" +
      rows.map(function (r) { return '<div class="attr"><dt>' + esc(r[0]) + '</dt><dd><span class="attr-val mono">' + esc(r[1]) + "</span></dd></div>"; }).join("") + "</dl></section>";
  }
  if (dbgFetch.id === d.id && dbgFetch.data) draw(dbgFetch.data);
  if (dbgFetch.id === d.id && Date.now() - dbgFetch.at < 5000) return;
  dbgFetch.id = d.id; dbgFetch.at = Date.now();
  api("/api/ha/devices/" + encodeURIComponent(d.id) + "/debug").then(function (x) {
    dbgFetch.data = x;
    if (S.open === d.id && DEBUG) draw(x);
  }).catch(function () { /* debug must never cause errors */ });
}

export function miAttrs(d) {
  const el = $("mi-attrs");
  if (!el) return;
  // Always visible: IP, MAC, response time, ports. The rest is in the "Other attributes" dropdown.
  const rows = [], fixedRows = [];
  function row(label, value, extra, fixed, cls) { (fixed ? fixedRows : rows).push({ label: label, html: value, extra: extra || "", cls: cls || "" }); }
  row(t("js.ha.attr.name"), evRowCells("name", t("js.ha.attr.name")), '<button type="button" class="icon-btn small touch rp" data-act="rename" title="' + esc(t("js.ha.act.rename")) +
    '" aria-label="' + esc(t("js.ha.act.rename")) + '">' + icon("pencil") + "</button>", true, "ev-attr");
  row(t("js.ha.attr.ip"), esc(d.ip + (d.port && d.port !== 80 ? ":" + d.port : "")),
    d.url && canOpen(d) ? '<a class="icon-btn small touch rp" href="' + esc(d.url) + '" target="_blank" rel="noopener" title="' + esc(t("js.ha.act.open")) +
      '" aria-label="' + esc(t("js.ha.act.open")) + '">' + icon("open-in-new") + "</a>" : "", true);
  if (d.mac) row(t("js.ha.attr.mac"), '<span class="mono">' + esc(d.mac) + "</span>",
    '<button type="button" class="icon-btn small touch rp" data-copy="' + esc(d.mac) + '" title="' + esc(t("js.ha.act.copy_mac")) + '" aria-label="' + esc(t("js.ha.act.copy_mac")) + '">' + icon("content-copy") + "</button>", true);
  // Two levels: product brand (with the source) and MAC manufacturer (chip/board).
  const ev = DEBUG && d.brand_evidence ? '<span class="ev ev-' + esc(d.brand_evidence) + '">' + esc(t("js.ha.ev." + d.brand_evidence)) + "</span>" : "";
  const brandShown = d.brand
    ? esc(d.brand) + (DEBUG && d.brand_source ? ' <span class="dbg-txt">· ' + esc(t("js.ha.brand_src." + d.brand_source)) + "</span>" : "") + ev
    : d.brand_declared
      ? '<span style="opacity:.75">' + esc(t("js.ha.brand_declared", { value: d.brand_declared })) + "</span>"
      : '<span style="opacity:.65">' + esc(t("js.ha.brand_unknown")) + "</span>";
  row(t("js.ha.attr.brand"), evRowCells("brand", t("js.ha.attr.brand")),
    '<button type="button" class="icon-btn small touch rp" data-act="brand-edit" title="' + esc(t("js.ha.act.edit_brand")) +
      '" aria-label="' + esc(t("js.ha.act.edit_brand")) + '">' + icon("pencil") + "</button>", true, "ev-attr");
  if (DEBUG && d.name_source) row(t("js.ha.attr.name_src"), esc(d.name_source), "", false, "dbg");
  const rr = (S.roles.by_ip || {})[d.ip];
  if (rr) row(t("js.ha.attr.roles"), Object.keys(rr).map(function (k) {
    return esc(t("js.ha.role." + k)) + ' <span style="opacity:.65">(' + esc(t("js.ha.role_src." + rr[k])) + ")</span>";
  }).join(", "));
  if ((S.roles.via || {})[d.ip]) row(t("js.ha.attr.via"), esc(viaText(d.ip, false)));
  const net = S.roles.internet;
  if (net && rr && rr.gateway) {
    var np = [];
    if (net.public_ip) np.push(t("js.ha.net.public", { ip: net.public_ip }));
    np.push(net.cgnat ? t("js.ha.net.cgnat") : net.double_nat ? t("js.ha.net.double", { ips: (net.private_hops || []).join(" \u2192 ") }) : t("js.ha.net.direct"));
    row(t("js.ha.attr.internet"), esc(np.join(" \u00b7 ")));
  }
  (S.roles.dhcp || []).filter(function (o) { return o.server === d.ip; }).forEach(function (o) {
    const parts = [];
    if (o.router) parts.push(t("js.ha.dhcp.router", { v: o.router.join(", ") }));
    if (o.dns) parts.push(t("js.ha.dhcp.dns", { v: o.dns.join(", ") }));
    if (o.domain) parts.push(t("js.ha.dhcp.domain", { v: o.domain }));
    if (o.lease) parts.push(t("js.ha.dhcp.lease", { v: o.lease }));
    if (parts.length) row(t("js.ha.attr.dhcp_gives"), esc(parts.join(" \u00b7 ")));
  });
  if (d.vendor && d.vendor !== d.brand) row(t("js.ha.attr.chip"), esc(chipText({ vendor: d.vendor, vendor_role: d.vendor_role })));
  if (DEBUG && d.battery === "yes") row(t("js.ha.attr.battery"), '<span class="batt-line">' + icon("battery") + "<span>" + esc(batteryTitle(d)) + "</span></span>", "", false, "dbg");
  const typeShown = esc(typeLabel(d.type)) + (d.type_user ? ' <span style="opacity:.65">· ' + esc(t("js.ha.type.manual")) + "</span>" : "");
  row(t("js.ha.attr.type"), evRowCells("group", t("js.ha.attr.type")),
    '<button type="button" class="icon-btn small touch rp" data-act="type-menu" aria-haspopup="true" title="' + esc(t("js.ha.act.edit_type")) +
      '" aria-label="' + esc(t("js.ha.act.edit_type")) + '">' + icon("chevron-down") + "</button>", true, "ev-attr");
  const an = S.analysis[d.id];
  if (an) row(t("js.ha.attr.analysis"), esc(t("js.ha.an.state." + an.state)) + '<div class="field-hint">' +
    (an.reasons || []).map(function (k) { return esc(t("js.ha.an.reason." + k)); }).join(" · ") + "</div>", "", true);
  if (d.signal) {
    row(t("js.ha.attr.signal"), '<span class="sig sig-' + esc(d.signal.color || "none") + '">' + icon(d.signal.kind === "wifi" ? "wifi" : "lan") + "</span> " +
      esc(d.signal.display) + (d.signal.text ? " · " + esc(d.signal.text) : ""));
  }
  if (d.online && d.latency_ms != null) row(t("js.ha.attr.latency"), '<span class="lat lat-' + esc(d.latency_color || "none") + '">' + esc(d.latency_ms + " ms") + "</span>", "", true);
  if (d.uptime != null && d.online) row(t("js.ha.attr.uptime"), esc(fmtUptime(d.uptime)));
  if (!d.online && d.last_seen) row(t("js.ha.attr.last_seen"), esc(ago(d.last_seen) + " · " + fmtStamp(d.last_seen, true)));
  if (d.scanned_at) row(t("js.ha.attr.scanned"), esc(ago(d.scanned_at)));
  else if (d.deep_empty_at) row(t("js.ha.attr.scanned_empty"), esc(ago(d.deep_empty_at)));
  (d.attrs || []).forEach(function (a) { row(a.label, esc(a.value)); });
  if (d.ports && d.ports.length) {
    var ports = d.ports.map(function (p) { return { p: p, cat: portCategory(p), n: parseInt(p.label, 10) || 0 }; });
    ports.sort(function (a, b) { return PORT_CATS.indexOf(a.cat) - PORT_CATS.indexOf(b.cat) || a.n - b.n; });
    row(t("js.ha.attr.ports"), '<span class="pills">' + ports.map(function (x) {
      const p = Object.assign({}, x.p, { category: x.cat });
      // Service not certain (nmap only inferred it from the number): only the port is shown.
      const label = p.confirmed ? p.label : String(p.label || "").split(" · ")[0];
      return '<span class="pill cat-' + esc(p.category) + (p.confirmed ? "" : " guess") + '" title="' + esc(label) + '">' + esc(label) + "</span>";
    }).join("") + "</span>", "", true);
  }
  fixedRows.sort(function (a, b) { return (a.cls === "ev-attr" ? 0 : 1) - (b.cls === "ev-attr" ? 0 : 1); });    // stable: name, brand, type first
  function html(list) {
    return list.map(function (r) {
      return '<div class="attr' + (r.cls ? " " + r.cls : "") + '"><dt>' + esc(r.label) + '</dt><dd><span class="attr-val">' + r.html + "</span>" + r.extra + "</dd></div>";
    }).join("");
  }
  // Dropdown closed initially; if opened it stays open when the data updates.
  el.innerHTML = html(fixedRows) + (rows.length
    ? '<details class="attr-more" id="attr-more"' + (S.mi.moreOpen ? " open" : "") + "><summary><span>" + esc(t("js.ha.attr.more", { n: rows.length })) +
      '</span><span class="icon-btn small touch attr-chev" aria-hidden="true">' + icon("chevron-down") + "</span></summary>" + html(rows) + "</details>"
    : "");
  const det = $("attr-more");
  if (det) det.addEventListener("toggle", function () { S.mi.moreOpen = det.open; });
  // the values of the three rows (kept out of the string above: they are text, not markup) and then the numbers
  const vals = { name: d.name, brand: null, group: typeLabel(d.type) + (d.type_user ? " \u00b7 " + t("js.ha.type.manual") : "") };
  EV_KEYS.forEach(function (key) {
    const cell = el.querySelector('[data-ev-v="' + key + '"]');
    if (!cell) return;
    if (key === "brand") cell.innerHTML = brandShown; else cell.textContent = vals[key];
  });
  evApply(d);
}

// All actions are inline (pencil and eye next to the name, power on next to the
// status, open next to the IP, copy next to the MAC): no button is left below.
// Port categories (same rules as scanner._PORT_CATEGORY_RULES), also computed
// here from the number: they apply immediately to ports saved before the new categories too.
var PORT_CATS = ["web", "media", "remote", "iot", "file", "print", "db", "infra", "vpn", "mail", "other"];
var PORT_NUM = {
  media: [554, 1935, 7000, 8008, 8009, 1400, 8060, 32400, 8096, 8200],
  print: [631, 9100, 515], vpn: [1194, 51820, 500, 4500, 1701, 1723], mail: [25, 465, 587, 110, 995, 143, 993],
  web: [80, 443, 3000, 8080, 8081, 8443, 8888, 9000, 9090, 8123, 8006],
  remote: [22, 23, 3389, 5900, 5555, 5985, 5986], iot: [1883, 8883, 5683, 6053],
  infra: [53, 67, 68, 111, 123, 137, 138, 139, 161, 162, 389, 5353, 5355], file: [21, 445, 548, 2049],
  db: [3306, 5432, 6379, 27017, 1433]
};
function portCategory(p) {
  const n = parseInt(p.label, 10);
  for (var i = 0; i < PORT_CATS.length; i++) {
    var c = PORT_CATS[i];
    if (PORT_NUM[c] && PORT_NUM[c].indexOf(n) >= 0) return c;
  }
  return p.category && PORT_CATS.indexOf(p.category) >= 0 ? p.category : "other";
}
export function miActions(d) {
  const el = $("mi-actions");
  if (!el) return;
  let html = "";
  // Sharing with Home Assistant (MQTT): the button is always there, and disabled while the link with MQTT is not active (no broker, publishing off: the summary says it in S.mqtt.active), with no message.
  // Shared = HA sees the device as a sub-device of "Vedetta"; "Remove" takes it out of HA.
  if (d) {
    var shareOff = S.mqtt && S.mqtt.active ? "" : " disabled";
    html += '<button type="button" class="btn ' + (d.ha_share ? "outlined" : "tonal") + ' rp" data-act="share"' + shareOff + '>' + icon("home-assistant") +
      "<span>" + esc(t(d.ha_share ? "js.ha.share.remove" : "js.ha.share.add")) + "</span></button>";
  }
  const flagTip = esc(t(d && d.focus ? "js.ha.focus.edit" : "js.ha.focus.add"));
  // The flag of the report lives here, not on the icon of the tile: always the plain icon button, never a word and never orange (aria-pressed tells the state).
  const flagOn = !!(d && d.focus);
  const flag = '<button type="button" class="icon-btn small mi-flag rp' + (flagOn ? " on" : "") + '" data-act="focus" title="' + flagTip + '" aria-label="' + flagTip + '" aria-pressed="' + flagOn + '">' +
    icon("flag") + "</button>";
  el.innerHTML = flag + html + '<button type="button" class="btn tonal rp" data-act="deep"' + (deepOneBusy(d && d.id) ? ' disabled title="' + esc(t("js.ha.deep.busy")) + '"' : "") + ">" + icon("magnify") + "<span>" + esc(t("js.ha.deep.title")) + "</span></button>";
}

