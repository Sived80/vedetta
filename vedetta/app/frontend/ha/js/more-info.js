import { $, ago, analysisText, canWake, devIcon, dlg, esc, fmtStamp, fmtUptime, icon, logoVar, t, typeLabel } from "./core.js";
import { S, raiseSnacks, snacksEl } from "./core-ui.js";
import { chipText } from "./filters.js";
import { miActions, miAttrs, miDebug } from "./more-attrs.js";
import { loadGraph } from "./more-graph.js";
import { renderBrandEdit, renderDeep, renderFocus, renderIgnore, renderRename } from "./more-edit.js";

// ------------------------------------------------- "More info" dialog
export function openMore(id) {
  if (!S.devices.has(id)) return;
  S.open = id;
  S.mi.moreOpen = false;   // "Other attributes" always starts closed
  S.mi.range = 24;
  S.mi.edit = false;       // the edit icons (pencils, type arrow) start off in every card
  S.mi.view = "main";
  S.mi.win = {};
  renderMore();
  if (!dlg.open) {
    if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
    if (snacksEl.children.length) raiseSnacks();
  }
}
export function closeMore() {
  if (dlg.open && typeof dlg.close === "function") dlg.close(); else dlg.removeAttribute("open");
  S.open = null;
}
dlg.addEventListener("close", function () { S.open = null; });
dlg.addEventListener("click", function (e) { if (e.target === dlg) closeMore(); });

export function miHeader(d, title, back) {
  return '<div class="mi-header"><button type="button" class="icon-btn touch rp" data-act="' + (back ? "back" : "close") + '" aria-label="' +
    esc(t("js.ha.more.close")) + '">' + icon("close") + '</button><div class="mi-titles"><div class="mi-name-row"><h2 class="mi-title" id="more-title">' + esc(title) +
    "</h2>" + (d ? '<button type="button" class="icon-btn small touch rp mi-ed" data-act="rename" title="' + esc(t("js.ha.act.rename")) +
    '" aria-label="' + esc(t("js.ha.act.rename")) + '">' + icon("pencil") + "</button>" +
    // The three dots: a menu with "Customize card" (shows the edit icons) and "Ignore device".
    '<button type="button" class="icon-btn small touch rp" data-act="card-menu" aria-haspopup="menu" aria-expanded="false" title="' + esc(t("js.ha.act.more_actions")) +
    '" aria-label="' + esc(t("js.ha.act.more_actions")) + '">' + icon("dots-vertical") + "</button>" : "") + "</div>" + (d ? '<div class="mi-sub" id="mi-sub">' + esc(miSub(d)) + "</div>" : "") + "</div></div>";
}
export function miSub(d) { return [chipText(d), typeLabel(d.type)].filter(Boolean).join(" · "); }

export function renderMore() {
  const d = S.devices.get(S.open);
  if (!d) return closeMore();
  dlg.classList.toggle("edit-on", !!S.mi.edit);
  if (S.mi.view === "rename") return renderRename(d);
  if (S.mi.view === "brand") return renderBrandEdit(d);
  if (S.mi.view === "focus") return renderFocus(d);
  if (S.mi.view === "ignore") return renderIgnore(d);
  if (S.mi.view === "deep") return renderDeep(d);
  dlg.innerHTML = '<div class="mi">' + miHeader(d, d.name, false) +
    '<div class="mi-body"><div class="mi-hero" id="mi-hero"></div>' +
    '<section class="mi-section"><div class="mi-sec-head"><h3>' + esc(t("js.ha.more.history")) + '</h3><div class="seg" role="group">' +
    '<button type="button" class="rp" data-range="24" aria-pressed="true">' + esc(t("js.ha.more.range24")) + "</button>" +
    '<button type="button" class="rp" data-range="168" aria-pressed="false">' + esc(t("js.ha.more.range7")) + "</button></div></div>" +
    '<div class="mi-graph" id="mi-graph"><div class="skeleton sk-graph"></div></div></section>' +
    '<section class="mi-section attrs"><dl class="attr-list" id="mi-attrs"></dl></section><div id="mi-debug"></div></div>' +
    '<div class="mi-actions" id="mi-actions"></div></div>';
  miHero(d);
  miAttrs(d);
  miDebug(d);
  miActions(d);
  loadGraph();
}

export function miHero(d) {
  brandSheetSync(d);
  const el = $("mi-hero");
  if (!el) return;
  el.className = "mi-hero " + (d.online ? "online" : "offline");
  // online and offline are written one on the other (a grid cell, the false one hidden): the cell is as wide as the wider, so the words of the analysis beside it do not move when the card changes state.
  const an = S.analysis[d.id], anText = analysisText(an);
  el.innerHTML = '<span class="hero-ic">' + icon(devIcon(d)) + '</span><div><div class="hero-state"><span class="hero-st"><span class="' + (d.online ? "" : "hs-hide") + '">' + esc(t("js.ha.state.online")) +
    '</span><span class="' + (d.online ? "hs-hide" : "") + '">' + esc(t("js.ha.state.offline")) + '</span></span><span class="hero-an" data-s="' + esc((an && an.state) || "") + '"' + (anText ? "" : " hidden") + ">" + esc(anText) +
    '</span></div><div class="hero-sub">' + esc(heroSub(d)) + "</div></div>" +
    (canWake(d) ? '<button type="button" class="icon-btn small touch rp hero-wake" data-act="wake" title="' + esc(t("js.ha.act.wake")) +
      '" aria-label="' + esc(t("js.ha.act.wake")) + '">' + icon("power") + "</button>" : "");
}
function heroSub(d) {
  if (d.online) return d.uptime != null ? t("js.ha.more.up_for", { uptime: fmtUptime(d.uptime) }) : "";
  return d.last_seen ? t("js.ha.more.seen_at", { ago: ago(d.last_seen), time: fmtStamp(d.last_seen, true) }) : "";
}

// Text of a translation keyed by a technical value; the value itself if there is no translation.
// Big faint logo on the device sheet, cut by the edge of the window.
function brandSheetSync(d) {
  const mi = dlg.querySelector(".mi");
  if (!mi) return;
  let el = mi.querySelector(".brand-sheet");
  if (!d || !d.logo) { if (el) el.remove(); return; }
  if (!el) {
    el = document.createElement("span");
    el.className = "brand-sheet";
    el.setAttribute("aria-hidden", "true");
    el.innerHTML = "<i></i>";
    mi.insertBefore(el, mi.firstChild);
  }
  el.style.setProperty("--logo", logoVar(d));
}
