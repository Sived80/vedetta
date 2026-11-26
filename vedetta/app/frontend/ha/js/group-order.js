import { $, TYPE_ORDER, api, esc, icon, setTypeOrder, t, typeIcon, typePlural } from "./core.js";
import { S, raiseSnacks, snacksEl } from "./core-ui.js";
import { schedule } from "./live.js";

// ------------------------------------------------- the order of the groups
// A small window from the menu: one row per group that has devices now, with «to top», up and down; «Reset» goes back to the default order.
// The groups with no device keep their place in the saved order. Every change is saved at once on the server (setting group_order: the same
// order on every device) and the page draws the groups in it right away.
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
// The groups shown in the window: the ones with devices, in the order of the page.
function present() {
  const has = {};
  S.list.forEach(function (d) { has[d.type] = true; });
  return TYPE_ORDER.filter(function (type) { return has[type]; });
}
function moveBtn(dir, type, off) {
  const label = t("js.ha.order." + dir, { name: typePlural(type) });
  const ic = dir === "up" ? "chevron-up" : dir === "down" ? "chevron-down" : "format-vertical-align-top";
  return '<button type="button" class="icon-btn go-mv rp" data-go-' + dir + '="1" aria-label="' + esc(label) + '" title="' + esc(label) + '"' + (off ? " disabled" : "") + ">" +
    icon(ic) + "</button>";
}
function renderOrder() {
  const shown = present(), last = shown.length - 1;
  orderDlg.innerHTML = '<div class="mi"><div class="mi-header"><button type="button" class="icon-btn touch rp" data-go-close="1" aria-label="' + esc(t("js.ha.more.close")) + '">' +
    icon("close") + '</button><div class="mi-titles"><h2 class="mi-title" id="orderdlg-title">' + esc(t("js.ha.order.title")) + '</h2><div class="mi-sub">' +
    esc(t("js.ha.order.sub")) + "</div></div></div>" +
    '<div class="mi-body go-body"><ol class="go-list">' + shown.map(function (type, i) {
      return '<li class="go-row" data-go-row="' + esc(type) + '"><span class="go-ic">' + icon(typeIcon(type)) + '</span><span class="go-name">' + esc(typePlural(type)) +
        "</span>" + moveBtn("top", type, i === 0) + moveBtn("up", type, i === 0) + moveBtn("down", type, i === last) + "</li>";
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
// One place up or down among the groups shown (it swaps with the shown neighbour; the empty groups do not move), or to the top.
function move(type, how) {
  const list = TYPE_ORDER.slice(), shown = present(), at = shown.indexOf(type);
  if (how === "top") {
    if (at <= 0) return;
    list.splice(list.indexOf(type), 1);
    list.unshift(type);
  } else {
    const other = shown[at + (how === "up" ? -1 : 1)];
    if (at < 0 || !other) return;
    const i = list.indexOf(type), j = list.indexOf(other);
    list[i] = other; list[j] = type;
  }
  apply(list, list);
  // the focus stays on the moved group: on the same button, or on another of its row when that one is off now
  const row = orderDlg.querySelector('[data-go-row="' + type + '"]');
  const btns = row ? ["[data-go-" + how + "]", "[data-go-down]", "[data-go-up]"].map(function (sel) { return row.querySelector(sel); }) : [];
  const focus = btns.filter(function (b) { return b && !b.disabled; })[0];
  if (focus) focus.focus();
}
orderDlg.addEventListener("click", function (e) {
  if (e.target === orderDlg || e.target.closest("[data-go-close]")) return closeOrder();
  if (e.target.closest("[data-go-reset]")) { apply([], []); const r = orderDlg.querySelector("[data-go-reset]"); if (r) r.focus(); return; }
  const btn = e.target.closest("[data-go-up], [data-go-down], [data-go-top]");
  if (!btn || btn.disabled) return;
  move(btn.closest("[data-go-row]").getAttribute("data-go-row"), btn.hasAttribute("data-go-up") ? "up" : btn.hasAttribute("data-go-down") ? "down" : "top");
});
