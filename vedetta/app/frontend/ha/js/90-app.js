  // ---------------------------------------------------------- update
  // Changes accumulate and are applied once per frame.
  function schedule() {
    if (S.flushQueued) return;
    S.flushQueued = true;
    requestAnimationFrame(flush);
  }
  function flush() {
    S.flushQueued = false;
    var dirty = S.dirty;
    if (!S.loaded) return;
    if (dirty.layout) { dirty.layout = false; layout(); dirty.ids.clear(); }
    else if (COMPACT && dirty.ids.size) { layout(); dirty.ids.clear(); }
    else { dirty.ids.forEach(updateTile); dirty.ids.clear(); }
    if (dirty.net) { dirty.net = false; updateNetwork(); updateScan(); }
    if (dirty.more) { dirty.more = false; updateMore(); }
  }


  // New devices detected on the network (card and notifications) are shown only when the
  // card panel is already populated, and a few seconds later: first the dashboard, then
  // the news. After a manual search they appear immediately (S.scanDone).
  var NEW_DELAY_MS = 10000;
  function armNew() {
    if (S.newReady || S.newTimer || !S.list.length) return;
    S.newTimer = setTimeout(function () {
      S.newReady = true;
      renderNew();
      S.dirty.net = true;
      schedule();
    }, NEW_DELAY_MS);
  }
  function onDevice(ev) {
    var d = prepare(ev.device), prev = S.devices.get(d.id);
    S.devices.set(d.id, d);
    if (S.refreshing) S.changedSince++;
    var structural = !prev || prev.type !== d.type || prev.icon !== d.icon || prev.name !== d.name || prev.ip !== d.ip || prev.is_mobile !== d.is_mobile;
    // New device or category, icon, name, IP changed: the internal list (from which the
    // groups are made) is rebuilt, otherwise the card stays in the old group.
    if (structural) rebuildList();
    if (prev && prev.online !== d.online) {
      flash(d.id, d.online ? "on" : "off");
      histPush(d.id, d.online);
      fetchLogSoon();
    }
    var f = S.filter;
    if (structural || prev.online !== d.online || f.status !== "all" || f.type || f.q || COMPACT) S.dirty.layout = true;
    S.dirty.ids.add(d.id);
    S.dirty.net = true;
    if (S.open === d.id) S.dirty.more = true;
    schedule();
    armNew();
  }
  function onRemoved(ev) {
    S.devices.delete(ev.id);
    S.tiles.delete(ev.id);
    S.hist.delete(ev.id);
    rebuildList();
    if (S.open === ev.id) closeMore();
    S.dirty.layout = true;
    S.dirty.net = true;
    schedule();
  }
  function onPoll(ev) {
    S.poll.known = true;
    S.poll.interval = ev.interval_ms || 30000;
    S.poll.nextAt = Date.now() + (ev.next_in_ms == null ? S.poll.interval : ev.next_in_ms);
    S.poll.paused = !!ev.paused;
    S.poll.pausedAt = ev.paused_in_ms == null ? null : Date.now() + ev.paused_in_ms;
    S.poll.pausedTotal = ev.paused_total_ms || null;
    refreshDone();
    updateScan();
  }
  function onActivity(ev) {
    var prev = S.activity.rescanning;
    S.activity.search = !!ev.search;
    S.activity.rescanning = new Set(ev.rescanning || []);
    prev.forEach(function (id) { S.dirty.ids.add(id); });
    S.activity.rescanning.forEach(function (id) { S.dirty.ids.add(id); });
    S.dirty.net = true;
    schedule();
  }
  function onNewDevices(ev) {
    var before = S.newDevices;
    var count = ev.count || 0;
    if ((S.scanDone || S.newReady) && before.init && count > before.count) {
      var known = {};
      before.devices.forEach(function (d) { known[d.mac] = true; });
      var fresh = (ev.devices || []).filter(function (d) { return !known[d.mac]; })[0] || {};
      snack(t("js.ha.new.toast", { label: fresh.hostname || fresh.brand || fresh.vendor || fresh.ip || "?" }), {
        kind: "warning", ms: 7000,
        action: { text: t("js.ha.toast.view"), fn: function () { if (newEl.scrollIntoView) newEl.scrollIntoView({ behavior: "smooth", block: "nearest" }); } }
      });
    }
    S.newDevices = { count: count, devices: ev.devices || [], init: true };
    renderNew();
    S.dirty.net = true;
    schedule();
  }
  var ALERT_TOAST = { "alert.ip_conflict": true, "alert.dhcp_multiple": true };
  function onAlert(ev) {
    if (S.log.open) fetchLogSoon();
    if (ev.message && ALERT_TOAST[ev.key]) snack(ev.message, { kind: "warning", ms: 7000 });
  }

  // ------------------------------------------------------- real-time stream
  function connect() {
    clearTimeout(S.retryTimer);
    if (S.es) { S.es.close(); S.es = null; }
    var es = new EventSource("/api/ha/events?rev=" + S.rev + "&lang=" + encodeURIComponent(LANG));
    S.es = es;
    S.conn.last = Date.now();
    function on(name, fn) {
      es.addEventListener(name, function (e) {
        S.conn.last = Date.now();
        var ev;
        try { ev = JSON.parse(e.data); } catch (err) { return; }
        if (typeof ev.rev === "number" && ev.rev > S.rev) S.rev = ev.rev;
        fn(ev);
      });
    }
    on("device", onDevice);
    on("removed", onRemoved);
    on("poll", onPoll);
    on("activity", onActivity);
    on("alert", onAlert);
    on("new_devices", onNewDevices);
    on("roles", function (ev) {
      // UPnP roles, names and types decide category, icon and name: if they change the groups are redone.
      function sig(r) { return JSON.stringify([r.by_ip || {}, r.names || {}, r.types || {}]); }
      var changed = sig(ev) !== sig(S.roles);
      S.roles = { by_ip: ev.by_ip || {}, via: ev.via || {}, names: ev.names || {}, types: ev.types || {}, dhcp: ev.dhcp || [], internet: ev.internet || null };
      S.tiles.forEach(function (el, id) { updateTile(id); });
      // The role also decides the category (e.g. gateway -> network equipment): the
      // devices are reloaded to redo the groups.
      if (changed && S.loaded) load({ silent: true });
      if (S.open && dlg.open && S.mi.view === "main") { var od = S.devices.get(S.open); if (od) miAttrs(od); }
    });
    es.onopen = function () {
      var wasDown = !S.conn.ok && S.conn.everOk;
      S.conn.retryAt = 3000;
      setConn(true);
      // After a drop (or a service restart, which resets the revisions) everything is
      // resynced: devices, categories, icons.
      if (wasDown) { if (S.loaded) load({ silent: true }); fetchLog(); fetchHist(); }
    };
    es.onerror = function () {
      // Reopens with the last seen revision: the server sends only the difference.
      es.close();
      if (S.es === es) S.es = null;
      setConn(false);
      S.retryTimer = setTimeout(connect, S.conn.retryAt);
      S.conn.retryAt = Math.min(15000, Math.round(S.conn.retryAt * 1.6));
    };
  }

  // ------------------------------------------------------------ startup
  var loadTimer = null;
  function load(opts) {
    opts = opts || {};
    clearTimeout(loadTimer);
    return Promise.all([api("/api/ha/summary"), api("/api/ha/devices")]).then(function (res) {
      var sum = res[0], dev = res[1];
      if (!dev.ready && S.loadTries < 8) {
        // The first check cycle has not finished yet: stay on the skeleton.
        S.loadTries++;
        loadTimer = setTimeout(load, 1500);
        return;
      }
      S.devices.clear();
      S.tiles.clear();
      (dev.devices || []).forEach(function (d) { S.devices.set(d.id, prepare(d)); });
      rebuildList();
      S.rev = dev.rev || 0;
      if (sum.poll && sum.poll.interval_ms) {
        S.poll = { known: true, interval: sum.poll.interval_ms, nextAt: Date.now() + (sum.poll.next_in_ms || 0),
          paused: !!sum.poll.paused, pausedAt: sum.poll.paused_in_ms == null ? null : Date.now() + sum.poll.paused_in_ms,
          pausedTotal: sum.poll.paused_total_ms || null };
      }
      S.mqtt = sum.mqtt || null;
      S.activity.search = !!(sum.activity && sum.activity.search);
      S.activity.rescanning = new Set((sum.activity && sum.activity.rescanning) || []);
      if (sum.roles) S.roles = sum.roles;
      var nd = sum.new_devices || {};
      S.newDevices = { count: nd.count || 0, devices: nd.devices || [], init: false };
      S.loaded = true;
      netEl.hidden = false;
      buildNetwork();
      renderNew();
      layout();
      armNew();
      updateNetwork();
      updateScan();
      fetchLog();
      fetchHist();
      api("/api/settings").then(function (s) { if (s && s.miss_limit) S.missLimit = s.miss_limit; }).catch(function () {});
      S.loadFails = 0;
      connect();
    }).catch(function (err) {
      S.loadFails = (S.loadFails || 0) + 1;
      S.lastErr = err || null;
      var expired = !!err && (err.status === 401 || err.status === 403);
      // Silent resync (return to the app, roles): the dashboard stays as it is.
      if (opts.silent && S.loaded) {
        if (expired) reloadHost();
        return;
      }
      S.loaded = false;
      var skeleton = $("skeleton-tiles");
      if (skeleton) skeleton.remove();
      netEl.hidden = true;
      reconcile(groupsEl, [emptyState("error")]);
      if (expired) reloadHost();  // only once a minute: then the button remains
    });
  }

  // What needs refreshing as time passes ("seen 5 min ago", 24 h bars).
  function tick() {
    if (!S.loaded) return;
    S.tiles.forEach(function (el, id) { updateTile(id); });
    document.querySelectorAll(".log-ago").forEach(function (el) { el.textContent = ago(parseFloat(el.dataset.ts)); });
    if (S.open && dlg.open && S.mi.view === "main") { var d = S.devices.get(S.open); if (d) { miHero(d); miAttrs(d); } }
    if (COMPACT) layout();
  }

  buildToolbar();
  showDebugBadge();
  load();
  setInterval(updateScan, 1000);
  // Log open: reloads by itself (more often at the detailed level, where
  // the service entries arrive continuously).
  setInterval(function () {
    if (S.log.open && !document.hidden) fetchLog();
  }, 6000);
  setInterval(tick, 30000);
  setInterval(fetchHist, 300000);
  // If the stream goes quiet (mobile network, standby): beyond the maximum interval between
  // two cycles with no event at all it is reopened from scratch.
  setInterval(function () {
    if (S.es && S.loaded && Date.now() - S.conn.last > POLL_WATCHDOG_MS) connect();
  }, 15000);
  window.addEventListener("pagehide", function () { if (S.es) { S.es.close(); S.es = null; } });
  window.addEventListener("pageshow", function (e) { if (e.persisted && S.loaded) connect(); });
  var hiddenAt = 0;
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") { hiddenAt = Date.now(); return; }
    if (!S.loaded) { load(); return; }                       // it was in error: retry immediately
    tick();
    // After more than 30 s in the background (mobile app, tab in standby) stream and session
    // may be dead: everything is resynced, without showing errors if not needed.
    if (hiddenAt && Date.now() - hiddenAt > 30000) load({ silent: true });
    else if (!S.es) connect();
  });
  // Tab open for a long time with no event (not even the heartbeats every 15 s): session or network
  // dropped without the browser noticing.
  setInterval(function () {
    if (S.loaded && !document.hidden && Date.now() - S.conn.last > 3 * POLL_WATCHDOG_MS) load({ silent: true });
  }, 60000);
})();
