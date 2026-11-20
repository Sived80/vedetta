// The ring of the device types on the home: every segment is apart from the next by the same gap. A type with a single device in a long list
// has an arc shorter than the round caps of the line: its segment came out longer than its arc and touched the next one (18/11, three types
// of 1 among 36 devices). Here the arcs of real counts: each one is long enough for its dot, the visible gaps are all TYPE_GAP, and the ring
// closes. No browser needed.   from the vedetta/ folder:  node ../tests/ui/check_gauge_gaps_ui.js
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const src = fs.readFileSync(path.join(__dirname, "..", "..", "vedetta", "app", "frontend", "ha", "js", "net-gauge.js"), "utf8");
const body = src.replace(/^import .*$/gm, "").replace(/^export /gm, "");
const box = { Math: Math, TYPE_ORDER: [], S: {}, $: () => null };
vm.runInNewContext(body + "\nthis.out = { segmentArcs, TYPES_C, SW_TYPES, TYPE_GAP };", box);
const { segmentArcs, TYPES_C, SW_TYPES, TYPE_GAP } = box.out;
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FAILED:", msg); } }

for (const counts of [[15, 6, 5, 3, 2, 2, 1, 1, 1], [1, 1], [40], [200, 1, 1, 1, 1, 1, 1, 1, 1, 1], [3, 3, 3]]) {
  const arcs = segmentArcs(counts);
  const sum = arcs.reduce((a, b) => a + b, 0);
  check(Math.abs(sum - TYPES_C) < 0.01, counts.join("/") + ": the ring closes (" + sum.toFixed(2) + ")");
  check(arcs.length < 2 || arcs.every((a) => a - SW_TYPES - TYPE_GAP >= 0.1 - 1e-9), counts.join("/") + ": every arc holds its dot (" + arcs.map((a) => a.toFixed(1)).join(" ") + ")");
  check(arcs.every((a, i) => i === 0 || counts[i] > counts[i - 1] || a <= arcs[i - 1] + 1e-9), counts.join("/") + ": a type with more devices never has a shorter arc");
}

console.log(failed ? "FAILED: " + failed : "ALL OK");
process.exit(failed ? 1 : 0);
