// ------------------------------------------------------------ network health: made-up findings, debug mode only
// To see the screens without a real problem. Nothing is asked of the server or of any device: the answer of /api/ha/health is replaced, in this page, by one of these scenarios.
// The addresses are the ones kept for documentation (192.0.2.x), the names say they are made up. The choice is kept in this browser only.
const SIM_KEY = "vedetta-health-sim";
export const SIM_SCENARIOS = ["off", "calm", "one", "all", "grave", "many"];

export function simScenario() {
  try { const v = localStorage.getItem(SIM_KEY); return SIM_SCENARIOS.indexOf(v) > 0 ? v : "off"; } catch (e) { return "off"; }
}
export function simOn() { return simScenario() !== "off"; }
// The next scenario in the list, back to "off" after the last; returns it.
export function simNext() {
  const next = SIM_SCENARIOS[(SIM_SCENARIOS.indexOf(simScenario()) + 1) % SIM_SCENARIOS.length];
  try { localStorage.setItem(SIM_KEY, next); } catch (e) { /* storage not available: the scenario lasts until the page is closed */ }
  return next;
}

function simDevs(n) {
  const list = [];
  for (let i = 0; i < n; i++) list.push({ name: "Simulated device " + (i + 1), ip: "192.0.2." + (20 + i) });
  return list;
}
function simFinding(rule, tile, lv, key, devs, ageSec, hits, data) {
  const now = Date.now() / 1000;
  return { id: "SIM-" + rule + ":" + key, rule: rule, tile: tile, lv: lv, devs: devs, since: now - ageSec, last: now - 60, hits: hits, shadow: true, data: data };
}
const SIM_FINDINGS = {
  addr: function () { return simFinding("H20", "addr", "warn", "addr", [{ name: "Simulated device 1", ip: "192.0.2.50" }, { name: null, ip: "192.0.2.50", mac: "02:00:5e:00:53:99" }], 1500, 3, { ips: 1, macs: 2 }); },
  drop: function (n) { return simFinding("H06", "drop", "warn", "lan", simDevs(n), 7200, 1, { devices: n, of: 20 }); },
  boot: function () { return simFinding("H05", "boot", "warn", "boot", simDevs(1), 10800, 30, { drops: 11, period_s: 600, cv: 0.1 }); },
  lat: function (lv) { return simFinding("H07", "lat", lv, "lat", simDevs(1), 3000, 6, { from_ms: 4, to_ms: 38 }); },
};
function simFindings(scenario) {
  if (scenario === "one") return [SIM_FINDINGS.boot()];
  if (scenario === "all") return [SIM_FINDINGS.addr(), SIM_FINDINGS.drop(6), SIM_FINDINGS.boot(), SIM_FINDINGS.lat("warn")];
  if (scenario === "grave") return [SIM_FINDINGS.lat("bad"), SIM_FINDINGS.drop(6)];
  if (scenario === "many") return [SIM_FINDINGS.drop(18)];
  return [];
}
// What /api/ha/health would answer in the chosen scenario (nothing hidden: the page keeps its own list while it simulates).
export function simAnswer() {
  const now = Date.now() / 1000;
  return { running: true, findings: simFindings(simScenario()), report: { judged: now - 120, last_problem: { rule: "H20", end: now - 3 * 86400 } }, hidden: [] };
}
