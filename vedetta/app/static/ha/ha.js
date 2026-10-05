// Vedetta in Home Assistant style (/ha). Vanilla JavaScript, no libraries.
// Data: /api/ha/devices, /api/ha/summary, /api/ha/logbook, /api/ha/history
// and the SSE stream /api/ha/events (JSON, with revision and automatic resume).
// Actions: the existing endpoints (refresh, wake, rename, delete, scan).
(function () {
  "use strict";

  var I = window.VedettaIcons;
  var LANG = window.VEDETTA_LANG || "en";
  var BASE = window.VEDETTA_BASE || ""; // HA ingress prefix (empty at the root)
  var params = new URLSearchParams(location.search);
  var ROOT = document.documentElement;
  var COMPACT = ROOT.getAttribute("data-compact") === "1";
  var COMPACT_LIMIT = parseInt(document.getElementById("root").dataset.limit, 10) || 6;
  var REDUCED = false;
  (function () {
    if (!window.matchMedia) return;
    var mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    REDUCED = !!mq.matches;
    var on = function (e) { REDUCED = !!e.matches; };
    if (mq.addEventListener) mq.addEventListener("change", on); else if (mq.addListener) mq.addListener(on);
  })();
  var TYPE_ORDER = ["router", "server", "pc", "phone", "media", "audio", "iot", "printer", "generic"];
  var POLL_WATCHDOG_MS = 90000;

  // ---------------------------------------------------------------- language
  // Like static/js/lang.js: ?lang= counts as a choice, otherwise the last saved
  // choice is restored (the cookie often does not travel inside an iframe).
  var LANG_KEY = "dash-lang";
  function langAvailable(code) {
    var list = window.VEDETTA_LANGS || [];
    for (var i = 0; i < list.length; i++) if (list[i][0] === code) return true;
    return false;
  }
  function goLang(code) {
    var next = new URLSearchParams(location.search);
    next.set("lang", code);
    location.replace(location.pathname + "?" + next.toString());
  }
  try {
    if (params.has("lang")) {
      localStorage.setItem(LANG_KEY, LANG);
    } else {
      var savedLang = localStorage.getItem(LANG_KEY);
      if (savedLang && savedLang !== LANG && langAvailable(savedLang)) {
        goLang(savedLang);
        return;
      }
      localStorage.setItem(LANG_KEY, LANG);
    }
  } catch (err) { /* storage not available: stay on the server's language */ }

  function t(key, vars) {
    var table = window.VEDETTA_I18N || {};
    var text;
    if (vars && typeof vars.n === "number") text = table[key + (vars.n === 1 ? "_one" : "_other")];
    if (text === undefined) text = table[key];
    if (text === undefined) return key;
    if (!vars) return text;
    return text.replace(/\{(\w+)\}/g, function (m, name) {
      return Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : m;
    });
  }

  // --------------------------------------------------------------- utilities
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function icon(name, cls) { return I.svg(name, cls); }
  function typeIcon(type) { return I.typeIcon[type] || I.typeIcon.generic; }
  // Device icon: the best-fitting one chosen by the server (MDI name) if we know it,
  // otherwise the one for its category.
  function devIcon(d) {
    return d && d.icon && I.paths[d.icon] ? d.icon : typeIcon(d && d.type);
  }
  // A web interface can be opened only if the scan found one (web port or page title).
  function canOpen(d) {
    return !!(d.title || (d.ports || []).some(function (p) { return p.category === "web"; }));
  }
  // Origin and reliability of brand and name: data for analysis, not for the user. Enabled with
  // 3 consecutive taps on the network card title (or ?debug=1); while enabled a fixed
  // "DEBUG" badge stays always visible. The API returns this data in any case.
  var DEBUG = /[?&]debug=1/.test(location.search) || (function () { try { return localStorage.getItem("vedetta-debug") === "1"; } catch (e) { return false; } })();
  function showDebugBadge() {
    ROOT.toggleAttribute("data-debug", DEBUG);
    var b = document.getElementById("debug-badge");
    if (DEBUG && !b) {
      b = document.createElement("div");
      b.id = "debug-badge"; b.setAttribute("role", "status");
      b.textContent = t("js.ha.debug.badge");
      document.body.appendChild(b);
    } else if (!DEBUG && b) { b.remove(); }
  }
  function setDebug(on) {
    DEBUG = !!on;
    ROOT.toggleAttribute("data-debug", DEBUG);
    try { localStorage.setItem("vedetta-debug", DEBUG ? "1" : "0"); } catch (e) { /* ignore */ }
    showDebugBadge();
    snack(t(DEBUG ? "js.ha.debug.on" : "js.ha.debug.off"), { kind: DEBUG ? "warning" : "success", ms: 3500 });
    S.tiles.forEach(function (el, id) { updateTile(id); });
    var od = S.open && S.devices.get(S.open);
    if (od && dlg.open && S.mi.view === "main") { miAttrs(od); miDebug(od); }
  }
  // 3 consecutive taps (within 2 s) on the network card title. Like Android's "build number":
  // from the second tap a notice says how many are left, so it is clear the gesture was understood.
  // In the capture phase (no other handler can stop the event) and with touch-action on the title
  // (no double-tap zoom). From the keyboard: Ctrl+Shift+D.
  var tapTimes = [];
  function debugTap(e) {
    var el = e.target && e.target.closest ? e.target.closest("#card-network .card-header .ch-text") : null;
    if (!el) return;
    var now = Date.now();
    tapTimes = tapTimes.filter(function (x) { return now - x < 2000; });
    tapTimes.push(now);
    if (tapTimes.length >= 3) { tapTimes = []; setDebug(!DEBUG); }
    else if (tapTimes.length === 2) snack(t(DEBUG ? "js.ha.debug.more_off" : "js.ha.debug.more_on"), { ms: 1500 });
  }
  document.addEventListener("click", debugTap, true);
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey && e.shiftKey && (e.key === "D" || e.key === "d")) { e.preventDefault(); setDebug(!DEBUG); }
  });
  // Wake-on-LAN: the packet gets no reply, so it cannot be known in advance whether the device
  // accepts it. It is offered only where it makes sense: device off, MAC known and real (not "private" like those
  // of phones), not mobile and of a type that usually supports it (PC, server, TV/media); or
  // when a previous wake-up has already worked (the server remembers it in wol_ok).
  var WAKE_TYPES = ["pc", "server", "media"];
  function macIsLocal(mac) { var b = parseInt(String(mac || "").slice(0, 2), 16); return isNaN(b) || (b & 2) === 2; }
  function canWake(d) {
    return !d.online && !!d.mac && !d.is_mobile && !macIsLocal(d.mac) && (!!d.wol_ok || WAKE_TYPES.indexOf(d.type) >= 0);
  }
  function typeLabel(type) { return t("js.ha.type1." + (I.typeIcon[type] ? type : "generic")); }
  function typePlural(type) { return t("js.ha.type." + (I.typeIcon[type] ? type : "generic")); }
  function nowSec() { return Date.now() / 1000; }

  function ago(ts) {
    var s = Math.max(0, nowSec() - ts);
    if (s < 60) return t("js.ha.ago.now");
    if (s < 3600) return t("js.ha.ago.minutes", { n: Math.floor(s / 60) });
    if (s < 86400) return t("js.ha.ago.hours", { n: Math.floor(s / 3600) });
    return t("js.ha.ago.days", { n: Math.floor(s / 86400) });
  }
  function fmtUptime(sec) {
    if (sec == null) return "";
    sec = Math.floor(sec);
    var d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
    if (d > 0) return t("js.ha.uptime.days", { d: d, h: h });
    if (h > 0) return t("js.ha.uptime.hours", { h: h, m: m });
    if (sec >= 60) return t("js.ha.uptime.minutes", { m: m });
    return t("js.ha.uptime.seconds", { n: sec });
  }
  function fmtClock(ts) {
    return new Date(ts * 1000).toLocaleTimeString(LANG, { hour: "2-digit", minute: "2-digit" });
  }
  function fmtDay(ts) {
    return new Date(ts * 1000).toLocaleDateString(LANG, { weekday: "short", day: "numeric", month: "short" });
  }
  function fmtStamp(ts, withDay) {
    return (withDay ? fmtDay(ts) + " " : "") + fmtClock(ts);
  }
  function ipKey(ip) {
    var p = String(ip || "").split(".");
    return ((+p[0] || 0) * 16777216) + ((+p[1] || 0) * 65536) + ((+p[2] || 0) * 256) + (+p[3] || 0);
  }
  function stateText(d) {
    if (d.online) {
      var ms = d.latency_ms;
      if (d.uptime != null) {
        return ms != null ? t("js.ha.state.online_for_ms", { uptime: fmtUptime(d.uptime), ms: ms }) : t("js.ha.state.online_for", { uptime: fmtUptime(d.uptime) });
      }
      return ms != null ? t("js.ha.state.online_ms", { ms: ms }) : t("js.ha.state.online");
    }
    return d.last_seen ? t("js.ha.state.offline_seen", { ago: ago(d.last_seen) }) : t("js.ha.state.offline");
  }
  function debounce(fn, ms) {
    var timer = null;
    return function () {
      var args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(null, args); }, ms);
    };
  }

  // JSON calls: the language travels in the X-Lang header and, for GETs,
  // also in the URL. An HTTP error becomes an exception with the server's text.
  function api(path, opts) {
    opts = opts || {};
    var method = opts.method || "GET";
    var url = path;
    if (method === "GET") url += (path.indexOf("?") < 0 ? "?" : "&") + "lang=" + encodeURIComponent(LANG);
    var headers = { "X-Lang": LANG };
    var body;
    if (opts.json !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(opts.json);
    }
    // Maximum time: after a mobile app standby a request can stay suspended forever.
    var ctrl = window.AbortController ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, opts.timeout || 25000);
    return fetch(url, { method: method, headers: headers, body: body, cache: "no-store", signal: ctrl ? ctrl.signal : undefined }).then(function (r) {
      clearTimeout(timer);
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (b) {
          var err = new Error(typeof b.detail === "string" ? b.detail : "HTTP " + r.status);
          err.status = r.status;
          throw err;
        });
      }
      return r.json().catch(function () { return {}; });
    }, function (err) { clearTimeout(timer); throw err; });
  }

  // The Home Assistant session (ingress) can expire while the app is in the background:
  // requests fail with 401/403 and retrying is useless. The page is on the same
  // domain as Home Assistant: the whole page is reloaded, which renews the session.
  function reloadHost(force) {
    var key = "vedetta-ha-reloaded", now = Date.now();
    if (!force) {
      try {
        if (now - (+sessionStorage.getItem(key) || 0) < 60000) return;  // no reload loops
        sessionStorage.setItem(key, String(now));
      } catch (err) { /* ignore */ }
    }
    try { window.top.location.reload(); } catch (err) { location.reload(); }
  }

  // ------------------------------------------------------------------ state
  var S = {
    devices: new Map(),
    list: [],               // devices in IP order
    rev: 0,
    loaded: false,
    loadTries: 0,
    filter: { q: (params.get("q") || "").toLowerCase(), status: "all", type: null },
    poll: { known: false, interval: 30000, nextAt: 0 },
    activity: { search: false, rescanning: new Set() },
    newDevices: { count: 0, devices: [], init: false },
    refreshing: false,
    refreshStart: 0,
    changedSince: 0,
    scanBusy: false,
    hist: new Map(),        // id -> {from,to,segments,online_pct} (last 24 h)
    log: { events: [], limit: 30, ids: null, open: false, q: "",
           level: (function () { try { var v = localStorage.getItem("vedetta-ha-loglevel"); return v === "normal" || v === "detail" ? v : "min"; } catch (e) { return "min"; } })() },
    open: null,             // device shown in the "More info" dialog
    mi: { range: 24, view: "main", win: {}, token: 0 },
    conn: { ok: false, everOk: false, retryAt: 3000, last: 0 },
    es: null,
    retryTimer: null,
    tiles: new Map(),       // id -> tile element (reused across redraws)
    groups: {},
    chipsSig: "",
    scanned: (function () { try { return localStorage.getItem("vedetta-ha-scanned") === "1"; } catch (err) { return false; } })(),
    scanDone: false,  // true only after a scan completed in this page
    roles: { by_ip: {}, via: {}, names: {} },  // who does what on the network (roles.py)
    adding: null,           // add in progress: {ips, done}
    found: [],              // devices found by the last scan and not yet added
    missLimit: 3,           // consecutive failed checks before going offline (shared setting)
    dirty: { ids: new Set(), layout: false, net: false, more: false },
    flushQueued: false,
    gauge: 0
  };

  // ---------------------------------------------------------------- toast
  // Snackbar at the bottom as in HA: text, optional action, disappears on its own.
  var snacksEl = $("snacks");
  // The modal dialog sits in the browser's "top layer" and would cover the toasts:
  // the container is a manual popover, brought back to the top every time.
  function raiseSnacks() {
    try {
      if (typeof snacksEl.showPopover !== "function") return;
      if (snacksEl.matches(":popover-open")) snacksEl.hidePopover();
      snacksEl.showPopover();
    } catch (err) { /* without the popover the toasts stay under the open dialog */ }
  }
  function snack(message, opts) {
    opts = opts || {};
    var el = document.createElement("div");
    el.className = "snack" + (opts.kind ? " " + opts.kind : "");
    el.setAttribute("role", opts.kind === "error" ? "alert" : "status");
    var ic = opts.kind === "error" ? "alert-circle" : (opts.kind === "warning" ? "alert" : "");
    el.innerHTML = (ic ? '<span class="snack-icon">' + icon(ic) + "</span>" : "") +
      '<span class="snack-text">' + esc(message) + "</span>";
    var timer = null;
    function close() {
      clearTimeout(timer);
      el.classList.remove("show");
      setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 260);
    }
    if (opts.action) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "snack-action rp";
      b.textContent = opts.action.text;
      b.addEventListener("click", function () { close(); opts.action.fn(); });
      el.appendChild(b);
    }
    snacksEl.appendChild(el);
    while (snacksEl.children.length > 3) snacksEl.removeChild(snacksEl.firstChild);
    raiseSnacks();
    requestAnimationFrame(function () { el.classList.add("show"); });
    timer = setTimeout(close, opts.ms || (opts.kind === "error" ? 6000 : 4200));
    el.addEventListener("click", function (e) { if (!e.target.closest(".snack-action")) close(); });
  }

  // ------------------------------------------------------------- ripple
  // Touch ripple as in HA components (mwc-ripple): a single delegation.
  document.addEventListener("pointerdown", function (e) {
    if (REDUCED || e.button > 0) return;
    var host = e.target.closest ? e.target.closest(".rp") : null;
    if (!host || host.disabled || host.getAttribute("aria-disabled") === "true") return;
    var rect = host.getBoundingClientRect();
    var size = Math.max(rect.width, rect.height) * 2;
    var wave = document.createElement("span");
    wave.className = "wave";
    wave.style.width = wave.style.height = size + "px";
    wave.style.left = (e.clientX - rect.left - size / 2) + "px";
    wave.style.top = (e.clientY - rect.top - size / 2) + "px";
    host.appendChild(wave);
    wave.addEventListener("animationend", function () { if (wave.parentNode) wave.parentNode.removeChild(wave); });
    setTimeout(function () { if (wave.parentNode) wave.parentNode.removeChild(wave); }, 900);
  }, { passive: true });

  // Counters that scroll toward the new value.
  function animateNumber(el, to) {
    if (!el) return;
    var from = el._v == null ? 0 : el._v;
    el._v = to;
    if (REDUCED || from === to) { el.textContent = String(to); return; }
    var start = performance.now(), dur = 450;
    cancelAnimationFrame(el._raf || 0);
    (function step(now) {
      var p = Math.min(1, (now - start) / dur);
      var e = 1 - Math.pow(1 - p, 3);
      el.textContent = String(Math.round(from + (to - from) * e));
      if (p < 1) el._raf = requestAnimationFrame(step);
    })(start);
  }

  // ---------------------------------------------------------------- bar
  var searchEl = $("search"), searchClear = $("search-clear");
  function buildToolbar() {
    $("search-icon").innerHTML = icon("magnify");
    searchEl.placeholder = t("js.ha.search");
    searchEl.setAttribute("aria-label", t("js.ha.search"));
    searchEl.value = params.get("q") || "";
    searchClear.innerHTML = icon("close");
    searchClear.title = t("js.ha.search_clear");
    searchClear.setAttribute("aria-label", t("js.ha.search_clear"));
    searchClear.hidden = !searchEl.value;
    $("btn-menu").innerHTML = icon("dots-vertical");
    $("btn-menu").title = t("js.ha.menu");
    $("btn-menu").setAttribute("aria-label", t("js.ha.menu"));
    $("btn-menu").classList.add("rp");
    searchClear.classList.add("rp");
    setConn(null);
  }

  var applySearch = debounce(function () {
    S.filter.q = searchEl.value.trim().toLowerCase();
    searchClear.hidden = !searchEl.value;
    S.dirty.layout = true;
    S.dirty.net = true;
    schedule();
  }, 90);
  searchEl.addEventListener("input", applySearch);
  searchEl.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && searchEl.value) { searchEl.value = ""; applySearch(); }
  });
  searchClear.addEventListener("click", function () { searchEl.value = ""; applySearch(); searchEl.focus(); });

  // "Real time" dot and banner if the stream drops.
  var bannerEl = $("banner");
  // Pause of the periodic check: left = ms remaining (null = no expiry).
  function pauseLeft() {
    if (!S.poll.paused) return null;
    return S.poll.pausedAt == null ? Infinity : Math.max(0, S.poll.pausedAt - Date.now());
  }
  function fmtLeft(ms) {
    var m = Math.ceil(ms / 60000);
    return m < 60 ? m + " min" : Math.floor(m / 60) + " h" + (m % 60 ? " " + (m % 60) + " min" : "");
  }
  // A single pill for the status: real time / paused / disconnected. Clickable.
  function renderLive() {
    var live = $("live"), text = $("live-text");
    if (!live) return;
    var ok = S.link === undefined ? null : S.link, left = pauseLeft();
    var paused = ok === true && S.poll.paused;
    live.classList.toggle("ok", ok === true && !paused);
    live.classList.toggle("paused", paused);
    // LED: blinking orange = timed pause; blinking red = stopped until
    // resumed; solid red = connection lost (class "bad").
    live.classList.toggle("timed", paused && left !== Infinity);
    live.classList.toggle("forever", paused && left === Infinity);
    live.classList.toggle("bad", ok === false);
    var label = ok === false ? t("js.ha.live.offline") : ok !== true ? t("js.ha.live.connecting")
      : paused ? (left === Infinity ? t("js.ha.pause.live") : t("js.ha.pause.live_left", { left: fmtLeft(left) })) : t("js.ha.live");
    if (text.textContent !== label) text.textContent = label;
    var title = paused ? t("js.ha.pause.resume_title") : t("js.ha.pause.title");
    if (live.title !== title) { live.title = title; live.setAttribute("aria-label", label + ". " + title); }
  }
  function setConn(ok) {
    S.link = ok;
    var live = $("live");
    var dot = document.getElementById("net-dot");
    renderLive();
    if (dot) dot.className = "net-dot" + (ok === true ? " ok" : ok === false ? " bad" : "");
    if (ok === true) {

      bannerEl.hidden = true;
      S.conn.everOk = true;
    } else if (ok === false) {
      bannerEl.hidden = false;
      bannerEl.innerHTML = icon("alert") + '<span class="banner-text">' + esc(t("js.ha.banner.lost")) + "</span>" +
        '<button type="button" class="btn text rp" id="banner-retry">' + esc(t("js.ha.banner.retry")) + "</button>";
      $("banner-retry").addEventListener("click", function () { connect(); });
    }
    S.conn.ok = ok === true;
  }

  // ----------------------------------------------------------------- menu
  var menuEl = $("menu"), menuBtn = $("btn-menu");
  // Button menu: each setting is a group with a title and a row of round
  // buttons (large for language and theme, small for numeric values).
  function menuGroup(label, buttons) {
    return '<div class="menu-group"><div class="menu-label">' + esc(label) + '</div><div class="menu-pills">' + buttons + "</div></div>";
  }
  function pill(size, attr, value, on, text, title) {
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
  function span(secs) { return secs < 120 ? secs + " s" : Math.round(secs / 60) + " min"; }
  function buildMenu() {
    var html = menuGroup(t("js.ha.menu.language"), (window.VEDETTA_LANGS || []).map(function (l) {
      return pill("lg half", "lang", l[0], l[0] === LANG, l[1]);
    }).join(""));
    var theme = ROOT.getAttribute("data-theme") || "auto";
    html += menuGroup(t("js.ha.menu.theme"), ["auto", "light", "dark"].map(function (v) {
      return pill("md", "theme", v, v === theme, t("js.ha.menu.theme_" + v));
    }).join(""));
    var view = ROOT.getAttribute("data-view") === "list" ? "list" : "tiles";
    html += menuGroup(t("js.ha.menu.view"), ["tiles", "list"].map(function (v) {
      return pill("md", "view", v, v === view, t("js.ha.menu.view_" + v));
    }).join(""));
    var pollNow = Math.round((S.poll.interval || 30000) / 1000);
    var cur = null;
    var pills = SPEEDS.map(function (s) {
      var on = s.poll === pollNow && s.miss === S.missLimit;
      if (on) cur = s;
      return pill("md", "speed", s.id, on, t("js.ha.menu.speed_" + s.id));
    }).join("");
    var secs = cur ? cur.poll * cur.miss : pollNow * S.missLimit;
    html += menuGroup(t("js.ha.menu.speed"), pills) +
      '<div class="menu-hint">' + esc(t("js.ha.menu.speed_hint", { t: span(secs) })) + "</div>";
    html += '<button type="button" class="menu-item menu-link rp" data-flows="1">' + esc(t("js.ha.menu.flows")) + icon("cog") + "</button>";
    html += '<button type="button" class="menu-item menu-link next rp" data-ignored="1">' + esc(t("js.ha.menu.ignored")) + icon("eye-off") + "</button>";
    // Export for analysis: almost invisible on purpose (small, faded icon).
    html += '<button type="button" class="menu-item menu-link menu-export next rp" data-export="1">' + esc(t("js.ha.export.title")) + icon("download") + "</button>";
    menuEl.innerHTML = html;
  }
  function toggleMenu(open) {
    if (open === undefined) open = menuEl.hidden;
    if (open) {
      closePopups("menu");
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
    if (e.target.closest("[data-export]")) { toggleMenu(false); openExport(); return; }
    var item = e.target.closest(".menu-item");
    if (!item) return;
    if (item.dataset.lang) {
      if (item.dataset.lang === LANG) return toggleMenu(false);
      try { localStorage.setItem(LANG_KEY, item.dataset.lang); } catch (err) { /* ignore */ }
      api("/api/lang/" + encodeURIComponent(item.dataset.lang), { method: "POST" })
        .catch(function () {}).then(function () { goLang(item.dataset.lang); });
    } else if (item.dataset.theme) {
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
        api("/api/settings", { method: "POST", json: { poll_interval: sp.poll, miss_limit: sp.miss } }).catch(function () {});
      }
      toggleMenu(false);
    } else {
      toggleMenu(false);
    }
  });
  document.addEventListener("click", function (e) {
    if (!menuEl.hidden && !e.target.closest(".menu-wrap")) toggleMenu(false);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !menuEl.hidden) { toggleMenu(false); menuBtn.focus(); }
  });
  window.addEventListener("resize", function () { if (!menuEl.hidden) toggleMenu(false); });
  // All popup menus (app, pause, deep search, log levels) behave the same way:
  // they close on page scroll, resize, Esc and click outside, and opening one closes the others.
  function closePopups(except) {
    if (except !== "menu" && !menuEl.hidden) toggleMenu(false);
    if (except !== "pause" && !pauseEl.hidden) togglePause(false);
    if (except !== "deep" && !deepMenuEl.hidden) toggleDeepMenu(false);
    if (except !== "log" && !logMenuEl.hidden) toggleLogMenu(false);
  }
  window.addEventListener("scroll", function (e) {
    // The page (or one of its containers) scrolls: the menus, which are fixed, close.
    // Scrolling INSIDE a menu does not close it.
    var open = [menuEl, pauseEl, deepMenuEl, logMenuEl].filter(function (el) { return el && !el.hidden; });
    if (!open.length || open.some(function (el) { return el.contains(e.target); })) return;
    closePopups();
  }, true);




  // ------------------------------------------------- export for analysis
  var exportDlg = $("exportdlg");
  function closeExport() {
    if (exportDlg.open && typeof exportDlg.close === "function") exportDlg.close(); else exportDlg.removeAttribute("open");
  }
  function openExport() {
    exportDlg.innerHTML = '<div class="mi"><div class="mi-header"><div class="mi-titles"><h2 class="mi-title" id="exportdlg-title">' + esc(t("js.ha.export.title")) + "</h2></div></div>" +
      '<div class="mi-body"><div class="confirm"><span class="confirm-ic info">' + icon("download") + "</span><p>" + esc(t("js.ha.export.text")) + "</p></div></div>" +
      '<div class="mi-actions"><button type="button" class="btn text rp" data-export-do="cancel">' + esc(t("js.ha.cancel")) + "</button>" +
      '<button type="button" class="btn filled rp" data-export-do="start">' + esc(t("js.ha.export.start")) + "</button></div></div>";
    if (typeof exportDlg.showModal === "function") exportDlg.showModal(); else exportDlg.setAttribute("open", "");
  }
  exportDlg.addEventListener("click", function (e) {
    if (e.target === exportDlg) return closeExport();
    var b = e.target.closest("[data-export-do]");
    if (!b) return;
    if (b.dataset.exportDo === "cancel") return closeExport();
    b.disabled = true;
    closeExport();
    snack(t("js.ha.export.working"), { ms: 4000 });
    fetch("/api/export", { method: "POST", headers: { "X-Lang": LANG }, cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      var m = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") || "");
      return r.blob().then(function (blob) { return { blob: blob, name: m ? m[1] : "vedetta-analisi.zip" }; });
    }).then(function (f) {
      var a = document.createElement("a");
      a.href = URL.createObjectURL(f.blob); a.download = f.name;
      document.body.appendChild(a); a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 4000);
      snack(t("js.ha.export.done"), { kind: "success" });
    }).catch(function () { snack(t("js.ha.export.failed"), { kind: "error" }); });
  });

  // ------------------------------------------------- deep search
  // First advanced search: system, open services, web page. Slow, so always
  // behind a confirmation. On a single device the confirmation can be disabled; on
  // all devices it cannot.
  var SKIP_DEEP_KEY = "vedetta-ha-skip-deep";
  function skipDeepConfirm() { try { return localStorage.getItem(SKIP_DEEP_KEY) === "1"; } catch (err) { return false; } }
  // Devices never analyzed in depth: scanned_at is written only by the deep search ("Last deep search").
  function deepPending() { return S.list.filter(function (d) { return !d.scanned_at && !d.deep_empty_at; }); }
  var deepIds = [];
  function runDeep(ids) {
    if (!ids.length) return;
    api("/api/devices/rescan", { method: "POST", json: { ids: ids } }).then(function () {
      snack(t("js.ha.deep.done"), { kind: "success" });
      fetchHist();
    }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); });
  }
  var deepDlg = $("deepall"), deepMenuEl = $("deep-menu");
  function toggleDeepMenu(open) {
    if (open === undefined) open = deepMenuEl.hidden;
    if (open) {
      closePopups("deep");
      var pending = deepPending().length;
      deepMenuEl.innerHTML = '<button type="button" class="menu-item dm-item rp" role="menuitem" data-deep="all">' + icon("magnify") + '<span class="dm-text"><b>' + esc(t("js.ha.deep.menu_title")) +
        "</b><span>" + esc(t("js.ha.deep.menu_hint")) + "</span></span></button>" +
        '<button type="button" class="menu-item dm-item rp" role="menuitem" data-deep="pending"' + (pending ? "" : " disabled") + ">" + icon("magnify") + '<span class="dm-text"><b>' + esc(t("js.ha.deep.menu_pending_title")) +
        "</b><span>" + esc(pending ? t("js.ha.deep.menu_pending_hint", { n: pending }) : t("js.ha.deep.menu_pending_none")) + "</span></span></button>";
      var btn = $("btn-deepmenu"), r = btn.getBoundingClientRect();
      deepMenuEl.style.top = Math.round(r.bottom + 4) + "px";
      deepMenuEl.style.left = "auto";
      deepMenuEl.style.right = Math.max(8, Math.round(window.innerWidth - r.right)) + "px";
    }
    deepMenuEl.hidden = !open;
    var b2 = $("btn-deepmenu"); if (b2) b2.setAttribute("aria-expanded", String(open));
  }
  function openDeepAll(mode) {
    var list = mode === "pending" ? deepPending() : S.list, n = list.length;
    if (!n) { snack(t(mode === "pending" ? "js.ha.deep.menu_pending_none" : "js.ha.deep.none"), { kind: "warning" }); return; }
    deepIds = list.map(function (d) { return d.id; });
    deepDlg.innerHTML = '<div class="mi"><div class="mi-header"><div class="mi-titles"><h2 class="mi-title" id="deepall-title">' + esc(t("js.ha.deep.title")) + "</h2></div></div>" +
      '<div class="mi-body"><div class="confirm"><span class="confirm-ic info">' + icon("magnify") + "</span><p>" + esc(t(mode === "pending" ? "js.ha.deep.pending_text" : "js.ha.deep.all_text", { n: n })) + "</p></div></div>" +
      '<div class="mi-actions"><button type="button" class="btn text rp" data-deep="cancel">' + esc(t("js.ha.cancel")) + "</button>" +
      '<button type="button" class="btn filled rp" data-deep="start">' + esc(t("js.ha.deep.start")) + "</button></div></div>";
    if (typeof deepDlg.showModal === "function") deepDlg.showModal(); else deepDlg.setAttribute("open", "");
  }
  function closeDeepAll() {
    if (deepDlg.open && typeof deepDlg.close === "function") deepDlg.close(); else deepDlg.removeAttribute("open");
  }
  document.addEventListener("click", function (e) {
    if (e.target.closest("#btn-deepmenu")) { e.stopPropagation(); toggleDeepMenu(); }
  });
  deepMenuEl.addEventListener("click", function (e) {
    var item = e.target.closest("[data-deep]");
    if (!item || item.disabled) return;
    toggleDeepMenu(false);
    openDeepAll(item.dataset.deep);
  });
  deepDlg.addEventListener("click", function (e) {
    if (e.target === deepDlg) return closeDeepAll();
    var b = e.target.closest("[data-deep]");
    if (!b) return;
    if (b.dataset.deep === "start") { closeDeepAll(); runDeep(deepIds); }
    else closeDeepAll();
  });
  document.addEventListener("click", function (e) {
    if (!deepMenuEl.hidden && !e.target.closest("#deep-menu") && !e.target.closest("#btn-deepmenu")) toggleDeepMenu(false);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !deepMenuEl.hidden) toggleDeepMenu(false);
  });
  window.addEventListener("resize", function () { if (!deepMenuEl.hidden) toggleDeepMenu(false); });

  // ------------------------------------------------------------- pause
  var pauseEl = $("pause-menu"), liveEl = $("live");
  function buildPause() {
    var html;
    if (S.poll.paused) {
      var left = pauseLeft();
      html = menuGroup(t("js.ha.pause.paused"), pill("lg", "resume", "1", false, t("js.ha.pause.resume"))) +
        '<div class="menu-hint">' + esc(left === Infinity ? t("js.ha.pause.idle") : t("js.ha.pause.idle_left", { left: fmtLeft(left) })) + "</div>";
    } else {
      html = menuGroup(t("js.ha.pause.title"), [15, 60, 480].map(function (n) {
        return pill("md", "pause", n, false, t("js.ha.pause.opt_" + n));
      }).join("") + pill("lg full", "pause", 0, false, t("js.ha.pause.opt_0"))) +
        '<div class="menu-hint">' + esc(t("js.ha.pause.hint")) + "</div>";
    }
    pauseEl.innerHTML = html;
  }
  function togglePause(open) {
    if (open === undefined) open = pauseEl.hidden;
    if (open) {
      closePopups("pause");
      buildPause();
      var r = liveEl.getBoundingClientRect();
      pauseEl.style.top = Math.round(r.bottom + 4) + "px";
      pauseEl.style.right = "auto";
      pauseEl.style.left = Math.max(8, Math.min(Math.round(r.left), window.innerWidth - 308)) + "px";
      pauseEl.style.maxHeight = Math.max(160, window.innerHeight - r.bottom - 16) + "px";
    }
    pauseEl.hidden = !open;
    liveEl.setAttribute("aria-expanded", String(open));
    if (open) { var f = pauseEl.querySelector(".menu-item"); if (f) f.focus(); }
  }
  liveEl.addEventListener("click", function (e) { e.stopPropagation(); togglePause(); });
  pauseEl.addEventListener("click", function (e) {
    var item = e.target.closest(".menu-item");
    if (!item) return;
    var req = item.dataset.resume
      ? api("/api/pause", { method: "DELETE" })
      : api("/api/pause", { method: "POST", json: { minutes: +item.dataset.pause } });
    togglePause(false);
    req.then(function (ev) {
      onPoll(ev);
    }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); });
  });
  document.addEventListener("click", function (e) {
    if (!pauseEl.hidden && !e.target.closest("#pause-menu")) togglePause(false);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !pauseEl.hidden) { togglePause(false); liveEl.focus(); }
  });
  window.addEventListener("resize", function () { if (!pauseEl.hidden) togglePause(false); });

  // ------------------------------------------------- ignored devices
  // Two origins: "Ignore" on a device found by the search (list of
  // ignored: IP, MAC or name) and "Ignore" on a device detected on the network (MAC).
  var ignDlg = $("ignored");
  function openIgnored() {
    Promise.all([api("/api/ignored"), api("/api/new-devices/ignored")]).then(function (res) {
      S.ign = { items: (res[0] && res[0].items) || [], macs: Array.isArray(res[1]) ? res[1] : [] };
      renderIgnored();
      if (!ignDlg.open) {
        if (typeof ignDlg.showModal === "function") ignDlg.showModal(); else ignDlg.setAttribute("open", "");
        if (snacksEl.children.length) raiseSnacks();
      }
    }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); });
  }
  function closeIgnored() {
    if (ignDlg.open && typeof ignDlg.close === "function") ignDlg.close(); else ignDlg.removeAttribute("open");
  }
  function renderIgnored() {
    var g = S.ign, rows = "";
    g.items.forEach(function (it) {
      rows += '<div class="nd-row"><span class="nd-ic">' + icon("eye-off") + '</span><div class="nd-text"><div class="nd-name">' +
        esc(it.label || it.value) + '</div><div class="nd-sub">' + esc(t("js.ha.ign.kind_" + it.kind) + " " + it.value + " \u00b7 " + t("js.ha.ign.from_search")) +
        '</div></div><div class="nd-actions"><button type="button" class="btn text rp" data-unign-id="' + esc(it.id) + '">' + esc(t("js.ha.ign.restore")) + "</button></div></div>";
    });
    g.macs.forEach(function (m) {
      rows += '<div class="nd-row"><span class="nd-ic">' + icon("eye-off") + '</span><div class="nd-text"><div class="nd-name">' +
        esc(m.hostname || m.vendor || m.ip || m.mac) + '</div><div class="nd-sub">' + esc([m.ip, m.mac, t("js.ha.ign.from_network")].filter(Boolean).join(" \u00b7 ")) +
        '</div></div><div class="nd-actions"><button type="button" class="btn text rp" data-unign-mac="' + esc(m.mac) + '">' + esc(t("js.ha.ign.restore")) + "</button></div></div>";
    });
    ignDlg.innerHTML = '<div class="mi"><div class="mi-header"><button type="button" class="icon-btn touch rp" data-ign="close" aria-label="' +
      esc(t("js.ha.more.close")) + '">' + icon("close") + '</button><div class="mi-titles"><h2 class="mi-title" id="ignored-title">' + esc(t("js.ha.menu.ignored")) +
      '</h2><div class="mi-sub">' + esc(t("js.ha.ign.hint")) + '</div></div></div><div class="fl-body nd-list">' +
      (rows || '<div class="log-empty">' + icon("eye-off") + "<div><b>" + esc(t("js.ha.ign.empty")) + "</b></div></div>") + "</div></div>";
  }
  ignDlg.addEventListener("click", function (e) {
    if (e.target === ignDlg || e.target.closest('[data-ign="close"]')) return closeIgnored();
    var b = e.target.closest("[data-unign-id], [data-unign-mac]");
    if (!b) return;
    b.disabled = true;
    var req = b.dataset.unignId
      ? api("/api/ignored/" + encodeURIComponent(b.dataset.unignId), { method: "DELETE" }).then(function (r) { S.ign.items = (r && r.items) || []; })
      : api("/api/new-devices/unignore", { method: "POST", json: { mac: b.dataset.unignMac } }).then(function (r) { S.ign.macs = Array.isArray(r) ? r : []; });
    req.then(function () { renderIgnored(); })
      .catch(function () { b.disabled = false; snack(t("js.ha.toast.error"), { kind: "error" }); });
  });

  // ------------------------------------------------- search methods (flows)
  // Same setting as the classic dashboard (/api/flows): for each type of search,
  // which functions to run. Saves on every switch.
  var flowsDlg = $("flows");
  function openFlows() {
    api("/api/flows").then(function (r) {
      S.fl = r;
      renderFlows();
      if (!flowsDlg.open) {
        if (typeof flowsDlg.showModal === "function") flowsDlg.showModal(); else flowsDlg.setAttribute("open", "");
        if (snacksEl.children.length) raiseSnacks();
      }
    }).catch(function () { snack(t("js.flows.load_failed"), { kind: "error" }); });
  }
  function closeFlows() {
    if (flowsDlg.open && typeof flowsDlg.close === "function") flowsDlg.close(); else flowsDlg.removeAttribute("open");
  }
  function renderFlows() {
    var r = S.fl, html = '<div class="mi-header"><button type="button" class="icon-btn touch rp" data-fl="close" aria-label="' +
      esc(t("js.ha.more.close")) + '">' + icon("close") + '</button><div class="mi-titles"><h2 class="mi-title" id="flows-title">' +
      esc(t("js.flows.title")) + '</h2><div class="mi-sub">' + esc(t("js.flows.hint")) + '</div></div></div><div class="fl-body">';
    // Legend of risk levels (the texts come from the server in the right language).
    html += '<div class="fl-legend">' + ["easy", "invasive", "risky"].map(function (k) {
      var info = (r.risks || {})[k] || { label: k, description: "" };
      return '<span class="risk r-' + k + '" title="' + esc(info.description) + '"><i></i>' + esc(info.label) + "</span>";
    }).join("") + "</div>";
    ["initial", "associative", "deep"].forEach(function (p) {
      var prof = r.flows[p];
      if (!prof) return;
      html += '<section class="fl-sec" data-profile="' + p + '"><h3>' + esc(prof.label) + "</h3><p>" + esc(prof.description) + "</p>";
      r.steps.forEach(function (s) {
        if (s.flows.indexOf(p) < 0) return;
        var locked = s.locked_in.indexOf(p) >= 0, on = locked || prof.steps.indexOf(s.id) >= 0;
        var rk = (r.risks || {})[s.risk] || {};
        html += '<label class="fl-row' + (locked ? " locked" : "") + '"><span class="fl-text"><b><span class="risk-dot r-' + esc(s.risk) + '" title="' +
          esc(rk.label || "") + '"></span>' + esc(s.label) + (locked ? " · " + esc(t("js.flows.required")) : "") +
          "</b><span>" + esc(s.description) +
          '</span></span><input type="checkbox" class="fl-sw" data-step="' + esc(s.id) + '"' + (on ? " checked" : "") + (locked ? " disabled" : "") + "></label>";
      });
      html += "</section>";
    });
    html += '</div><div class="card-actions"><button type="button" class="btn text rp" data-fl="reset">' + esc(t("js.flows.reset")) + "</button></div>";
    flowsDlg.innerHTML = html;
  }
  flowsDlg.addEventListener("click", function (e) {
    if (e.target === flowsDlg || e.target.closest('[data-fl="close"]')) return closeFlows();
    if (e.target.closest('[data-fl="reset"]')) {
      api("/api/flows/reset", { method: "POST" }).then(function (r) {
        S.fl = r; renderFlows();
      }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); });
    }
  });
  flowsDlg.addEventListener("change", function (e) {
    if (!e.target.classList.contains("fl-sw")) return;
    var out = {};
    flowsDlg.querySelectorAll(".fl-sec").forEach(function (sec) {
      out[sec.dataset.profile] = Array.prototype.map.call(sec.querySelectorAll(".fl-sw:checked"), function (i) { return i.dataset.step; });
    });
    api("/api/flows", { method: "POST", json: { flows: out } }).then(function (r) {
      S.fl = r;
    }).catch(function (err) {
      snack(err && err.message ? err.message : t("js.ha.toast.error"), { kind: "error" });
      return api("/api/flows").then(function (r) { S.fl = r; renderFlows(); });
    });
  });

  // ------------------------------------------------------------ filters
  // Chosen from the badges of the "Network" card (All, Online, Offline, Mobile).
  function matches(d) {
    var f = S.filter;
    if (f.status === "online" && !d.online) return false;
    if (f.status === "offline" && d.online) return false;
    if (f.status === "mobile" && !d.is_mobile) return false;
    if (f.type && d.type !== f.type) return false;
    if (f.q && d._hay.indexOf(f.q) < 0) return false;
    return true;
  }
  function counts() {
    var c = { total: S.list.length, online: 0, offline: 0, mobile: 0, types: {} };
    S.list.forEach(function (d) {
      if (d.online) c.online++; else c.offline++;
      if (d.is_mobile) c.mobile++;
      c.types[d.type] = (c.types[d.type] || 0) + 1;
    });
    return c;
  }
  function setFilter(kind, value) {
    if (kind === "status") S.filter.status = value;
    else S.filter.type = S.filter.type === value ? null : value;
    S.dirty.layout = true;
    S.dirty.net = true;
    schedule();
  }

  // ---------------------------------------------------------- "Network" card
  var netEl = $("card-network");
  var GAUGE_C = 2 * Math.PI * 52;
  // Number and ring advance together (same duration and same curve): a CSS
  // transition on the ring does not start on first draw, when the element is born already at its final value.
  function animateGauge(online, total) {
    var fill = $("g-fill"), val = $("g-val");
    var to = total ? online / total : 0;
    function paint(r, n) {
      fill._cur = r; val._cur = n;
      fill.setAttribute("stroke-dashoffset", (GAUGE_C * (1 - r)).toFixed(2));
      val.textContent = String(n);
    }
    if (REDUCED) { cancelAnimationFrame(fill._raf || 0); fill._r = to; val._v = online; paint(to, online); return; }
    // Same values as before: do not touch the animation possibly in progress
    // (the card is updated several times in a row as soon as it is drawn).
    if (fill._r === to && val._v === online) return;
    var from = fill._cur == null ? 0 : fill._cur, fromN = val._cur == null ? 0 : val._cur;
    fill._r = to;
    val._v = online;
    cancelAnimationFrame(fill._raf || 0);
    var start = performance.now(), dur = 700;
    (function step(now) {
      var p = Math.min(1, (now - start) / dur);
      var e = 1 - Math.pow(1 - p, 3);
      paint(from + (to - from) * e, Math.round(fromN + (online - fromN) * e));
      if (p < 1) fill._raf = requestAnimationFrame(step);
    })(start);
  }

  // The app name appears in the title only if HA does not show its bar
  // (wide window or page opened outside HA); with the HA bar it is already written there.
  var haBar = false;
  function renderNetTitle() {
    var title = $("net-title"), sub = $("net-sub");
    if (!title || !sub) return;
    var cnt = t("js.ha.devices_count", { n: S.list.length });
    title.textContent = haBar ? t("js.ha.network") : "Vedetta";
    sub.textContent = haBar ? cnt : t("js.ha.network") + " · " + cnt;
  }
  window.addEventListener("message", function (e) {
    if (e.source !== window.parent || !e.data || e.data.type !== "home-assistant/properties") return;
    var narrow = !!e.data.narrow;
    if (narrow !== haBar) { haBar = narrow; renderNetTitle(); }
  });
  if (window.parent !== window) {
    try { window.parent.postMessage({ type: "home-assistant/subscribe-properties" }, "*"); } catch (err) {}
  }

  // Search, real-time status and settings: nodes created only once (with their
  // handlers) and moved into the network card. If the card is rebuilt (resync
  // after a service restart or a roles change) they must be put in a safe place first, otherwise they
  // would vanish with the old content and the buttons would stop responding.
  var NET_PARTS = null;
  function buildNetwork() {
    if (!NET_PARTS) NET_PARTS = { live: $("live"), wrap: document.querySelector(".menu-wrap"), search: $("search-box") };
    var stash = document.createDocumentFragment();
    [NET_PARTS.live, NET_PARTS.wrap, NET_PARTS.search].forEach(function (n) { if (n) stash.appendChild(n); });
    netEl.innerHTML =
      '<div class="card-header"><div class="ch-text">' +
        '<div class="ch-title"><span class="net-dot" id="net-dot"></span><span id="net-title"></span></div>' +
        '<div class="ch-sub" id="net-sub"></div></div>' +
        '<div class="card-tools" id="card-tools">' +
        '<button type="button" class="icon-btn touch rp" id="btn-refresh" title="' + esc(t("js.ha.refresh")) + '" aria-label="' + esc(t("js.ha.refresh")) + '">' +
        icon("refresh") + "</button></div></div>" +
      '<div class="card-search" id="card-search"></div>' +
      '<div class="card-content">' +
        '<div class="gauge-row">' +
          '<div class="gauge" id="gauge" role="img">' +
            '<svg viewBox="0 0 120 120" aria-hidden="true"><circle class="g-track" cx="60" cy="60" r="52"></circle>' +
            '<circle class="g-fill" id="g-fill" cx="60" cy="60" r="52" stroke-dasharray="' + GAUGE_C.toFixed(2) + '" stroke-dashoffset="' + GAUGE_C.toFixed(2) + '" transform="rotate(-90 60 60)"></circle></svg>' +
            '<div class="gauge-center"><span class="gauge-value" id="g-val">0</span><span class="gauge-of" id="g-of"></span></div>' +
          "</div>" +
          '<div class="gauge-side">' +
            '<div class="scan-state"><span class="scan-ic" id="scan-ic">' + icon("history") + '</span><span class="scan-text" id="scan-text"></span></div>' +
            '<div class="split"><button type="button" class="btn outlined rp" id="btn-scan">' + icon("magnify") + "<span>" + esc(t("js.ha.scan")) + "</span></button>" +
            '<button type="button" class="btn outlined rp split-more" id="btn-deepmenu" aria-haspopup="true" aria-expanded="false" aria-label="' + esc(t("js.ha.deep.title")) + '">' + icon("chevron-down") + "</button></div>" +
          "</div>" +
        "</div>" +
        '<div class="badges" id="badges"></div>' +
        '<div class="brands" id="brands"></div>' +
      "</div>" +
      '<div class="progress" id="progress" aria-hidden="true"><div class="bar" id="progress-bar"></div></div>';
    // Search, real-time status and settings live inside this card: the already created
    // nodes (with their handlers) are moved here from the hidden container.
    var tools = $("card-tools");
    tools.insertBefore(NET_PARTS.live, tools.firstChild);
    tools.appendChild(NET_PARTS.wrap);
    $("card-search").appendChild(NET_PARTS.search);
    var holder = $("toolbar");
    if (holder) holder.remove();
    $("btn-refresh").addEventListener("click", doRefresh);
    $("btn-scan").addEventListener("click", doScan);
    $("badges").addEventListener("click", function (e) {
      var b = e.target.closest(".badge");
      if (!b) return;
      if (b.dataset.badge === "new") {
        var card = $("card-new");
        if (!card.hidden && card.scrollIntoView) card.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "nearest" });
        return;
      }
      setFilter("status", S.filter.status === b.dataset.badge ? "all" : b.dataset.badge);
    });
  }

  var BADGES = [
    ["all", "devices", "primary"],
    ["online", "check-circle", "success"],
    ["offline", "close-circle", "error"],
    ["mobile", "cellphone", "primary"],
    ["new", "plus-circle", "warning"]
  ];
  function updateNetwork() {
    var c = counts();
    var gauge = $("gauge");
    if (!gauge) return;
    var ratio = c.total ? c.online / c.total : 0;
    var tone = !c.total ? "none" : ratio >= 0.8 ? "ok" : ratio >= 0.5 ? "warn" : "bad";
    gauge.className = "gauge " + tone;
    animateGauge(c.online, c.total);
    $("g-of").textContent = t("js.ha.gauge.of", { n: c.total });
    gauge.setAttribute("aria-label", t("js.ha.gauge.aria", { online: c.online, total: c.total }));
    renderNetTitle();

    var badges = $("badges");
    if (!badges.firstChild) {
      badges.innerHTML = BADGES.map(function (b) {
        return '<button type="button" class="badge rp touch tone-' + b[2] + '" data-badge="' + b[0] + '">' +
          '<span class="badge-ic">' + icon(b[1]) + '</span><span class="badge-val" data-v="0">0</span>' +
          '<span class="badge-lb">' + esc(t("js.ha.badge." + b[0])) + "</span></button>";
      }).join("");
    }
    var values = { all: c.total, online: c.online, offline: c.offline, mobile: c.mobile, "new": S.newDevices.count };
    var nodes = badges.querySelectorAll(".badge");
    for (var i = 0; i < nodes.length; i++) {
      var key = nodes[i].dataset.badge, v = values[key];
      var valEl = nodes[i].querySelector(".badge-val");
      if (valEl._v !== v) {
        var first = valEl._v == null;
        animateNumber(valEl, v);
        if (!first) { nodes[i].classList.remove("bump"); void nodes[i].offsetWidth; nodes[i].classList.add("bump"); }
      }
      nodes[i].setAttribute("aria-pressed", key === "new" ? "false" : String(S.filter.status === key));
      nodes[i].classList.toggle("dim", key === "new" && v === 0);
    }
    renderBrands();
  }

  var BRAND_COLORS = 8;
  // Short and honest text for those without a known brand: what is really known, i.e.
  // the MAC manufacturer and its role (chip, board, virtual machine).
  function chipText(d) {
    if (d.brand) return d.brand;
    if (d.vendor_role === "private") return t("js.ha.chip.private");
    if (!d.vendor) return "";
    var role = d.vendor_role === "component" || d.vendor_role === "virtual" || d.vendor_role === "dual" ? d.vendor_role : "brand";
    return t("js.ha.chip." + role, { vendor: d.vendor });
  }
  // MAC manufacturers of devices without a brand (tooltip of the "Unknown" entry).
  function batteryTitle(d) {
    return t("js.ha.battery.yes") + (d.battery_source ? " · " + t("js.ha.battery.src_" + d.battery_source) : "");
  }
  function renderBrands() {
    var el = $("brands");
    if (!el) return;
    var map = {};
    S.list.forEach(function (d) {
      // Brand of the PRODUCT, never the network card manufacturer (an
      // Espressif chip is not a brand). Those without a known brand do not appear.
      if (!d.brand) return;
      map[d.brand] = (map[d.brand] || 0) + 1;
    });
    var rows = Object.keys(map).map(function (k) { return { name: k, n: map[k] }; });
    rows.sort(function (a, b) { return b.n - a.n || a.name.localeCompare(b.name); });
    var shown = rows.slice(0, BRAND_COLORS);
    var rest = rows.slice(BRAND_COLORS).reduce(function (s, r) { return s + r.n; }, 0);
    if (rest) shown.push({ name: "\u0000other", n: rest });
    var total = rows.length;
    var sig = JSON.stringify(shown);
    if (el._sig === sig) return;
    el._sig = sig;
    if (!total) { el.innerHTML = ""; return; }
    var bar = "", legend = "";
    shown.forEach(function (r, i) {
      var label = r.name === "\u0000other" ? t("js.ha.brands.other") : r.name;
      var cls = r.name === "\u0000other" ? "c-other" : "c" + (i + 1);
      var tip = label + ": " + r.n;
      bar += '<i class="' + cls + '" style="flex-grow:' + r.n + '" title="' + esc(tip) + '"></i>';
      legend += '<li title="' + esc(tip) + '"><span class="dot ' + cls + '"></span><span class="b-name">' + esc(label) + '</span><span class="b-n">' + r.n + "</span></li>";
    });
    el.innerHTML = '<div class="brands-title">' + esc(t("js.ha.brands.title")) + '</div><div class="brand-bar">' + bar + "</div><ul>" + legend + "</ul>";
  }

  // Search status: text and bar (determinate = countdown to the
  // next cycle; indeterminate = something is working).
  function updateScan() {
    var textEl = $("scan-text");
    if (!textEl) return;
    var busy = false, text;
    var rescanning = S.activity.rescanning.size;
    if (S.activity.search) { text = t("js.ha.scan.searching"); busy = true; }
    else if (rescanning) { text = t("js.ha.scan.deep", { n: rescanning }); busy = true; }
    else if (S.refreshing) { text = t("js.ha.scan.refreshing"); busy = true; }
    else if (!S.poll.known) { text = t("js.ha.scan.waiting"); busy = true; }
    else if (S.poll.paused) {
      var pl = pauseLeft();
      text = pl === Infinity ? t("js.ha.pause.idle") : t("js.ha.pause.idle_left", { left: fmtLeft(pl) });
    } else {
      var remaining = Math.max(0, Math.ceil((S.poll.nextAt - Date.now()) / 1000));
      if (remaining === 0) { text = t("js.ha.scan.refreshing"); }
      else text = t("js.ha.scan.idle", { ago: ago((S.poll.nextAt - S.poll.interval) / 1000), s: remaining });
    }
    if (textEl.textContent !== text) { textEl.textContent = text; textEl.title = text; }
    renderLive();
    var prog = $("progress"), bar = $("progress-bar");
    prog.classList.toggle("indet", busy);
    if (!busy) {
      var pct = Math.min(1, Math.max(0, 1 - (S.poll.nextAt - Date.now()) / S.poll.interval));
      bar.style.transform = "scaleX(" + pct.toFixed(3) + ")";
    } else {
      bar.style.transform = "";
    }
    $("scan-ic").classList.toggle("busy", busy);
    var refreshBtn = $("btn-refresh");
    refreshBtn.classList.toggle("spinning", S.refreshing);
    var scanBtn = $("btn-scan");
    var scanning = S.activity.search || S.scanBusy;
    scanBtn.disabled = scanning;
    scanBtn.classList.toggle("busy", scanning);
    document.querySelectorAll(".empty-ic.scan").forEach(function (b) {
      b.disabled = scanning;
      b.classList.toggle("busy", scanning);
    });
  }

  function doRefresh() {
    if (S.refreshing) return;
    S.refreshing = true;
    S.refreshStart = Date.now();
    S.changedSince = 0;
    S.poll.nextAt = Date.now();
    updateScan();
    api("/api/refresh", { method: "POST" }).catch(function () {
      S.refreshing = false;
      updateScan();
      snack(t("js.ha.toast.refresh_failed"), { kind: "error" });
    });
    setTimeout(function () { if (S.refreshing) { S.refreshing = false; updateScan(); } }, 15000);
  }
  function refreshDone() {
    if (!S.refreshing) return;
    var wait = Math.max(0, 700 - (Date.now() - S.refreshStart));
    var changed = S.changedSince;
    setTimeout(function () {
      if (!S.refreshing) return;
      S.refreshing = false;
      updateScan();
      if (changed) snack(t("js.ha.toast.refresh_changes", { n: changed }), { kind: "success", ms: 3200 });
    }, wait);
  }

  function doScan() {
    if (S.scanBusy || S.activity.search) return;
    S.scanBusy = true;
    updateScan();
    api("/api/scan/quick", { method: "POST" }).then(function (list) {
      // An address appears only once in the acquisition list.
      var once = {};
      S.found = (Array.isArray(list) ? list : []).filter(function (h) {
        if (!h.ip || once[h.ip]) return false;
        once[h.ip] = true;
        return true;
      });
      var n = S.found.length;
      S.scanned = true;
      S.scanDone = true;
      try { localStorage.setItem("vedetta-ha-scanned", "1"); } catch (err) { /* ignore */ }
      renderNew();
      snack(n === 0 ? t("js.ha.toast.scan_none") : t("js.ha.toast.scan_found", { n: n }), { kind: "success" });
      // The card of found devices may sit below the visible part (on mobile especially).
      if (n && !newEl.hidden && newEl.scrollIntoView) newEl.scrollIntoView({ behavior: "smooth", block: "start" });
    }).catch(function () {
      snack(t("js.ha.toast.scan_failed"), { kind: "error" });
    }).then(function () {
      S.scanBusy = false;
      updateScan();
    });
  }

  // ----------------------------------------------------------------- tile
  var groupsEl = $("groups");

  function prepare(d) {
    d.type = I.typeIcon[d.type] ? d.type : "generic";
    d._hay = [d.name, d.ip, d.mac, d.brand, d.vendor, d.title, typeLabel(d.type), typePlural(d.type)]
      .filter(Boolean).join(" ").toLowerCase();
    return d;
  }
  function rebuildList() {
    S.list = Array.from(S.devices.values()).sort(function (a, b) { return ipKey(a.ip) - ipKey(b.ip) || a.name.localeCompare(b.name); });
  }

  function createTile(d, index) {
    var el = document.createElement("div");
    el.className = "tile rp";
    el.setAttribute("role", "button");
    el.tabIndex = 0;
    el.dataset.id = d.id;
    el.style.animationDelay = Math.min(index || 0, 14) * 22 + "ms";
    el.innerHTML =
      '<span class="tile-icon"><span class="ic"></span><span class="ring"></span></span>' +
      '<span class="tile-body"><span class="tile-name"></span><span class="tile-ip"></span><span class="tile-state"></span><span class="tile-sub"><span class="tile-sub-txt"></span><span class="tile-batt" role="img" style="display:inline-flex;vertical-align:-2px;margin-left:.35em;opacity:.65"></span></span></span>' +
      '<button type="button" class="icon-btn small tile-open touch rp" title="' + esc(t("js.ha.act.open")) + '" aria-label="' + esc(t("js.ha.act.open")) + '">' + icon("open-in-new") + "</button>" +
      '<button type="button" class="icon-btn small tile-wake touch rp" hidden>' + icon("power") + "</button>" +
      '<span class="hbar" role="img"></span>';
    el._r = {
      ic: el.querySelector(".ic"), name: el.querySelector(".tile-name"), ip: el.querySelector(".tile-ip"), subRow: el.querySelector(".tile-sub"), state: el.querySelector(".tile-state"),
      sub: el.querySelector(".tile-sub-txt"), batt: el.querySelector(".tile-batt"), wake: el.querySelector(".tile-wake"), open: el.querySelector(".tile-open"), hbar: el.querySelector(".hbar")
    };
    el._r.wake.title = t("js.ha.act.wake");
    el._r.wake.setAttribute("aria-label", t("js.ha.act.wake"));
    S.tiles.set(d.id, el);
    return el;
  }

  // Network roles (gateway, DHCP, DNS, router, AP, repeater) and the repeater it goes through.
  function roleText(ip) {
    var rr = (S.roles.by_ip || {})[ip];
    return rr ? Object.keys(rr).map(function (k) { return t("js.ha.role." + k); }).join(" \u00b7 ") : "";
  }
  function viaText(ip, short) {
    var v = (S.roles.via || {})[ip];
    if (!v) return "";
    if (!v.ip) return short ? t("js.ha.via.short", { name: t("js.ha.role.repeater").toLowerCase() }) : t("js.ha.via.unknown", { mac: v.mac });
    var name = v.name || v.ip;
    return short ? t("js.ha.via.short", { name: name }) : name + " (" + v.ip + ")";
  }
  function updateTile(id) {
    var d = S.devices.get(id), el = S.tiles.get(id);
    if (!d || !el) return;
    var r = el._r;
    el.classList.toggle("online", d.online);
    el.classList.toggle("offline", !d.online);
    el.dataset.type = d.type;
    el.classList.toggle("scanning", S.activity.rescanning.has(id));
    if (el._type !== d.type + "|" + d.icon) { el._type = d.type + "|" + d.icon; r.ic.innerHTML = icon(devIcon(d)); }
    if (r.name.textContent !== d.name) r.name.textContent = d.name;
    var st = stateText(d);
    if (r.state.textContent !== st) r.state.textContent = st;
    var chip = [roleText(d.ip), viaText(d.ip, true), chipText(d)].filter(Boolean).join(" \u00b7 ");
    // Order: name, IP (in full), status and latency, other information (role, brand/chip, battery).
    if (r.ip.textContent !== d.ip) r.ip.textContent = d.ip;
    if (r.sub.textContent !== chip) r.sub.textContent = chip;
    // Battery: discreet icon only if the device is certainly battery-powered.
    var bt = DEBUG && d.battery === "yes" ? batteryTitle(d) : "";
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
    el.setAttribute("aria-label", d.name + ", " + st);
    renderHbar(id);
  }

  // Mini bar of the last 24 h (like the HA history bar): sliding window
  // ending now, clipped segments; with no data it stays empty.
  function renderHbar(id) {
    var el = S.tiles.get(id);
    if (!el) return;
    var bar = el._r.hbar, h = S.hist.get(id);
    var html = "", title = "";
    if (h && h.segments.length) {
      var to = nowSec(), from = to - 86400, span = 86400;
      h.segments.forEach(function (s, i) {
        var end = (i === h.segments.length - 1 && s.to >= h.to - 5) ? to : s.to;
        var a = Math.max(s.from, from), b = Math.min(end, to);
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

  function reconcile(parent, nodes) {
    var ref = parent.firstChild;
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

  function emptyState(kind) {
    var el = document.createElement("div");
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

  function layout() {
    if (!S.loaded) return;
    var visible = S.list.filter(matches);
    if (COMPACT) return layoutCompact(visible);
    var nodes = [];
    TYPE_ORDER.forEach(function (type) {
      var items = visible.filter(function (d) { return d.type === type; });
      var g = S.groups[type];
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
      var online = items.filter(function (d) { return d.online; }).length;
      g.count.textContent = String(items.length);
      g.sub.textContent = online === items.length ? "" : t("js.ha.group.online", { n: online });
      var tiles = items.map(function (d, i) {
        var el = S.tiles.get(d.id) || createTile(d, i);
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
    var rank = function (d) { return d.online ? 2 : (d.is_mobile ? 1 : 0); };
    var sorted = visible.slice().sort(function (a, b) { return rank(a) - rank(b) || a.name.localeCompare(b.name); });
    var shown = sorted.slice(0, COMPACT_LIMIT);
    var card = document.createElement("div");
    card.className = "ha-card compact-list";
    var full = new URLSearchParams(location.search);
    full.delete("compact");
    full.delete("limit");
    var html = '<div class="card-header slim"><div class="ch-title">' + esc(t("js.ha.devices")) + "</div></div><div class=\"crows\">";
    if (!shown.length) html += '<div class="crow-empty">' + esc(t("js.ha.empty.title")) + "</div>";
    shown.forEach(function (d) {
      html += '<div class="crow rp ' + (d.online ? "online" : "offline") + '" data-type="' + esc(d.type) + '" role="button" tabindex="0" data-id="' + esc(d.id) + '">' +
        '<span class="tile-icon"><span class="ic">' + icon(devIcon(d)) + '</span></span>' +
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
    var opn = e.target.closest(".tile-open");
    if (opn) {
      e.stopPropagation();
      var od = S.devices.get(opn.closest(".tile").dataset.id);
      // When offline the button is grey and does nothing.
      if (od && od.online) openExternal(od.url || "http://" + od.ip + (od.port && od.port !== 80 ? ":" + od.port : ""));
      return;
    }
    var wake = e.target.closest(".tile-wake");
    if (wake) {
      e.stopPropagation();
      var wid = wake.closest(".tile").dataset.id;
      return wakeDevice(wid);
    }
    var empty = e.target.closest("[data-empty]");
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
    var host = e.target.closest("[data-id]");
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

  function flash(id, kind) {
    var el = S.tiles.get(id);
    if (!el || REDUCED) return;
    var ic = el.querySelector(".tile-icon");
    ic.classList.remove("flash-on", "flash-off");
    void ic.offsetWidth;
    ic.classList.add(kind === "on" ? "flash-on" : "flash-off");
  }

  // ---------------------------------------------------- new devices
  var newEl = $("card-new");
  // Rows of the card: the devices found by the last scan (S.found, with
  // Add) and the never-seen MACs detected on the network (S.newDevices); no duplicates by IP.
  function newRows() {
    var seen = {}, rows = [];
    // The same device appears only once: by IP or by MAC.
    function keys(d) {
      var k = [];
      if (d.ip) k.push("i:" + d.ip);
      if (d.mac) k.push("m:" + String(d.mac).toUpperCase());
      return k;
    }
    function take(row) {
      var k = keys(row);
      if (k.some(function (x) { return seen[x]; })) return;
      k.forEach(function (x) { seen[x] = true; });
      rows.push(row);
    }
    S.found.forEach(function (h) {
      take({ src: "found", ip: h.ip, mac: h.mac });
    });
    // Never-seen MACs detected on the network are added only after a completed scan.
    var list = (S.scanDone || S.newReady) ? S.newDevices.devices : [];
    list.forEach(function (d) {
      take({ src: "new", ip: d.ip, mac: d.mac });
    });
    // In IP address order (those without a known one at the bottom).
    rows.sort(function (a, b) { return (a.ip ? ipKey(a.ip) : Infinity) - (b.ip ? ipKey(b.ip) : Infinity); });
    return rows;
  }
  function renderNew() {
    if (COMPACT) { newEl.hidden = true; return; }
    var list = newRows();
    if (!list.length) { newEl.hidden = true; newEl.innerHTML = ""; return; }
    newEl.hidden = false;
    var ad = S.adding;  // {ips: {ip: true}, done: {ip: true}} during the add
    var busy = !!ad;
    var rows = list.map(function (d) {
      var working = busy && ad.ips[d.ip], finished = working && ad.done[d.ip];
      var label = d.ip || d.mac;  // only IP and MAC: names are found later, by analyzing the device
      var state = finished ? " is-done" : working ? " is-adding" : "";
      var actions;
      if (working) {
        actions = '<span class="nd-status">' + esc(finished ? t("js.ha.new.done") : t("js.ha.new.analyzing")) + "</span>";
      } else {
        var dis = "";  // the other rows stay usable: additions run in parallel
        var ignoreBtn = d.src === "found"
          ? '<button type="button" class="btn text rp" data-ign-ip="' + esc(d.ip) + '"' + dis + ' data-ign-mac="' + esc(d.mac || "") +
            '" data-ign-host="' + esc(d.name || "") + '">' + esc(t("js.ha.new.ignore")) + "</button>"
          : '<button type="button" class="btn text rp"' + dis + ' data-ignore-mac="' + esc(d.mac) + '">' + esc(t("js.ha.new.ignore")) + "</button>";
        actions = (d.ip ? '<button type="button" class="btn tonal rp"' + dis + ' data-add-ip="' + esc(d.ip) + '" data-add-host="' + esc(d.name || "") + '">' +
          esc(t("js.ha.new.add_one")) + "</button>" : "") + ignoreBtn;
      }
      return '<div class="nd-row' + state + '" data-ip="' + esc(d.ip || "") + '"><span class="nd-ic">' + icon(finished ? "check" : "devices") +
        '</span><div class="nd-text"><div class="nd-name">' + esc(label) +
        '</div><div class="nd-sub">' + esc(d.ip && d.mac ? d.mac : "") + '</div></div>' +
        '<div class="nd-actions">' + actions + "</div></div>";
    }).join("");
    var title, sub;
    if (busy) {
      var total = Object.keys(ad.ips).length, done = Object.keys(ad.done).length;
      title = t("js.ha.new.progress", { done: done, total: total });
      sub = t("js.ha.new.progress_hint");
    } else {
      title = S.found.length ? t("js.ha.new.found", { n: list.length }) : t("js.ha.new.title", { n: list.length });
      sub = t("js.ha.new.hint");
    }
    var actionsBar = "";
    var dsb = busy ? " disabled" : "";
    var free = S.found.filter(function (h) { return !(busy && ad.ips[h.ip]); }).length;
    if (free > 1) actionsBar += '<button type="button" class="btn text rp" data-add-all="1">' + esc(t("js.ha.new.add_all")) + "</button>";
    if (list.length > 1 || busy) actionsBar += '<button type="button" class="btn text rp" data-ignore-all="1">' + esc(t("js.ha.new.cancel_all")) + "</button>";
    newEl.innerHTML =
      '<div class="card-header"><span class="ch-ic warn' + (busy ? " is-adding" : "") + '">' + icon("plus-circle") + '</span><div class="ch-text"><div class="ch-title small">' +
      esc(title) + '</div><div class="ch-sub">' + esc(sub) + "</div></div>" +
      // "Add all" and "Cancel" at the top right, on the title row
      (actionsBar ? '<div class="nd-head-actions">' + actionsBar + "</div>" : "") + "</div>" +
      '<div class="nd-list">' + rows + "</div>" +
      (busy ? '<div class="progress indet" aria-hidden="true"><div class="bar"></div></div>' : "");
  }
  // Adding directly from here (in the HA mobile app a link to the classic
  // dashboard would be blocked): associative search on the devices by recommended
  // name and port, then a single save.
  function scanMany(ips, hosts, onResult, signal) {
    var hints = {}, NL = String.fromCharCode(10);
    ips.forEach(function (ip) { if (hosts[ip]) hints[ip] = hosts[ip]; });
    var results = [], complete = [];
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
      body: JSON.stringify({ ips: ips, hints: hints }), signal: signal
    }).then(function (r) {
      // Stream reading: each completed device is reported immediately.
      if (!r.body || !r.body.getReader) {
        return r.text().then(function (txt) { txt.split(NL).forEach(eat); });
      }
      var reader = r.body.getReader(), dec = new TextDecoder(), buf = "";
      function pump() {
        return reader.read().then(function (x) {
          if (x.done) { buf.split(NL).forEach(eat); return; }
          buf += dec.decode(x.value, { stream: true });
          var lines = buf.split(NL);
          buf = lines.pop();
          lines.forEach(eat);
          return pump();
        });
      }
      return pump();
    }).then(function () { return complete.length ? complete : results; }).catch(function () { return complete.length ? complete : results; });
  }
  function toDevice(ip, host, r) {
    return { ip: ip, name: (r && r.suggested_name) || host || ip, adapter: (r && r.adapter) || "generic",
      port: (r && r.suggested_port) || 80, scan_info: r && r.scan_info, name_source: r && r.name_source };
  }
  function afterAdd(ips) {
    // Rows already added stay green ("Finished") for the duration of the batch: they are removed
    // all together at the end, both with "Add all" and when adding one device at a time.
    if (S.adding) (S.adding.added || (S.adding.added = [])).push.apply(S.adding.added, ips);
    else S.found = S.found.filter(function (h) { return ips.indexOf(h.ip) < 0; });
    snack(t("js.ha.new.added"), { kind: "success" });
    return api("/api/new-devices").then(function (list) {
      if (Array.isArray(list)) S.newDevices = { count: list.length, devices: list, init: true };
      renderNew();
      S.dirty.net = true;
      schedule();
    });
  }
  function addDevices(ips, hosts) {
    // "Adding" state, shared among several parallel additions: the affected rows
    // blink, turn green when their device has been analyzed, and the
    // card shows "N of M" of the total. The other rows stay clickable: each new
    // addition starts at once with its own search (the server queues the heavy jobs).
    var ad = S.adding || (S.adding = { ips: {}, done: {}, jobs: 0 });
    ips = ips.filter(function (ip) { return !ad.ips[ip]; });
    if (!ips.length) return;
    ips.forEach(function (ip) { ad.ips[ip] = true; });
    ad.jobs++;
    var job = { ips: ips, cancelled: false, ctrl: window.AbortController ? new AbortController() : null };
    (ad.list || (ad.list = [])).push(job);
    renderNew();
    function finish() {
      ad.jobs--;
      if (ad.jobs <= 0 && S.adding === ad) {
        S.adding = null;
        if (ad.added && ad.added.length) S.found = S.found.filter(function (h) { return ad.added.indexOf(h.ip) < 0; });
        if (S.cancelAll) {  // Cancel: list closed when all additions have stopped
          S.cancelAll = false;
          S.found = [];
          S.scanDone = false;
          renderNew();
        }
      }
    }
    var use = ips;
    scanMany(ips, hosts, function (r) { ad.done[r.ip] = true; renderNew(); }, job.ctrl && job.ctrl.signal).then(function (results) {
      var byIp = {};
      results.forEach(function (r) { byIp[r.ip] = r; });
      // Cancelled: only the devices whose analysis had already finished are kept.
      use = job.cancelled ? ips.filter(function (ip) { return byIp[ip]; }) : ips;
      use.forEach(function (ip) { ad.done[ip] = true; });
      renderNew();
      if (!use.length) return null;
      var devices = use.map(function (ip) { return toDevice(ip, hosts[ip], byIp[ip]); });
      return api("/api/devices/add", { method: "POST", json: { devices: devices } });
    }).then(function (res) {
      finish();
      return res ? afterAdd(use) : null;
    }).catch(function () {
      ips.forEach(function (ip) { delete ad.ips[ip]; delete ad.done[ip]; });
      finish();
      renderNew();
      snack(t("js.ha.toast.error"), { kind: "error" });
    });
  }
  newEl.addEventListener("click", function (e) {
    var add = e.target.closest("[data-add-ip]");
    if (add) {
      var hosts = {};
      hosts[add.dataset.addIp] = add.dataset.addHost;
      addDevices([add.dataset.addIp], hosts);
      return;
    }
    var all = e.target.closest("[data-add-all]");
    if (all) {
      var map = {};
      S.found.forEach(function (h) { map[h.ip] = h.hostname || ""; });
      addDevices(S.found.map(function (h) { return h.ip; }), map);  // those already in progress are skipped
      return;
    }
    if (S.adding && e.target.closest("[data-ignore-all]")) {
      // Cancel during an add: the analyses in progress are stopped (on the server too) and
      // only the already analyzed devices are added; then the list closes.
      var pending = [];
      (S.adding.list || []).forEach(function (job) {
        job.cancelled = true;
        job.ips.forEach(function (ip) { if (!S.adding.done[ip]) pending.push(ip); });
        if (job.ctrl) job.ctrl.abort();
      });
      S.cancelAll = true;
      if (pending.length) api("/api/scan/cancel", { method: "POST", json: { ips: pending } }).catch(function () {});
      snack(t("js.ha.new.cancelled"), { ms: 4000 });
      return;
    }
    var ign = e.target.closest("[data-ign-ip]");
    if (ign) {
      ign.disabled = true;
      api("/api/ignored/hosts", { method: "POST", json: { hosts: [{ ip: ign.dataset.ignIp, mac: ign.dataset.ignMac || null, hostname: ign.dataset.ignHost || null }] } })
        .then(function () {
          S.found = S.found.filter(function (h) { return h.ip !== ign.dataset.ignIp; });
          renderNew();

        }).catch(function () {
          ign.disabled = false;
          snack(t("js.ha.toast.error"), { kind: "error" });
        });
      return;
    }
    var ia = e.target.closest("[data-ignore-all]");
    if (ia) {
      // Cancel: closes the list of this scan; the devices are not ignored
      // and a new scan finds them again.
      S.found = [];
      S.scanDone = false;
      renderNew();
      return;
    }
    var b = e.target.closest("[data-ignore-mac]");
    if (!b) return;
    var mac = b.dataset.ignoreMac;
    b.disabled = true;
    api("/api/new-devices/ignore", { method: "POST", json: mac === "*" ? {} : { macs: [mac] } }).then(function (list) {
      if (Array.isArray(list)) S.newDevices = { count: list.length, devices: list, init: true };
      renderNew();
      S.dirty.net = true;
      schedule();

    }).catch(function () {
      b.disabled = false;
      snack(t("js.ha.toast.error"), { kind: "error" });
    });
  });

  // --------------------------------------------------------------- log
  var logEl = $("card-log");
  function dayLabel(ts) {
    var d = new Date(ts * 1000), n = new Date();
    var key = function (x) { return x.getFullYear() * 400 + x.getMonth() * 32 + x.getDate(); };
    var y = new Date(n.getTime() - 86400000);
    if (key(d) === key(n)) return t("js.ha.day.today");
    if (key(d) === key(y)) return t("js.ha.day.yesterday");
    return d.toLocaleDateString(LANG, { weekday: "long", day: "numeric", month: "long" });
  }
  var LOG_LEVELS = ["min", "normal", "detail"];
  function renderLog(onlyRows) {
    if (COMPACT) { logEl.hidden = true; return; }
    logEl.hidden = false;
    var all = S.log.events, html = "", lastDay = "";
    var prev = S.log.ids;
    // Search: on text, name and IP (lowercase), without reloading from the server.
    var q = (S.log.q || "").trim().toLowerCase();
    var ev = q ? all.filter(function (e) {
      return [e.message, e.name, e.ip, typeLabel(e.type)].join(" ").toLowerCase().indexOf(q) >= 0;
    }) : all;
    // Only consecutive state changes of the same device are grouped.
    var IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/;
    var groups = [];
    ev.forEach(function (e) {
      var last = groups[groups.length - 1];
      var key = e.kind === "event" ? e.id : (e.device_id || e.name);
      if (e.kind !== "event" && last && last.key === key && dayLabel(last.e.ts) === dayLabel(e.ts)) last.n++;
      else groups.push({ key: key, e: e, n: 1 });
    });
    groups.forEach(function (g) {
      var e = g.e, day = dayLabel(e.ts);
      if (day !== lastDay) { lastDay = day; html += '<div class="log-day">' + esc(day) + "</div>"; }
      var fresh = prev && !prev.has(e.id) ? " fresh" : "";
      if (e.kind === "event") {
        var tone = e.icon === "alert" ? " warn" : "";
        html += '<div class="log-row svc' + fresh + '"><span class="log-ic svc' + tone + '">' + icon(e.icon || "history") + "</span>" +
          '<span class="log-text"><span class="log-msg">' + esc(e.message) + '</span><span class="log-ago" data-ts="' + e.ts + '">' + esc(ago(e.ts)) +
          "</span></span>" + '<span class="log-time">' + esc(fmtClock(e.ts)) + "</span></div>";
        return;
      }
      var cls = e.online ? "on" : "off";
      var name = IPV4.test(e.name || "") && e.type && e.type !== "generic" ? typeLabel(e.type) + " " + e.name : e.name;
      var msg = g.n > 1 ? t("js.ha.log.flap", { n: g.n, state: t(e.online ? "js.ha.state.online" : "js.ha.state.offline") }) : e.message;
      html += '<' + (e.known ? 'button type="button"' : 'div') + ' class="log-row' + (e.known ? " rp" : "") + fresh + '"' + (e.known ? ' data-id="' + esc(e.device_id) + '"' : "") + ">" +
        '<span class="log-ic ' + cls + '">' + icon(e.dev_icon && I.paths[e.dev_icon] ? e.dev_icon : typeIcon(e.type)) + "</span>" +
        '<span class="log-text"><span class="log-msg"><b>' + esc(name) + "</b> " + esc(msg) + '</span><span class="log-ago" data-ts="' + e.ts + '">' + esc(ago(e.ts)) + "</span></span>" +
        '<span class="log-time">' + esc(fmtClock(e.ts)) + "</span></" + (e.known ? "button" : "div") + ">";
    });
    if (!ev.length) {
      html = q
        ? '<div class="log-empty">' + icon("magnify") + "<div><b>" + esc(t("js.ha.log.nomatch")) + "</b></div></div>"
        : '<div class="log-empty">' + icon("history") + "<div><b>" + esc(t("js.ha.log.empty")) + "</b><span>" + esc(t("js.ha.log.empty_hint")) + "</span></div></div>";
    }
    if (onlyRows && S.log.open && $("log-rows")) {
      // While typing only the list is updated: the field does not lose the cursor.
      $("log-rows").innerHTML = html;
      var subEl = logEl.querySelector(".ch-sub");
      if (subEl) subEl.textContent = t("js.ha.log.level_" + S.log.level) + " · " + t("js.ha.log.today", { n: all.filter(function (e) { return dayLabel(e.ts) === dayLabel(Date.now() / 1000); }).length });
      S.log.ids = new Set(all.map(function (e) { return e.id; }));
      return;
    }
    var more = all.length >= S.log.limit && S.log.limit < 200
      ? '<div class="card-actions"><button type="button" class="btn text rp" id="log-more">' + esc(t("js.ha.log.more")) + "</button></div>" : "";
    var today = dayLabel(Date.now() / 1000);
    var nToday = all.filter(function (e) { return dayLabel(e.ts) === today; }).length;
    var sub = t("js.ha.log.level_" + S.log.level) + " · " + t("js.ha.log.today", { n: nToday });
    logEl.innerHTML = '<div class="card-header log-head rp" id="log-toggle" role="button" tabindex="0" aria-expanded="' + S.log.open + '">' +
      '<div class="ch-text"><div class="ch-title">' + esc(t("js.ha.log.title")) + '</div><div class="ch-sub">' + esc(sub) + "</div></div>" +
      '<span class="log-chev">' + icon("chevron-down") + "</span></div>" +
      (S.log.open ? '<div class="log-search"><label class="search">' + icon("magnify", "search-icon") +
        '<input type="search" id="log-q" autocomplete="off" placeholder="' + esc(t("js.ha.log.search")) + '" value="' + esc(S.log.q) + '"></label>' +
        // Log level: next to the search, in a column with the title arrow
        '<button type="button" class="icon-btn touch rp" id="log-level-btn" aria-haspopup="true" aria-expanded="false" title="' + esc(t("js.ha.log.level")) +
        '" aria-label="' + esc(t("js.ha.log.level")) + '">' + icon("format-list-bulleted-type") + "</button></div>" +
        '<div class="log-list" id="log-rows">' + html + "</div>" + more : "");
    logEl.classList.toggle("is-open", S.log.open);
    S.log.ids = new Set(all.map(function (e) { return e.id; }));
  }
  // Log level menu: same buttons as the dashboard menu.
  var logMenuEl = $("log-menu");
  function buildLogMenu() {
    logMenuEl.innerHTML = menuGroup(t("js.ha.log.level"), LOG_LEVELS.map(function (l) {
      return pill("md", "loglevel", l, l === S.log.level, t("js.ha.log.level_" + l));
    }).join("")) + '<div class="menu-hint">' + esc(t("js.ha.log.hint_" + S.log.level)) + "</div>";
  }
  function toggleLogMenu(open) {
    if (open === undefined) open = logMenuEl.hidden;
    var btn = $("log-level-btn");
    if (open && btn) {
      closePopups("log");
      buildLogMenu();
      var r = btn.getBoundingClientRect();
      logMenuEl.style.top = Math.round(r.bottom + 4) + "px";
      logMenuEl.style.left = "auto";
      logMenuEl.style.right = Math.max(8, Math.round(window.innerWidth - r.right)) + "px";
    }
    logMenuEl.hidden = !open;
    if (btn) btn.setAttribute("aria-expanded", String(open));
  }
  logMenuEl.addEventListener("click", function (e) {
    var item = e.target.closest("[data-loglevel]");
    if (!item) return;
    S.log.level = item.dataset.loglevel;
    try { localStorage.setItem("vedetta-ha-loglevel", S.log.level); } catch (err) { /* ignore */ }
    toggleLogMenu(false);
    S.log.open = true;
    fetchLog();
  });
  document.addEventListener("click", function (e) {
    if (!logMenuEl.hidden && !e.target.closest("#log-menu") && !e.target.closest("#log-level-btn")) toggleLogMenu(false);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !logMenuEl.hidden) toggleLogMenu(false);
  });
  window.addEventListener("resize", function () { if (!logMenuEl.hidden) toggleLogMenu(false); });
  logEl.addEventListener("click", function (e) {
    if (e.target.closest("#log-level-btn")) { e.stopPropagation(); toggleLogMenu(); return; }
    if (e.target.closest("#log-toggle")) { S.log.open = !S.log.open; if (!S.log.open) S.log.q = ""; renderLog(); return; }
    if (e.target.closest("#log-more")) {
      S.log.limit = Math.min(200, S.log.limit + 30);
      fetchLog();
      return;
    }
    var row = e.target.closest("[data-id]");
    if (row) openMore(row.dataset.id);
  });
  logEl.addEventListener("input", function (e) {
    if (e.target.id !== "log-q") return;
    S.log.q = e.target.value;
    renderLog(true);
  });
  logEl.addEventListener("keydown", function (e) {
    if ((e.key === "Enter" || e.key === " ") && e.target.id === "log-toggle") { e.preventDefault(); S.log.open = !S.log.open; renderLog(); }
  });
  function fetchLog() {
    return api("/api/ha/logbook?limit=" + S.log.limit + "&level=" + S.log.level).then(function (r) {
      S.log.events = r.events || [];
      // With the log open only the rows are updated: search and scroll stay.
      renderLog(S.log.open && !!$("log-rows"));
    }).catch(function () { /* the log is secondary: retry at the next change */ });
  }
  var fetchLogSoon = debounce(fetchLog, 1500);

  function fetchHist() {
    return api("/api/ha/history?hours=24").then(function (r) {
      Object.keys(r.devices || {}).forEach(function (id) { S.hist.set(id, r.devices[id]); });
      S.tiles.forEach(function (el, id) { renderHbar(id); });
    }).catch(function () { /* without history the bars stay empty */ });
  }
  // A live state change extends/closes the last segment without requesting anything.
  function histPush(id, online) {
    var h = S.hist.get(id), now = Math.floor(nowSec());
    if (!h) { h = { from: now - 86400, to: now, segments: [], online_pct: null }; S.hist.set(id, h); }
    var last = h.segments[h.segments.length - 1];
    if (last) last.to = now;
    h.segments.push({ from: now, to: now, online: online });
    h.to = now;
  }

  // ------------------------------------------------- "More info" dialog
  var dlg = $("more");
  function openMore(id) {
    if (!S.devices.has(id)) return;
    S.open = id;
    S.mi.moreOpen = false;   // "Other attributes" always starts closed
    S.mi.range = 24;
    S.mi.view = "main";
    S.mi.win = {};
    renderMore();
    if (!dlg.open) {
      if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
      if (snacksEl.children.length) raiseSnacks();
    }
  }
  function closeMore() {
    if (dlg.open && typeof dlg.close === "function") dlg.close(); else dlg.removeAttribute("open");
    S.open = null;
  }
  dlg.addEventListener("close", function () { S.open = null; });
  dlg.addEventListener("click", function (e) { if (e.target === dlg) closeMore(); });

  function miHeader(d, title, back) {
    return '<div class="mi-header"><button type="button" class="icon-btn touch rp" data-act="' + (back ? "back" : "close") + '" aria-label="' +
      esc(t("js.ha.more.close")) + '">' + icon("close") + '</button><div class="mi-titles"><div class="mi-name-row"><h2 class="mi-title" id="more-title">' + esc(title) +
      "</h2>" + (d ? '<button type="button" class="icon-btn small touch rp" data-act="rename" title="' + esc(t("js.ha.act.rename")) +
      '" aria-label="' + esc(t("js.ha.act.rename")) + '">' + icon("pencil") + "</button>" +
      '<button type="button" class="icon-btn small touch rp" data-act="ignore" title="' + esc(t("js.ha.act.ignore")) +
      '" aria-label="' + esc(t("js.ha.act.ignore")) + '">' + icon("eye-off") + "</button>" : "") + "</div>" + (d ? '<div class="mi-sub" id="mi-sub">' + esc(miSub(d)) + "</div>" : "") + "</div></div>";
  }
  function miSub(d) { return [chipText(d), typeLabel(d.type)].filter(Boolean).join(" · "); }

  function renderMore() {
    var d = S.devices.get(S.open);
    if (!d) return closeMore();
    if (S.mi.view === "rename") return renderRename(d);
    if (S.mi.view === "brand") return renderBrandEdit(d);
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

  function miHero(d) {
    var el = $("mi-hero");
    if (!el) return;
    el.className = "mi-hero " + (d.online ? "online" : "offline");
    el.innerHTML = '<span class="hero-ic">' + icon(devIcon(d)) + '</span><div><div class="hero-state">' +
      esc(d.online ? t("js.ha.state.online") : t("js.ha.state.offline")) + '</div><div class="hero-sub">' + esc(heroSub(d)) + "</div></div>" +
      (canWake(d) ? '<button type="button" class="icon-btn small touch rp hero-wake" data-act="wake" title="' + esc(t("js.ha.act.wake")) +
        '" aria-label="' + esc(t("js.ha.act.wake")) + '">' + icon("power") + "</button>" : "");
  }
  function heroSub(d) {
    if (d.online) return d.uptime != null ? t("js.ha.more.up_for", { uptime: fmtUptime(d.uptime) }) : "";
    return d.last_seen ? t("js.ha.more.seen_at", { ago: ago(d.last_seen), time: fmtStamp(d.last_seen, true) }) : "";
  }

  // Debug mode: why the device has this type, name and brand (data from the server, not in the normal list).
  var dbgFetch = { id: null, at: 0, data: null };
  function miDebug(d) {
    var el = $("mi-debug");
    if (!el) return;
    if (!DEBUG) { el.innerHTML = ""; return; }
    function fmt(o) {
      return Object.keys(o || {}).map(function (k) { return k + " " + o[k]; }).join(", ") || "-";
    }
    function draw(x) {
      if (!x) return;
      var rows = [
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

  function miAttrs(d) {
    var el = $("mi-attrs");
    if (!el) return;
    // Always visible: IP, MAC, response time, ports. The rest is in the "Other attributes" dropdown.
    var rows = [], fixedRows = [];
    function row(label, value, extra, fixed, cls) { (fixed ? fixedRows : rows).push({ label: label, html: value, extra: extra || "", cls: cls || "" }); }
    row(t("js.ha.attr.ip"), esc(d.ip + (d.port && d.port !== 80 ? ":" + d.port : "")),
      d.url && canOpen(d) ? '<a class="icon-btn small touch rp" href="' + esc(d.url) + '" target="_blank" rel="noopener" title="' + esc(t("js.ha.act.open")) +
        '" aria-label="' + esc(t("js.ha.act.open")) + '">' + icon("open-in-new") + "</a>" : "", true);
    if (d.mac) row(t("js.ha.attr.mac"), '<span class="mono">' + esc(d.mac) + "</span>",
      '<button type="button" class="icon-btn small touch rp" data-copy="' + esc(d.mac) + '" title="' + esc(t("js.ha.act.copy_mac")) + '" aria-label="' + esc(t("js.ha.act.copy_mac")) + '">' + icon("content-copy") + "</button>", true);
    // Two levels: product brand (with the source) and MAC manufacturer (chip/board).
    var ev = DEBUG && d.brand_evidence ? '<span class="ev ev-' + esc(d.brand_evidence) + '">' + esc(t("js.ha.ev." + d.brand_evidence)) + "</span>" : "";
    row(t("js.ha.attr.brand"), d.brand
      ? esc(d.brand) + (DEBUG && d.brand_source ? ' <span class="dbg-txt">· ' + esc(t("js.ha.brand_src." + d.brand_source)) + "</span>" : "") + ev
      : d.brand_declared
        ? '<span style="opacity:.75">' + esc(t("js.ha.brand_declared", { value: d.brand_declared })) + "</span>"
        : '<span style="opacity:.65">' + esc(t("js.ha.brand_unknown")) + "</span>",
      '<button type="button" class="icon-btn small touch rp" data-act="brand-edit" title="' + esc(t("js.ha.act.edit_brand")) +
        '" aria-label="' + esc(t("js.ha.act.edit_brand")) + '">' + icon("pencil") + "</button>");
    if (DEBUG && d.name_source) row(t("js.ha.attr.name_src"), esc(d.name_source), "", false, "dbg");
    var rr = (S.roles.by_ip || {})[d.ip];
    if (rr) row(t("js.ha.attr.roles"), Object.keys(rr).map(function (k) {
      return esc(t("js.ha.role." + k)) + ' <span style="opacity:.65">(' + esc(t("js.ha.role_src." + rr[k])) + ")</span>";
    }).join(", "));
    if ((S.roles.via || {})[d.ip]) row(t("js.ha.attr.via"), esc(viaText(d.ip, false)));
    var net = S.roles.internet;
    if (net && rr && rr.gateway) {
      var np = [];
      if (net.public_ip) np.push(t("js.ha.net.public", { ip: net.public_ip }));
      np.push(net.cgnat ? t("js.ha.net.cgnat") : net.double_nat ? t("js.ha.net.double", { ips: (net.private_hops || []).join(" \u2192 ") }) : t("js.ha.net.direct"));
      row(t("js.ha.attr.internet"), esc(np.join(" \u00b7 ")));
    }
    (S.roles.dhcp || []).filter(function (o) { return o.server === d.ip; }).forEach(function (o) {
      var parts = [];
      if (o.router) parts.push(t("js.ha.dhcp.router", { v: o.router.join(", ") }));
      if (o.dns) parts.push(t("js.ha.dhcp.dns", { v: o.dns.join(", ") }));
      if (o.domain) parts.push(t("js.ha.dhcp.domain", { v: o.domain }));
      if (o.lease) parts.push(t("js.ha.dhcp.lease", { v: o.lease }));
      if (parts.length) row(t("js.ha.attr.dhcp_gives"), esc(parts.join(" \u00b7 ")));
    });
    if (d.vendor && d.vendor !== d.brand) row(t("js.ha.attr.chip"), esc(chipText({ vendor: d.vendor, vendor_role: d.vendor_role })));
    if (DEBUG && d.battery === "yes") row(t("js.ha.attr.battery"), '<span class="batt-line">' + icon("battery") + "<span>" + esc(batteryTitle(d)) + "</span></span>", "", false, "dbg");
    row(t("js.ha.attr.type"), esc(typeLabel(d.type)) + (d.type_user ? ' <span style="opacity:.65">· ' + esc(t("js.ha.type.manual")) + "</span>" : ""),
      '<button type="button" class="icon-btn small touch rp" data-act="type-menu" aria-haspopup="true" title="' + esc(t("js.ha.act.edit_type")) +
        '" aria-label="' + esc(t("js.ha.act.edit_type")) + '">' + icon("chevron-down") + "</button>");
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
        var p = Object.assign({}, x.p, { category: x.cat });
        // Service not certain (nmap only inferred it from the number): only the port is shown.
        var label = p.confirmed ? p.label : String(p.label || "").split(" · ")[0];
        return '<span class="pill cat-' + esc(p.category) + (p.confirmed ? "" : " guess") + '" title="' + esc(label) + '">' + esc(label) + "</span>";
      }).join("") + "</span>", "", true);
    }
    function html(list) {
      return list.map(function (r) {
        return '<div class="attr' + (r.cls ? " " + r.cls : "") + '"><dt>' + esc(r.label) + '</dt><dd><span class="attr-val">' + r.html + "</span>" + r.extra + "</dd></div>";
      }).join("");
    }
    // Dropdown closed initially; if opened it stays open when the data updates.
    el.innerHTML = html(fixedRows) + (rows.length
      ? '<details class="attr-more" id="attr-more"' + (S.mi.moreOpen ? " open" : "") + "><summary>" + esc(t("js.ha.attr.more", { n: rows.length })) +
        "</summary>" + html(rows) + "</details>"
      : "");
    var det = $("attr-more");
    if (det) det.addEventListener("toggle", function () { S.mi.moreOpen = det.open; });
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
    var n = parseInt(p.label, 10);
    for (var i = 0; i < PORT_CATS.length; i++) {
      var c = PORT_CATS[i];
      if (PORT_NUM[c] && PORT_NUM[c].indexOf(n) >= 0) return c;
    }
    return p.category && PORT_CATS.indexOf(p.category) >= 0 ? p.category : "other";
  }
  function miActions(d) {
    var el = $("mi-actions");
    if (!el) return;
    var html = "";
    // Sharing with Home Assistant (MQTT): only if the link exists. Shared = HA sees the device as a
    // sub-device of "Vedetta"; "Remove" takes it out of HA.
    if (d && S.mqtt && S.mqtt.active) {
      html += '<button type="button" class="btn ' + (d.ha_share ? "outlined" : "tonal") + ' rp" data-act="share">' + icon("home-assistant") +
        "<span>" + esc(t(d.ha_share ? "js.ha.share.remove" : "js.ha.share.add")) + "</span></button>";
    }
    el.innerHTML = html + '<button type="button" class="btn tonal rp" data-act="deep">' + icon("magnify") + "<span>" + esc(t("js.ha.deep.title")) + "</span></button>";
  }

  function updateMore() {
    if (!S.open || !dlg.open || S.mi.view !== "main") return;
    var d = S.devices.get(S.open);
    if (!d) return closeMore();
    var title = $("more-title");
    if (title && title.textContent !== d.name) title.textContent = d.name;
    var sub = $("mi-sub");
    if (sub) sub.textContent = miSub(d);
    miHero(d);
    miAttrs(d);
    miDebug(d);
    miActions(d);
  }

  // History chart: a single segmented band (online / offline / no data)
  // like the HA history bar, with tooltip on hover or touch.
  function loadGraph() {
    var id = S.open, hours = S.mi.range;
    var cached = S.mi.win[hours];
    if (cached && Date.now() - cached.at < 30000) { S.mi.token++; return paintGraph(cached.data, hours); }
    var graph = $("mi-graph");
    if (graph && !cached) graph.innerHTML = '<div class="skeleton sk-graph"></div>';
    var token = ++S.mi.token;
    api("/api/ha/history/" + encodeURIComponent(id) + "?hours=" + hours).then(function (data) {
      if (token !== S.mi.token || S.open !== id) return;
      S.mi.win[hours] = { at: Date.now(), data: data };
      if (hours === S.mi.range) paintGraph(data, hours);
    }).catch(function () {
      if (token !== S.mi.token) return;
      var g = $("mi-graph");
      if (g) g.innerHTML = '<div class="graph-msg">' + esc(t("js.ha.more.history_failed")) + "</div>";
    });
  }

  // Timeline strokes: online/offline segments plus the "no data" gaps,
  // clipped to the window. No intermediate state.
  function bucketsFor(win) {
    var segs = win.segments.slice().sort(function (x, y) { return x.from - y.from; });
    var out = [], cur = win.from;
    segs.forEach(function (s) {
      var a = Math.max(s.from, win.from), b = Math.min(s.to, win.to);
      if (b <= a) return;
      if (a > cur) out.push({ a: cur, b: a, st: "nodata" });
      out.push({ a: a, b: b, st: s.online ? "on" : "off" });
      cur = Math.max(cur, b);
    });
    if (cur < win.to) out.push({ a: cur, b: win.to, st: "nodata" });
    return out;
  }

  // Small line chart (SVG) of the response time: series already reduced by the
  // server to ~120 points [ts, ms]. Empty if there is no data.
  function latencyChart(lat) {
    var pts = lat && lat.points ? lat.points : [];
    if (pts.length < 2) return "";
    var W = 300, H = 56, pad = 3, span = Math.max(1, lat.to - lat.from);
    var max = 1;
    pts.forEach(function (p) { if (p[1] > max) max = p[1]; });
    var line = pts.map(function (p, i) {
      var x = (p[0] - lat.from) / span * W, y = H - pad - p[1] / max * (H - 2 * pad);
      return (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
    }).join(" ");
    var lastX = ((pts[pts.length - 1][0] - lat.from) / span * W).toFixed(1), firstX = ((pts[0][0] - lat.from) / span * W).toFixed(1);
    var area = line + " L" + lastX + " " + H + " L" + firstX + " " + H + " Z";
    return '<div class="lat-chart"><div class="lat-head"><span>' + esc(t("js.ha.more.latency_title")) + "</span><span>" +
      esc(t("js.ha.more.latency_stats", { avg: Math.round(lat.avg), max: Math.round(lat.max) })) + "</span></div>" +
      '<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" role="img" aria-label="' + esc(t("js.ha.more.latency_aria")) + '">' +
      '<path class="lat-area" d="' + area + '"></path><path class="lat-line" d="' + line + '"></path></svg></div>';
  }

  function paintGraph(win, hours) {
    var el = $("mi-graph");
    if (!el) return;
    var latHtml = latencyChart(win.latency);
    if (!win.segments || !win.segments.length) {
      el.innerHTML = '<div class="graph-msg">' + icon("history") + "<span>" + esc(t("js.ha.more.nodata")) + "</span></div>" + latHtml;
      return;
    }
    var from = win.from, to = win.to, span = to - from, longRange = hours > 24;
    var outages = win.segments.filter(function (s) { return !s.online; }).length;
    var label = { on: t("js.ha.more.tip_online_seg"), off: t("js.ha.more.tip_offline_seg"), nodata: t("js.ha.more.nodata") };
    var strip = bucketsFor(win).map(function (b) {
      var left = (b.a - from) / span * 100, w = Math.max(0.4, (b.b - b.a) / span * 100);
      var tip = label[b.st] + "\n" + fmtStamp(b.a, longRange) + " – " + fmtStamp(b.b, longRange);
      return '<i class="' + b.st + '" style="left:' + left.toFixed(2) + "%;width:" + w.toFixed(2) + '%" data-tip="' + esc(tip) + '"></i>';
    }).join("");
    var ticks = [];
    if (!longRange) { for (var h = 0; h <= 24; h += 6) ticks.push(h === 24 ? t("js.ha.more.now") : fmtClock(from + h * 3600)); }
    else {
      for (var d = 0; d < 7; d++) ticks.push(new Date((from + d * 86400) * 1000).toLocaleDateString(LANG, { weekday: "short" }));
      ticks.push(t("js.ha.more.now"));
    }
    var pct = win.online_pct;
    el.innerHTML =
      '<div class="stats">' +
      '<div class="stat"><span class="stat-v">' + outages + '</span><span class="stat-l">' + esc(t("js.ha.more.outages", { n: outages })) + "</span></div></div>" +
      '<div class="chart" role="img" aria-label="' + esc(t("js.ha.more.chart_aria")) + '">' +
        '<div class="tl">' + strip + "</div>" +
        '<div class="axis">' + ticks.map(function (x) { return "<span>" + esc(x) + "</span>"; }).join("") + "</div>" +
        '<div class="tip" id="tip" hidden></div></div>' + latHtml;
  }

  // Single chart tooltip.
  var tipTimer = null;
  function tipFor(e) {
    var chart = e.target.closest ? e.target.closest(".chart") : null;
    if (!chart) {
      var stray = dlg.querySelector(".tip");
      if (stray && !stray.hidden && e.pointerType !== "touch") stray.hidden = true;
      return;
    }
    var tip = chart.querySelector(".tip");
    var target = e.target.closest("[data-tip]");
    if (!target) { tip.hidden = true; return; }
    tip.textContent = target.dataset.tip;
    tip.hidden = false;
    var cr = chart.getBoundingClientRect();
    var x = e.clientX - cr.left;
    var w = tip.offsetWidth;
    x = Math.max(w / 2 + 4, Math.min(cr.width - w / 2 - 4, x));
    tip.style.left = x + "px";
    clearTimeout(tipTimer);
    if (e.pointerType === "touch") tipTimer = setTimeout(function () { tip.hidden = true; }, 1800);
  }
  dlg.addEventListener("pointermove", tipFor);
  dlg.addEventListener("pointerdown", tipFor);
  dlg.addEventListener("pointerleave", function (e) {
    var tip = dlg.querySelector(".tip");
    if (tip && e.pointerType !== "touch") tip.hidden = true;
  });

  function renderRename(d) {
    var mode = d.mobile_mode || "auto";
    dlg.innerHTML = '<div class="mi">' + miHeader(null, t("js.ha.rename.title"), true) +
      '<form class="mi-body" id="rename-form" autocomplete="off">' +
      '<label class="field"><input id="rn-name" type="text" maxlength="80" required placeholder=" " value="' + esc(d.name) + '"><span class="field-label">' + esc(t("js.ha.rename.name")) + "</span></label>" +
      '<div class="field-group"><div class="field-caption">' + esc(t("js.ha.rename.mobile")) + '</div><div class="seg wide" role="radiogroup" id="rn-mode">' +
      ["auto", "yes", "no"].map(function (m) {
        return '<button type="button" role="radio" class="rp" data-mode="' + m + '" aria-checked="' + (m === mode) + '" aria-pressed="' + (m === mode) + '">' + esc(t("js.ha.rename.mode_" + m)) + "</button>";
      }).join("") + '</div><div class="field-hint">' + esc(t("js.ha.rename.mobile_hint")) + "</div></div>" +
      '<div class="mi-actions"><button type="button" class="btn text rp" data-act="back">' + esc(t("js.ha.cancel")) + '</button>' +
      '<button type="submit" class="btn filled rp">' + esc(t("js.ha.save")) + "</button></div></form></div>";
    var input = $("rn-name");
    if (input) { input.focus(); input.select(); }
  }
  function renderBrandEdit(d) {
    dlg.innerHTML = '<div class="mi">' + miHeader(null, t("js.ha.brand.title"), true) +
      '<form class="mi-body" id="brand-form" autocomplete="off">' +
      '<label class="field"><input id="br-name" type="text" maxlength="40" placeholder=" " value="' + esc(d.brand_user || d.brand || "") + '"><span class="field-label">' + esc(t("js.ha.brand.label")) + "</span></label>" +
      '<div class="field-hint">' + esc(t("js.ha.brand.hint")) + "</div>" +
      '<div class="mi-actions"><button type="button" class="btn text rp" data-act="back">' + esc(t("js.ha.cancel")) + '</button>' +
      '<button type="submit" class="btn filled rp">' + esc(t("js.ha.save")) + "</button></div></form></div>";
    var input = $("br-name");
    if (input) { input.focus(); input.select(); }
  }
  // Manual choice of brand or type: stays until switching back to automatic.
  function saveOverride(d, body) {
    return api("/api/devices/" + encodeURIComponent(d.id) + "/override", { method: "POST", json: body }).then(function () {
      return load({ silent: true });
    }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); });
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
    var m = document.createElement("div");
    m.className = "menu type-menu"; m.setAttribute("role", "menu");
    var cur = d.type_user || "";
    var items = [["", t("js.ha.type.auto")]].concat(TYPE_ORDER.map(function (k) { return [k, typeLabel(k)]; }));
    m.innerHTML = items.map(function (it) {
      return '<button type="button" class="menu-item rp" role="menuitemradio" data-type="' + esc(it[0]) + '" aria-checked="' + (it[0] === cur) + '">' +
        (it[0] ? icon(I.typeIcon[it[0]]) : icon("auto-fix")) + "<span>" + esc(it[1]) + "</span></button>";
    }).join("");
    var r = btn.getBoundingClientRect();
    m.style.top = Math.round(r.bottom + 4) + "px";
    m.style.right = Math.max(8, Math.round(window.innerWidth - r.right)) + "px";
    m.style.maxHeight = Math.max(160, window.innerHeight - r.bottom - 16) + "px";
    dlg.appendChild(m);
    typeMenu = m;
    m.addEventListener("click", function (e) {
      var b = e.target.closest("[data-type]");
      if (!b) return;
      closeTypeMenu();
      saveOverride(d, { type: b.dataset.type || null });
    });
  }
  document.addEventListener("click", function (e) {
    if (typeMenu && !e.target.closest(".type-menu") && !e.target.closest('[data-act="type-menu"]')) closeTypeMenu();
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && typeMenu) { closeTypeMenu(); } });
  window.addEventListener("scroll", function (e) { if (typeMenu && !typeMenu.contains(e.target)) closeTypeMenu(); }, true);
  function renderDeep(d) {
    dlg.innerHTML = '<div class="mi">' + miHeader(null, t("js.ha.deep.title"), true) +
      '<div class="mi-body"><div class="confirm"><span class="confirm-ic info">' + icon("magnify") + "</span><p>" + esc(t("js.ha.deep.one_text", { name: d.name })) + "</p></div>" +
      '<label class="fl-row"><span class="fl-text"><b>' + esc(t("js.ha.deep.skip")) + '</b></span><input type="checkbox" class="fl-sw" id="deep-skip"></label></div>' +
      '<div class="mi-actions"><button type="button" class="btn text rp" data-act="back">' + esc(t("js.ha.cancel")) + "</button>" +
      '<button type="button" class="btn filled rp" data-act="deep-confirm">' + esc(t("js.ha.deep.start")) + "</button></div></div>";
  }
  function renderIgnore(d) {
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
      var host = document.querySelector("dialog[open]") || document.body;
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("aria-hidden", "true");
      ta.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;font-size:16px";
      host.appendChild(ta);
      ta.focus();
      ta.select();
      try { ta.setSelectionRange(0, text.length); } catch (err) { /* ignore */ }
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
      host.removeChild(ta);
      return ok;
    }
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return fallback(); });
    }
    return Promise.resolve(fallback());
  }

  function wakeDevice(id) {
    var d = S.devices.get(id);
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
  function openExternal(url) {
    var w = null;
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
    var inApp = window.top !== window && /home\s?assistant/i.test(navigator.userAgent || "");
    if (!inApp) { copyFallback(); return; }
    var left = false;
    function onHide() { if (document.hidden) left = true; }
    document.addEventListener("visibilitychange", onHide);
    try { window.open(url, "_top"); } catch (err) { /* ignore */ }
    setTimeout(function () {
      document.removeEventListener("visibilitychange", onHide);
      if (!left) copyFallback();
    }, 900);
  }
  document.addEventListener("click", function (e) {
    var a = e.target.closest ? e.target.closest('a[target="_blank"]') : null;
    if (!a || e.defaultPrevented || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    openExternal(a.href);
  });

  dlg.addEventListener("click", function (e) {
    var copy = e.target.closest("[data-copy]");
    if (copy) {
      copyText(copy.dataset.copy).then(function (ok) {
        snack(ok ? t("js.ha.toast.mac_copied") : t("js.ha.toast.copy_failed"), { kind: ok ? "success" : "error", ms: 2200 });
      });
      return;
    }
    var range = e.target.closest("[data-range]");
    if (range) {
      S.mi.range = parseInt(range.dataset.range, 10);
      dlg.querySelectorAll("[data-range]").forEach(function (b) { b.setAttribute("aria-pressed", String(b === range)); });
      loadGraph();
      return;
    }
    var mode = e.target.closest("[data-mode]");
    if (mode) {
      dlg.querySelectorAll("[data-mode]").forEach(function (b) {
        b.setAttribute("aria-checked", String(b === mode));
        b.setAttribute("aria-pressed", String(b === mode));
      });
      return;
    }
    var act = e.target.closest("[data-act]");
    if (!act) return;
    var d = S.devices.get(S.open);
    switch (act.dataset.act) {
      case "close": closeMore(); break;
      case "back": S.mi.view = "main"; renderMore(); break;
      case "rename": S.mi.view = "rename"; renderMore(); break;
      case "brand-edit": S.mi.view = "brand"; renderMore(); break;
      case "type-menu": if (d) openTypeMenu(act, d); break;
      case "ignore": S.mi.view = "ignore"; renderMore(); break;
      case "deep":
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
      case "share": if (d) saveOverride(d, { ha_share: !d.ha_share }).then(function () { snack(t(d.ha_share ? "js.ha.share.removed" : "js.ha.share.added"), { kind: "success" }); }); break;
      case "ignore-confirm": if (d) ignoreDevice(d, act); break;
    }
  });
  dlg.addEventListener("submit", function (e) {
    e.preventDefault();
    var d = S.devices.get(S.open);
    if (!d) return;
    if (e.target.id === "brand-form") {
      var submitB = e.target.querySelector('[type="submit"]');
      if (submitB) submitB.disabled = true;
      saveOverride(d, { brand: $("br-name").value.trim() || null }).then(function () { S.mi.view = "main"; renderMore(); });
      return;
    }
    var name = $("rn-name").value.trim();
    if (!name) return;
    var selected = dlg.querySelector('[data-mode][aria-checked="true"]');
    var m = selected ? selected.dataset.mode : "auto";
    var body = { name: name };
    if (m === "yes") body.mobile = true;
    else if (m === "no") body.mobile = false; // "auto": missing field = the heuristic decides again
    var submit = e.target.querySelector('[type="submit"]');
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

  // ---------------------------------------------------------- update
  // Changes accumulate and are applied once per frame.
  function schedule() {
    if (S.flushQueued) return;
    S.flushQueued = true;
    requestAnimationFrame(flush);
  }
  function flush() {
    S.flushQueued = false;
    var dirty = S.dirty;
    if (!S.loaded) return;
    if (dirty.layout) { dirty.layout = false; layout(); dirty.ids.clear(); }
    else if (COMPACT && dirty.ids.size) { layout(); dirty.ids.clear(); }
    else { dirty.ids.forEach(updateTile); dirty.ids.clear(); }
    if (dirty.net) { dirty.net = false; updateNetwork(); updateScan(); }
    if (dirty.more) { dirty.more = false; updateMore(); }
  }


  // New devices detected on the network (card and notifications) are shown only when the
  // card panel is already populated, and a few seconds later: first the dashboard, then
  // the news. After a manual search they appear immediately (S.scanDone).
  var NEW_DELAY_MS = 10000;
  function armNew() {
    if (S.newReady || S.newTimer || !S.list.length) return;
    S.newTimer = setTimeout(function () {
      S.newReady = true;
      renderNew();
      S.dirty.net = true;
      schedule();
    }, NEW_DELAY_MS);
  }
  function onDevice(ev) {
    var d = prepare(ev.device), prev = S.devices.get(d.id);
    S.devices.set(d.id, d);
    if (S.refreshing) S.changedSince++;
    var structural = !prev || prev.type !== d.type || prev.icon !== d.icon || prev.name !== d.name || prev.ip !== d.ip || prev.is_mobile !== d.is_mobile;
    // New device or category, icon, name, IP changed: the internal list (from which the
    // groups are made) is rebuilt, otherwise the card stays in the old group.
    if (structural) rebuildList();
    if (prev && prev.online !== d.online) {
      flash(d.id, d.online ? "on" : "off");
      histPush(d.id, d.online);
      fetchLogSoon();
    }
    var f = S.filter;
    if (structural || prev.online !== d.online || f.status !== "all" || f.type || f.q || COMPACT) S.dirty.layout = true;
    S.dirty.ids.add(d.id);
    S.dirty.net = true;
    if (S.open === d.id) S.dirty.more = true;
    schedule();
    armNew();
  }
  function onRemoved(ev) {
    S.devices.delete(ev.id);
    S.tiles.delete(ev.id);
    S.hist.delete(ev.id);
    rebuildList();
    if (S.open === ev.id) closeMore();
    S.dirty.layout = true;
    S.dirty.net = true;
    schedule();
  }
  function onPoll(ev) {
    S.poll.known = true;
    S.poll.interval = ev.interval_ms || 30000;
    S.poll.nextAt = Date.now() + (ev.next_in_ms == null ? S.poll.interval : ev.next_in_ms);
    S.poll.paused = !!ev.paused;
    S.poll.pausedAt = ev.paused_in_ms == null ? null : Date.now() + ev.paused_in_ms;
    refreshDone();
    updateScan();
  }
  function onActivity(ev) {
    var prev = S.activity.rescanning;
    S.activity.search = !!ev.search;
    S.activity.rescanning = new Set(ev.rescanning || []);
    prev.forEach(function (id) { S.dirty.ids.add(id); });
    S.activity.rescanning.forEach(function (id) { S.dirty.ids.add(id); });
    S.dirty.net = true;
    schedule();
  }
  function onNewDevices(ev) {
    var before = S.newDevices;
    var count = ev.count || 0;
    if ((S.scanDone || S.newReady) && before.init && count > before.count) {
      var known = {};
      before.devices.forEach(function (d) { known[d.mac] = true; });
      var fresh = (ev.devices || []).filter(function (d) { return !known[d.mac]; })[0] || {};
      snack(t("js.ha.new.toast", { label: fresh.hostname || fresh.brand || fresh.vendor || fresh.ip || "?" }), {
        kind: "warning", ms: 7000,
        action: { text: t("js.ha.toast.view"), fn: function () { if (newEl.scrollIntoView) newEl.scrollIntoView({ behavior: "smooth", block: "nearest" }); } }
      });
    }
    S.newDevices = { count: count, devices: ev.devices || [], init: true };
    renderNew();
    S.dirty.net = true;
    schedule();
  }
  var ALERT_TOAST = { "alert.ip_conflict": true, "alert.dhcp_multiple": true };
  function onAlert(ev) {
    if (S.log.open) fetchLogSoon();
    if (ev.message && ALERT_TOAST[ev.key]) snack(ev.message, { kind: "warning", ms: 7000 });
  }

  // ------------------------------------------------------- real-time stream
  function connect() {
    clearTimeout(S.retryTimer);
    if (S.es) { S.es.close(); S.es = null; }
    var es = new EventSource("/api/ha/events?rev=" + S.rev + "&lang=" + encodeURIComponent(LANG));
    S.es = es;
    S.conn.last = Date.now();
    function on(name, fn) {
      es.addEventListener(name, function (e) {
        S.conn.last = Date.now();
        var ev;
        try { ev = JSON.parse(e.data); } catch (err) { return; }
        if (typeof ev.rev === "number" && ev.rev > S.rev) S.rev = ev.rev;
        fn(ev);
      });
    }
    on("device", onDevice);
    on("removed", onRemoved);
    on("poll", onPoll);
    on("activity", onActivity);
    on("alert", onAlert);
    on("new_devices", onNewDevices);
    on("roles", function (ev) {
      // UPnP roles, names and types decide category, icon and name: if they change the groups are redone.
      function sig(r) { return JSON.stringify([r.by_ip || {}, r.names || {}, r.types || {}]); }
      var changed = sig(ev) !== sig(S.roles);
      S.roles = { by_ip: ev.by_ip || {}, via: ev.via || {}, names: ev.names || {}, types: ev.types || {}, dhcp: ev.dhcp || [], internet: ev.internet || null };
      S.tiles.forEach(function (el, id) { updateTile(id); });
      // The role also decides the category (e.g. gateway -> network equipment): the
      // devices are reloaded to redo the groups.
      if (changed && S.loaded) load({ silent: true });
      if (S.open && dlg.open && S.mi.view === "main") { var od = S.devices.get(S.open); if (od) miAttrs(od); }
    });
    es.onopen = function () {
      var wasDown = !S.conn.ok && S.conn.everOk;
      S.conn.retryAt = 3000;
      setConn(true);
      // After a drop (or a service restart, which resets the revisions) everything is
      // resynced: devices, categories, icons.
      if (wasDown) { if (S.loaded) load({ silent: true }); fetchLog(); fetchHist(); }
    };
    es.onerror = function () {
      // Reopens with the last seen revision: the server sends only the difference.
      es.close();
      if (S.es === es) S.es = null;
      setConn(false);
      S.retryTimer = setTimeout(connect, S.conn.retryAt);
      S.conn.retryAt = Math.min(15000, Math.round(S.conn.retryAt * 1.6));
    };
  }

  // ------------------------------------------------------------ startup
  var loadTimer = null;
  function load(opts) {
    opts = opts || {};
    clearTimeout(loadTimer);
    return Promise.all([api("/api/ha/summary"), api("/api/ha/devices")]).then(function (res) {
      var sum = res[0], dev = res[1];
      if (!dev.ready && S.loadTries < 8) {
        // The first check cycle has not finished yet: stay on the skeleton.
        S.loadTries++;
        loadTimer = setTimeout(load, 1500);
        return;
      }
      S.devices.clear();
      S.tiles.clear();
      (dev.devices || []).forEach(function (d) { S.devices.set(d.id, prepare(d)); });
      rebuildList();
      S.rev = dev.rev || 0;
      if (sum.poll && sum.poll.interval_ms) {
        S.poll = { known: true, interval: sum.poll.interval_ms, nextAt: Date.now() + (sum.poll.next_in_ms || 0),
          paused: !!sum.poll.paused, pausedAt: sum.poll.paused_in_ms == null ? null : Date.now() + sum.poll.paused_in_ms };
      }
      S.mqtt = sum.mqtt || null;
      S.activity.search = !!(sum.activity && sum.activity.search);
      S.activity.rescanning = new Set((sum.activity && sum.activity.rescanning) || []);
      if (sum.roles) S.roles = sum.roles;
      var nd = sum.new_devices || {};
      S.newDevices = { count: nd.count || 0, devices: nd.devices || [], init: false };
      S.loaded = true;
      netEl.hidden = false;
      buildNetwork();
      renderNew();
      layout();
      armNew();
      updateNetwork();
      updateScan();
      fetchLog();
      fetchHist();
      api("/api/settings").then(function (s) { if (s && s.miss_limit) S.missLimit = s.miss_limit; }).catch(function () {});
      S.loadFails = 0;
      connect();
    }).catch(function (err) {
      S.loadFails = (S.loadFails || 0) + 1;
      S.lastErr = err || null;
      var expired = !!err && (err.status === 401 || err.status === 403);
      // Silent resync (return to the app, roles): the dashboard stays as it is.
      if (opts.silent && S.loaded) {
        if (expired) reloadHost();
        return;
      }
      S.loaded = false;
      var skeleton = $("skeleton-tiles");
      if (skeleton) skeleton.remove();
      netEl.hidden = true;
      reconcile(groupsEl, [emptyState("error")]);
      if (expired) reloadHost();  // only once a minute: then the button remains
    });
  }

  // What needs refreshing as time passes ("seen 5 min ago", 24 h bars).
  function tick() {
    if (!S.loaded) return;
    S.tiles.forEach(function (el, id) { updateTile(id); });
    document.querySelectorAll(".log-ago").forEach(function (el) { el.textContent = ago(parseFloat(el.dataset.ts)); });
    if (S.open && dlg.open && S.mi.view === "main") { var d = S.devices.get(S.open); if (d) { miHero(d); miAttrs(d); } }
    if (COMPACT) layout();
  }

  buildToolbar();
  showDebugBadge();
  load();
  setInterval(updateScan, 1000);
  // Log open: reloads by itself (more often at the detailed level, where
  // the service entries arrive continuously).
  setInterval(function () {
    if (S.log.open && !document.hidden) fetchLog();
  }, 6000);
  setInterval(tick, 30000);
  setInterval(fetchHist, 300000);
  // If the stream goes quiet (mobile network, standby): beyond the maximum interval between
  // two cycles with no event at all it is reopened from scratch.
  setInterval(function () {
    if (S.es && S.loaded && Date.now() - S.conn.last > POLL_WATCHDOG_MS) connect();
  }, 15000);
  window.addEventListener("pagehide", function () { if (S.es) { S.es.close(); S.es = null; } });
  window.addEventListener("pageshow", function (e) { if (e.persisted && S.loaded) connect(); });
  var hiddenAt = 0;
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") { hiddenAt = Date.now(); return; }
    if (!S.loaded) { load(); return; }                       // it was in error: retry immediately
    tick();
    // After more than 30 s in the background (mobile app, tab in standby) stream and session
    // may be dead: everything is resynced, without showing errors if not needed.
    if (hiddenAt && Date.now() - hiddenAt > 30000) load({ silent: true });
    else if (!S.es) connect();
  });
  // Tab open for a long time with no event (not even the heartbeats every 15 s): session or network
  // dropped without the browser noticing.
  setInterval(function () {
    if (S.loaded && !document.hidden && Date.now() - S.conn.last > 3 * POLL_WATCHDOG_MS) load({ silent: true });
  }, 60000);
})();
