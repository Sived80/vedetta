import { $, api, esc, fmtClock, icon, t } from "./core.js";
import { raiseSnacks, snack, snacksEl } from "./core-ui.js";

// ------------------------------------------------- alerts outside this page (the Sentinel's way out)
// The events on the bus of Home Assistant (on/off) and the table of the recipients, in the style of Networks: one row for every notify
// service Home Assistant has; the switch puts a recipient in line (1st, 2nd, 3rd...), the arrows move it, the wait is the time after
// the one before (the message goes on whether the one before took it or not), «Try» sends to that one only, and the last answer
// of each one is shown. «Send a test» sends the test event and a test message to the whole line. Saves on every change.
var alDlg = $("alertsdlg");
var AL_DELAYS = [0, 30, 60, 120, 300, 600];
var al = { cfg: { ha_events: false, notify_order: [] }, services: [], last: {}, waiting: 0, test: null, busy: false, trying: {} };
function closeAlerts() {
  alCloseMenu();
  if (alDlg.open && typeof alDlg.close === "function") alDlg.close(); else alDlg.removeAttribute("open");
}
function alReadStatus(r) {
  al.services = (r && r.services) || [];
  al.last = (r && r.last) || {};
  al.waiting = (r && r.waiting) || 0;
}
export function openAlerts() {
  al.test = null;
  Promise.all([api("/api/sentinel"), api("/api/sentinel/services").catch(function () { return { services: [] }; })]).then(function (r) {
    al.cfg = r[0]; alReadStatus(r[1]);
    renderAlerts();
    if (!alDlg.open) {
      if (typeof alDlg.showModal === "function") alDlg.showModal(); else alDlg.setAttribute("open", "");
      if (snacksEl.children.length) raiseSnacks();
    }
  }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); });
}
function alOrder() { return al.cfg.notify_order || []; }
function alPlace(svc) { return alOrder().findIndex(function (r) { return r.service === svc; }); }
// The rows: the recipients in line first (in their order), then the other services of Home Assistant by name. A recipient that
// Home Assistant no longer has stays in its place, marked, so that it can be taken out.
function alRows() {
  const inLine = alOrder().map(function (r) { return r.service; });
  return inLine.concat(al.services.filter(function (s) { return inLine.indexOf(s) < 0; }).sort());
}
function alDelayLabel(s) {
  if (!s) return t("js.ha.alerts.at_once");
  return s < 60 ? t("js.ha.alerts.sec", { n: s }) : t("js.ha.alerts.min", { n: s / 60 });
}
function alDelayCell(svc, n) {
  if (n < 0) return '<span class="al-muted">—</span>';
  if (n === 0) return '<span class="al-muted">' + esc(t("js.ha.alerts.first")) + "</span>";
  // the choice opens the menu of the app (like the type of a device), not the list of the browser
  const cur = alOrder()[n].delay_s;
  return '<button type="button" class="al-dd" data-al-dd="' + esc(svc) + '" aria-haspopup="menu" aria-expanded="false" aria-label="' + esc(t("js.ha.alerts.col_delay") + " " + svc) + '"><span>' +
    esc(t("js.ha.alerts.after", { wait: alDelayLabel(cur) })) + "</span>" + icon("chevron-down") + "</button>";
}
// The menu of the waits: fixed under its button, closed by a touch outside, Esc or a scroll of the page.
var alMenu = null;
function alCloseMenu() {
  if (!alMenu) return;
  alMenu.remove(); alMenu = null;
  const b = alDlg.querySelector('[data-al-dd][aria-expanded="true"]');
  if (b) b.setAttribute("aria-expanded", "false");
}
function alOpenMenu(btn) {
  const svc = btn.getAttribute("data-al-dd"), was = alMenu && alMenu.dataset.svc === svc;
  alCloseMenu();
  if (was) return;
  const cur = (alOrder()[alPlace(svc)] || {}).delay_s;
  const m = document.createElement("div");
  m.className = "menu al-menu"; m.setAttribute("role", "menu"); m.dataset.svc = svc;
  m.innerHTML = AL_DELAYS.map(function (d) {
    return '<button type="button" class="menu-item rp" role="menuitemradio" data-al-wait="' + d + '" aria-checked="' + (d === cur) + '"><span>' +
      esc(t("js.ha.alerts.after", { wait: alDelayLabel(d) })) + '</span><span class="mi-check">' + (d === cur ? icon("check") : "") + "</span></button>";
  }).join("");
  const r = btn.getBoundingClientRect(), vw = document.documentElement.clientWidth || window.innerWidth;
  // under the button, as wide as it: the column stays the column; on a phone the button may sit at the edge of the scrolled table, the menu
  // never leaves the screen (19/11 review), and opens above the button when there is no room below
  m.style.width = Math.round(r.width) + "px";
  m.style.left = Math.round(Math.max(8, Math.min(r.left, vw - r.width - 8))) + "px";
  m.style.top = Math.round(r.bottom + 4) + "px";
  alDlg.appendChild(m);
  const h = m.offsetHeight, vh = window.innerHeight;
  if (h && r.bottom + 4 + h > vh - 8 && r.top - 4 - h >= 8) m.style.top = Math.round(r.top - 4 - h) + "px";
  alMenu = m;
  btn.setAttribute("aria-expanded", "true");
  const on = m.querySelector('[aria-checked="true"]') || m.querySelector(".menu-item");
  if (on && on.focus) on.focus();
}
function alPickWait(el) {
  const svc = alMenu.dataset.svc, s = parseInt(el.getAttribute("data-al-wait"), 10);
  alPending = { name: "data-al-dd", value: svc };          // the menu item goes with the menu: the focus comes back to the button that opened it
  alCloseMenu();
  alSaveOrder(alOrder().map(function (r) { return r.service === svc ? { service: svc, delay_s: s } : r; }));
}
function alLastCell(svc) {
  const l = al.last[svc];
  if (al.trying[svc]) return '<span class="al-muted">' + esc(t("js.ha.alerts.sending")) + "</span>";
  if (!l) return '<span class="al-muted">—</span>';
  const when = fmtClock(l.at);
  return l.ok ? '<span class="al-last ok">' + icon("check-circle") + "<span>" + esc(when) + "</span></span>"
    : '<span class="al-last fail" title="' + esc(l.error || "") + '">' + icon("alert-circle") + "<span>" + esc(when) + "</span></span>";
}
function alMoveBtns(svc, n) {
  if (n < 0) return '<span class="al-ph"></span><span class="al-ph"></span>';      // the place of the arrows: «Try» stays in the same column on every row
  const up = t("js.ha.alerts.up"), down = t("js.ha.alerts.down");
  return '<button type="button" class="icon-btn small rp al-ib" data-al-up="' + esc(svc) + '"' + (n === 0 ? " disabled" : "") + ' title="' + esc(up) + '" aria-label="' + esc(up + " " + svc) + '">' + icon("chevron-up") + "</button>" +
    '<button type="button" class="icon-btn small rp al-ib" data-al-down="' + esc(svc) + '"' + (n === alOrder().length - 1 ? " disabled" : "") + ' title="' + esc(down) + '" aria-label="' + esc(down + " " + svc) + '">' + icon("chevron-down") + "</button>";
}
function alRow(svc) {
  const n = alPlace(svc), gone = al.services.indexOf(svc) < 0, on = n >= 0, tryTip = t("js.ha.alerts.try");
  return '<div role="row" class="al-gr al-rw' + (on ? " on" : "") + '" data-svc="' + esc(svc) + '">' +
    '<div role="cell"><span class="al-num' + (on ? " on" : "") + '">' + (on ? n + 1 : "—") + "</span></div>" +
    '<div role="cell" class="al-who"><b>' + esc(svc.replace(/^notify\./, "")) + "</b>" + (gone ? '<span class="al-gone">' + esc(t("js.ha.alerts.gone")) + "</span>" : "") + "</div>" +
    '<div role="cell">' + alDelayCell(svc, n) + '</div><div role="cell" class="al-c-last">' + alLastCell(svc) + "</div>" +
    '<div role="cell" class="al-acts">' + alMoveBtns(svc, n) + '<button type="button" class="icon-btn small rp al-ib" data-al-try="' + esc(svc) + '"' + (al.trying[svc] ? " disabled" : "") +
    ' title="' + esc(tryTip) + '" aria-label="' + esc(tryTip + " " + svc) + '">' + icon("send") + "</button></div>" +
    '<div role="cell"><button type="button" class="rv-switch' + (on ? " on" : "") + '" role="switch" aria-checked="' + on + '" data-al-on="' + esc(svc) + '" aria-label="' +
    esc(t("js.ha.alerts.col_on") + " " + svc) + '"></button></div></div>';
}
function alTable() {
  const list = alRows();
  if (!list.length) return '<div class="al-empty">' + esc(t("js.ha.alerts.no_services")) + "</div>";
  const cols = ["col_n", "col_who", "col_delay", "col_last", "col_try", "col_on"];
  const head = '<div role="row" class="al-gr al-hd">' + cols.map(function (c) { return '<div role="columnheader"' + (c === "col_last" ? ' class="al-c-last"' : "") + ">" + esc(t("js.ha.alerts." + c)) + "</div>"; }).join("") + "</div>";
  return '<div class="al-tab"><div class="al-tw"><div class="al-grid" role="table" aria-label="' + esc(t("js.ha.alerts.notify")) + '">' + head + list.map(alRow).join("") + "</div></div></div>";
}
function testLine() {
  if (!al.test) return al.waiting ? '<div class="al-result">' + icon("clock-outline") + "<span>" + esc(t("js.ha.alerts.waiting", { n: al.waiting })) + "</span></div>" : "";
  const queued = al.test.queued ? " " + t("js.ha.alerts.queued", { n: al.test.queued }) : "";
  if (al.test.ok) return '<div class="al-result ok">' + icon("check-circle") + "<span>" + esc(t("js.ha.alerts.test_ok") + queued) + "</span></div>";
  // the request never arrived: a whole sentence; a refusal says what Home Assistant answered, closed by a full stop before the queue line (19/11)
  const fail = al.test.down ? t("js.ha.alerts.test_noanswer") : t("js.ha.alerts.test_fail", { error: al.test.error || "" }).replace(/([^.!?])\s*$/, "$1.");
  const msg = al.test.error === "no_home_assistant" ? t("js.ha.alerts.test_noha") : fail + queued;
  return '<div class="al-result fail">' + icon("alert-circle") + "<span>" + esc(msg) + "</span></div>";
}
// A page like Networks: the bar on top (the X first on the left, the title, «Send a test» on the right), then the boxes; only the page
// scrolls, the page behind stays still.
// The whole page is drawn again after each action: the focus goes back to the same control (by its data-al-* attribute). An arrow that is now
// disabled (the end of the line) hands it to the other arrow of its row; any other control that is disabled for a moment («Try», «Send a test»)
// is waited for: the page holds the focus (Enter does nothing there) until the control comes back (18/11 review: keyboard users lost their place,
// or a second Enter moved a recipient).
var alPending = null;
function alFocusKey(el) {
  if (!el || !alDlg.contains(el)) return null;
  const a = Array.prototype.find.call(el.attributes, function (x) { return x.name.indexOf("data-al") === 0; });
  return a ? { name: a.name, value: a.value } : null;
}
function alRefocus(key) {
  if (!key) return;
  const sel = function (name) { return alDlg.querySelector("[" + name + '="' + (window.CSS && CSS.escape ? CSS.escape(key.value) : key.value) + '"]'); };
  const arrow = key.name === "data-al-up" || key.name === "data-al-down";
  const el = [sel(key.name), arrow ? sel(key.name === "data-al-up" ? "data-al-down" : "data-al-up") : null].filter(function (x) { return x && !x.disabled; })[0];
  alPending = el || arrow ? null : key;
  if (el) { el.focus({ preventScroll: true }); return; }
  if (!alDlg.hasAttribute("tabindex")) alDlg.setAttribute("tabindex", "-1");
  alDlg.focus({ preventScroll: true });
}
function renderAlerts() {
  const top = alDlg.scrollTop, focus = alFocusKey(document.activeElement) || alPending;
  alMenu = null;                                                                   // the drawing below takes the menu away
  alDlg.innerHTML = '<div class="al-top"><button type="button" class="al-x" data-al="close" title="' + esc(t("js.ha.more.close")) + '" aria-label="' + esc(t("js.ha.more.close")) + '">' +
    icon("close") + '</button><h2 id="alertsdlg-title">' + esc(t("js.ha.alerts.title")) + '</h2><span class="al-grow"></span>' +
    '<button type="button" class="al-btn" data-al="test"' + (al.busy || !alOrder().length ? " disabled" : "") + ">" + icon("bell-ring") + "<span>" + esc(t("js.ha.alerts.test")) + "</span></button></div>" +
    '<div class="al-wrap">' +
    '<section class="al-card al-row"><div class="al-txt"><div class="al-lbl">' + esc(t("js.ha.alerts.events")) + '</div><div class="al-hint">' + esc(t("js.ha.alerts.events_hint")) +
    '</div></div><button type="button" class="rv-switch' + (al.cfg.ha_events ? " on" : "") + '" data-al="events" role="switch" aria-checked="' + !!al.cfg.ha_events +
    '" aria-label="' + esc(t("js.ha.alerts.events")) + '"></button></section>' +
    '<section class="al-card al-sec"><h3 class="al-what">' + esc(t("js.ha.alerts.notify")) + '</h3><p class="al-hint">' + esc(t("js.ha.alerts.order_hint")) + "</p>" + testLine() + alTable() + "</section>" +
    '<p class="al-hint al-watch">' + icon("bell-outline") + "<span>" + esc(t("js.ha.alerts.watch_hint")) + "</span></p></div>";
  alDlg.scrollTop = top;
  alRefocus(focus);
}
// The saves go one after the other (19/11 review: two switches touched quickly could cross, and the older answer undo the newer touch):
// the page shows each touch at once, takes the server's answer only when nothing else is waiting, and after a refusal reads it again.
let alSaveQueue = Promise.resolve(), alSaving = 0;
function save(changes) {
  Object.assign(al.cfg, changes); al.test = null; renderAlerts();
  alSaving++;
  alSaveQueue = alSaveQueue.then(function () {
    return api("/api/sentinel", { method: "POST", json: changes }).then(function (r) {
      if (--alSaving === 0) { al.cfg = r; renderAlerts(); }
    }, function () {
      alSaving--;
      snack(t("js.ha.toast.error"), { kind: "error" });
      if (alSaving === 0) return api("/api/sentinel").then(function (r) { al.cfg = r; renderAlerts(); }, function () {});
    });
  });
}
function alSaveOrder(list) { save({ notify_order: list }); }
function alToggle(svc) {
  const list = alOrder().slice(), n = alPlace(svc);
  if (n >= 0) list.splice(n, 1); else list.push({ service: svc, delay_s: 0 });
  if (list.length) list[0] = { service: list[0].service, delay_s: 0 };            // the first never waits
  alSaveOrder(list);
}
function alMove(svc, by) {
  const list = alOrder().slice(), n = alPlace(svc), m = n + by;
  if (n < 0 || m < 0 || m >= list.length) return;
  const a = list[n]; list[n] = list[m]; list[m] = a;
  list[0] = { service: list[0].service, delay_s: 0 };
  alSaveOrder(list);
}
function alTryOne(svc) {
  al.trying[svc] = true; renderAlerts();
  api("/api/sentinel/test", { method: "POST", json: { service: svc } })
    .then(function (r) { al.last[svc] = { at: Date.now() / 1000, ok: !!r.ok, error: r.ok ? "" : (r.error === "no_home_assistant" ? t("js.ha.alerts.test_noha") : r.error) }; })
    .catch(function () { al.last[svc] = { at: Date.now() / 1000, ok: false, error: "" }; })
    .then(function () { delete al.trying[svc]; renderAlerts(); });
}
// any scroll closes the menu (the page, or the table sideways on a phone: the menu would float away from its button), but not one inside the menu
alDlg.addEventListener("scroll", function (e) { if (alMenu && !alMenu.contains(e.target)) alCloseMenu(); }, true);
alDlg.addEventListener("close", function () { alPending = null; });
alDlg.addEventListener("cancel", function (e) { if (alMenu) { e.preventDefault(); alCloseMenu(); } });       // Esc closes the menu first, then the page
alDlg.addEventListener("click", function (e) {
  const wait = e.target.closest("[data-al-wait]");
  if (wait && alMenu) return alPickWait(wait);
  const dd = e.target.closest("[data-al-dd]");
  if (dd) return alOpenMenu(dd);
  if (alMenu && !e.target.closest(".al-menu")) alCloseMenu();
  if (e.target.closest('[data-al="close"]')) return closeAlerts();
  if (e.target.closest('[data-al="events"]')) return save({ ha_events: !al.cfg.ha_events });
  const b = e.target.closest("[data-al-on], [data-al-up], [data-al-down], [data-al-try]");
  if (b && !b.disabled) {
    if (b.hasAttribute("data-al-on")) return alToggle(b.getAttribute("data-al-on"));
    if (b.hasAttribute("data-al-up")) return alMove(b.getAttribute("data-al-up"), -1);
    if (b.hasAttribute("data-al-down")) return alMove(b.getAttribute("data-al-down"), 1);
    return alTryOne(b.getAttribute("data-al-try"));
  }
  if (e.target.closest('[data-al="test"]') && !al.busy) {
    al.busy = true; al.test = null; renderAlerts();
    api("/api/sentinel/test", { method: "POST", json: {} }).then(function (r) { al.test = r; })
      .catch(function () { al.test = { ok: false, error: "", down: true }; })
      .then(function () { al.busy = false; renderAlerts(); });
  }
});
