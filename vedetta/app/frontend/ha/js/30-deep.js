  // ------------------------------------------------- deep search
  // Advanced search: system, open services, web page. Slow. From the menu (all devices, or the ones never analysed) it starts
  // as soon as the choice is made; on a single device the confirmation can be switched off. While one is running no other
  // can start: the buttons are off until it is over (the network search is independent and stays available).
  var SKIP_DEEP_KEY = "vedetta-ha-skip-deep";
  function skipDeepConfirm() { try { return localStorage.getItem(SKIP_DEEP_KEY) === "1"; } catch (err) { return false; } }
  // Devices never analyzed in depth: scanned_at is written only by the deep search ("Last deep search").
  function deepPending() { return Array.from(S.devices.values()).filter(function (d) { return !d.scanned_at && !d.deep_empty_at; }); }
  var deepRunning = false;          // this page started one and the request is still open
  function deepBusy() { return deepRunning; }                       // only a search started from the top buttons blocks the top buttons
  function deepOneBusy(id) { return !!id && S.activity.rescanning.has(id); }   // a device already being searched cannot be started again
  function syncDeepBusy() {
    var busy = deepBusy(), btn = $("btn-deepmenu");
    if (btn) { btn.disabled = busy; btn.title = busy ? t("js.ha.deep.busy") : ""; }
    if (busy && deepMenuEl && !deepMenuEl.hidden) toggleDeepMenu(false);
    if (typeof dlg !== "undefined" && dlg) {
      var sheetBtn = dlg.querySelector('[data-act="deep"]');
      if (sheetBtn) { var one = deepOneBusy(S.open); sheetBtn.disabled = one; sheetBtn.title = one ? t("js.ha.deep.busy") : ""; }
    }
  }
  function runDeep(ids) {
    if (!ids.length || deepBusy()) return;
    deepRunning = true;
    syncDeepBusy();
    api("/api/devices/rescan", { method: "POST", json: { ids: ids } }).then(function () {
      snack(t("js.ha.deep.done"), { kind: "success" });
      fetchHist();
    }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); }).then(function () { deepRunning = false; syncDeepBusy(); });
  }
  var deepMenuEl = $("deep-menu");
  // The badge: how many devices were never analysed in depth. It is ONE element that changes place: on the corner of the arrow
  // while the menu is closed, in the "to analyse" tile while it is open. While it moves it lives in <body>, fixed, so nothing it
  // crosses (overflow, stacking order, the menu itself) can hide it, and it lands in exactly the place it was measured for.
  var deepBadge = document.createElement("span");
  deepBadge.id = "deep-badge"; deepBadge.className = "deep-badge"; deepBadge.dataset.at = "corner"; deepBadge.hidden = true;
  var deepFlight = null, deepFlightId = 0;
  function deepSplit() { return document.querySelector(".gauge-side .split"); }
  function updateDeepBadge() {
    var split = deepSplit();
    if (!split) return;
    var n = S.loaded ? deepPending().length : 0;
    // it lives in the arrow of the network card: when that card is rebuilt (return to the app, reload) the badge is put back
    if (deepBadge.dataset.at === "corner" && deepBadge.parentNode !== split) split.appendChild(deepBadge);
    else if (!deepBadge.parentNode) split.appendChild(deepBadge);
    deepBadge.textContent = n > 99 ? "99+" : String(n);
    deepBadge.hidden = n === 0;
    var label = t("js.ha.deep.badge", { n: n });
    deepBadge.setAttribute("aria-label", label);
    deepBadge.title = label;
    var btn = $("btn-deepmenu");
    if (btn) btn.setAttribute("aria-label", t("js.ha.deep.title") + (n ? " \u00b7 " + label : ""));
    var tile = deepMenuEl.querySelector('[data-deep="pending"]');
    if (tile) {
      tile.disabled = n === 0;
      tile.querySelector("span:not(.dm-slot)").textContent = t(n ? "js.ha.deep.tile_pending_sub" : "js.ha.deep.tile_pending_done");
    }
  }
  function moveDeepBadge(toSlot) {
    var b = deepBadge, dest = toSlot ? deepMenuEl.querySelector(".dm-slot") : deepSplit();
    if (!dest) return;
    var first = b.getBoundingClientRect();           // where it is now (also when it is half way)
    if (deepFlight) { deepFlight.cancel(); deepFlight = null; }
    deepFlightId++;
    b.style.left = b.style.top = "";
    dest.appendChild(b);
    b.dataset.at = toSlot ? "slot" : "corner";
    if (b.hidden || REDUCED || !b.animate || !first.width) return;
    var last = b.getBoundingClientRect(), id = deepFlightId;
    document.body.appendChild(b);
    b.dataset.at = "fly";
    b.style.left = last.left + "px";
    b.style.top = last.top + "px";
    var anim = b.animate([{ transform: "translate(" + (first.left - last.left) + "px," + (first.top - last.top) + "px)" }, { transform: "translate(0px,0px)" }],
      { duration: 320, easing: "cubic-bezier(0.2, 0, 0, 1)" });
    deepFlight = anim;
    function land() {
      if (id !== deepFlightId) return;               // another move started: this one is not the last
      b.style.left = b.style.top = "";
      dest.appendChild(b);
      b.dataset.at = toSlot ? "slot" : "corner";
      deepFlight = null;
    }
    anim.onfinish = land;
    anim.oncancel = land;
  }
  deepBadge.addEventListener("click", function (e) {
    if (deepBadge.dataset.at !== "corner" || deepBusy()) return;
    e.stopPropagation();
    toggleDeepMenu(true);
  });
  function toggleDeepMenu(open) {
    if (open === undefined) open = deepMenuEl.hidden;
    if (open === !deepMenuEl.hidden) return;         // already so: the badge must not move twice
    if (open && deepBusy()) return;                  // one search at a time
    if (open) {
      closePopups("deep");
      if (deepMenuEl.contains(deepBadge)) deepSplit().appendChild(deepBadge);      // never lost with the old tiles
      var pending = deepPending().length;
      deepMenuEl.innerHTML = '<div class="dm-tiles">' +
        '<button type="button" class="dm-tile rp" role="menuitem" data-deep="all">' + icon("magnify") + "<b>" + esc(t("js.ha.deep.tile_all")) + "</b><span>" + esc(t("js.ha.deep.tile_all_sub")) + "</span></button>" +
        '<button type="button" class="dm-tile rp" role="menuitem" data-deep="pending"' + (pending ? "" : " disabled") + ">" + icon("clock-outline") + "<b>" + esc(t("js.ha.deep.tile_pending")) + "</b><span>" +
        esc(t(pending ? "js.ha.deep.tile_pending_sub" : "js.ha.deep.tile_pending_done")) + '</span><span class="dm-slot"></span></button></div>' +
        '<p class="dm-foot">' + esc(t("js.ha.deep.note", { hour: "03:00" })) + "</p>";
      var btn = $("btn-deepmenu"), r = btn.getBoundingClientRect();
      deepMenuEl.style.top = Math.round(r.bottom + 4) + "px";
      deepMenuEl.style.left = "auto";
      deepMenuEl.style.right = Math.max(8, Math.round(window.innerWidth - r.right)) + "px";
      deepMenuEl.hidden = false;
      (deepMenuEl.getAnimations ? deepMenuEl.getAnimations() : []).forEach(function (a) { a.finish(); });   // measure the final place, not the opening one
      moveDeepBadge(true);
    } else {
      moveDeepBadge(false);
      deepMenuEl.hidden = true;
    }
    var b2 = $("btn-deepmenu"); if (b2) b2.setAttribute("aria-expanded", String(open));
  }
  // The choice in the menu starts the search: no confirmation (the badge and the tiles already say what it will do).
  function startDeepAll(mode) {
    if (deepBusy()) { snack(t("js.ha.deep.busy"), { kind: "warning" }); return; }
    var list = mode === "pending" ? deepPending() : S.list;
    if (!list.length) { snack(t(mode === "pending" ? "js.ha.deep.menu_pending_none" : "js.ha.deep.none"), { kind: "warning" }); return; }
    runDeep(list.map(function (d) { return d.id; }));
  }
  document.addEventListener("click", function (e) {
    if (e.target.closest("#btn-deepmenu")) { e.stopPropagation(); toggleDeepMenu(); }
  });
  deepMenuEl.addEventListener("click", function (e) {
    var item = e.target.closest("[data-deep]");
    if (!item || item.disabled) return;
    toggleDeepMenu(false);
    startDeepAll(item.dataset.deep);
  });
  document.addEventListener("click", function (e) {
    if (!deepMenuEl.hidden && !e.target.closest("#deep-menu") && !e.target.closest("#btn-deepmenu")) toggleDeepMenu(false);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !deepMenuEl.hidden) toggleDeepMenu(false);
  });
  window.addEventListener("resize", function () { if (!deepMenuEl.hidden) toggleDeepMenu(false); });

