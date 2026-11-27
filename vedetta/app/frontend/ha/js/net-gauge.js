// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
import { $, TYPE_ORDER, esc, t, typePlural } from "./core.js";
import { S, animateNumber, pauseLeft } from "./core-ui.js";
import { newWaitingCount } from "./new-devices.js";

// ------------------------------------------------------------ "living cycle" circle
// Inner ring: the devices by type. Outer ring: the real check cycle (S.poll / S.activity), told by the card's data-phase:
// idle (accent arc filling up to the next check), scan (short arc that turns), deep (full ring that blinks),
// pause (amber arc that empties while the pause runs), stop (full red ring until the service is resumed).
var R_TYPES = 48, SW_TYPES = 10, TYPE_GAP = 3, R_CYCLE = 58;
var TYPES_C = 2 * Math.PI * R_TYPES, CYCLE_C = 2 * Math.PI * R_CYCLE;
var SCAN_ARC = 0.22;
var hovered = null;                 // type under the pointer: the centre shows its count

export function gaugeHTML() {
  return '<svg viewBox="0 0 120 120" role="img"><circle class="g-track" cx="60" cy="60" r="' + R_TYPES + '" stroke-linecap="round"></circle><g id="g-types"></g>' +
    '<g class="cycg"><circle class="cyc" id="cyc" cx="60" cy="60" r="' + R_CYCLE + '" stroke-dasharray="0 ' + CYCLE_C.toFixed(2) + '" transform="rotate(-90 60 60)"></circle></g></svg>' +
    '<div class="gauge-center"><span class="gauge-value" id="g-val">0</span><span class="gauge-of" id="g-of"></span></div>' +
    '<button type="button" class="newdot" id="newdot" hidden></button>';
}

// Types by quantity (ties in the order of the groups), only the ones with devices; each keeps its own colour (.gc-<group>, never red: red
// says offline). Beyond SHOWN_MAX groups, the smallest after the first SHOWN_KEEP become one grey «Others» arc, last: a ring with more
// slices than that cannot be read.
var SHOWN_MAX = 7, SHOWN_KEEP = 6, OTHER = "_other";
function typeSegments(c) {
  const keys = TYPE_ORDER.filter(function (k) { return c.types[k]; }).sort(function (a, b) {
    return c.types[b] - c.types[a] || TYPE_ORDER.indexOf(a) - TYPE_ORDER.indexOf(b);
  });
  const segs = keys.map(function (k) { return { k: k, n: c.types[k] }; });
  if (segs.length <= SHOWN_MAX) return segs;
  const rest = segs.slice(SHOWN_KEEP).reduce(function (sum, s) { return sum + s.n; }, 0);
  return segs.slice(0, SHOWN_KEEP).concat([{ k: OTHER, n: rest }]);
}
function segName(k) { return k === OTHER ? t("js.ha.gauge.others") : typePlural(k); }
// The arc of each segment, in the order of the counts: as its share of the devices, but never shorter than its dot (the line and its round
// caps plus the gap), or a type with one device among many comes out longer than its arc and touches the next one. The arcs held at the
// minimum are taken out and the others share what is left, until none is below it; the ring always closes.
function segmentArcs(counts) {
  const min = SW_TYPES + TYPE_GAP + 0.1, arcs = counts.map(function () { return 0; });
  if (counts.length < 2 || min * counts.length >= TYPES_C) return counts.map(function () { return TYPES_C / counts.length; });
  let held = counts.map(function () { return false; }), changed = true;
  while (changed) {
    changed = false;
    const room = TYPES_C - min * held.filter(Boolean).length;
    const share = counts.reduce(function (sum, n, i) { return held[i] ? sum : sum + n; }, 0);
    counts.forEach(function (n, i) {
      if (held[i]) { arcs[i] = min; return; }
      arcs[i] = room * n / share;
      if (arcs[i] < min) { held[i] = true; changed = true; }
    });
  }
  return arcs;
}
function paintTypes(c) {
  const g = $("g-types"), segs = typeSegments(c), sig = segs.map(function (s) { return s.k + s.n; }).join();
  if (g._sig === sig) return;
  g._sig = sig;
  g._other = segs.length && segs[segs.length - 1].k === OTHER ? segs[segs.length - 1].n : 0;
  const arcs = segmentArcs(segs.map(function (s) { return s.n; }));
  let off = 0, html = "";
  segs.forEach(function (s, i) {
    const arc = arcs[i], len = Math.max(0.1, arc - SW_TYPES - TYPE_GAP);
    html += '<circle class="g-seg gc-' + (s.k === OTHER ? "other" : s.k) + '" data-k="' + s.k + '" cx="60" cy="60" r="' + R_TYPES + '" stroke-linecap="round" stroke-dasharray="' + len.toFixed(2) + " " + TYPES_C.toFixed(2) +
      '" stroke-dashoffset="' + (-(off + SW_TYPES / 2 + TYPE_GAP / 2)).toFixed(2) + '" transform="rotate(-90 60 60)"><title>' + esc(segName(s.k) + ": " + s.n) + "</title></circle>";
    off += arc;
  });
  g.innerHTML = html;
}

// The total in the centre; on a type (hover or chosen filter) its count, and the other segments fade.
function paintCenter(c) {
  const k = hovered || S.filter.type;
  $("g-of").textContent = k ? segName(k) : t("js.ha.gauge.devices");
  animateNumber($("g-val"), k === OTHER ? $("g-types")._other || 0 : k ? c.types[k] || 0 : c.total);
  $("gauge").classList.toggle("has-hl", !!k);
  document.querySelectorAll("#g-types .g-seg").forEach(function (s) { s.classList.toggle("hl", s.dataset.k === k); });
}
export function paintGauge(c) {
  $("gauge")._counts = c;                 // what a hover repaints the centre from
  paintTypes(c);
  paintCenter(c);
  $("gauge").setAttribute("aria-label", t("js.ha.gauge.aria", { online: c.online, total: c.total }));
}

// Hover on a segment shows its type in the centre; the click is handed over (the filter belongs to the card).
export function bindGauge(gauge, onPick) {
  gauge.addEventListener("click", function (e) {
    const seg = e.target.closest(".g-seg");
    if (seg) onPick(seg.dataset.k);
  });
  gauge.addEventListener("pointerover", function (e) {
    if (e.pointerType !== "mouse") return;
    const seg = e.target.closest(".g-seg"), k = seg ? seg.dataset.k : null;
    if (k === hovered) return;
    hovered = k;
    const c = gauge._counts;
    if (c) paintCenter(c);
  });
}

// ------------------------------------------------------------ the new devices dot (+N)
export function paintNewDot() {
  const dot = $("newdot"), n = newWaitingCount();
  if (!dot) return;
  dot.hidden = n === 0;
  dot.textContent = "+" + (n > 99 ? "99" : n);
  const label = t(n === 1 ? "js.ha.new.dot_one" : "js.ha.new.dot_other", { n: n });
  dot.setAttribute("aria-label", label);
  dot.title = label;
}

// ------------------------------------------------------------ the cycle ring
function pauseFraction(left) {
  if (left === Infinity) return 1;
  const all = S.poll.pausedTotal || Math.max(left, S.poll.pausedSeen || 0);
  S.poll.pausedSeen = all;
  return all ? Math.min(1, left / all) : 1;
}
// What the ring tells now. Work in progress wins over the pause (the ring must show that something is running).
export function cycleState() {
  if (S.activity.rescanning.size) return { phase: "deep", frac: 1 };
  if (S.activity.search || S.scanBusy || S.refreshing || !S.poll.known) return { phase: "scan", frac: SCAN_ARC };
  const left = pauseLeft();
  if (left !== null) return { phase: left === Infinity ? "stop" : "pause", frac: pauseFraction(left) };
  S.poll.pausedSeen = 0;
  const rest = S.poll.nextAt - Date.now();
  if (rest <= 0) return { phase: "scan", frac: SCAN_ARC };      // the check is due and its result has not arrived yet
  return { phase: "idle", frac: Math.min(1, 1 - rest / S.poll.interval) };
}
export function paintCycle() {
  const cyc = $("cyc"), st = cycleState();
  if (!cyc) return st;
  $("card-network").dataset.phase = st.phase;
  cyc.setAttribute("stroke-dasharray", Math.max(0.1, CYCLE_C * st.frac).toFixed(2) + " " + CYCLE_C.toFixed(2));
  return st;
}
