import { fmtClock, fmtStamp, nowSec, t } from "./core.js";

// ------------------------------------------------------------ network health: what the page says about a finding
// Pure: the findings come from /api/ha/health (who, what, when) and the texts from the translations; nothing here touches the page.
export const HEALTH_TILES = ["addr", "drop", "boot", "lat"];
var HEALTH_DAY = 86400, HEALTH_MAX_DOTS = 24;

// The four tiles: the findings that are shown, the ones the person has hidden, and the time of the last of the shown ones.
export function healthTiles(findings, hidden) {
  return HEALTH_TILES.map(function (key) {
    const mine = findings.filter(function (f) { return f.tile === key; });
    const shown = mine.filter(function (f) { return hidden.indexOf(f.id) < 0; });
    return { key: key, finds: shown, hid: mine.filter(function (f) { return hidden.indexOf(f.id) >= 0; }),
      last: shown.reduce(function (m, f) { return Math.max(m, f.last); }, 0) };
  });
}
// "bad" if any shown finding is, "warn" if there is one, "ok" if the four tiles are quiet.
export function healthWorst(finds) {
  if (finds.some(function (f) { return f.lv === "bad"; })) return "bad";
  return finds.length ? "warn" : "ok";
}

function healthRule(f) { return "js.ha.health." + f.rule.toLowerCase(); }
export function healthName(f) { return t(healthRule(f) + ".name"); }
export function healthAction(f) { return t(healthRule(f) + ".action"); }

function healthEvery(sec) {
  return sec < 3600 ? t("js.ha.health.every_min", { n: Math.max(1, Math.round(sec / 60)) }) : t("js.ha.health.every_h", { n: Math.round(sec / 3600) });
}
export function healthWhat(f) {
  const d = f.data || {};
  return t(healthRule(f) + ".what", { every: d.period_s ? healthEvery(d.period_s) : "", from: d.from_ms, to: d.to_ms });
}
// "Since 11:00 · last 13:40" (with the day when it began before today).
export function healthWhen(f) {
  const today = f.since > nowSec() - HEALTH_DAY && new Date(f.since * 1000).getDate() === new Date().getDate();
  return t(today ? "js.ha.health.when_today" : "js.ha.health.when_day", { since: fmtStamp(f.since, !today), last: fmtClock(f.last) });
}

// Who: the name of the device, or what tells it apart when it has none.
export function healthDeviceName(d) {
  if (d.name) return d.name;
  return d.mac ? t("js.ha.health.unknown", { mac: "…" + d.mac.slice(-5) }) : t("js.ha.health.noname");
}
// The line of the list: the device and its IP, or how many devices and the one thing they have in common.
export function healthRowFacts(f) {
  if (f.devs.length === 1) return healthDeviceName(f.devs[0]) + (f.devs[0].ip ? " · " + f.devs[0].ip : "");
  const n = t("js.ha.devices_count", { n: f.devs.length });
  return n + " · " + (f.tile === "addr" ? f.devs[0].ip : fmtClock(f.last));
}
// The dots of a restart that repeats: as many as the drops (at most 24), evenly spaced because the rule only fires for a regular one.
export function healthStrip(f) {
  const d = f.data || {};
  if (f.tile !== "boot" || !d.drops) return null;
  const n = Math.min(d.drops, HEALTH_MAX_DOTS), pts = [];
  for (let i = 0; i < n; i++) pts.push(n === 1 ? 0.5 : i / (n - 1));
  return { pts: pts, l1: t("js.ha.health.times", { n: d.drops }), l2: t("js.ha.health.every", { every: healthEvery(d.period_s || 0) }) };
}
