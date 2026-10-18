import { $, api, dlg, esc, icon, t, typePlural } from "./core.js";
import { S } from "./core-ui.js";

function evKey(prefix, raw) {
  const key = prefix + String(raw || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  const text = t(key);
  return text === key ? String(raw || "") : text;
}
var EV_CLUES = [[/^ruolo di rete$/, "role"], [/^porta (\d+)$/, "port"], [/^parola nel testo$/, "words"], [/^parola: (.+)$/, "word"],
  [/^marca: (.+)$/, "brand"], [/^firma (.+)$/, "sig"], [/^integrazione HA (.+)$/, "ha"], [/^piattaforma IoT$/, "platform"], [/^solo porte IoT$/, "iotports"]];
function evClue(src) {
  for (var i = 0; i < EV_CLUES.length; i++) {
    var m = EV_CLUES[i][0].exec(src);
    if (m) return t("js.ha.ev.clue." + EV_CLUES[i][1], { n: m[1], k: m[1] });
  }
  return src;    // mDNS, UPnP, API names are the technical names
}
// Evidence on the rows Name, Brand and Type: a thin bar and the certainty next to the (i) that opens a small pop-up with
// what decided it and what was rejected. The numbers come from the server (/evidence); the rows are drawn without them and
// only filled in later, so nothing moves when they arrive or change.
var evData = { id: null, at: 0, sig: "", data: null };
export var EV_KEYS = ["name", "brand", "group"];
function evLevel(n) { return n >= 70 ? "high" : n >= 40 ? "mid" : "low"; }
export function evRowCells(key, label) {
  const info = esc(t("js.ha.ev.info", { what: label }));
  return '<span class="ev-cell"><span class="ev-v" data-ev-v="' + key + '"></span><span class="ev-meter">' +
    '<span class="ev-bar" data-ev-bar="' + key + '" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><i></i></span>' +
    '<span class="ev-pct" data-ev-pct="' + key + '">\u2014</span>' +
    '<button type="button" class="ev-i" data-ev-i="' + key + '" aria-haspopup="dialog" aria-expanded="false" title="' + info + '" aria-label="' + info + '">' +
    icon("information-outline") + "</button></span></span>";
}
// What the pop-up says, as data: one line of "why" (when there are no clues to list), the clues with their points (the type), and the
// rejected hypotheses, each with its points (the type) and a short note.
function evText(x, key) {
  const e = x[key], out = { certainty: e.certainty, line: "", clues: [], rej: [] };
  if (key === "group") {
    if (e.basis === "scored") out.clues = (e.clues || []).map(function (c) { return { name: evClue(c.source), pts: c.points }; });
    else out.line = e.basis === "manual" ? t("js.ha.ev.g.manual") : e.basis === "mobile" ? t("js.ha.ev.g.mobile", { reason: evKey("js.ha.ev.reason.", e.reason) }) : t("js.ha.ev.g." + e.basis);
    out.rej = (e.rejected || []).map(function (r) {
      return { name: typePlural(r.value), pts: r.points, note: t("js.ha.ev.why." + r.why, { chosen: typePlural(e.value) }) };
    });
  } else if (key === "brand") {
    out.line = e.basis === "manual" ? t("js.ha.ev.b.manual") : e.basis === "found" ? t("js.ha.ev.b.found", { source: evKey("js.ha.ev.bsrc.", e.source) }) : t("js.ha.ev.b.none");
    out.rej = (e.rejected || []).map(function (r) {
      return { name: r.value, pts: null, note: r.kind === "vendor" ? t("js.ha.ev.vendor", { role: evKey("js.ha.ev.role.", r.role || "other") }) : t("js.ha.ev.declared") };
    });
  } else {
    out.line = e.basis === "ip" ? t("js.ha.ev.n.ip") : e.basis === "manual" ? t("js.ha.ev.n.manual") : e.basis === "placeholder" ? t("js.ha.ev.n.placeholder")
      : e.basis === "brand" ? t("js.ha.ev.n.brand") : e.basis === "source" ? t("js.ha.ev.n.source", { source: evKey("js.ha.ev.nsrc.", e.source) }) : t("js.ha.ev.n.unknown");
    out.rej = (e.rejected || []).map(function (r) {
      return { name: r.value, pts: null, note: evKey("js.ha.ev.nsrc.", r.source) + " — " + t(r.cleaned ? "js.ha.ev.n.lower" : "js.ha.ev.n.technical") };
    });
  }
  return out;
}
// The rows of the pop-up: name, small bar and points in three aligned columns (no bar when the hypothesis has no points).
function evRows(list, max) {
  return '<ul class="evp-rows">' + list.map(function (r) {
    const has = r.pts != null;
    return '<li class="evp-row' + (has ? "" : " nopts") + '"><span class="evp-name" title="' + esc(r.name) + '">' + esc(r.name) + "</span>" +
      (has ? '<span class="evp-bar"><i style="width:' + Math.max(8, Math.round(100 * r.pts / max)) + '%"></i></span><span class="evp-pts">' + (r.note === undefined ? "+" : "") + r.pts + "</span>" : "") +
      (r.note ? '<span class="evp-note" title="' + esc(r.note) + '">' + esc(r.note) + "</span>" : "") + "</li>";
  }).join("") + "</ul>";
}
function evPaint(x) {
  const root = $("mi-attrs");
  if (!root || !x) return;
  EV_KEYS.forEach(function (key) {
    const n = x[key].certainty, pct = root.querySelector('[data-ev-pct="' + key + '"]'), bar = root.querySelector('[data-ev-bar="' + key + '"]');
    if (!pct || !bar) return;
    pct.textContent = n > 0 ? n + "%" : "\u2014";
    bar.className = "ev-bar" + (n > 0 ? " lvl-" + evLevel(n) : "");
    bar.setAttribute("aria-valuenow", String(n));
    bar.firstChild.style.width = n + "%";
  });
}
export function evApply(d) {
  const sig = [d.name, d.brand, d.type, d.type_user, d.brand_user].join("|");
  if (evData.id !== d.id || evData.sig !== sig) evData.data = null;       // the value changed: the old numbers are not for it
  if (evData.data) evPaint(evData.data);
  if (evData.id === d.id && evData.sig === sig && Date.now() - evData.at < 5000) return;
  evData.id = d.id; evData.sig = sig; evData.at = Date.now();
  api("/api/ha/devices/" + encodeURIComponent(d.id) + "/evidence").then(function (x) {
    evData.data = x;
    if (S.open === d.id) evPaint(x);
  }).catch(function () { /* the numbers are extra: the rows work without them */ });
}
// The pop-up: small, inside the sheet, closed by pressing anywhere outside it (or Escape, or scrolling the sheet).
var evPop = { el: null, key: null, btn: null };
function evPopClose() {
  if (!evPop.el) return;
  evPop.el.remove();
  if (evPop.btn) evPop.btn.setAttribute("aria-expanded", "false");
  evPop.el = evPop.key = evPop.btn = null;
  document.removeEventListener("pointerdown", evPopOutside, true);
  document.removeEventListener("mousedown", evPopOutside, true);
  document.removeEventListener("keydown", evPopKey, true);
}
function evPopOutside(e) {
  if (evPop.el && !evPop.el.contains(e.target) && !(evPop.btn && evPop.btn.contains(e.target))) evPopClose();
}
function evPopKey(e) {
  if (e.key === "Escape" && evPop.el) { e.preventDefault(); e.stopPropagation(); evPopClose(); }
}
function evPopOpen(key, btn) {
  const x = evData.data, host = dlg.querySelector(".mi");
  if (!x || !host) return;
  evPopClose();
  const info = evText(x, key), label = btn.closest(".attr").querySelector("dt").textContent;
  const el = document.createElement("div");
  el.className = "ev-pop"; el.id = "ev-pop"; el.setAttribute("role", "dialog"); el.setAttribute("aria-label", label);
  const maxPts = Math.max.apply(null, [1].concat(info.clues.map(function (c) { return c.pts; }), info.rej.map(function (r) { return r.pts || 0; })));
  const n = info.certainty, sure = n > 0 ? esc(t("js.ha.ev.sure", { n: n })) : "";
  el.innerHTML = '<div class="evp-h"><b>' + esc(label) + '</b><span class="evp-n' + (n > 0 ? " lvl-" + evLevel(n) : "") + '"' + (sure ? ' title="' + sure + '"' : "") + ">" + (n > 0 ? n + "%" : "—") + "</span></div>" +
    (info.line ? '<p class="evp-line" title="' + esc(info.line) + '">' + esc(info.line) + "</p>" : "") +
    (info.clues.length ? '<div class="evp-sec">' + esc(t("js.ha.ev.h_clues")) + "</div>" + evRows(info.clues.map(function (c) { return { name: c.name, pts: c.pts, note: undefined }; }), maxPts) : "") +
    (info.rej.length ? '<div class="evp-sec">' + esc(t("js.ha.ev.rejected", { n: info.rej.length })) + "</div>" + evRows(info.rej, maxPts) : "");
  host.appendChild(el);
  const hr = host.getBoundingClientRect(), br = btn.getBoundingClientRect(), w = Math.min(300, hr.width - 16);
  el.style.width = w + "px";
  el.style.left = Math.round(Math.max(8, Math.min(br.right - hr.left - w + 12, hr.width - w - 8))) + "px";
  // The same rule on every screen: it opens below the button, or above it when there is more room there, and never taller than the
  // room (the visible part of the window sheet); what does not fit scrolls inside it.
  const seenTop = Math.max(hr.top, 0), seenBottom = Math.min(hr.bottom, window.innerHeight || hr.bottom), gap = 6, edge = 10;
  const below = seenBottom - br.bottom - gap - edge, above = br.top - seenTop - gap - edge, need = el.scrollHeight;
  const up = need > below && above > below, room = Math.max(120, up ? above : below);
  el.style.maxHeight = Math.round(room) + "px";
  const h = Math.min(need, room);
  el.style.top = Math.round((up ? br.top - hr.top - gap - h : br.bottom - hr.top + gap)) + "px";
  evPop.el = el; evPop.key = key; evPop.btn = btn;
  btn.setAttribute("aria-expanded", "true");
  document.addEventListener("pointerdown", evPopOutside, true);
  document.addEventListener("mousedown", evPopOutside, true);
  document.addEventListener("keydown", evPopKey, true);
}
document.addEventListener("click", function (e) {
  const btn = e.target.closest && e.target.closest("[data-ev-i]");
  if (!btn) return;
  if (evPop.btn === btn) evPopClose(); else evPopOpen(btn.getAttribute("data-ev-i"), btn);
});
dlg.addEventListener("cancel", function (e) { if (evPop.el) { e.preventDefault(); evPopClose(); } });
dlg.addEventListener("close", evPopClose);
dlg.addEventListener("scroll", function (e) { if (evPop.el && evPop.el.contains(e.target)) return; evPopClose(); }, true);   // scrolling the pop-up itself does not close it

// Debug mode: why the device has this type, name and brand (data from the server, not in the normal list).
export var dbgFetch = { id: null, at: 0, data: null };
