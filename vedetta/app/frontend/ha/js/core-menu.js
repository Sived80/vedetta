import { $, LANG, LANG_KEY, ROOT, api, esc, goLang, icon, t } from "./core.js";
import { S } from "./core-ui.js";
import { openExport } from "./export.js";
import { deepMenuEl, toggleDeepMenu } from "./deep.js";
import { pauseEl, togglePause } from "./network.js";
import { openIgnored } from "./ignored.js";
import { openFlows } from "./flows.js";
import { logMenuEl, toggleLogMenu } from "./log.js";

// ----------------------------------------------------------------- guided typing
// Fields that ask for an address help the typing: in a MAC the colons appear by themselves (and the letters become capitals); in an IP address
// the right arrow at the end of the number writes the dot (192.16 -> .1 -> .12 = 192.16.1.12). The colon or the dot typed by hand always works.
// kind: "mac" or "ip"; any other kind (a name) is left alone. Usable by any field.
function guidedFormat(kind, raw) {
  if (kind === "mac") return raw.replace(/[^0-9a-fA-F]/g, "").toUpperCase().slice(0, 12).replace(/(..)(?=.)/g, "$1:");
  const v = raw.replace(/[^0-9.]/g, "").replace(/\.{2,}/g, "."), parts = v.split(".").slice(0, 4).map(function (x) { return x.slice(0, 3); });
  return parts.join(".").replace(/^\./, "");
}
export function guidedInput(field, kind) {
  if (kind !== "mac" && kind !== "ip") return;
  const pos = field.selectionStart, before = field.value.slice(0, pos), atEnd = pos === field.value.length, out = guidedFormat(kind, field.value);
  if (out === field.value) return;
  const keep = kind === "mac" ? /[0-9A-F]/ : /[0-9]/, count = before.replace(kind === "mac" ? /[^0-9a-fA-F]/g : /[^0-9]/g, "").length;
  field.value = out;
  let np = out.length;
  if (!atEnd) { var c = 0; np = 0; while (np < out.length && c < count) { if (keep.test(out[np])) c++; np++; } }
  field.setSelectionRange(np, np);
}
// true if the key was used (the right arrow wrote a dot)
export function guidedKey(e, field, kind) {
  if (kind !== "ip" || e.key !== "ArrowRight" || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) return false;
  const v = field.value;
  if (field.selectionStart !== v.length || field.selectionEnd !== v.length || !/[0-9]$/.test(v) || v.split(".").length >= 4) return false;
  e.preventDefault();
  field.value = v + ".";
  return true;
}

// ----------------------------------------------------------------- menu
export var menuEl = $("menu"), menuBtn = $("btn-menu");
// Button menu: each setting is a group with a title and a row of round
// buttons (large for language and theme, small for numeric values).
export function menuGroup(label, buttons) {
  return '<div class="menu-group"><div class="menu-label">' + esc(label) + '</div><div class="menu-pills">' + buttons + "</div></div>";
}
export function pill(size, attr, value, on, text, title) {
  return '<button type="button" class="menu-item pill ' + size + ' rp" data-' + attr + '="' + esc(value) + '" aria-pressed="' + on +
    '"' + (title ? ' title="' + esc(title) + '" aria-label="' + esc(title) + '"' : "") + ">" + esc(text) + "</button>";
}
// "Responsiveness": a single choice for the user; the combination of check
// interval and offline threshold is decided here (values accepted by the server).
var SPEEDS = [
  { id: "fast", poll: 10, miss: 2 },
  { id: "normal", poll: 30, miss: 3 },
  { id: "saver", poll: 60, miss: 5 }
];
export function span(secs) { return secs < 120 ? secs + " s" : Math.round(secs / 60) + " min"; }
function everyLabel(secs) { return secs < 60 ? secs + " s" : Math.round(secs / 60) + " min"; }      // how often: 10 s, 30 s, 1 min
// The one-time invitation to star the project: a small star on the menu button, and, the first time the menu is opened, its first
// entry (a link to GitHub). The server remembers that it was shown, so it never comes back (storage/starhint.py).
var STAR_URL = "https://github.com/Sived80/vedetta/tree/main#readme";       // an address nobody else links to: the visits to it in the repository statistics are the clicks from here (the app sends nothing)
var REPO_URL = "https://github.com/Sived80/vedetta";       // the plain address of the project: the link at the foot of the menu (the star entry above has its own, to count its clicks)
var starBadge = document.createElement("span");
starBadge.className = "star-badge";
starBadge.hidden = true;
starBadge.setAttribute("aria-hidden", "true");
starBadge.innerHTML = icon("star");
menuBtn.parentNode.appendChild(starBadge);
export function setStarBadge() { starBadge.hidden = !S.starHint; }
function starEntry() {
  if (!S.starMenu) return "";
  return '<a class="menu-item menu-link star-entry rp" href="' + STAR_URL + '" target="_blank" rel="noopener noreferrer" data-star="1"><span class="star-text">' +
    esc(t("js.ha.menu.star")) + "<small>" + esc(t("js.ha.menu.star_sub")) + "</small></span>" + icon("star") + "</a>";
}
// ---------------------------------------------------------- themed select
// A selection list in the look of the app (the native one opens with the colours of the system). Used for the language, which
// will grow as languages are added: one row in the menu whatever their number, a list that scrolls beyond 60% of the screen.
// themedSelect(button, options, current, onPick): options = [[value, label], ...]; the list is drawn under the button (above, if it does
// not fit), closes on a pick, Escape, Tab, a click outside, a scroll or a resize, and works with the keyboard (arrows, Home, End,
// Enter, Space, first letter).
var selEl = null, selBtn = null;
function closeSelect(refocus) {
  if (!selEl) return;
  const b = selBtn;
  selEl.parentNode.removeChild(selEl); selEl = null; selBtn = null;
  if (b) { b.setAttribute("aria-expanded", "false"); if (refocus) b.focus(); }
}
function themedSelect(btn, options, current, onPick) {
  closeSelect(false);
  let list = document.createElement("ul"), idx = Math.max(0, options.map(function (o) { return o[0]; }).indexOf(current));
  list.className = "sel-list"; list.setAttribute("role", "listbox"); list.tabIndex = -1; list.setAttribute("aria-label", btn.getAttribute("aria-label") || "");
  list.innerHTML = options.map(function (o) {
    return '<li class="sel-li" role="option" data-v="' + esc(o[0]) + '" aria-selected="' + (o[0] === current) + '"><span>' + esc(o[1]) + "</span>" + icon("check") + "</li>";
  }).join("");
  document.body.appendChild(list);
  selEl = list; selBtn = btn; btn.setAttribute("aria-expanded", "true");
  let r = btn.getBoundingClientRect(), h;
  list.style.left = Math.round(r.left) + "px"; list.style.width = Math.round(r.width) + "px"; list.style.top = Math.round(r.bottom + 4) + "px";
  h = list.offsetHeight;
  if (r.bottom + 4 + h > window.innerHeight - 8) list.style.top = Math.max(8, Math.round(r.top - h - 4)) + "px";
  function mark() {
    [].forEach.call(list.children, function (li, i) { li.classList.toggle("act", i === idx); });
    if (list.children[idx] && list.children[idx].scrollIntoView) list.children[idx].scrollIntoView({ block: "nearest" });
  }
  function pick(v) { closeSelect(true); onPick(v); }
  mark(); list.focus();
  list.addEventListener("click", function (e) { e.stopPropagation(); const li = e.target.closest(".sel-li"); if (li) pick(li.getAttribute("data-v")); });
  list.addEventListener("mousemove", function (e) { const li = e.target.closest(".sel-li"); if (li) { idx = [].indexOf.call(list.children, li); mark(); } });
  list.addEventListener("keydown", function (e) {
    const n = options.length;
    if (e.key === "ArrowDown") { e.preventDefault(); idx = (idx + 1) % n; mark(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); idx = (idx - 1 + n) % n; mark(); }
    else if (e.key === "Home") { e.preventDefault(); idx = 0; mark(); }
    else if (e.key === "End") { e.preventDefault(); idx = n - 1; mark(); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(options[idx][0]); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeSelect(true); }
    else if (e.key === "Tab") { closeSelect(false); }
    else if (e.key.length === 1) {
      var k = e.key.toLowerCase(), j = -1, i;
      for (i = idx + 1; i < n && j < 0; i++) if (options[i][1].toLowerCase().indexOf(k) === 0) j = i;
      for (i = 0; i <= idx && j < 0; i++) if (options[i][1].toLowerCase().indexOf(k) === 0) j = i;
      if (j >= 0) { idx = j; mark(); }
    }
  });
}
document.addEventListener("pointerdown", function (e) { if (selEl && !selEl.contains(e.target) && !(selBtn && selBtn.contains(e.target))) closeSelect(false); }, true);
window.addEventListener("resize", function () { closeSelect(false); });

// The language: one choice among those the server offers (window.VEDETTA_LANGS = [[code, name in its own language], ...]).
function langName(code) {
  const hit = (window.VEDETTA_LANGS || []).find(function (l) { return l[0] === code; });
  return hit ? hit[1] : code;
}
function pickLang(code) {
  const auto = code === "auto";
  if (auto ? window.VEDETTA_LANG_AUTO : (code === LANG && !window.VEDETTA_LANG_AUTO)) return;
  try { if (auto) localStorage.removeItem(LANG_KEY); else localStorage.setItem(LANG_KEY, code); } catch (err) { /* ignore */ }
  api("/api/lang/" + encodeURIComponent(code), { method: "POST" }).catch(function () {}).then(function () { goLang(auto ? "" : code); });
}
function langGroup() {
  return '<div class="menu-group"><div class="menu-label">' + esc(t("js.ha.menu.language")) + '</div><button type="button" class="sel-btn rp" id="lang-btn" aria-haspopup="listbox" aria-expanded="false" aria-label="' +
    esc(t("js.ha.menu.language")) + '">' + icon("earth", "sel-ic") + '<span class="sel-val">' +
    esc((window.VEDETTA_LANG_AUTO ? t("js.ha.menu.lang_auto") + " · " : "") + langName(LANG)) + "</span>" + icon("chevron-down", "sel-chev") + "</button></div>";
}

function buildMenu() {
  let html = starEntry() + langGroup();
  const theme = ROOT.getAttribute("data-theme") || "auto";
  html += menuGroup(t("js.ha.menu.theme"), ["auto", "light", "dark"].map(function (v) {
    return pill("md", "theme", v, v === theme, t("js.ha.menu.theme_" + v));
  }).join(""));
  const view = ROOT.getAttribute("data-view") === "list" ? "list" : "tiles";
  html += menuGroup(t("js.ha.menu.view"), ["tiles", "list"].map(function (v) {
    return pill("md", "view", v, v === view, t("js.ha.menu.view_" + v));
  }).join(""));
  const pollNow = Math.round((S.poll.interval || 30000) / 1000);
  // The chosen speed is the one that matches what the server runs; right after a choice the server has not told the new
  // interval yet, so the choice made here stands in until it does (otherwise no button would look chosen).
  const cur = SPEEDS.filter(function (s) { return s.poll === pollNow && s.miss === S.missLimit; })[0] ||
    SPEEDS.filter(function (s) { return s.id === S.speedId; })[0] || null;
  const pills = SPEEDS.map(function (s) {
    return '<button type="button" class="menu-item pill md speed rp" data-speed="' + s.id + '" aria-pressed="' + (s === cur) + '">' +
      '<span class="pill-main">' + esc(t("js.ha.menu.speed_" + s.id)) + '</span><span class="pill-sub">' + esc(everyLabel(s.poll)) + "</span></button>";
  }).join("");
  const secs = cur ? cur.poll * cur.miss : pollNow * S.missLimit;
  html += menuGroup(t("js.ha.menu.speed"), pills) +
    '<div class="menu-hint">' + esc(t("js.ha.menu.speed_hint", { t: span(secs) })) + "</div>";
  html += '<button type="button" class="menu-item menu-link rp" data-flows="1">' + esc(t("js.ha.menu.flows")) + icon("cog") + "</button>";
  html += '<button type="button" class="menu-item menu-link next rp" data-ignored="1">' + esc(t("js.ha.menu.ignored")) + icon("eye-off") + "</button>";
  // Export for analysis: almost invisible on purpose (small, faded icon).
  html += '<button type="button" class="menu-item menu-link menu-export next rp" data-export="1">' + esc(t("js.ha.export.title")) + icon("download") + "</button>";
  // The foot of the menu: the repository (the running version is in the title of the Network card).
  html += '<a class="menu-repo rp" href="' + REPO_URL + '" target="_blank" rel="noopener noreferrer" aria-label="' + esc(t("js.ha.menu.repo")) + '"><span>github.com/Sived80/vedetta</span>' + icon("open-in-new") + "</a>";
  menuEl.innerHTML = html;
}
function toggleMenu(open) {
  if (open === undefined) open = menuEl.hidden;
  if (!open) closeSelect(false);
  if (!open && S.starMenu) { S.starMenu = false; S.starHint = false; setStarBadge(); }       // it has been seen: the star goes away
  if (open) {
    closePopups("menu");
    if (S.starHint && !S.starMenu) {
      S.starMenu = true;
      api("/api/ha/star", { method: "POST" }).catch(function () { /* the next summary says again if it was not saved */ });
    }
    buildMenu();
    // The menu sits inside a card that clips whatever goes past its edges: it is
    // positioned relative to the window, below the button, with a maximum height.
    var r = menuBtn.getBoundingClientRect();
    menuEl.style.top = Math.round(r.bottom + 4) + "px";
    menuEl.style.right = Math.max(8, Math.round(window.innerWidth - r.right)) + "px";
    menuEl.style.maxHeight = Math.max(160, window.innerHeight - r.bottom - 16) + "px";
  }
  menuEl.hidden = !open;
  menuBtn.setAttribute("aria-expanded", String(open));
  if (open) {
    var first = menuEl.querySelector(".menu-item");
    if (first) first.focus();
  }
}
menuBtn.addEventListener("click", function (e) { e.stopPropagation(); toggleMenu(); });
menuEl.addEventListener("click", function (e) {
  const star = e.target.closest("[data-star]");
  if (star) {
    star.style.display = "none";                                  // gone at once; the link still opens (the browser follows it)
    setTimeout(function () { toggleMenu(false); }, 0);
    return;
  }
  const sb = e.target.closest("#lang-btn");
  if (sb) {
    if (selBtn === sb) { closeSelect(false); return; }
    themedSelect(sb, [["auto", t("js.ha.menu.lang_auto")]].concat((window.VEDETTA_LANGS || []).map(function (l) { return [l[0], l[1]]; })),
      window.VEDETTA_LANG_AUTO ? "auto" : LANG, pickLang);
    return;
  }
  if (e.target.closest("[data-export]")) { toggleMenu(false); openExport(); return; }
  const item = e.target.closest(".menu-item");
  if (!item) return;
  if (item.dataset.theme) {
    ROOT.setAttribute("data-theme", item.dataset.theme);
    try { localStorage.setItem("vedetta-ha-theme", item.dataset.theme); } catch (err) { /* ignore */ }
    toggleMenu(false);
  } else if (item.dataset.view) {
    // Same elements, different layout (CSS): updates, filters and windows do not change.
    if (item.dataset.view === "list") ROOT.setAttribute("data-view", "list"); else ROOT.removeAttribute("data-view");
    try { localStorage.setItem("vedetta-ha-view", item.dataset.view); } catch (err) { /* ignore */ }
    toggleMenu(false);
  } else if (item.dataset.ignored) {
    toggleMenu(false);
    openIgnored();
  } else if (item.dataset.flows) {
    toggleMenu(false);
    openFlows();
  } else if (item.dataset.speed) {
    var sp = SPEEDS.filter(function (s) { return s.id === item.dataset.speed; })[0];
    if (sp) {
      S.missLimit = sp.miss;
      S.speedId = sp.id;
      api("/api/settings", { method: "POST", json: { poll_interval: sp.poll, miss_limit: sp.miss } }).catch(function () {});
    }
    buildMenu();      // the menu stays open: the chosen button lights up at once and the line under it (when a device is called offline) can be read
  } else {
    toggleMenu(false);
  }
});
document.addEventListener("click", function (e) {
  // A click inside the menu that redraws it leaves its target outside the page: the path recorded at the click says where it was.
  const inside = (e.composedPath ? e.composedPath() : []).some(function (n) { return n === menuEl || (n.classList && n.classList.contains("menu-wrap")); });
  if (!menuEl.hidden && !inside && !e.target.closest(".menu-wrap") && !(selEl && selEl.contains(e.target))) toggleMenu(false);
});
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape" && !menuEl.hidden && !selEl) { toggleMenu(false); menuBtn.focus(); }
});
window.addEventListener("resize", function () { if (!menuEl.hidden) toggleMenu(false); });
// All popup menus (app, pause, deep search, log levels) behave the same way:
// they close on page scroll, resize, Esc and click outside, and opening one closes the others.
export function closePopups(except) {
  if (except !== "menu" && !menuEl.hidden) toggleMenu(false);
  if (except !== "pause" && !pauseEl.hidden) togglePause(false);
  if (except !== "deep" && !deepMenuEl.hidden) toggleDeepMenu(false);
  if (except !== "log" && !logMenuEl.hidden) toggleLogMenu(false);
}
window.addEventListener("scroll", function (e) {
  // The page (or one of its containers) scrolls: the menus, which are fixed, close.
  // Scrolling INSIDE a menu does not close it.
  const open = [menuEl, pauseEl, deepMenuEl, logMenuEl].filter(function (el) { return el && !el.hidden; });
  if (!open.length || open.some(function (el) { return el.contains(e.target); }) || (selEl && selEl.contains(e.target))) return;
  closePopups();
}, true);




