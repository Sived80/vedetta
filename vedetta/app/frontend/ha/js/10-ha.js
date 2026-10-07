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
  // ---- Brand logos. The server sends d.logo (file id) and d.logo_color for the brand the device shows now; nothing is
  // stored, so a brand changed by hand or by a new clue changes the logo at the next update, and no logo means none shown.
  function logoVar(d) { return 'url("' + BASE + "/static/ha/logos/" + encodeURIComponent(d.logo) + '.svg")'; }
  // Colour of the small logo in the list: very dark brand colours (Apple, Sony) would disappear on a dark theme.
  function logoTint(d) {
    var m = /^#([0-9a-f]{6})$/i.exec(d.logo_color || "");
    if (!m) return "var(--primary-text-color)";
    var n = parseInt(m[1], 16), lum = (0.2126 * (n >> 16) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255)) / 255;
    return lum < 0.28 ? "var(--primary-text-color)" : "#" + m[1];
  }
  // Big faint logo on the device sheet, cut by the edge of the window.
  function brandSheetSync(d) {
    var mi = dlg.querySelector(".mi");
    if (!mi) return;
    var el = mi.querySelector(".brand-sheet");
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

  // The button only appears where a page for people really answers. web_open: true/false once the open ports have been
  // requested; null for devices analysed before that check existed (old rule until the next deep search).
  function canOpen(d) {
    if (d.title || d.web_open === true) return true;
    if (d.web_open === false) return false;
    return (d.ports || []).some(function (p) { return p.category === "web"; });
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
    dismissedNew: {},          // devices seen on the network that the user closed with "Cancel" (by MAC): the card does not come back for them
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
  // One window, five moments: who is it for (the developer: masked and encrypted; me: my own data as it is) -> which days (two
  // taps on the columns, or a preset) -> the job runs (the server says each step) -> what could not be fixed is decided one by one
  // -> the file. The size is estimated from what the server says each day weighs.
  var exportDlg = $("exportdlg");
  var X = null;                                             // state of the open window (null = closed)
  var XP = { MIN: 2, MAXN: 20, W: 20, HOR: 90, SHOWN: 10 };
  function xpT(key, vars) { var v = t(key, vars); return v === key ? "" : v; }          // a text that may not exist
  function xpDay(a) { var d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() - a); return d; }
  function xpFmt(d, o) { try { return d.toLocaleDateString(LANG, o); } catch (e) { return d.toDateString(); } }
  function xpShort(a) { return xpFmt(xpDay(a), { day: "numeric", month: "short" }); }
  function xpLong(a) { return xpFmt(xpDay(a), { day: "numeric", month: "long" }); }
  function xpSize(bytes) { var mb = bytes / 1048576; return (mb < 0.1 ? "0.1" : mb.toFixed(1)).replace(".", LANG === "it" ? "," : ".") + " MB"; }
  function xpDays() { return X.from - X.to; }
  function xpIn(a) { return X.all || (a >= X.to && a <= X.from - 1); }
  function xpBytes(all) {
    var i = X.info;
    if (!i) return 0;
    var a0 = all || X.all ? i.horizon - 1 : X.from - 1, a1 = all || X.all ? 0 : X.to, sum = i.base;
    for (var a = a1; a <= a0; a++) sum += i.daily[a] || 0;
    return sum * i.ratio * (X.dest === "dev" ? i.seal_factor : 1);
  }
  function xpLimited() { return X.dest !== "me"; }
  function xpOver(all) { return !!(X.info && xpLimited() && xpBytes(all) > X.info.limit); }
  function xpClose() {
    if (X && X.job) { api("/api/export/jobs/" + X.job, { method: "DELETE" }).catch(function () {}); }
    if (X) clearTimeout(X.timer);
    X = null;
    if (exportDlg.open && typeof exportDlg.close === "function") exportDlg.close(); else exportDlg.removeAttribute("open");
  }
  function closeExport() { xpClose(); }

  function xpChart() {
    var i = X.info, max = 1, h = "", lab = "", a, k;
    if (i) i.daily.forEach(function (v) { if (v > max) max = v; });
    var w = XP.W, off = X.off, rows = [[], [], []];
    for (k = 0; k < w; k++) {
      a = off + w - 1 - k;
      var d = xpDay(a), nod = a >= XP.HOR, weekend = d.getDay() === 0 || d.getDay() === 6, isIn = xpIn(a);
      var height = nod ? 12 : Math.round(66 + 24 * (((i && i.daily[a]) || 0) / max) + 10 * Math.sin(k * 0.9));   // always full (easy to click), a light wave
      var edge = !X.all && (a === X.from - 1 || a === X.to);
      h += '<button type="button" class="xp-col' + (nod ? " nod" : "") + (isIn ? " in" : "") + (edge ? " edge" : "") + (X.pend === a ? " pend" : "") + '" data-xa="' + a + '"' + (nod ? " disabled" : "") +
        ' style="height:' + height + '%" aria-label="' + esc(xpFmt(d, { weekday: "long", day: "numeric", month: "long" })) + '"></button>';
      var cls = (isIn ? "in " : "") + (weekend ? "we " : "") + (a === 0 ? "today" : "");
      rows[0].push('<i class="' + cls + '">' + d.getDate() + "</i>");
      rows[1].push('<i class="m">' + ((d.getDate() === 1 || k === 0) ? esc(xpFmt(d, { month: "short" })) : "") + "</i>");
    }
    lab = '<div class="xp-lab">' + rows[0].join("") + '</div><div class="xp-lab">' + rows[1].join("") + "</div>";
    var i1 = off + w - 1 - (X.from - 1), i2 = off + w - 1 - X.to, finger = "";
    if (X.intro && !X.all) {
      var x1 = (i1 >= 0 && i1 < w ? (i1 + 0.5) / w : 0.15) * 100, x2 = (i2 >= 0 && i2 < w ? (i2 + 0.5) / w : 0.85) * 100;
      finger = '<span class="xp-finger" style="--x1:' + x1 + "%;--x2:" + x2 + '%"><i></i>' + icon("gesture-tap") + "</span>";
    }
    var caption = esc(xpShort(off + w - 1)) + " – " + (off === 0 ? esc(t("js.ha.export.today")) : esc(xpShort(off)));
    var pan = '<div class="xp-pan"><button type="button" data-xp="older"' + (off + w >= XP.HOR ? " disabled" : "") + ">" + icon("chevron-left") + "<span>" + esc(t("js.ha.export.older")) + "</span></button>" +
      '<span class="xp-cap">' + caption + '</span><button type="button" data-xp="newer"' + (off === 0 ? " disabled" : "") + "><span>" + esc(t("js.ha.export.newer")) + "</span>" + icon("chevron-right") + "</button></div>";
    return "<div>" + pan + '<div class="xp-days' + (X.intro ? " intro" : "") + '">' + h + finger + "</div>" + lab + "</div>";
  }
  function xpSummary() {
    var bytes = xpBytes(), over = xpOver(), lim = X.info ? xpSize(X.info.limit) : "";
    var head = X.all ? t("js.ha.export.sum_all")
      : X.to === 0 ? t("js.ha.export.sum_to_today", { from: xpLong(X.from - 1) }) : t("js.ha.export.sum_from_to", { from: xpLong(X.from - 1), to: xpLong(X.to) });
    var meter = xpLimited() && X.info ? '<div class="xp-meter' + (over ? " over" : "") + '"><i style="width:' + Math.min(100, bytes / X.info.limit * 100).toFixed(1) + '%"></i></div><div class="xp-sub">' +
      esc(over ? t("js.ha.export.limit_over", { size: lim }) : t("js.ha.export.limit_ok", { size: lim })) + "</div>" : "";
    return '<div><div class="xp-read"><b>' + esc(head) + "</b><span>" + esc(t("js.ha.export.sum_size", { n: X.all ? XP.HOR : xpDays(), size: xpSize(bytes) })) + "</span></div>" + meter +
      (X.note ? '<div class="xp-sub warn">' + esc(X.note) + "</div>" : "") + "</div>";
  }
  function xpPresets() {
    function p(n) { return '<button type="button" data-xp="p:' + n + '" aria-pressed="' + (!X.all && X.to === 0 && xpDays() === n) + '">' + esc(t("js.ha.export.days", { n: n })) + "</button>"; }
    var dis = xpOver(true);
    return '<div class="xp-segm" role="group">' + p(2) + p(7) + p(20) + '<button type="button" data-xp="all" aria-pressed="' + X.all + '"' + (dis ? ' disabled title="' + esc(t("js.ha.export.limit_over", { size: xpSize(X.info.limit) })) + '"' : "") + ">" + esc(t("js.ha.export.all")) + "</button></div>";
  }
  function xpDestCards() {
    function card(d, ic, title, text, tag) {
      return '<button type="button" class="xp-dcard" data-xp="dest:' + d + '"><span class="xp-dic">' + icon(ic) + "</span><span><b>" + esc(t(title)) + '</b><em class="xp-tag' + (d === "me" ? " warn" : "") + '">' + tag + '</em><span class="xp-sub">' + esc(t(text)) + "</span></span></button>";
    }
    return card("dev", "lock", "js.ha.export.dev_title", "js.ha.export.dev_text", ".txt") + card("me", "download", "js.ha.export.me_title", "js.ha.export.me_text", ".zip");
  }
  function xpSteps() {
    var s = X.snap || { steps: [], status: "running" }, ids = s.steps.slice(), out = "";
    var plan = X.dest === "me" ? ["collect", "prepare", "ready"] : ["collect", "mask", "check", "fix", "seal", "ready"];
    var shown = plan.filter(function (id) { return id !== "fix" || ids.indexOf("fix") >= 0; });
    shown.forEach(function (id, n) {
      var at = ids.indexOf(id), last = ids.length - 1, st = "wait";
      if (s.status === "done") st = "done";
      else if (at >= 0) st = at < last ? "done" : (s.status === "choose" && id === "fix") ? "bad" : s.status === "error" ? "bad" : "run";
      if (!ids.length && n === 0 && s.status === "running") st = "run";                 // before the first answer of the server
      var sub = xpT("js.ha.export.step_" + id + "_sub");
      if (id === "fix" && at >= 0) sub = s.status === "choose" ? t("js.ha.export.step_fix_left", { n: s.items_total }) : t("js.ha.export.step_fix_sub");
      out += '<div class="xp-step ' + st + '"><span class="xp-dot">' + (st === "done" ? icon("check") : st === "bad" ? icon("close") : n + 1) + "</span><div><b>" + esc(t("js.ha.export.step_" + id)) + "</b>" + (sub ? '<span class="xp-sub">' + esc(sub) + "</span>" : "") + "</div></div>";
    });
    return "<div>" + out + "</div>";
  }
  function xpChoose() {
    var s = X.snap, many = s.items_total > XP.SHOWN, rows = "";
    s.items.forEach(function (it) {
      var c = X.choice[it.id];
      rows += '<li><code>' + esc(it.value) + '</code><span>' + esc(it.file + (it.where ? " · " + it.where : "")) + '<div class="xp-rowact"><button type="button" class="rm" data-xp="rm:' + it.id + '" aria-pressed="' + (c === "rm") + '">' + esc(t("js.ha.export.rm")) +
        '</button><button type="button" data-xp="keep:' + it.id + '" aria-pressed="' + (c === "keep") + '">' + esc(t("js.ha.export.keep")) + "</button></div></span></li>";
    });
    return '<div class="xp-tone ' + (many ? "bad" : "warn") + '"><span>' + icon("alert") + "</span><div>" + esc(t(many ? "js.ha.export.choose_many" : "js.ha.export.choose_head", { n: s.items_total })) + "</div></div>" +
      '<div><div class="xp-bulk"><span>' + esc(t("js.ha.export.choose_note")) + '</span><button type="button" class="xp-link" data-xp="rmall">' + esc(t("js.ha.export.rmall")) + '</button></div><ul class="xp-fl">' + rows + "</ul>" +
      (many ? '<div class="xp-more">' + esc(t("js.ha.export.choose_more", { n: s.items_total - XP.SHOWN })) + "</div>" : "") + "</div>";
  }
  function xpDone() {
    var s = X.snap, me = X.dest === "me", sub = me ? t("js.ha.export.done_me", { size: xpSize(s.size || 0) }) : t("js.ha.export.done_dev", { size: xpSize(s.size || 0) });
    var extra = [];
    if (!me && s.fixed) extra.push(t("js.ha.export.done_fixed", { n: s.fixed }));
    if (X.decided) extra.push(t("js.ha.export.done_decided", { r: X.decided.rm, k: X.decided.keep }));
    return '<div class="xp-res"><div class="xp-rt"><span class="ok">' + icon("check-circle") + "</span><div><b>" + esc(t(me ? "js.ha.export.step_ready" : "js.ha.export.done_title")) + '</b><span class="xp-sub">' + esc(sub) + "</span></div></div></div>" +
      (extra.length ? '<div class="xp-sub">' + esc(extra.join(" ")) + "</div>" : "") + (me ? '<div class="xp-sub">' + esc(t("js.ha.export.done_me_note")) + "</div>" : "");
  }
  function xpFocusLine() {
    var n = 0;
    S.devices.forEach(function (x) { if (x.focus) n++; });
    return n ? '<div class="xp-flag">' + icon("flag") + "<span><b>" + esc(t("js.ha.export.focus_title", { n: n })) + "</b> " + esc(t("js.ha.export.focus_text")) + "</span></div>" : "";
  }
  function xpView() {
    var title = '<div class="mi-header"><div class="mi-titles"><h2 class="mi-title" id="exportdlg-title">' + esc(t("js.ha.export.title")) + "</h2></div></div>";
    var cancel = '<button type="button" class="btn text rp" data-xp="cancel">' + esc(t("js.ha.cancel")) + "</button>";
    var body, acts;
    if (X.stage === "dest") {
      body = '<div class="xp-sub">' + esc(t("js.ha.export.dest_q")) + "</div>" + xpDestCards() + xpFocusLine();
      acts = cancel;
    } else if (X.stage === "pick") {
      var over = xpOver();
      body = '<div class="xp-chosen"><span class="xp-tag' + (X.dest === "me" ? " warn" : "") + '">' + esc(t(X.dest === "me" ? "js.ha.export.chip_me" : "js.ha.export.chip_dev")) + "</span></div>" + xpChart() + xpSummary() + xpPresets();
      acts = cancel + '<button type="button" class="btn filled rp" data-xp="go"' + (over || !X.info ? " disabled" : "") + ">" + icon("download") + "<span>" + esc(t(X.dest === "me" ? "js.ha.export.go_me" : "js.ha.export.go_dev")) + "</span></button>";
    } else if (X.stage === "run") {
      body = xpSteps();
      acts = '<button type="button" class="btn text rp" data-xp="stop">' + esc(t("js.ha.export.stop")) + "</button>";
    } else if (X.stage === "choose") {
      body = xpSteps() + xpChoose();
      var ready = X.snap.items.every(function (it) { return X.choice[it.id]; });
      acts = cancel.replace("data-xp=\"cancel\"", "data-xp=\"stop\"") + '<button type="button" class="btn filled rp" data-xp="apply"' + (ready ? "" : " disabled") + "><span>" + esc(t("js.ha.export.continue")) + "</span></button>";
    } else if (X.stage === "done") {
      body = xpSteps() + xpDone();
      acts = '<button type="button" class="btn text rp" data-xp="finish">' + esc(t("js.ha.export.close")) + '</button><button type="button" class="btn filled rp" data-xp="save"' + (X.saved ? " disabled" : "") + ">" + icon("download") + "<span>" + esc(t(X.saved ? "js.ha.export.saved" : "js.ha.export.save")) + "</span></button>";
    } else {
      var code = X.error || "export_failed";
      body = '<div class="xp-tone bad"><span>' + icon("alert") + "</span><div>" + esc(code === "too_big" ? t("js.ha.export.err_too_big", { size: X.info ? xpSize(X.info.limit) : "20 MB" }) : code === "encryption_unavailable" ? t("js.ha.export.no_crypto") : code === "busy" ? t("js.ha.export.err_busy") : t("js.ha.export.failed")) + "</div></div>";
      acts = '<button type="button" class="btn text rp" data-xp="back">' + esc(t("js.ha.export.back")) + "</button>";
    }
    return '<div class="mi">' + title + '<div class="mi-body xp-body">' + body + '</div><div class="mi-actions">' + acts + "</div></div>";
  }
  function xpRender() {
    if (!X) return;
    exportDlg.innerHTML = xpView();
    X.intro = false;
  }
  function openExport() {
    X = { stage: "dest", dest: null, from: 7, to: 0, off: 0, all: false, pend: null, intro: false, note: "", info: null, job: null, snap: null, choice: {}, error: null, saved: false, decided: null, timer: null };
    xpRender();
    if (typeof exportDlg.showModal === "function") exportDlg.showModal(); else exportDlg.setAttribute("open", "");
    var mine = X;
    api("/api/export/info").then(function (i) { if (X === mine) { X.info = i; xpRender(); } }).catch(function () {});
  }
  function xpPick(a) {
    X.note = "";
    if (X.all) { X.all = false; X.pend = null; X.from = 7; X.to = 0; }
    if (X.pend === null) { X.pend = a; return; }
    var lo = Math.min(X.pend, a), hi = Math.max(X.pend, a);
    if (hi - lo + 1 > XP.MAXN) { X.note = t("js.ha.export.note_max", { n: XP.MAXN }); if (a > X.pend) hi = lo + XP.MAXN - 1; else lo = hi - XP.MAXN + 1; }
    X.from = hi + 1; X.to = lo; X.pend = null;
    if (xpDays() < XP.MIN) X.to = Math.max(0, X.from - XP.MIN);
  }
  function xpPoll() {
    clearTimeout(X.timer);
    var mine = X, fails = 0;
    (function tick() {
      mine.timer = setTimeout(function () {
        if (X !== mine || !mine.job) return;
        api("/api/export/jobs/" + mine.job).then(function (s) {
          if (X !== mine) return;
          mine.snap = s;
          if (s.status === "running") { xpRender(); tick(); return; }
          if (s.status === "choose") { mine.stage = "choose"; mine.choice = mine.choice || {}; }
          else if (s.status === "done") mine.stage = "done";
          else { mine.stage = "error"; mine.error = s.error; }
          xpRender();
        }).catch(function () { fails++; if (fails > 5) { mine.stage = "error"; mine.error = "export_failed"; xpRender(); } else tick(); });
      }, 600);
    })();
  }
  function xpGo() {
    var body = { dest: X.dest };
    if (X.all) body.all = true; else { body.from_day = X.from - 1; body.to_day = X.to; }
    var mine = X;
    mine.stage = "run"; mine.snap = { steps: [], status: "running", items: [], items_total: 0 }; mine.decided = null; mine.saved = false;
    xpRender();
    api("/api/export/jobs", { method: "POST", json: body }).then(function (s) {
      if (X !== mine) { api("/api/export/jobs/" + s.id, { method: "DELETE" }).catch(function () {}); return; }
      mine.job = s.id; mine.snap = s; xpPoll();
    }).catch(function (err) { if (X !== mine) return; mine.stage = "error"; mine.error = /already running/.test(err && err.message || "") ? "busy" : "export_failed"; xpRender(); });
  }
  function xpSave() {
    var mine = X, id = mine.job;
    fetch("/api/export/jobs/" + id + "/file", { method: "POST", headers: { "X-Lang": LANG }, cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      var m = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") || "");
      return r.blob().then(function (blob) { return { blob: blob, name: m ? m[1] : "vedetta-export" }; });
    }).then(function (f) {
      var a = document.createElement("a");
      a.href = URL.createObjectURL(f.blob); a.download = f.name;
      document.body.appendChild(a); a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 4000);
      mine.job = null; mine.saved = true;
      snack(t(mine.dest === "me" ? "js.ha.export.done_plain" : "js.ha.export.done"), { kind: "success" });
      if (X === mine) xpRender();
    }).catch(function () { snack(t("js.ha.export.failed"), { kind: "error" }); });
  }
  exportDlg.addEventListener("click", function (e) {
    if (!X) return;
    if (e.target === exportDlg) return xpClose();
    var col = e.target.closest("[data-xa]");
    if (col && X.stage === "pick" && !col.disabled) { xpPick(parseInt(col.dataset.xa, 10)); xpRender(); return; }
    var b = e.target.closest("[data-xp]");
    if (!b || b.disabled) return;
    var act = b.dataset.xp;
    if (act.indexOf("dest:") === 0) { X.dest = act.slice(5); X.stage = "pick"; X.intro = true; X.all = false; X.pend = null; X.note = ""; }
    else if (act === "cancel") { if (X.stage === "pick") { X.stage = "dest"; X.pend = null; X.note = ""; } else return xpClose(); }
    else if (act === "older") X.off = Math.min(XP.HOR - XP.W, X.off + 10);
    else if (act === "newer") X.off = Math.max(0, X.off - 10);
    else if (act.indexOf("p:") === 0) { X.all = false; X.from = parseInt(act.slice(2), 10); X.to = 0; X.off = 0; X.pend = null; X.note = ""; }
    else if (act === "all") { X.all = true; X.from = XP.HOR; X.to = 0; X.pend = null; X.note = ""; }
    else if (act === "go") return xpGo();
    else if (act === "stop" || act === "back") {
      if (X.job) { api("/api/export/jobs/" + X.job, { method: "DELETE" }).catch(function () {}); X.job = null; }
      clearTimeout(X.timer); X.stage = "pick"; X.snap = null; X.error = null;
    }
    else if (act.indexOf("rm:") === 0) X.choice[parseInt(act.slice(3), 10)] = "rm";
    else if (act.indexOf("keep:") === 0) X.choice[parseInt(act.slice(5), 10)] = "keep";
    else if (act === "rmall") X.snap.items.forEach(function (it) { X.choice[it.id] = "rm"; });
    else if (act === "apply") {
      var mine = X, choices = {}, rm = 0, keep = 0;
      for (var n = 0; n < mine.snap.items_total; n++) { var c = mine.choice[n] || "rm"; choices[n] = c; if (c === "keep") keep++; else rm++; }
      mine.decided = { rm: rm, keep: keep };
      mine.stage = "run"; mine.snap = Object.assign({}, mine.snap, { status: "running" });
      xpRender();
      api("/api/export/jobs/" + mine.job + "/choices", { method: "POST", json: { choices: choices } }).then(function (s) { if (X === mine) { mine.snap = s; xpPoll(); } })
        .catch(function () { if (X === mine) { mine.stage = "error"; mine.error = "export_failed"; xpRender(); } });
      return;
    }
    else if (act === "save") return xpSave();
    else if (act === "finish") return xpClose();
    xpRender();
  });
  exportDlg.addEventListener("close", function () { if (X) xpClose(); });

  // ------------------------------------------------- deep search
  // Advanced search: system, open services, web page. Slow. From the menu (all devices, or the ones never analysed) it starts
  // as soon as the choice is made; on a single device the confirmation can be switched off. While one is running no other
  // can start: the buttons are off until it is over (the network search is independent and stays available).
  var SKIP_DEEP_KEY = "vedetta-ha-skip-deep";
  function skipDeepConfirm() { try { return localStorage.getItem(SKIP_DEEP_KEY) === "1"; } catch (err) { return false; } }
  // Devices never analyzed in depth: scanned_at is written only by the deep search ("Last deep search").
  function deepPending() { return Array.from(S.devices.values()).filter(function (d) { return !d.scanned_at && !d.deep_empty_at; }); }
  var deepRunning = false;          // this page started one and the request is still open
  function deepBusy() { return deepRunning; }                       // only a search started from the top buttons blocks the top buttons
  function deepOneBusy(id) { return !!id && S.activity.rescanning.has(id); }   // a device already being searched cannot be started again
  function syncDeepBusy() {
    var busy = deepBusy(), btn = $("btn-deepmenu");
    if (btn) { btn.disabled = busy; btn.title = busy ? t("js.ha.deep.busy") : ""; }
    if (busy && deepMenuEl && !deepMenuEl.hidden) toggleDeepMenu(false);
    if (typeof dlg !== "undefined" && dlg) {
      var sheetBtn = dlg.querySelector('[data-act="deep"]');
      if (sheetBtn) { var one = deepOneBusy(S.open); sheetBtn.disabled = one; sheetBtn.title = one ? t("js.ha.deep.busy") : ""; }
    }
  }
  function runDeep(ids) {
    if (!ids.length || deepBusy()) return;
    deepRunning = true;
    syncDeepBusy();
    api("/api/devices/rescan", { method: "POST", json: { ids: ids } }).then(function () {
      snack(t("js.ha.deep.done"), { kind: "success" });
      fetchHist();
    }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); }).then(function () { deepRunning = false; syncDeepBusy(); });
  }
  var deepMenuEl = $("deep-menu");
  // The badge: how many devices were never analysed in depth. It is ONE element that changes place: on the corner of the arrow
  // while the menu is closed, in the "to analyse" tile while it is open. While it moves it lives in <body>, fixed, so nothing it
  // crosses (overflow, stacking order, the menu itself) can hide it, and it lands in exactly the place it was measured for.
  var deepBadge = document.createElement("span");
  deepBadge.id = "deep-badge"; deepBadge.className = "deep-badge"; deepBadge.dataset.at = "corner"; deepBadge.hidden = true;
  var deepFlight = null, deepFlightId = 0;
  function deepSplit() { return document.querySelector(".gauge-side .split"); }
  function updateDeepBadge() {
    var split = deepSplit();
    if (!split) return;
    var n = S.loaded ? deepPending().length : 0;
    // it lives in the arrow of the network card: when that card is rebuilt (return to the app, reload) the badge is put back
    if (deepBadge.dataset.at === "corner" && deepBadge.parentNode !== split) split.appendChild(deepBadge);
    else if (!deepBadge.parentNode) split.appendChild(deepBadge);
    deepBadge.textContent = n > 99 ? "99+" : String(n);
    deepBadge.hidden = n === 0;
    var label = t("js.ha.deep.badge", { n: n });
    deepBadge.setAttribute("aria-label", label);
    deepBadge.title = label;
    var btn = $("btn-deepmenu");
    if (btn) btn.setAttribute("aria-label", t("js.ha.deep.title") + (n ? " \u00b7 " + label : ""));
    var tile = deepMenuEl.querySelector('[data-deep="pending"]');
    if (tile) {
      tile.disabled = n === 0;
      tile.querySelector("span:not(.dm-slot)").textContent = t(n ? "js.ha.deep.tile_pending_sub" : "js.ha.deep.tile_pending_done");
    }
  }
  function moveDeepBadge(toSlot) {
    var b = deepBadge, dest = toSlot ? deepMenuEl.querySelector(".dm-slot") : deepSplit();
    if (!dest) return;
    var first = b.getBoundingClientRect();           // where it is now (also when it is half way)
    if (deepFlight) { deepFlight.cancel(); deepFlight = null; }
    deepFlightId++;
    b.style.left = b.style.top = "";
    dest.appendChild(b);
    b.dataset.at = toSlot ? "slot" : "corner";
    if (b.hidden || REDUCED || !b.animate || !first.width) return;
    var last = b.getBoundingClientRect(), id = deepFlightId;
    document.body.appendChild(b);
    b.dataset.at = "fly";
    b.style.left = last.left + "px";
    b.style.top = last.top + "px";
    var anim = b.animate([{ transform: "translate(" + (first.left - last.left) + "px," + (first.top - last.top) + "px)" }, { transform: "translate(0px,0px)" }],
      { duration: 320, easing: "cubic-bezier(0.2, 0, 0, 1)" });
    deepFlight = anim;
    function land() {
      if (id !== deepFlightId) return;               // another move started: this one is not the last
      b.style.left = b.style.top = "";
      dest.appendChild(b);
      b.dataset.at = toSlot ? "slot" : "corner";
      deepFlight = null;
    }
    anim.onfinish = land;
    anim.oncancel = land;
  }
  deepBadge.addEventListener("click", function (e) {
    if (deepBadge.dataset.at !== "corner" || deepBusy()) return;
    e.stopPropagation();
    toggleDeepMenu(true);
  });
  function toggleDeepMenu(open) {
    if (open === undefined) open = deepMenuEl.hidden;
    if (open === !deepMenuEl.hidden) return;         // already so: the badge must not move twice
    if (open && deepBusy()) return;                  // one search at a time
    if (open) {
      closePopups("deep");
      if (deepMenuEl.contains(deepBadge)) deepSplit().appendChild(deepBadge);      // never lost with the old tiles
      var pending = deepPending().length;
      deepMenuEl.innerHTML = '<div class="dm-tiles">' +
        '<button type="button" class="dm-tile rp" role="menuitem" data-deep="all">' + icon("magnify") + "<b>" + esc(t("js.ha.deep.tile_all")) + "</b><span>" + esc(t("js.ha.deep.tile_all_sub")) + "</span></button>" +
        '<button type="button" class="dm-tile rp" role="menuitem" data-deep="pending"' + (pending ? "" : " disabled") + ">" + icon("clock-outline") + "<b>" + esc(t("js.ha.deep.tile_pending")) + "</b><span>" +
        esc(t(pending ? "js.ha.deep.tile_pending_sub" : "js.ha.deep.tile_pending_done")) + '</span><span class="dm-slot"></span></button></div>' +
        '<p class="dm-foot">' + esc(t("js.ha.deep.note", { hour: "03:00" })) + "</p>";
      var btn = $("btn-deepmenu"), r = btn.getBoundingClientRect();
      deepMenuEl.style.top = Math.round(r.bottom + 4) + "px";
      deepMenuEl.style.left = "auto";
      deepMenuEl.style.right = Math.max(8, Math.round(window.innerWidth - r.right)) + "px";
      deepMenuEl.hidden = false;
      (deepMenuEl.getAnimations ? deepMenuEl.getAnimations() : []).forEach(function (a) { a.finish(); });   // measure the final place, not the opening one
      moveDeepBadge(true);
    } else {
      moveDeepBadge(false);
      deepMenuEl.hidden = true;
    }
    var b2 = $("btn-deepmenu"); if (b2) b2.setAttribute("aria-expanded", String(open));
  }
  // The choice in the menu starts the search: no confirmation (the badge and the tiles already say what it will do).
  function startDeepAll(mode) {
    if (deepBusy()) { snack(t("js.ha.deep.busy"), { kind: "warning" }); return; }
    var list = mode === "pending" ? deepPending() : S.list;
    if (!list.length) { snack(t(mode === "pending" ? "js.ha.deep.menu_pending_none" : "js.ha.deep.none"), { kind: "warning" }); return; }
    runDeep(list.map(function (d) { return d.id; }));
  }
  document.addEventListener("click", function (e) {
    if (e.target.closest("#btn-deepmenu")) { e.stopPropagation(); toggleDeepMenu(); }
  });
  deepMenuEl.addEventListener("click", function (e) {
    var item = e.target.closest("[data-deep]");
    if (!item || item.disabled) return;
    toggleDeepMenu(false);
    startDeepAll(item.dataset.deep);
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
      pauseEl.style.maxHeight = Math.max(160, window.innerHeight - r.bottom - 16) + "px";
      pauseEl.hidden = false;                                  // visible to measure its width: the centre of the menu is the centre of the button
      var w = pauseEl.offsetWidth || 300, centre = r.left + r.width / 2;
      var left = Math.max(8, Math.min(Math.round(centre - w / 2), window.innerWidth - w - 8));
      pauseEl.style.left = left + "px";
      pauseEl.style.transformOrigin = Math.round(centre - left) + "px top";
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
    updateDeepBadge();
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
    syncDeepBusy();
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
    // Pause: the bar is no longer the countdown to the next check. Timed pause = orange, it fills while the pause
    // runs and is full when the service resumes; stopped until resumed = solid red. A busy search keeps the moving bar.
    var pausedNow = S.poll.paused && !busy, pauseRest = pausedNow ? pauseLeft() : null;
    prog.classList.toggle("pause-timed", pausedNow && pauseRest !== Infinity);
    prog.classList.toggle("pause-stop", pausedNow && pauseRest === Infinity);
    if (pausedNow) {
      var pauseAll = S.poll.pausedTotal || Math.max(pauseRest === Infinity ? 0 : pauseRest, S.poll.pausedSeen || 0);
      S.poll.pausedSeen = pauseAll;
      var filled = pauseRest === Infinity || !pauseAll ? 1 : Math.min(1, Math.max(0, 1 - pauseRest / pauseAll));
      bar.style.transform = "scaleX(" + filled.toFixed(3) + ")";
    } else if (!busy) {
      S.poll.pausedSeen = 0;
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
      S.dismissedNew = {};      // a search the user asks for shows again what the app had seen by itself
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

