import { $, I, TYPE_ORDER, api, dlg, esc, icon, t, typeLabel } from "./core.js";
import { S, snack } from "./core-ui.js";
import { closePopups } from "./core-menu.js";
import { SKIP_DEEP_KEY, deepOneBusy, runDeep, skipDeepConfirm } from "./deep.js";
import { closeMore, miHeader, renderMore } from "./more-info.js";
import { loadGraph } from "./more-graph.js";
import { schedule } from "./live.js";

export function renderRename(d) {
  const mode = d.mobile_mode || "auto";
  dlg.innerHTML = '<div class="mi">' + miHeader(null, t("js.ha.rename.title"), true) +
    '<form class="mi-body" id="rename-form" autocomplete="off">' +
    '<label class="field"><input id="rn-name" type="text" maxlength="80" required placeholder=" " value="' + esc(d.name) + '"><span class="field-label">' + esc(t("js.ha.rename.name")) + "</span></label>" +
    '<div class="field-group"><div class="field-caption">' + esc(t("js.ha.rename.mobile")) + '</div><div class="seg wide" role="radiogroup" id="rn-mode">' +
    ["auto", "yes", "no"].map(function (m) {
      return '<button type="button" role="radio" class="rp" data-mode="' + m + '" aria-checked="' + (m === mode) + '" aria-pressed="' + (m === mode) + '">' + esc(t("js.ha.rename.mode_" + m)) + "</button>";
    }).join("") + '</div><div class="field-hint">' + esc(t("js.ha.rename.mobile_hint")) + "</div></div>" +
    '<div class="mi-actions"><button type="button" class="btn text rp" data-act="back">' + esc(t("js.ha.cancel")) + '</button>' +
    '<button type="submit" class="btn filled rp">' + esc(t("js.ha.save")) + "</button></div></form></div>";
  const input = $("rn-name");
  if (input) { input.focus(); input.select(); }
}
// Flag the device for the report: its card, history and this note go in the export for analysis.
export function renderFocus(d) {
  dlg.innerHTML = '<div class="mi">' + miHeader(null, t("js.ha.focus.title"), true) +
    '<form class="mi-body" id="focus-form" autocomplete="off">' +
    '<label class="field"><textarea id="fc-note" rows="4" maxlength="500" placeholder=" ">' + esc(d.focus_note || "") + '</textarea><span class="field-label">' + esc(t("js.ha.focus.label")) + "</span></label>" +
    '<div class="field-hint">' + esc(t("js.ha.focus.hint")) + "</div>" +
    '<div class="mi-actions"><button type="button" class="btn text rp" data-act="back">' + esc(t("js.ha.cancel")) + "</button>" +
    (d.focus ? '<button type="button" class="btn outlined rp" data-act="focus-off">' + esc(t("js.ha.focus.remove")) + "</button>" : "") +
    '<button type="submit" class="btn filled rp">' + esc(t("js.ha.focus.save")) + "</button></div></form></div>";
  const input = $("fc-note");
  if (input) input.focus();
}
export function renderBrandEdit(d) {
  dlg.innerHTML = '<div class="mi">' + miHeader(null, t("js.ha.brand.title"), true) +
    '<form class="mi-body" id="brand-form" autocomplete="off">' +
    '<label class="field"><input id="br-name" type="text" maxlength="40" placeholder=" " value="' + esc(d.brand_user || d.brand || "") + '"><span class="field-label">' + esc(t("js.ha.brand.label")) + "</span></label>" +
    '<div class="field-hint">' + esc(t("js.ha.brand.hint")) + "</div>" +
    '<div class="mi-actions"><button type="button" class="btn text rp" data-act="back">' + esc(t("js.ha.cancel")) + '</button>' +
    '<button type="submit" class="btn filled rp">' + esc(t("js.ha.save")) + "</button></div></form></div>";
  const input = $("br-name");
  if (input) { input.focus(); input.select(); }
}
// Manual choice of brand or type: stays until switching back to automatic.
function saveOverride(d, body) {
  return api("/api/devices/" + encodeURIComponent(d.id) + "/override", { method: "POST", json: body }).then(function () {
    // the choice is shown at once (the server sends the card again when it has re-read the device); no full reload, which
    // rebuilt every tile and played all their animations again
    Object.assign(d, body);
    S.dirty.ids.add(d.id);
    S.dirty.more = true;
    S.dirty.net = true;
    schedule();
    return true;
  }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); return false; });
}
// Type dropdown menu: inside the dialog (it is modal), with the same rules as the other
// menus (closes with Esc, click outside and scroll; opening one closes the others).
var typeMenu = null;
function closeTypeMenu() {
  if (typeMenu) { typeMenu.remove(); typeMenu = null; }
}
function openTypeMenu(btn, d) {
  if (typeMenu) { closeTypeMenu(); return; }
  closePopups();
  const m = document.createElement("div");
  m.className = "menu type-menu"; m.setAttribute("role", "menu");
  const cur = d.type_user || "";
  const items = [["", t("js.ha.type.auto")]].concat(TYPE_ORDER.map(function (k) { return [k, typeLabel(k)]; }));
  m.innerHTML = items.map(function (it) {
    return '<button type="button" class="menu-item rp" role="menuitemradio" data-type="' + esc(it[0]) + '" aria-checked="' + (it[0] === cur) + '">' +
      (it[0] ? icon(I.typeIcon[it[0]]) : icon("auto-fix")) + "<span>" + esc(it[1]) + "</span></button>";
  }).join("");
  const r = btn.getBoundingClientRect();
  m.style.top = Math.round(r.bottom + 4) + "px";
  m.style.right = Math.max(8, Math.round(window.innerWidth - r.right)) + "px";
  m.style.maxHeight = Math.max(160, window.innerHeight - r.bottom - 16) + "px";
  dlg.appendChild(m);
  typeMenu = m;
  m.addEventListener("click", function (e) {
    const b = e.target.closest("[data-type]");
    if (!b) return;
    closeTypeMenu();
    saveOverride(d, { type: b.dataset.type || null });
  });
}
// Menu of the three dots in the header of the card: "Customize card" (the edit icons show or hide) and "Ignore device". Same rules as the type menu.
var cardMenu = null;
function closeCardMenu() {
  if (cardMenu) { cardMenu.remove(); cardMenu = null; }
  const b = dlg.querySelector('[data-act="card-menu"]');
  if (b) b.setAttribute("aria-expanded", "false");
}
function openCardMenu(btn) {
  if (cardMenu) { const wasOpen = cardMenu.isConnected; closeCardMenu(); if (wasOpen) return; }      // (a redraw of the card may have removed it already)
  closeTypeMenu();
  closePopups();
  const m = document.createElement("div");
  m.className = "menu type-menu card-menu"; m.setAttribute("role", "menu");
  m.innerHTML = '<button type="button" class="menu-item rp" role="menuitemcheckbox" data-act="edit-toggle" aria-checked="' + !!S.mi.edit + '">' + icon("pencil") +
    "<span>" + esc(t("js.ha.act.edit_toggle")) + '</span><span class="menu-check">' + icon("check") + "</span></button>" +
    '<button type="button" class="menu-item rp" role="menuitem" data-act="ignore">' + icon("eye-off") + "<span>" + esc(t("js.ha.act.ignore")) + "</span></button>";
  const r = btn.getBoundingClientRect();
  m.style.top = Math.round(r.bottom + 4) + "px";
  m.style.right = Math.max(8, Math.round(window.innerWidth - r.right)) + "px";
  m.style.maxHeight = Math.max(160, window.innerHeight - r.bottom - 16) + "px";
  dlg.appendChild(m);
  cardMenu = m;
  btn.setAttribute("aria-expanded", "true");
  m.addEventListener("click", function () { closeCardMenu(); });      // the choice itself is done by the click handler of the card (data-act)
  const first = m.querySelector(".menu-item");
  if (first) first.focus();
}
document.addEventListener("click", function (e) {
  if (cardMenu && !e.target.closest(".card-menu") && !e.target.closest('[data-act="card-menu"]')) closeCardMenu();
});
document.addEventListener("keydown", function (e) { if (e.key === "Escape" && cardMenu) { closeCardMenu(); } });
document.addEventListener("click", function (e) {
  if (typeMenu && !e.target.closest(".type-menu") && !e.target.closest('[data-act="type-menu"]')) closeTypeMenu();
});
document.addEventListener("keydown", function (e) { if (e.key === "Escape" && typeMenu) { closeTypeMenu(); } });
window.addEventListener("scroll", function (e) { if (typeMenu && !typeMenu.contains(e.target)) closeTypeMenu(); }, true);
export function renderDeep(d) {
  dlg.innerHTML = '<div class="mi">' + miHeader(null, t("js.ha.deep.title"), true) +
    '<div class="mi-body"><div class="confirm"><span class="confirm-ic info">' + icon("magnify") + "</span><p>" + esc(t("js.ha.deep.one_text", { name: d.name })) + "</p></div>" +
    '<label class="fl-row"><span class="fl-text"><b>' + esc(t("js.ha.deep.skip")) + '</b></span><input type="checkbox" class="fl-sw" id="deep-skip"></label></div>' +
    '<div class="mi-actions"><button type="button" class="btn text rp" data-act="back">' + esc(t("js.ha.cancel")) + "</button>" +
    '<button type="button" class="btn filled rp" data-act="deep-confirm">' + esc(t("js.ha.deep.start")) + "</button></div></div>";
}
export function renderIgnore(d) {
  dlg.innerHTML = '<div class="mi">' + miHeader(null, t("js.ha.ignore.title", { name: d.name }), true) +
    '<div class="mi-body"><div class="confirm"><span class="confirm-ic">' + icon("eye-off") + "</span><p>" + esc(t("js.ha.ignore.text")) + "</p></div></div>" +
    '<div class="mi-actions"><button type="button" class="btn text rp" data-act="back">' + esc(t("js.ha.cancel")) + "</button>" +
    '<button type="button" class="btn filled danger rp" data-act="ignore-confirm">' + esc(t("js.ha.act.ignore")) + "</button></div></div>";
}

function copyText(text) {
  function fallback() {
    // With a modal dialog open the rest of the page is "inert": the support
    // field must be inside the dialog, otherwise it cannot be selected and
    // the copy fails silently (happens on HTTP, where the clipboard API is missing).
    const host = document.querySelector("dialog[open]") || document.body;
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("aria-hidden", "true");
    ta.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;font-size:16px";
    host.appendChild(ta);
    ta.focus();
    ta.select();
    try { ta.setSelectionRange(0, text.length); } catch (err) { /* ignore */ }
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
    host.removeChild(ta);
    return ok;
  }
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return fallback(); });
  }
  return Promise.resolve(fallback());
}

export function wakeDevice(id) {
  const d = S.devices.get(id);
  if (!d) return;
  api("/api/devices/" + encodeURIComponent(id) + "/wake", { method: "POST" }).then(function () {
    snack(t("js.ha.toast.wake_sent", { name: d.name }), { kind: "success" });
  }).catch(function (err) {
    snack(err.message && err.message.indexOf("HTTP") !== 0 ? err.message : t("js.ha.toast.wake_failed"), { kind: "error" });
  });
}

// Opening an external page (the device's web interface, classic
// dashboard): a link with target="_blank" inside the iframe of the HA mobile app
// may be ignored. It is opened with window.open from a user gesture; if the
// browser blocks it, the address is copied and a notice is shown.
export function openExternal(url) {
  let w = null;
  try { w = window.open(url, "_blank"); } catch (err) { w = null; }
  if (w) { try { w.opener = null; } catch (err) { /* ignore */ } return; }
  function copyFallback() {
    copyText(url).then(function (ok) {
      snack(t("js.ha.toast.open_blocked"), { kind: ok ? "success" : "error", ms: 4500 });
    });
  }
  // In the HA mobile app the iframe cannot open windows: the upper level
  // (the app) is asked to navigate, which opens an external address in the default
  // browser. If the page does not go to the background within a moment, it did not
  // succeed and the fallback is copying the address.
  const inApp = window.top !== window && /home\s?assistant/i.test(navigator.userAgent || "");
  if (!inApp) { copyFallback(); return; }
  let left = false;
  function onHide() { if (document.hidden) left = true; }
  document.addEventListener("visibilitychange", onHide);
  try { window.open(url, "_top"); } catch (err) { /* ignore */ }
  setTimeout(function () {
    document.removeEventListener("visibilitychange", onHide);
    if (!left) copyFallback();
  }, 900);
}
document.addEventListener("click", function (e) {
  const a = e.target.closest ? e.target.closest('a[target="_blank"]') : null;
  if (!a || e.defaultPrevented || e.ctrlKey || e.metaKey || e.shiftKey) return;
  e.preventDefault();
  openExternal(a.href);
});

dlg.addEventListener("click", function (e) {
  const copy = e.target.closest("[data-copy]");
  if (copy) {
    copyText(copy.dataset.copy).then(function (ok) {
      snack(ok ? t("js.ha.toast.mac_copied") : t("js.ha.toast.copy_failed"), { kind: ok ? "success" : "error", ms: 2200 });
    });
    return;
  }
  const range = e.target.closest("[data-range]");
  if (range) {
    S.mi.range = parseInt(range.dataset.range, 10);
    dlg.querySelectorAll("[data-range]").forEach(function (b) { b.setAttribute("aria-pressed", String(b === range)); });
    loadGraph();
    return;
  }
  const mode = e.target.closest("[data-mode]");
  if (mode) {
    dlg.querySelectorAll("[data-mode]").forEach(function (b) {
      b.setAttribute("aria-checked", String(b === mode));
      b.setAttribute("aria-pressed", String(b === mode));
    });
    return;
  }
  const act = e.target.closest("[data-act]");
  if (!act) return;
  const d = S.devices.get(S.open);
  switch (act.dataset.act) {
    case "close": closeMore(); break;
    case "back": S.mi.view = "main"; renderMore(); break;
    case "edit-toggle":
      S.mi.edit = !S.mi.edit;
      dlg.classList.toggle("edit-on", S.mi.edit);
      break;
    case "card-menu": openCardMenu(act); break;
    case "rename": S.mi.view = "rename"; renderMore(); break;
    case "brand-edit": S.mi.view = "brand"; renderMore(); break;
    case "focus": S.mi.view = "focus"; renderMore(); break;
    case "focus-off": if (d) saveOverride(d, { focus: false }).then(function () { S.mi.view = "main"; renderMore(); snack(t("js.ha.focus.removed"), { kind: "success" }); }); break;
    case "type-menu": if (d) openTypeMenu(act, d); break;
    case "ignore": S.mi.view = "ignore"; renderMore(); break;
    case "deep":
      if (d && deepOneBusy(d.id)) break;
      // Once the search has started, return to the dashboard: progress is visible on the card.
      if (d && skipDeepConfirm()) { runDeep([d.id]); closeMore(); break; }
      S.mi.view = "deep"; renderMore(); break;
    case "deep-confirm":
      if (d) {
        var skip = $("deep-skip");
        if (skip && skip.checked) { try { localStorage.setItem(SKIP_DEEP_KEY, "1"); } catch (err) { /* ignore */ } }
        runDeep([d.id]);
      }
      S.mi.view = "main"; closeMore(); break;
    case "wake": if (d) wakeDevice(d.id); break;
    case "share": if (d) { const share = !d.ha_share; saveOverride(d, { ha_share: share }).then(function (saved) { if (saved) snack(t(share ? "js.ha.share.added" : "js.ha.share.removed"), { kind: "success" }); }); } break;
    case "ignore-confirm": if (d) ignoreDevice(d, act); break;
  }
});
dlg.addEventListener("submit", function (e) {
  e.preventDefault();
  const d = S.devices.get(S.open);
  if (!d) return;
  if (e.target.id === "focus-form") {
    var flagged = 0;
    S.devices.forEach(function (x) { if (x.focus && x.id !== d.id) flagged++; });
    if (flagged >= 5) { snack(t("js.ha.focus.too_many"), { kind: "warning" }); return; }
    var submitF = e.target.querySelector('[type="submit"]');
    if (submitF) submitF.disabled = true;
    saveOverride(d, { focus: true, focus_note: $("fc-note").value.trim() || null }).then(function () { S.mi.view = "main"; renderMore(); snack(t("js.ha.focus.saved"), { kind: "success" }); });
    return;
  }
  if (e.target.id === "brand-form") {
    var submitB = e.target.querySelector('[type="submit"]');
    if (submitB) submitB.disabled = true;
    saveOverride(d, { brand: $("br-name").value.trim() || null }).then(function () { S.mi.view = "main"; renderMore(); });
    return;
  }
  const name = $("rn-name").value.trim();
  if (!name) return;
  const selected = dlg.querySelector('[data-mode][aria-checked="true"]');
  const m = selected ? selected.dataset.mode : "auto";
  const body = { name: name };
  if (m === "yes") body.mobile = true;
  else if (m === "no") body.mobile = false; // "auto": missing field = the heuristic decides again
  const submit = e.target.querySelector('[type="submit"]');
  if (submit) submit.disabled = true;
  api("/api/devices/" + encodeURIComponent(d.id) + "/rename", { method: "POST", json: body }).then(function () {

    S.mi.view = "main";
    renderMore();
  }).catch(function (err) {
    if (submit) submit.disabled = false;
    snack(err.message && err.message.indexOf("HTTP") !== 0 ? err.message : t("js.ha.toast.save_failed"), { kind: "error" });
  });
});
function ignoreDevice(d, btn) {
  btn.disabled = true;
  api("/api/devices/" + encodeURIComponent(d.id) + "?ignore=true", { method: "DELETE" }).then(function () {

    closeMore();
  }).catch(function () {
    btn.disabled = false;
    snack(t("js.ha.toast.ignore_failed"), { kind: "error" });
  });
}

