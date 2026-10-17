import { $, esc, icon, t } from "./core.js";
import { S } from "./core-ui.js";

// ------------------------------------------------- update available
// Vedetta does not update itself. This window says what is going to happen and, on the button, asks Home Assistant to open its own Updates page
// (a message to the host, which navigates its page: from there the user decides, with the backup option of Home Assistant).
var updDlg = $("updatedlg");
var HOST_PATH = "/config/updates";
var STEPS = ["js.ha.update.step1", "js.ha.update.step2", "js.ha.update.step3", "js.ha.update.step4"];      // written out: the keys of the words are checked by name
export function inHomeAssistant() { return window.parent !== window; }
function closeUpdate() {
  if (updDlg.open && typeof updDlg.close === "function") updDlg.close(); else updDlg.removeAttribute("open");
}
function updateHTML(u) {
  const steps = STEPS.map(function (key) { return "<li>" + esc(t(key)) + "</li>"; });
  return '<div class="mi"><div class="mi-header"><button type="button" class="icon-btn touch rp" data-upd="close" aria-label="' + esc(t("js.ha.more.close")) + '">' + icon("close") +
    '</button><div class="mi-titles"><h2 class="mi-title" id="updatedlg-title">' + esc(t("js.ha.update.title")) + '</h2><div class="mi-sub">' +
    esc(t("js.ha.update.sub", { installed: u.installed || "", latest: u.latest || "" })) + "</div></div></div>" +
    '<div class="mi-body upd-body"><p class="upd-intro">' + esc(t("js.ha.update.intro")) + '</p><div class="upd-what">' + esc(t("js.ha.update.what")) +
    '</div><ol class="upd-steps">' + steps.join("") + "</ol></div>" +
    '<div class="mi-actions"><button type="button" class="btn text rp" data-upd="close">' + esc(t("js.ha.cancel")) + '</button>' +
    '<button type="button" class="btn filled rp" data-upd="go">' + icon("upload") + "<span>" + esc(t("js.ha.update.go")) + "</span></button></div></div>";
}
export function openUpdate() {
  updDlg.innerHTML = updateHTML(S.update || {});
  if (!updDlg.open) { if (typeof updDlg.showModal === "function") updDlg.showModal(); else updDlg.setAttribute("open", ""); }
}
updDlg.addEventListener("click", function (e) {
  if (e.target === updDlg || e.target.closest('[data-upd="close"]')) return closeUpdate();
  if (e.target.closest('[data-upd="go"]')) {
    closeUpdate();
    window.parent.postMessage({ type: "home-assistant/navigate", path: HOST_PATH }, "*");
  }
});
