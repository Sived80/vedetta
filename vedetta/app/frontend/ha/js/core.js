// Vedetta in Home Assistant style (/ha). Vanilla JavaScript, no libraries.
// Data: /api/ha/devices, /api/ha/summary, /api/ha/logbook, /api/ha/history
// and the SSE stream /api/ha/events (JSON, with revision and automatic resume).
// Actions: the existing endpoints (refresh, wake, rename, delete, scan).
export const I = window.VedettaIcons;
export const LANG = window.VEDETTA_LANG || "en";
export const BASE = window.VEDETTA_BASE || ""; // HA ingress prefix (empty at the root)
export const params = new URLSearchParams(location.search);
export const ROOT = document.documentElement;
export const COMPACT = ROOT.getAttribute("data-compact") === "1";
export const COMPACT_LIMIT = parseInt(document.getElementById("root").dataset.limit, 10) || 6;
export let REDUCED = false;
(function () {
  if (!window.matchMedia) return;
  const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  REDUCED = !!mq.matches;
  const on = function (e) { REDUCED = !!e.matches; };
  if (mq.addEventListener) mq.addEventListener("change", on); else if (mq.addListener) mq.addListener(on);
})();
export const TYPE_ORDER = ["router", "server", "pc", "phone", "media", "audio", "iot", "printer", "generic"];
export const POLL_WATCHDOG_MS = 90000;

// ---------------------------------------------------------------- language
// The server decides the language: the choice of the logged-in Home Assistant user (kept on the server), the language of Home
// Assistant, the browser's. VEDETTA_LANG_AUTO says that nobody picked it. Where the server cannot tell who is looking (no user id), the
// last choice made in this browser is restored (the cookie often does not travel inside an iframe). Only a choice is remembered here,
// never the language that was simply worked out: that one must be free to follow Home Assistant.
export const LANG_KEY = "dash-lang-choice";
function langAvailable(code) {
  return (window.VEDETTA_LANGS || []).some(function (l) { return l[0] === code; });
}
export function goLang(code) {
  const next = new URLSearchParams(location.search);
  if (code) next.set("lang", code); else next.delete("lang");
  location.replace(location.pathname + (next.toString() ? "?" + next.toString() : ""));
}
// set when the page is going to the language the visitor chose: nothing else must start
export let redirecting = false;
try {
  localStorage.removeItem("dash-lang");   // the key of the versions before: it held the language shown, not a choice
  if (params.has("lang")) {
    localStorage.setItem(LANG_KEY, LANG);
  } else if (window.VEDETTA_LANG_AUTO) {
    var savedLang = localStorage.getItem(LANG_KEY);
    if (savedLang && savedLang !== LANG && langAvailable(savedLang)) {
      goLang(savedLang);
      redirecting = true;
    }
  }
} catch (err) { /* storage not available: stay on the server's language */ }

export function t(key, vars) {
  const table = window.VEDETTA_I18N || {};
  let text;
  if (vars && typeof vars.n === "number") text = table[key + (vars.n === 1 ? "_one" : "_other")];
  if (text === undefined) text = table[key];
  if (text === undefined) return key;
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, function (m, name) {
    return Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : m;
  });
}

// --------------------------------------------------------------- utilities
export function $(id) { return document.getElementById(id); }
export function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}
export function icon(name, cls) { return I.svg(name, cls); }
export function typeIcon(type) { return I.typeIcon[type] || I.typeIcon.generic; }
// Device icon: the best-fitting one chosen by the server (MDI name) if we know it,
// otherwise the one for its category.
export function devIcon(d) {
  return d && d.icon && I.paths[d.icon] ? d.icon : typeIcon(d && d.type);
}
// A web interface can be opened only if the scan found one (web port or page title).
// ---- Brand logos. The server sends d.logo (file id) and d.logo_color for the brand the device shows now; nothing is
// stored, so a brand changed by hand or by a new clue changes the logo at the next update, and no logo means none shown.
export function logoVar(d) { return 'url("' + BASE + "/static/ha/logos/" + encodeURIComponent(d.logo) + '.svg")'; }
// Colour of the small logo in the list: very dark brand colours (Apple, Sony) would disappear on a dark theme.
export function logoTint(d) {
  const m = /^#([0-9a-f]{6})$/i.exec(d.logo_color || "");
  if (!m) return "var(--primary-text-color)";
  const n = parseInt(m[1], 16), lum = (0.2126 * (n >> 16) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255)) / 255;
  // a colour that would vanish on one of the themes (near black on dark, near white on light) is drawn in the text colour of the theme
  return lum < 0.28 || lum > 0.85 ? "var(--primary-text-color)" : "#" + m[1];
}

// The button only appears where a page for people really answers. web_open: true/false once the open ports have been
// requested; null for devices analysed before that check existed (old rule until the next deep search).
export function canOpen(d) {
  if (d.title || d.web_open === true) return true;
  if (d.web_open === false) return false;
  return (d.ports || []).some(function (p) { return p.category === "web"; });
}
// Wake-on-LAN: the packet gets no reply, so it cannot be known in advance whether the device
// accepts it. It is offered only where it makes sense: device off, MAC known and real (not "private" like those
// of phones), not mobile and of a type that usually supports it (PC, server, TV/media); or
// when a previous wake-up has already worked (the server remembers it in wol_ok).
var WAKE_TYPES = ["pc", "server", "media"];
function macIsLocal(mac) { const b = parseInt(String(mac || "").slice(0, 2), 16); return isNaN(b) || (b & 2) === 2; }
export function canWake(d) {
  return !d.online && !!d.mac && !d.is_mobile && !macIsLocal(d.mac) && (!!d.wol_ok || WAKE_TYPES.indexOf(d.type) >= 0);
}
export function typeLabel(type) { return t("js.ha.type1." + (I.typeIcon[type] ? type : "generic")); }
export function typePlural(type) { return t("js.ha.type." + (I.typeIcon[type] ? type : "generic")); }
export function nowSec() { return Date.now() / 1000; }

export function ago(ts) {
  const s = Math.max(0, nowSec() - ts);
  if (s < 60) return t("js.ha.ago.now");
  if (s < 3600) return t("js.ha.ago.minutes", { n: Math.floor(s / 60) });
  if (s < 86400) return t("js.ha.ago.hours", { n: Math.floor(s / 3600) });
  return t("js.ha.ago.days", { n: Math.floor(s / 86400) });
}
export function fmtUptime(sec) {
  if (sec == null) return "";
  sec = Math.floor(sec);
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
  if (d > 0) return t("js.ha.uptime.days", { d: d, h: h });
  if (h > 0) return t("js.ha.uptime.hours", { h: h, m: m });
  if (sec >= 60) return t("js.ha.uptime.minutes", { m: m });
  return t("js.ha.uptime.seconds", { n: sec });
}
export function fmtClock(ts) {
  return new Date(ts * 1000).toLocaleTimeString(LANG, { hour: "2-digit", minute: "2-digit" });
}
function fmtDay(ts) {
  return new Date(ts * 1000).toLocaleDateString(LANG, { weekday: "short", day: "numeric", month: "short" });
}
export function fmtStamp(ts, withDay) {
  return (withDay ? fmtDay(ts) + " " : "") + fmtClock(ts);
}
export function ipKey(ip) {
  const p = String(ip || "").split(".");
  return ((+p[0] || 0) * 16777216) + ((+p[1] || 0) * 65536) + ((+p[2] || 0) * 256) + (+p[3] || 0);
}
// The short words of the state of analysis of a card (info = S.analysis[id]), or "" when it is identified.
export function analysisText(info) { return info ? t("js.ha.an.short." + info.state) : ""; }
export function stateText(d) {
  if (d.online) {
    var ms = d.latency_ms;
    if (d.uptime != null) {
      return ms != null ? t("js.ha.state.online_for_ms", { uptime: fmtUptime(d.uptime), ms: ms }) : t("js.ha.state.online_for", { uptime: fmtUptime(d.uptime) });
    }
    return ms != null ? t("js.ha.state.online_ms", { ms: ms }) : t("js.ha.state.online");
  }
  return d.last_seen ? t("js.ha.state.offline_seen", { ago: ago(d.last_seen) }) : t("js.ha.state.offline");
}
export function debounce(fn, ms) {
  let timer = null;
  return function () {
    const args = arguments;
    clearTimeout(timer);
    timer = setTimeout(function () { fn.apply(null, args); }, ms);
  };
}

// JSON calls: the language travels in the X-Lang header and, for GETs,
// also in the URL. An HTTP error becomes an exception with the server's text.
export function api(path, opts) {
  opts = opts || {};
  const method = opts.method || "GET";
  let url = path;
  if (method === "GET") url += (path.indexOf("?") < 0 ? "?" : "&") + "lang=" + encodeURIComponent(LANG);
  const headers = { "X-Lang": LANG };
  let body;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  }
  // Maximum time: after a mobile app standby a request can stay suspended forever.
  const ctrl = window.AbortController ? new AbortController() : null;
  const timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, opts.timeout || 25000);
  return fetch(url, { method: method, headers: headers, body: body, cache: "no-store", signal: ctrl ? ctrl.signal : undefined }).then(function (r) {
    clearTimeout(timer);
    if (!r.ok) {
      return r.json().catch(function () { return {}; }).then(function (b) {
        const err = new Error(typeof b.detail === "string" ? b.detail : "HTTP " + r.status);
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
export function reloadHost(force) {
  const key = "vedetta-ha-reloaded", now = Date.now();
  if (!force) {
    try {
      if (now - (+sessionStorage.getItem(key) || 0) < 60000) return;  // no reload loops
      sessionStorage.setItem(key, String(now));
    } catch (err) { /* ignore */ }
  }
  try { window.top.location.reload(); } catch (err) { location.reload(); }
}
// The "More info" sheet: its parts and the debug mode all use it.
export var dlg = $("more");
