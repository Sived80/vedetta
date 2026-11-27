// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
import { $, api, esc, icon, t } from "./core.js";
import { S } from "./core-ui.js";

// ------------------------------------------------- how to connect Home Assistant (Docker)
// In Docker Vedetta needs the address of Home Assistant and a long-lived access token (DOCKER.md). This window says the state of the
// connection (S.haLink, from the server: ha_registry.link) and the four steps to connect it. It opens by itself once per page, after the
// login, while Home Assistant is not connected, unless the person ticked «Do not show again» (setting ha_help_hidden, kept on the server:
// the same on every browser); the Home Assistant tile of the carousel opens it again at any time.
var helpDlg = $("hahelpdlg");
var GUIDE = "https://github.com/Sived80/vedetta/blob/main/docs/DOCKER.md#home-assistant";
var STEPS = ["js.ha.hahelp.step1", "js.ha.hahelp.step2", "js.ha.hahelp.step3", "js.ha.hahelp.step4"];      // written out: the keys are checked by name
var SUBS = { no_url: "js.ha.hahelp.sub_no_url", no_token: "js.ha.hahelp.sub_no_token", refused: "js.ha.hahelp.sub_refused",
  unreachable: "js.ha.hahelp.sub_unreachable", connected: "js.ha.hahelp.sub_connected" };
var shownOnce = false;

function closeHelp() {
  const box = helpDlg.querySelector("[data-hahelp-hide]");
  const hide = !!(box && box.checked);
  if (S.haLink && hide !== !!S.haLink.help_hidden) {
    S.haLink.help_hidden = hide;
    api("/api/settings", { method: "POST", json: { ha_help_hidden: hide } }).catch(function () {});
  }
  if (helpDlg.open && typeof helpDlg.close === "function") helpDlg.close(); else helpDlg.removeAttribute("open");
}
function helpHTML(link) {
  const state = link.connected ? "connected" : (link.problem || "no_url");
  const steps = STEPS.map(function (key) { return "<li>" + esc(t(key)) + "</li>"; });
  return '<div class="mi"><div class="mi-header"><button type="button" class="icon-btn touch rp" data-hahelp="close" aria-label="' + esc(t("js.ha.more.close")) + '">' + icon("close") +
    '</button><div class="mi-titles"><h2 class="mi-title" id="hahelpdlg-title">' + esc(t("js.ha.hahelp.title")) + '</h2><div class="mi-sub hh-state hh-' + state + '">' +
    esc(t(SUBS[state])) + "</div></div></div>" +
    '<div class="mi-body upd-body"><p class="upd-intro">' + esc(t("js.ha.hahelp.intro")) + '</p><ol class="upd-steps">' + steps.join("") + "</ol>" +
    '<label class="hh-hide"><input type="checkbox" data-hahelp-hide="1"' + (link.help_hidden ? " checked" : "") + "> " + esc(t("js.ha.hahelp.dont_show")) + "</label></div>" +
    '<div class="mi-actions"><button type="button" class="btn text rp" data-hahelp="close">' + esc(t("js.ha.more.close")) + "</button>" +
    '<a class="btn filled rp" href="' + GUIDE + '" target="_blank" rel="noopener noreferrer">' + icon("open-in-new") + "<span>" + esc(t("js.ha.hahelp.guide")) + "</span></a></div></div>";
}
export function openHaHelp() {
  if (!S.haLink) return;
  helpDlg.innerHTML = helpHTML(S.haLink);
  if (!helpDlg.open) { if (typeof helpDlg.showModal === "function") helpDlg.showModal(); else helpDlg.setAttribute("open", ""); }
}
// After a summary of the server: the first time on this page, open it if Home Assistant is not connected and the person did not hide it.
export function maybeHaHelp() {
  const link = S.haLink;
  if (shownOnce || !link || link.connected || link.help_hidden) return;
  shownOnce = true;
  openHaHelp();
}
helpDlg.addEventListener("click", function (e) {
  if (e.target === helpDlg || e.target.closest('[data-hahelp="close"]')) closeHelp();
});
helpDlg.addEventListener("cancel", function (e) { e.preventDefault(); closeHelp(); });
