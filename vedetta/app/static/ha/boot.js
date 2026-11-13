// The start of the /ha page (issue #48): the data the server wrote in <script type="application/json" id="vedetta-boot"> (a block of data, never
// run, so no Content-Security-Policy of a reverse proxy can stop it) becomes the window.VEDETTA_* names the page reads; then the theme and the
// view chosen before are applied before the first paint (no flash). A file of the app: allowed by any "script-src 'self'".
(function () {
  var boot = {};
  try {
    var el = document.getElementById("vedetta-boot");
    boot = JSON.parse((el && el.textContent) || "{}") || {};
  } catch (err) {}
  window.VEDETTA_BASE = boot.base || "";
  window.VEDETTA_LANG = boot.lang || "en";
  window.VEDETTA_LANG_AUTO = boot.lang_auto !== false;
  window.VEDETTA_I18N = boot.i18n || {};
  window.VEDETTA_LANGS = boot.langs || [];
  // Theme before the first paint: the ?theme= parameter already written by the server wins; without it, the last choice made in the menu.
  try {
    if (!new URLSearchParams(location.search).has("theme")) {
      var s = localStorage.getItem("vedetta-ha-theme");
      if (s === "light" || s === "dark") document.documentElement.setAttribute("data-theme", s);
    }
    if (localStorage.getItem("vedetta-ha-view") === "list") document.documentElement.setAttribute("data-view", "list");
  } catch (err) {}
})();
