// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
import { $, esc, icon, t } from "./core.js";
import { versionText } from "./filters.js";

// ------------------------------------------------- about
// The Appropriate Legal Notices of the GPL-3.0 (sections 0 and 5d) behind one entry at the foot of the menu, as section 0 allows: the copyright, the
// license with the additional terms of NOTICE, no warranty, and the links to the license and to the source code. COPYRIGHT is the copyright of the
// original; a modified version keeps it here, next to its own, with the line NOTICE (b) asks for: "Based on Vedetta by Sived80 — " + REPO_URL.
var aboutDlg = $("aboutdlg");
var REPO_URL = "https://github.com/Sived80/vedetta";
var LICENSE_URL = REPO_URL + "/blob/main/LICENSE";
var COPYRIGHT = "© 2026 Sived80";
var NEW_TAB = '" target="_blank" rel="noopener noreferrer"';
function closeAbout() {
  if (aboutDlg.open && typeof aboutDlg.close === "function") aboutDlg.close(); else aboutDlg.removeAttribute("open");
}
function aboutHTML() {
  const version = versionText().replace(/^v/, "");      // the same number as the title of the Network card
  return '<div class="mi"><div class="mi-header"><button type="button" class="icon-btn touch rp" data-about="close" aria-label="' + esc(t("js.ha.more.close")) + '">' + icon("close") +
    '</button><div class="mi-titles"><h2 class="mi-title" id="aboutdlg-title">Vedetta</h2><div class="mi-sub">' + esc(t("js.ha.about.sub", { version: version })) + "</div></div></div>" +
    '<div class="mi-body ab-body"><p class="ab-copy">' + esc(COPYRIGHT) + "</p><p>" + esc(t("js.ha.about.free")) + "</p><p>" + esc(t("js.ha.about.warranty")) + "</p>" +
    '<p><a class="ab-link" href="' + LICENSE_URL + NEW_TAB + ">" + esc(t("js.ha.about.license")) + "</a></p></div>" +
    '<div class="mi-actions"><button type="button" class="btn text rp" data-about="close">' + esc(t("js.ha.more.close")) + "</button>" +
    '<a class="btn filled rp" href="' + REPO_URL + NEW_TAB + ">" + icon("open-in-new") + "<span>" + esc(t("js.ha.about.github")) + "</span></a></div></div>";
}
export function openAbout() {
  aboutDlg.innerHTML = aboutHTML();
  if (!aboutDlg.open) { if (typeof aboutDlg.showModal === "function") aboutDlg.showModal(); else aboutDlg.setAttribute("open", ""); }
}
aboutDlg.addEventListener("click", function (e) {
  if (e.target === aboutDlg || e.target.closest('[data-about="close"]')) closeAbout();
});
