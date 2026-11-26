import { $, TYPE_ORDER, api, esc, icon, setTypeOrder, t, typeIcon, typePlural } from "./core.js";
import { S, raiseSnacks, snacksEl } from "./core-ui.js";
import { schedule } from "./live.js";

// ------------------------------------------------- the order of the groups
// A small window from the menu: one row per group, with up and down; «Reset» goes back to the default order. Every change is saved at once
// on the server (setting group_order: the same order on every device) and the page draws the groups in it right away.
var orderDlg = $("orderdlg");
function closeOrder() {
  if (orderDlg.open && typeof orderDlg.close === "function") orderDlg.close(); else orderDlg.removeAttribute("open");
}
export function openOrder() {
  renderOrder();
  if (!orderDlg.open) {
    if (typeof orderDlg.showModal === "function") orderDlg.showModal(); else orderDlg.setAttribute("open", "");
    if (snacksEl.children.length) raiseSnacks();
  }
}
function arrow(dir, type, off) {
  const name = typePlural(type);
  return '<button type="button" class="icon-btn go-mv rp" data-go-' + dir + '="1" aria-label="' + esc(t("js.ha.order." + dir, { name: name })) + '" title="' +
    esc(t("js.ha.order." + dir, { name: name })) + '"' + (off ? " disabled" : "") + ">" + icon(dir === "up" ? "chevron-up" : "chevron-down") + "</button>";
}
function renderOrder() {
  const last = TYPE_ORDER.length - 1;
  orderDlg.innerHTML = '<div class="mi"><div class="mi-header"><button type="button" class="icon-btn touch rp" data-go-close="1" aria-label="' + esc(t("js.ha.more.close")) + '">' +
    icon("close") + '</button><div class="mi-titles"><h2 class="mi-title" id="orderdlg-title">' + esc(t("js.ha.order.title")) + '</h2><div class="mi-sub">' +
    esc(t("js.ha.order.sub")) + "</div></div></div>" +
    '<div class="mi-body go-body"><ol class="go-list">' + TYPE_ORDER.map(function (type, i) {
      return '<li class="go-row" data-go-row="' + esc(type) + '"><span class="go-ic">' + icon(typeIcon(type)) + '</span><span class="go-name">' + esc(typePlural(type)) +
        "</span>" + arrow("up", type, i === 0) + arrow("down", type, i === last) + "</li>";
    }).join("") + "</ol></div>" +
    '<div class="mi-actions"><button type="button" class="btn text rp" data-go-reset="1">' + esc(t("js.ha.order.reset")) + "</button>" +
    '<button type="button" class="btn filled rp" data-go-close="1">' + esc(t("js.ha.more.close")) + "</button></div></div>";
}
// The new order: drawn in the window and on the page, then saved ([] = the default order).
function apply(list, saved) {
  setTypeOrder(list);
  renderOrder();
  S.dirty.layout = true;
  schedule();
  api("/api/settings", { method: "POST", json: { group_order: saved } }).catch(function () { /* the next load says the order the server kept */ });
}
function move(type, step) {
  const list = TYPE_ORDER.slice(), i = list.indexOf(type), j = i + step;
  if (i < 0 || j < 0 || j >= list.length) return;
  list[i] = list[j]; list[j] = type;
  apply(list, list);
  // the focus stays on the moved group: on the same arrow, or on the other one when it reached an end
  const row = orderDlg.querySelector('[data-go-row="' + type + '"]');
  const same = row && row.querySelector(step < 0 ? "[data-go-up]" : "[data-go-down]");
  const focus = same && !same.disabled ? same : row && row.querySelector(step < 0 ? "[data-go-down]" : "[data-go-up]");
  if (focus) focus.focus();
}
orderDlg.addEventListener("click", function (e) {
  if (e.target === orderDlg || e.target.closest("[data-go-close]")) return closeOrder();
  if (e.target.closest("[data-go-reset]")) { apply([], []); const r = orderDlg.querySelector("[data-go-reset]"); if (r) r.focus(); return; }
  const btn = e.target.closest("[data-go-up], [data-go-down]");
  if (!btn || btn.disabled) return;
  move(btn.closest("[data-go-row]").getAttribute("data-go-row"), btn.hasAttribute("data-go-up") ? -1 : 1);
});
