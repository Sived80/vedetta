  // ---------------------------------------------------- new devices
  var newEl = $("card-new");
  // Rows of the card: the devices found by the last scan (S.found, with
  // Add) and the never-seen MACs detected on the network (S.newDevices); no duplicates by IP.
  // The rows being added (S.adding) stay in the card until "Close", even when the server no longer lists them as new.
  function newRows() {
    var seen = {}, rows = [];
    // The same device appears only once: by IP or by MAC.
    function keys(d) {
      var k = [];
      if (d.ip) k.push("i:" + d.ip);
      if (d.mac) k.push("m:" + String(d.mac).toUpperCase());
      return k;
    }
    function take(row) {
      var k = keys(row);
      if (k.some(function (x) { return seen[x]; })) return;
      k.forEach(function (x) { seen[x] = true; });
      rows.push(row);
    }
    S.found.forEach(function (h) {
      take({ src: "found", ip: h.ip, mac: h.mac, name: h.hostname || "" });
    });
    // Never-seen MACs detected on the network are added only after a completed scan.
    var list = (S.scanDone || S.newReady) ? S.newDevices.devices : [];
    list.forEach(function (d) {
      if (S.dismissedNew[String(d.mac || d.ip).toUpperCase()]) return;     // closed with "Cancel": it comes back only for a device not seen before
      take({ src: "new", ip: d.ip, mac: d.mac, name: d.hostname || "" });
    });
    var ad = S.adding;
    if (ad) Object.keys(ad.ips).forEach(function (ip) { if (ad.meta[ip]) take(ad.meta[ip]); });
    // In IP address order (those without a known one at the bottom).
    rows.sort(function (a, b) { return (a.ip ? ipKey(a.ip) : Infinity) - (b.ip ? ipKey(b.ip) : Infinity); });
    return rows;
  }
  // The ring in the icon of a row: it turns while the device is analysed, closes when it is saved and becomes a tick.
  function ndRing(state, fresh) {
    var c = '<circle class="tr" cx="16" cy="16" r="13"/>';
    if (state === "run") return '<svg class="nd-ring" viewBox="0 0 32 32" aria-hidden="true">' + c + '<circle class="sp" cx="16" cy="16" r="13"/></svg>';
    if (state === "save") return '<svg class="nd-ring" viewBox="0 0 32 32" aria-hidden="true">' + c + '<circle class="close" cx="16" cy="16" r="13"/></svg>';
    return '<svg class="nd-ring" viewBox="0 0 32 32" aria-hidden="true"><circle class="full' + (fresh ? " fresh" : "") + '" cx="16" cy="16" r="13"/><path class="tick' + (fresh ? " fresh" : "") + '" d="M10 16.5l4 4 8-9"/></svg>';
  }
  function renderNew() {
    if (COMPACT) { newEl.hidden = true; return; }
    var list = newRows();
    if (!list.length) { newEl.hidden = true; newEl.innerHTML = ""; return; }
    var opening = newEl.hidden;      // the card appears now: it opens (below), instead of the page jumping to it
    newEl.hidden = false;
    var ad = S.adding;  // during the add: {ips, done (analysed), saved, mode ("single" | "batch"), meta, fresh, jobs, list, batch}
    var run = 0, analysed = 0, saved = 0;
    if (ad) Object.keys(ad.ips).forEach(function (ip) { if (ad.saved[ip]) saved++; else if (ad.done[ip]) analysed++; else run++; });
    var active = run + analysed, total = run + analysed + saved, fin = !!ad && !active && saved > 0;
    var none = "<span></span>";
    var rows = list.map(function (d) {
      var state = ad && ad.ips[d.ip] ? (ad.saved[d.ip] ? "done" : ad.done[d.ip] ? "save" : "run") : "idle";
      var label = d.ip || d.mac;  // only IP and MAC: names are found later, by analyzing the device
      var cells;
      if (state === "idle") {
        var ignoreBtn = d.src === "found"
          ? '<button type="button" class="btn text rp" data-ign-ip="' + esc(d.ip) + '" data-ign-mac="' + esc(d.mac || "") + '" data-ign-host="' + esc(d.name || "") + '" title="' + esc(t("js.ha.new.ignore")) + '" aria-label="' + esc(t("js.ha.new.ignore")) + '">'
          : '<button type="button" class="btn text rp" data-ignore-mac="' + esc(d.mac) + '" title="' + esc(t("js.ha.new.ignore")) + '" aria-label="' + esc(t("js.ha.new.ignore")) + '">';
        ignoreBtn += '<span class="nd-lbl">' + esc(t("js.ha.new.ignore")) + "</span>" + icon("eye-off", "nd-ico") + "</button>";
        cells = (d.ip ? '<button type="button" class="btn tonal rp" data-add-ip="' + esc(d.ip) + '" data-add-host="' + esc(d.name || "") + '">' + esc(t("js.ha.new.add_one")) + "</button>" : none) + ignoreBtn;
      } else if (state === "done") {
        cells = none + none;
      } else {
        cells = (ad.mode[d.ip] === "single" ? '<button type="button" class="btn text rp" data-add-cancel="' + esc(d.ip) + '">' + esc(t("js.ha.cancel")) + "</button>" : none) +
          '<span class="nd-status" title="' + esc(t("js.ha.new.working")) + '"><span class="nd-lbl">' + esc(t("js.ha.new.working")) + '</span><svg class="nd-mini nd-ico" viewBox="0 0 32 32" aria-hidden="true"><circle class="tr" cx="16" cy="16" r="13"/><circle class="sp" cx="16" cy="16" r="13"/></svg></span>';
      }
      var fresh = state === "done" && ad.fresh[d.ip] && Date.now() - ad.fresh[d.ip] < 900;
      return '<div class="nd-row nd-' + state + '" data-ip="' + esc(d.ip || "") + '"><span class="nd-ic">' + (state === "idle" ? icon("devices") : ndRing(state, fresh)) + '</span><div class="nd-text"><div class="nd-name">' + esc(label) +
        '</div><div class="nd-sub">' + esc(d.ip && d.mac ? d.mac : "") + '</div></div><div class="nd-actions">' + cells + "</div></div>";
    }).join("");
    var title, sub;
    if (active) { title = t("js.ha.new.run_title", { done: saved, total: total }); sub = t("js.ha.new.run_sub"); }
    else if (fin) { title = t("js.ha.new.added_title", { n: saved }); sub = t("js.ha.new.added_sub"); }
    else { title = S.found.length ? t("js.ha.new.found", { n: list.length }) : t("js.ha.new.title", { n: list.length }); sub = t("js.ha.new.hint"); }
    // The bar of the card: always two cells, "Add all" and "Cancel" (or "Close" when everything has ended), under the title.
    var free = S.found.filter(function (h) { return !(ad && ad.ips[h.ip]); }).length;
    var all = '<button type="button" class="btn text rp" data-add-all="1">' + esc(t("js.ha.new.add_all")) + "</button>", bar;
    if (active && ad.batch) bar = '<button type="button" class="btn text rp" disabled>' + esc(t("js.ha.new.add_all")) + '</button><button type="button" class="btn text rp" data-add-cancel-all="1">' + esc(t("js.ha.cancel")) + "</button>";
    else if (active) bar = (free > 1 ? all : none) + none;                                    // added by hand: no "Cancel" on top
    else if (fin) bar = (free > 1 ? all : none) + '<button type="button" class="btn tonal rp" data-add-close="1">' + esc(t("js.ha.new.close")) + "</button>";
    else bar = (free > 1 ? all : none) + '<button type="button" class="btn text rp" data-ignore-all="1">' + esc(t("js.ha.cancel")) + "</button>";
    var pct = total ? Math.max(4, Math.min(100, (saved + 0.9 * analysed + 0.3 * run) / total * 100)) : 0;
    newEl.innerHTML =
      '<div class="card-header"><span class="ch-ic ' + (fin ? "ok" : "warn") + '">' + icon(fin ? "check-circle" : "plus-circle") + '</span><div class="ch-text"><div class="ch-title small">' +
      esc(title) + '</div><div class="ch-sub">' + esc(sub) + "</div></div></div>" +
      '<div class="nd-bar-actions">' + bar + "</div>" +
      '<div class="nd-list">' + rows + "</div>" +
      '<div class="nd-prog' + (fin ? " ok" : "") + (ad ? "" : " idle") + '" aria-hidden="true"><i style="width:' + pct.toFixed(1) + '%"></i></div>';
    // Opening: the card grows from nothing to its height and what is under it (the log) slides down with it.
    if (opening && !REDUCED && newEl.animate) {
      var full = newEl.getBoundingClientRect().height;
      if (full > 0) newEl.animate([{ height: "0px", opacity: 0 }, { height: full + "px", opacity: 1 }], { duration: 280, easing: "ease-out" });
    }
  }
  // Adding directly from here (in the HA mobile app a link to the classic
  // dashboard would be blocked): associative search on the devices by recommended
  // name and port, then a single save.
  function scanMany(ips, hosts, onResult, signal) {
    var hints = {}, NL = String.fromCharCode(10);
    ips.forEach(function (ip) { if (hosts[ip]) hints[ip] = hosts[ip]; });
    var results = [], complete = [];
    function eat(line) {
      if (line.indexOf("data: ") !== 0) return;
      try {
        var ev = JSON.parse(line.slice(6));
        if (ev.type === "progress" && ev.result) { results.push(ev.result); if (onResult) onResult(ev.result); }
        else if (ev.type === "complete" && ev.results) complete = ev.results;
      } catch (err) { /* invalid row: ignored */ }
    }
    return fetch("/api/scan/deep", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Lang": LANG },
      body: JSON.stringify({ ips: ips, hints: hints }), signal: signal
    }).then(function (r) {
      // Stream reading: each completed device is reported immediately.
      if (!r.body || !r.body.getReader) {
        return r.text().then(function (txt) { txt.split(NL).forEach(eat); });
      }
      var reader = r.body.getReader(), dec = new TextDecoder(), buf = "";
      function pump() {
        return reader.read().then(function (x) {
          if (x.done) { buf.split(NL).forEach(eat); return; }
          buf += dec.decode(x.value, { stream: true });
          var lines = buf.split(NL);
          buf = lines.pop();
          lines.forEach(eat);
          return pump();
        });
      }
      return pump();
    }).then(function () { return complete.length ? complete : results; }).catch(function () { return complete.length ? complete : results; });
  }
  function toDevice(ip, host, r) {
    return { ip: ip, name: (r && r.suggested_name) || host || ip, adapter: (r && r.adapter) || "generic",
      port: (r && r.suggested_port) || 80, scan_info: r && r.scan_info, name_source: r && r.name_source };
  }
  function afterAdd(ips) {
    // The rows added stay in the card (green) until "Close"; without the card (nothing in progress) they leave the list at once.
    if (!S.adding) S.found = S.found.filter(function (h) { return ips.indexOf(h.ip) < 0; });
    return api("/api/new-devices").then(function (list) {
      if (Array.isArray(list)) S.newDevices = { count: list.length, devices: list, init: true };
      renderNew();
      S.dirty.net = true;
      schedule();
    });
  }
  function closeAdding() {
    var ad = S.adding;
    if (!ad) return;
    S.adding = null;
    // "Close" closes the card: the devices added are in the list, the others were not wanted now and a new scan finds them again
    S.found = [];
    S.scanDone = false;
    renderNew();
  }
  function addDevices(ips, hosts, mode) {
    // "Adding" state, shared among several parallel additions. Each row goes: analysed (ring turns) -> saved (ring closes into
    // a tick). The other rows stay usable: each new addition starts at once with its own search (the server queues the heavy
    // jobs). mode "batch" = started with "Add all": from then on the only "Cancel" is the one of the bar and it stops them all.
    var ad = S.adding || (S.adding = { ips: {}, done: {}, saved: {}, mode: {}, meta: {}, fresh: {}, jobs: 0, list: [], batch: false });
    if (mode === "batch") {
      ad.batch = true;
      Object.keys(ad.ips).forEach(function (ip) { if (!ad.saved[ip]) ad.mode[ip] = "batch"; });
    }
    ips = ips.filter(function (ip) { return !ad.ips[ip]; });
    if (!ips.length) { renderNew(); return; }
    var current = newRows();
    ips.forEach(function (ip) {
      var row = current.filter(function (r) { return r.ip === ip; })[0];
      ad.meta[ip] = row ? { src: row.src, ip: row.ip, mac: row.mac, name: row.name } : { src: "found", ip: ip };
      ad.ips[ip] = true;
      ad.mode[ip] = mode === "batch" ? "batch" : "single";
    });
    ad.jobs++;
    var job = { ips: ips, cancelled: false, dropAll: false, ctrl: window.AbortController ? new AbortController() : null };
    ad.list.push(job);
    renderNew();
    function finish() {
      ad.jobs--;
      if (ad.jobs <= 0 && S.adding === ad) {
        ad.batch = false;
        if (!Object.keys(ad.saved).length) S.adding = null;      // nothing was added: the card goes back to how it was
        renderNew();                                             // otherwise it stays, green, until "Close"
        // A device that the card itself brought (seen on the network, not chosen from a search) has no list to come back to:
        // when it is saved the card goes away by itself, after the tick has been seen.
        var savedIps = Object.keys(ad.saved);
        if (S.adding === ad && savedIps.length && !S.found.length && savedIps.every(function (ip) { return ad.meta[ip] && ad.meta[ip].src === "new"; })) {
          setTimeout(function () { if (S.adding === ad && !ad.jobs) closeAdding(); }, 2200);
        }
      }
    }
    var use = ips;
    scanMany(ips, hosts, function (r) { if (ad.ips[r.ip]) ad.done[r.ip] = true; renderNew(); }, job.ctrl && job.ctrl.signal).then(function (results) {
      var byIp = {};
      results.forEach(function (r) { byIp[r.ip] = r; });
      // Cancelled: only the devices whose analysis had already finished are kept (none, if that row was cancelled by hand).
      use = job.dropAll ? [] : (job.cancelled ? ips.filter(function (ip) { return byIp[ip]; }) : ips);
      use = use.filter(function (ip) { return ad.ips[ip]; });
      use.forEach(function (ip) { ad.done[ip] = true; });
      renderNew();
      if (!use.length) return null;
      var devices = use.map(function (ip) { return toDevice(ip, hosts[ip], byIp[ip]); });
      return api("/api/devices/add", { method: "POST", json: { devices: devices } });
    }).then(function (res) {
      if (res) use.forEach(function (ip) { ad.saved[ip] = true; ad.fresh[ip] = Date.now(); });
      finish();
      return res ? afterAdd(use) : null;
    }).catch(function () {
      ips.forEach(function (ip) { delete ad.ips[ip]; delete ad.done[ip]; delete ad.mode[ip]; delete ad.meta[ip]; });
      finish();
      renderNew();
      snack(t("js.ha.toast.error"), { kind: "error" });
    });
  }
  newEl.addEventListener("click", function (e) {
    var add = e.target.closest("[data-add-ip]");
    if (add) {
      var hosts = {};
      hosts[add.dataset.addIp] = add.dataset.addHost;
      addDevices([add.dataset.addIp], hosts, "single");
      return;
    }
    var all = e.target.closest("[data-add-all]");
    if (all) {
      var map = {};
      S.found.forEach(function (h) { map[h.ip] = h.hostname || ""; });
      addDevices(S.found.map(function (h) { return h.ip; }), map, "batch");  // those already in progress are skipped (and join the batch)
      return;
    }
    var rowCancel = e.target.closest("[data-add-cancel]");
    if (rowCancel && S.adding) {
      // "Cancel" on a row: that device goes back to how it was and is not added.
      var ad1 = S.adding, ip1 = rowCancel.dataset.addCancel;
      var job1 = (ad1.list || []).filter(function (j) { return !j.cancelled && j.ips.indexOf(ip1) >= 0; })[0];
      var wasDone = !!ad1.done[ip1];
      delete ad1.ips[ip1]; delete ad1.done[ip1]; delete ad1.mode[ip1]; delete ad1.meta[ip1];
      if (job1) {
        if (job1.ips.length === 1) { job1.dropAll = true; job1.cancelled = true; if (job1.ctrl) job1.ctrl.abort(); }
        if (!wasDone) api("/api/scan/cancel", { method: "POST", json: { ips: [ip1] } }).catch(function () {});
      }
      renderNew();
      return;
    }
    if (S.adding && e.target.closest("[data-add-cancel-all]")) {
      // "Cancel" in the bar, during "Add all": the analyses in progress are stopped (on the server too); the devices already
      // analysed are still added, the others go back to the list.
      var ad2 = S.adding, pending = [];
      (ad2.list || []).forEach(function (job) {
        if (job.cancelled) return;
        job.cancelled = true;
        job.ips.forEach(function (ip) { if (ad2.ips[ip] && !ad2.done[ip]) pending.push(ip); });
        if (job.ctrl) job.ctrl.abort();
      });
      pending.forEach(function (ip) { delete ad2.ips[ip]; delete ad2.mode[ip]; delete ad2.meta[ip]; });
      ad2.batch = false;
      if (pending.length) api("/api/scan/cancel", { method: "POST", json: { ips: pending } }).catch(function () {});
      renderNew();
      return;
    }
    if (e.target.closest("[data-add-close]")) { closeAdding(); return; }
    var ign = e.target.closest("[data-ign-ip]");
    if (ign) {
      ign.disabled = true;
      api("/api/ignored/hosts", { method: "POST", json: { hosts: [{ ip: ign.dataset.ignIp, mac: ign.dataset.ignMac || null, hostname: ign.dataset.ignHost || null }] } })
        .then(function () {
          S.found = S.found.filter(function (h) { return h.ip !== ign.dataset.ignIp; });
          renderNew();

        }).catch(function () {
          ign.disabled = false;
          snack(t("js.ha.toast.error"), { kind: "error" });
        });
      return;
    }
    var ia = e.target.closest("[data-ignore-all]");
    if (ia) {
      // Cancel: closes the list of this scan; the devices are not ignored
      // and a new scan finds them again.
      // Cancel closes what the card shows. With the list of a search on screen it closes only that list: the devices the app saw by
      // itself stay and are the second card (a second Cancel closes it). Without a list it closes the card until something new
      // appears: the devices seen on the network are remembered as dismissed.
      if (!S.found.length) newRows().forEach(function (r) { if (r.src === "new") S.dismissedNew[String(r.mac || r.ip).toUpperCase()] = true; });
      S.found = [];
      S.scanDone = false;
      renderNew();
      return;
    }
    var b = e.target.closest("[data-ignore-mac]");
    if (!b) return;
    var mac = b.dataset.ignoreMac;
    b.disabled = true;
    api("/api/new-devices/ignore", { method: "POST", json: mac === "*" ? {} : { macs: [mac] } }).then(function (list) {
      if (Array.isArray(list)) S.newDevices = { count: list.length, devices: list, init: true };
      renderNew();
      S.dirty.net = true;
      schedule();

    }).catch(function () {
      b.disabled = false;
      snack(t("js.ha.toast.error"), { kind: "error" });
    });
  });

