import { $, TYPE_ORDER, esc, t, typePlural } from "./core.js";
import { S, animateNumber, pauseLeft } from "./core-ui.js";

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

// Types by quantity (ties in the fixed order), each one keeps its own colour slot: the position in TYPE_ORDER.
function typeSegments(c) {
  return TYPE_ORDER.filter(function (k) { return c.types[k]; }).sort(function (a, b) {
    return c.types[b] - c.types[a] || TYPE_ORDER.indexOf(a) - TYPE_ORDER.indexOf(b);
  });
}
function paintTypes(c) {
  const g = $("g-types"), keys = typeSegments(c), sig = keys.map(function (k) { return k + c.types[k]; }).join();
  if (g._sig === sig) return;
  g._sig = sig;
  let off = 0, html = "";
  keys.forEach(function (k) {
    const arc = TYPES_C * c.types[k] / c.total, len = Math.max(0.1, arc - SW_TYPES - TYPE_GAP);
    html += '<circle class="g-seg c' + (TYPE_ORDER.indexOf(k) + 1) + '" data-k="' + k + '" cx="60" cy="60" r="' + R_TYPES + '" stroke-linecap="round" stroke-dasharray="' + len.toFixed(2) + " " + TYPES_C.toFixed(2) +
      '" stroke-dashoffset="' + (-(off + SW_TYPES / 2 + TYPE_GAP / 2)).toFixed(2) + '" transform="rotate(-90 60 60)"><title>' + esc(typePlural(k) + ": " + c.types[k]) + "</title></circle>";
    off += arc;
  });
  g.innerHTML = html;
}

// The total in the centre; on a type (hover or chosen filter) its count, and the other segments fade.
function paintCenter(c) {
  const k = hovered || S.filter.type;
  $("g-of").textContent = k ? typePlural(k) : t("js.ha.gauge.devices");
  animateNumber($("g-val"), k ? c.types[k] || 0 : c.total);
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
  const dot = $("newdot"), n = S.newDevices.count;
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
