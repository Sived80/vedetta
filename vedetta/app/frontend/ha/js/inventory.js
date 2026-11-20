import { $, LANG, esc, icon, t } from "./core.js";
import { raiseSnacks, snack, snacksEl } from "./core-ui.js";

// ------------------------------------------------- the list of devices, to keep (CSV or JSON)
// Not the export for analysis (that one is the zip for the developer): the person's own list, with «Hide MAC and IP» on by default
// (a list goes around more easily than the person thinks). The file is downloaded the same way as the export.
var invDlg = $("invdlg");
var inv = { format: "csv", hide: true, busy: false };
function closeInv() {
  if (invDlg.open && typeof invDlg.close === "function") invDlg.close(); else invDlg.removeAttribute("open");
}
export function openInventory() {
  inv.busy = false;
  renderInv();
  if (!invDlg.open) {
    if (typeof invDlg.showModal === "function") invDlg.showModal(); else invDlg.setAttribute("open", "");
    if (snacksEl.children.length) raiseSnacks();
  }
}
function fmt(value, label, hint) {
  const on = inv.format === value;
  return '<button type="button" class="al-opt rp" role="radio" aria-checked="' + on + '" data-inv-fmt="' + value + '"><span class="al-dot"></span><span class="al-name">' +
    esc(label) + '</span><span class="inv-hint">' + esc(hint) + "</span></button>";
}
function renderInv() {
  invDlg.innerHTML = '<div class="mi"><div class="mi-header"><button type="button" class="icon-btn touch rp" data-inv="close" aria-label="' + esc(t("js.ha.more.close")) + '">' +
    icon("close") + '</button><div class="mi-titles"><h2 class="mi-title" id="invdlg-title">' + esc(t("js.ha.inv.title")) + '</h2><div class="mi-sub">' +
    esc(t("js.ha.inv.sub")) + "</div></div></div>" +
    '<div class="mi-body al-body"><div class="al-list" role="radiogroup" aria-label="' + esc(t("js.ha.inv.format")) + '">' +
    fmt("csv", "CSV", t("js.ha.inv.csv_hint")) + fmt("json", "JSON", t("js.ha.inv.json_hint")) + "</div>" +
    '<div class="al-row"><div class="al-txt"><div class="al-lbl">' + esc(t("js.ha.inv.hide")) + '</div><div class="al-hint">' + esc(t("js.ha.inv.hide_hint")) +
    '</div></div><button type="button" class="rv-switch' + (inv.hide ? " on" : "") + '" data-inv="hide" role="switch" aria-checked="' + inv.hide +
    '" aria-label="' + esc(t("js.ha.inv.hide")) + '"></button></div></div>' +
    '<div class="mi-actions"><button type="button" class="btn text rp" data-inv="close">' + esc(t("js.ha.cancel")) + "</button>" +
    '<button type="button" class="btn filled rp" data-inv="go"' + (inv.busy ? " disabled" : "") + ">" + icon("download") + "<span>" + esc(t("js.ha.inv.go")) + "</span></button></div></div>";
}
function download() {
  inv.busy = true; renderInv();
  fetch("/api/ha/inventory?format=" + inv.format + "&hide=" + (inv.hide ? 1 : 0) + "&lang=" + encodeURIComponent(LANG), { headers: { "X-Lang": LANG }, cache: "no-store" }).then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status);
    const m = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") || "");
    return r.blob().then(function (blob) { return { blob: blob, name: m ? m[1] : "vedetta-inventory." + inv.format }; });
  }).then(function (f) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(f.blob); a.download = f.name;
    document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 4000);
    closeInv();
    snack(t("js.ha.inv.done"), { kind: "success" });
  }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); })
    .then(function () { inv.busy = false; if (invDlg.open || invDlg.hasAttribute("open")) renderInv(); });
}
invDlg.addEventListener("click", function (e) {
  if (e.target === invDlg || e.target.closest('[data-inv="close"]')) return closeInv();
  const f = e.target.closest("[data-inv-fmt]");
  if (f) { inv.format = f.getAttribute("data-inv-fmt"); return renderInv(); }
  if (e.target.closest('[data-inv="hide"]')) { inv.hide = !inv.hide; return renderInv(); }
  if (e.target.closest('[data-inv="go"]') && !inv.busy) download();
});
