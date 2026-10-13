import { $, api, esc, icon, t } from "./core.js";
import { S, raiseSnacks, snack, snacksEl } from "./core-ui.js";

// ------------------------------------------------- search methods (flows)
// Same setting as the classic dashboard (/api/flows): for each type of search,
// which functions to run. Saves on every switch.
var flowsDlg = $("flows");
export function openFlows() {
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
// The three searches are three tabs; under them the functions of the chosen search, grouped by risk, in panels that start closed.
var FL_PROFILES = ["initial", "associative", "deep"], FL_RISKS = ["easy", "invasive", "risky"], flTab = "initial", flOpen = {};
function flSteps(p) { return S.fl.steps.filter(function (s) { return s.flows.indexOf(p) >= 0; }); }
function flLocked(s, p) { return s.locked_in.indexOf(p) >= 0; }
function flOn(s, p) { return flLocked(s, p) || S.fl.flows[p].steps.indexOf(s.id) >= 0; }
function flCount(p) {
  const c = { all: 0, easy: 0, invasive: 0, risky: 0 };
  flSteps(p).forEach(function (s) { if (flOn(s, p)) { c.all++; c[s.risk]++; } });
  return c;
}
function flChips(p) {
  const c = flCount(p);
  return '<span class="risk r-easy"><i></i>' + c.all + " " + esc(t("js.flows.n_on")) + "</span>" +
    '<span class="risk r-invasive' + (c.invasive ? "" : " zero") + '"><i></i>' + c.invasive + " " + esc(t("js.flows.n_inv")) + "</span>" +
    '<span class="risk r-risky' + (c.risky ? "" : " zero") + '"><i></i>' + c.risky + " " + esc(t("js.flows.n_risk")) + "</span>";
}
// Only the numbers change while the user switches functions: the boxes keep their size and place.
function flRefresh() {
  const chips = flowsDlg.querySelector(".fl-chips");
  if (chips) chips.innerHTML = flChips(flTab);
  FL_RISKS.forEach(function (k) {
    const e = flowsDlg.querySelector('[data-gc="' + k + '"]');
    if (!e) return;
    const list = flSteps(flTab).filter(function (s) { return s.risk === k; });
    e.textContent = list.filter(function (s) { return flOn(s, flTab); }).length + "/" + list.length;
  });
}
function renderFlows(focusTab) {
  let r = S.fl, html = '<div class="mi-header"><button type="button" class="icon-btn touch rp" data-fl="close" aria-label="' +
    esc(t("js.ha.more.close")) + '">' + icon("close") + '</button><div class="mi-titles"><h2 class="mi-title" id="flows-title">' +
    esc(t("js.flows.title")) + '</h2><div class="mi-sub">' + esc(t("js.flows.hint")) + "</div></div></div>";
  html += '<div class="fl-top"><div class="fl-tabs" role="tablist">' + FL_PROFILES.map(function (p) {
    const prof = r.flows[p] || {};
    return '<button type="button" role="tab" class="pill rp" id="fl-tab-' + p + '" aria-label="' + esc(prof.label) + '" title="' + esc(prof.description) +
      '" aria-selected="' + (p === flTab) + '" aria-controls="fl-panel" tabindex="' + (p === flTab ? 0 : -1) + '" data-fl-tab="' + p + '"><span class="fl-long">' + esc(prof.label) +
      '</span><span class="fl-short">' + esc(t("js.flows.short_" + p)) + "</span></button>";
  }).join("") + '</div><div class="fl-chips" aria-live="polite"></div></div>';
  html += '<div class="fl-body" id="fl-panel" role="tabpanel" aria-labelledby="fl-tab-' + flTab + '">';
  FL_RISKS.forEach(function (k) {
    const list = flSteps(flTab).filter(function (s) { return s.risk === k; });
    if (!list.length) return;
    const info = (r.risks || {})[k] || { label: k, description: "" }, key = flTab + k, open = !!flOpen[key], id = "fl-g-" + k;
    html += '<section class="fl-grp r-' + k + '"><button type="button" class="fl-grp-h rp" data-fl-grp="' + key + '" aria-expanded="' + open + '" aria-controls="' + id +
      '"><span class="risk-dot r-' + k + '"></span><span class="fl-gt"><b>' + esc(info.label) + "</b><span>" + esc(info.description) + '</span></span><em data-gc="' + k + '"></em>' +
      icon("chevron-down") + '</button><div class="fl-grp-b" id="' + id + '"' + (open ? "" : " hidden") + ">";
    list.forEach(function (s) {
      const locked = flLocked(s, flTab);
      html += '<label class="fl-row' + (locked ? " locked" : "") + '"><span class="fl-text"><b>' + esc(s.label) +
        (locked ? '<span class="fl-req">' + icon("lock") + esc(t("js.flows.required")) + "</span>" : "") + "</b><span>" + esc(s.description) +
        '</span></span><input type="checkbox" class="fl-sw" data-p="' + flTab + '" data-step="' + esc(s.id) + '"' + (flOn(s, flTab) ? " checked" : "") + (locked ? " disabled" : "") + "></label>";
    });
    html += "</div></section>";
  });
  html += '</div><div class="card-actions"><button type="button" class="btn text rp" data-fl="reset">' + esc(t("js.flows.reset")) + "</button></div>";
  flowsDlg.innerHTML = html;
  flRefresh();
  if (focusTab) flowsDlg.querySelector("#fl-tab-" + flTab).focus();
}
flowsDlg.addEventListener("click", function (e) {
  if (e.target === flowsDlg || e.target.closest('[data-fl="close"]')) return closeFlows();
  const tab = e.target.closest("[data-fl-tab]");
  if (tab) { flTab = tab.dataset.flTab; renderFlows(true); return; }
  const grp = e.target.closest("[data-fl-grp]");
  if (grp) {
    var open = grp.getAttribute("aria-expanded") !== "true";
    flOpen[grp.dataset.flGrp] = open;
    grp.setAttribute("aria-expanded", String(open));
    grp.nextElementSibling.hidden = !open;
    return;
  }
  if (e.target.closest('[data-fl="reset"]')) flReset();
});
flowsDlg.addEventListener("keydown", function (e) {
  const tab = e.target.closest("[data-fl-tab]");
  if (!tab || ["ArrowLeft", "ArrowRight", "Home", "End"].indexOf(e.key) < 0) return;
  let i = FL_PROFILES.indexOf(flTab);
  i = e.key === "Home" ? 0 : e.key === "End" ? 2 : (i + (e.key === "ArrowRight" ? 1 : 2)) % 3;
  flTab = FL_PROFILES[i];
  renderFlows(true);
  e.preventDefault();
});
// a line under the header block appears only when the list is scrolled
flowsDlg.addEventListener("scroll", function (e) {
  if (e.target.id === "fl-panel") flowsDlg.querySelector(".fl-top").classList.toggle("scrolled", e.target.scrollTop > 0);
}, true);
// Saving: everything that writes to the server (a change, the reset) goes through one queue, one request at a time and in the order of the
// clicks: requests sent together can arrive out of order and leave an older choice saved. A change waits for the one on its way and is saved
// alone with the latest state (several quick changes make one save).
var flChain = Promise.resolve(), flPending = false;
function flQueue(fn) { flChain = flChain.then(fn, fn); return flChain; }
function flSave() {
  if (flPending) return;
  flPending = true;
  flQueue(function () {
    flPending = false;
    const out = {};
    FL_PROFILES.forEach(function (q) { out[q] = S.fl.flows[q].steps.slice(); });
    return api("/api/flows", { method: "POST", json: { flows: out } }).then(function (r) {
      if (!flPending) S.fl = r;
    }).catch(function (err) {
      snack(err && err.message ? err.message : t("js.ha.toast.error"), { kind: "error" });
      return api("/api/flows").then(function (r) { S.fl = r; renderFlows(); });
    });
  });
}
function flReset() {
  flQueue(function () {
    flPending = false;
    return api("/api/flows/reset", { method: "POST" }).then(function (r) {
      S.fl = r; renderFlows();
    }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); });
  });
}
flowsDlg.addEventListener("change", function (e) {
  if (!e.target.classList.contains("fl-sw")) return;
  const p = e.target.dataset.p, id = e.target.dataset.step, steps = S.fl.flows[p].steps, at = steps.indexOf(id);
  if (e.target.checked && at < 0) steps.push(id); else if (!e.target.checked && at >= 0) steps.splice(at, 1);
  flRefresh();
  flSave();
});

