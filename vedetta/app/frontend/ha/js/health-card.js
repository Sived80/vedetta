import { $, ROOT, api, dlg, esc, fmtClock, icon, t } from "./core.js";
import { healthAction, healthDeviceName, healthName, healthReport, healthRowFacts, healthStrip, healthTiles, healthWhat, healthWhen, healthWorst } from "./health-model.js";
import { gatewayLatencyText, paintTile, setExtraTile } from "./net-rotator.js";
import { openMore } from "./more-info.js";

// ------------------------------------------------------------ network health: the "Health" screen of the Network card
// Dormant: it exists only while the debug mode is on (three taps on the title). The carousel of the card gets one more tile, the only way in: it opens, from its own place, the health screen (four tiles, or a short report when
// all is well); a tile of the four opens, from its own place, the big tile with its findings; a row opens the detail of one finding: who (name and IP), what, when, what to do. The data comes from /api/ha/health, the judge runs on the server in any case.
var HC_POLL_MS = 30000, HC_HIDDEN_KEY = "vedetta-health-hidden";
var HC_LEVEL_ICON = { bad: "alert-circle", warn: "alert", ok: "check-circle" };
var HC_TILE_ICON = { addr: "lan", drop: "access-point", boot: "refresh", lat: "wifi-arrow-up-down" };
var HC_COLOR = { bad: "var(--error-color)", warn: "var(--warning-color)", ok: "var(--success-color)", none: "var(--secondary-text-color)" };
var HC = { findings: [], report: null, running: false, hidden: hcLoadHidden(), stack: null, screen: null, tilesEl: null, detail: null, rot: null, timer: 0, tile: null, page: null, showHidden: false, anim: false, from: null };

function hcLoadHidden() {
  try { const v = JSON.parse(localStorage.getItem(HC_HIDDEN_KEY) || "[]"); return Array.isArray(v) ? v : []; } catch (e) { return []; }
}
function hcSaveHidden() {
  try { localStorage.setItem(HC_HIDDEN_KEY, JSON.stringify(HC.hidden)); } catch (e) { /* storage not available: the choice lasts until the page is closed */ }
}
function hcDebugOn() { return ROOT.hasAttribute("data-debug"); }
function hcModel() { return healthTiles(HC.findings, HC.hidden); }
function hcTile(key) { return hcModel().filter(function (x) { return x.key === key; })[0]; }
function hcFind(tile, id) { return tile.finds.concat(tile.hid).filter(function (f) { return f.id === id; })[0]; }

// ------------------------------------------------------------ the four tiles
function hcStatBox(label, value, color, tinted) {
  return '<div class="stat-box' + (tinted ? " tinted" : "") + '"' + (color ? ' style="--sc:' + color + '"' : "") + '><span class="stat-box-lbl">' + esc(label) + '</span><span class="stat-box-val">' + value + "</span></div>";
}
function hcSecond(tl) {
  if (tl.key !== "lat") return hcStatBox(t("js.ha.health.last"), tl.last ? esc(fmtClock(tl.last)) : "–");
  const ms = gatewayLatencyText();
  return hcStatBox(t("js.ha.health.router"), ms === null ? "–" : esc(ms) + ' <span class="unit">ms</span>');
}
function hcTileHTML(tl) {
  const c = HC_COLOR[healthWorst(tl.finds)];
  return '<button type="button" class="hs-tile" data-key="' + tl.key + '"><div class="t-card" style="--c:' + c + '"><div class="t-head"><span class="t-ic">' + icon(HC_TILE_ICON[tl.key]) + '</span><span class="t-l">' +
    esc(t("js.ha.health.tile." + tl.key)) + '</span></div><div class="t-mid"><div class="stat-grid-2">' + hcStatBox(t("js.ha.health.active"), tl.finds.length, c, tl.finds.length > 0) + hcSecond(tl) + "</div></div></div></button>";
}
// With no finding at all the four tiles would only say zero: the screen is a short report of the network instead.
function hcReportHTML() {
  const r = healthReport(HC.report);
  return '<div class="hs-report"><span class="hs-lv" style="--c:' + HC_COLOR.ok + '">' + icon("check-circle") + "</span><b>" + esc(t("js.ha.health.report.ok")) + "</b><p>" + esc(r.checked) +
    '</p><span class="hs-rep-f">' + esc(r.judged) + '</span><span class="hs-rep-f">' + esc(r.last) + "</span></div>";
}
function hcPaintTiles() {
  const m = hcModel(), quiet = HC.findings.length === 0;
  HC.tilesEl.classList.toggle("quiet", quiet);
  HC.tilesEl.innerHTML = quiet ? hcReportHTML() : m.map(hcTileHTML).join("");
  paintTile(false);                                            // the tile of the carousel says the same in two numbers
}

// ------------------------------------------------------------ the tile of the carousel: the one way in
// All well: "Status: all good" and the time of the last check. Findings: how many and when the last was seen, in the colour of the worst. `attention` changes with the set of shown findings: the carousel goes to the tile then.
function hcCarouselTile() {
  if (!HC.stack) return null;
  const finds = HC.findings.filter(function (f) { return HC.hidden.indexOf(f.id) < 0; }), worst = healthWorst(finds), judged = HC.report && HC.report.judged;
  const c = finds.length || judged ? HC_COLOR[worst] : HC_COLOR.none, last = finds.reduce(function (m, f) { return Math.max(m, f.last); }, 0);
  const one = finds.length ? hcStatBox(t("js.ha.health.card.problems"), finds.length, c, true) : hcStatBox(t("js.ha.health.card.state"), esc(t(judged ? "js.ha.health.card.ok" : "js.ha.health.card.watching")), c, !!judged);
  const two = finds.length ? hcStatBox(t("js.ha.health.last"), esc(fmtClock(last))) : hcStatBox(t("js.ha.health.card.check"), judged ? esc(fmtClock(judged)) : "–");
  return {
    id: "health", tip: t("js.ha.health.card.tip"), open: hcOpenScreen, color: c, attention: finds.map(function (f) { return f.id; }).join("|"),
    html: '<div class="t-card" style="--c:' + c + '"><div class="t-head"><span class="t-ic">' + icon(HC_LEVEL_ICON[worst]) + '</span><span class="t-l">' + esc(t("js.ha.health.title")) +
      '</span></div><div class="t-mid"><div class="stat-grid-2">' + one + two + '</div></div><div class="t-foot"><span class="hs-go">' + esc(t("js.ha.health.card.open")) + icon("chevron-right") + "</span></div></div>",
  };
}

// ------------------------------------------------------------ the big tile: the list of findings and the detail of one
function hcHead(tl, f) {
  if (f) {
    return '<div class="hs-d-head"><button type="button" class="hs-x hs-lx" data-act="back" aria-label="' + esc(t("js.ha.health.back")) + '">' + icon("close") + '</button><span class="t-l hs-ttl">' + esc(healthName(f)) +
      '</span><button type="button" class="hs-x" data-act="hide" data-id="' + esc(f.id) + '" aria-label="' + esc(t("js.ha.health.hide")) + '" title="' + esc(t("js.ha.health.hide")) + '">' + icon("eye-off") + "</button></div>";
  }
  return '<div class="hs-d-head"><button type="button" class="hs-x hs-lx" data-act="close" aria-label="' + esc(t("js.ha.more.close")) + '">' + icon("close") + '</button><span class="t-l hs-ttl">' + esc(t("js.ha.health.tile." + tl.key)) + "</span></div>";
}
function hcRow(f, dim) {
  const who = dim && f.devs.length === 1 ? healthDeviceName(f.devs[0]) : healthRowFacts(f);
  const inner = '<span class="hs-lv" style="--c:' + HC_COLOR[dim ? "none" : f.lv] + '">' + icon(dim ? "eye-off" : HC_LEVEL_ICON[f.lv]) + '</span><span class="hs-rt"><span class="hs-rn">' + esc(healthName(f)) + '</span><span class="hs-rf">' + esc(who) + "</span></span>";
  if (dim) return '<div class="hs-row dim"><div class="hs-row-main">' + inner + '<button type="button" class="hs-btn" data-act="restore" data-id="' + esc(f.id) + '">' + icon("undo") + esc(t("js.ha.health.restore")) + "</button></div></div>";
  return '<div class="hs-row"><button type="button" class="hs-row-main" data-act="page" data-id="' + esc(f.id) + '">' + inner + '<span class="hs-ch">' + icon("chevron-right") + "</span></button></div>";
}
function hcHiddenRow(tl) {
  return '<button type="button" class="hs-hidrow" data-act="showhidden"><span class="hs-lv" style="--c:' + HC_COLOR.none + '">' + icon("eye-off") + "</span><span>" + esc(t("js.ha.health.hidden", { n: tl.hid.length })) +
    '</span><span class="hs-ch" style="transform:rotate(' + (HC.showHidden ? 180 : 0) + 'deg)">' + icon("chevron-down") + "</span></button>";
}
function hcList(tl) {
  let h = tl.finds.length ? tl.finds.map(function (f) { return hcRow(f, false); }).join("") :
    '<div class="hs-empty"><span class="hs-lv" style="--c:' + HC_COLOR.ok + '">' + icon("check-circle") + "</span><b>" + esc(t("js.ha.health.none")) + "</b><span>" + esc(t("js.ha.health.watch")) + "</span></div>";
  if (tl.hid.length) h += hcHiddenRow(tl);
  if (tl.hid.length && HC.showHidden) h += tl.hid.map(function (f) { return hcRow(f, true); }).join("");
  return h;
}

function hcAction(f) {
  return '<div class="hs-act" style="--c:' + HC_COLOR[f.lv] + '">' + icon("lightbulb-on-outline") + "<span>" + esc(healthAction(f)) + "</span></div>";
}
function hcStrip(s, color) {
  const dots = s.pts.map(function (x) { return '<circle cx="' + (6 + x * 288).toFixed(1) + '" cy="6" r="3.5"/>'; }).join("");
  return '<div class="hs-strip"><div class="hs-sl"><b>' + esc(s.l1) + "</b><span>" + esc(s.l2) + '</span></div><svg viewBox="0 0 300 12" width="100%" height="12" preserveAspectRatio="none" aria-hidden="true">' +
    '<line x1="0" y1="6" x2="300" y2="6" stroke="currentColor" stroke-opacity="0.2"/><g fill="' + color + '">' + dots + "</g></svg></div>";
}
function hcOne(f) {
  const d = f.devs[0], strip = healthStrip(f);
  return '<div class="hs-pg"><button type="button" class="hs-nm" data-act="dev" data-i="0"' + (d.id ? "" : " disabled") + "><b>" + esc(healthDeviceName(d)) + "</b><span>" + esc(d.ip || "") + "</span></button>" +
    '<div class="hs-ln">' + esc(healthWhat(f)) + "</div>" + (strip ? hcStrip(strip, HC_COLOR[f.lv]) : "") + '<div class="hs-ln">' + esc(healthWhen(f)) + "</div>" + hcAction(f) + "</div>";
}
function hcMany(f) {
  const list = f.devs.map(function (d, i) {
    return '<button type="button" class="hs-dev" data-act="dev" data-i="' + i + '"' + (d.id ? "" : " disabled") + "><b>" + esc(healthDeviceName(d)) + "</b><span>" + esc(d.ip || "") + '</span><i class="hs-ch">' + icon("chevron-right") + "</i></button>";
  }).join("");
  return '<div class="hs-pg"><div class="hs-devs">' + list + '</div><div class="hs-ln">' + esc(healthWhat(f)) + '</div><div class="hs-ln">' + esc(healthWhen(f)) + "</div>" + hcAction(f) + "</div>";
}
function hcPaintDetail() {
  const tl = hcTile(HC.tile), f = tl && HC.page ? hcFind(tl, HC.page) : null;
  if (!tl) return;
  if (HC.page && !f) HC.page = null;
  const body = f ? (f.devs.length === 1 ? hcOne(f) : hcMany(f)) : hcList(tl);
  HC.detail.innerHTML = hcHead(tl, f) + '<div class="hs-d-body' + (f ? " pgbody" : "") + (HC.anim ? " hs-in" : "") + '">' + body + "</div>";
  HC.anim = false;
}

// ------------------------------------------------------------ opening and closing
function hcAt() { return HC.stack ? HC.stack.getAttribute("data-at") : "0"; }
function hcGo(i) { HC.stack.setAttribute("data-at", String(i)); }
// A pane grows from the place of the small tile: its start is that place, set without a transition.
function hcGrow(pane, tileEl, go) {
  const stack = HC.stack.getBoundingClientRect(), tile = tileEl.getBoundingClientRect();
  pane.style.transition = "none";
  pane.style.setProperty("--t", (tile.top - stack.top) + "px"); pane.style.setProperty("--r", (stack.right - tile.right) + "px");
  pane.style.setProperty("--b", (stack.bottom - tile.bottom) + "px"); pane.style.setProperty("--l", (tile.left - stack.left) + "px");
  void pane.offsetWidth;
  pane.style.transition = "";
  hcGo(go);
  const first = pane.querySelector(".hs-x");
  if (first) first.focus({ preventScroll: true });
}
function hcOpenScreen(rotEl) {
  if (!HC.stack || hcAt() !== "0") return;
  HC.rot = rotEl;
  hcGrow(HC.screen, rotEl, 1);
}
function hcExit() {
  if (hcAt() !== "1") return;
  hcGo(0);
  if (HC.rot && HC.rot.focus) HC.rot.focus({ preventScroll: true });
}
function hcOpen(key, tileEl) {
  HC.tile = key; HC.page = null; HC.showHidden = false;
  hcPaintDetail();
  HC.from = tileEl;
  hcGrow(HC.detail, tileEl, 2);
}
function hcClose() {
  if (hcAt() !== "2") return;
  hcGo(1);
  if (HC.from && HC.from.focus) HC.from.focus({ preventScroll: true });
}
// One step back: from the detail to the list, from the list to the tiles, from the tiles to the carousel.
function hcBack() {
  if (HC.page) { HC.page = null; HC.anim = true; hcPaintDetail(); } else if (hcAt() === "2") hcClose(); else hcExit();
}
function hcHide(id) {
  const tl = hcTile(HC.tile);
  if (!tl || !hcFind(tl, id)) return;
  HC.hidden.push(id); hcSaveHidden(); HC.page = null; HC.anim = true;
  hcPaintTiles(); hcPaintDetail();
}
function hcRestore(id) {
  HC.hidden = HC.hidden.filter(function (x) { return x !== id; }); hcSaveHidden();
  hcPaintTiles(); hcPaintDetail();
}
function hcOnClick(e) {
  const b = e.target.closest("[data-act]");
  if (!b) return;
  const act = b.dataset.act, id = b.dataset.id;
  if (act === "close") hcClose();
  else if (act === "back") hcBack();
  else if (act === "page") { HC.page = id; HC.anim = true; hcPaintDetail(); }
  else if (act === "showhidden") { HC.showHidden = !HC.showHidden; hcPaintDetail(); }
  else if (act === "hide") hcHide(id);
  else if (act === "restore") hcRestore(id);
  else if (act === "dev") hcOpenDevice(+b.dataset.i);
}
function hcOpenDevice(i) {
  const f = hcFind(hcTile(HC.tile), HC.page), d = f && f.devs[i];
  if (d && d.id) openMore(d.id);
}

// ------------------------------------------------------------ the card: the stack of the two screens
// Esc is listened to only while the screens exist: in the normal mode the page has no listener of this feature.
function hcOnKey(e) {
  if (e.key === "Escape" && hcAt() !== "0" && !dlg.open) { e.preventDefault(); hcBack(); }
}
function hcDiv(cls) { const e = document.createElement("div"); e.className = cls; return e; }
function hcBuild() {
  const card = $("card-network"), hero = card && card.querySelector(".hero-row"), search = $("search-row"), badges = $("badges");
  if (!hero || !search || !badges) return;
  const stack = hcDiv("hs-stack"), net = hcDiv("hs-pane net");
  HC.stack = stack; HC.screen = hcDiv("hs-pane health"); HC.tilesEl = hcDiv("hs-tiles"); HC.detail = hcDiv("hs-pane detail");
  stack.setAttribute("data-at", "0");
  HC.screen.setAttribute("role", "region"); HC.screen.setAttribute("aria-label", t("js.ha.health.title"));
  HC.screen.innerHTML = '<div class="hs-d-head"><button type="button" class="hs-x hs-lx" data-act="exit" aria-label="' + esc(t("js.ha.more.close")) + '">' + icon("close") + '</button><span class="t-l hs-ttl">' + esc(t("js.ha.health.title")) + "</span></div>";
  HC.screen.appendChild(HC.tilesEl);
  HC.detail.setAttribute("role", "region"); HC.detail.setAttribute("aria-label", t("js.ha.health.detail"));
  hero.parentNode.insertBefore(stack, hero);
  net.appendChild(search); net.appendChild(hero); net.appendChild(badges);
  stack.appendChild(net); stack.appendChild(HC.screen); stack.appendChild(HC.detail);
  HC.screen.addEventListener("click", function (e) { if (e.target.closest("[data-act='exit']")) hcExit(); });
  HC.tilesEl.addEventListener("click", function (e) { const tl = e.target.closest(".hs-tile"); if (tl) hcOpen(tl.dataset.key, tl); });
  HC.detail.addEventListener("click", hcOnClick);
  document.addEventListener("keydown", hcOnKey);
  setExtraTile(hcCarouselTile);
  hcPaintTiles();
}
// The three parts of the network screen go back where they were and the screens are taken away, the tile leaves the carousel.
function hcRemove() {
  if (!HC.stack) return;
  document.removeEventListener("keydown", hcOnKey);
  const parent = HC.stack.parentNode, net = HC.stack.querySelector(".hs-pane.net");
  if (parent && net) Array.prototype.slice.call(net.children).forEach(function (n) { parent.insertBefore(n, HC.stack); });
  HC.stack.remove();
  HC.stack = HC.screen = HC.tilesEl = HC.detail = HC.rot = null;
  setExtraTile(null);
  paintTile(false);
}
function hcRepaint() {
  if (!HC.stack) return;
  hcPaintTiles();
  if (hcAt() === "2") hcPaintDetail();
}
function hcRefresh() {
  if (!hcDebugOn()) return;
  api("/api/ha/health").then(function (x) {
    HC.running = !!(x && x.running); HC.findings = (x && x.findings) || []; HC.report = (x && x.report) || null;
    if (!HC.running) { hcRemove(); return; }
    if (!HC.stack) hcBuild();
    hcRepaint();
  }).catch(function () { /* the next round asks again */ });
}

// Called after the card is built and when the debug mode is turned on or off.
export function mountHealth() {
  if (HC.stack && !document.contains(HC.stack)) HC.stack = HC.screen = HC.tilesEl = HC.detail = HC.rot = null;        // the card was rebuilt: the old screens went with it
  if (!hcDebugOn()) { hcRemove(); clearInterval(HC.timer); HC.timer = 0; return; }
  if (HC.running && !HC.stack) hcBuild();
  hcRefresh();
  if (!HC.timer) HC.timer = setInterval(function () { if (!document.hidden) hcRefresh(); }, HC_POLL_MS);
}
