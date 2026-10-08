  // ------------------------------------------------------------- pause
  var pauseEl = $("pause-menu"), liveEl = $("live");
  function buildPause() {
    var html;
    if (S.poll.paused) {
      var left = pauseLeft();
      html = menuGroup(t("js.ha.pause.paused"), pill("lg", "resume", "1", false, t("js.ha.pause.resume"))) +
        '<div class="menu-hint">' + esc(left === Infinity ? t("js.ha.pause.idle") : t("js.ha.pause.idle_left", { left: fmtLeft(left) })) + "</div>";
    } else {
      html = menuGroup(t("js.ha.pause.title"), [15, 60, 480].map(function (n) {
        return pill("md", "pause", n, false, t("js.ha.pause.opt_" + n));
      }).join("") + pill("lg full", "pause", 0, false, t("js.ha.pause.opt_0"))) +
        '<div class="menu-hint">' + esc(t("js.ha.pause.hint")) + "</div>";
    }
    pauseEl.innerHTML = html;
  }
  function togglePause(open) {
    if (open === undefined) open = pauseEl.hidden;
    if (open) {
      closePopups("pause");
      buildPause();
      var r = liveEl.getBoundingClientRect();
      pauseEl.style.top = Math.round(r.bottom + 4) + "px";
      pauseEl.style.right = "auto";
      pauseEl.style.maxHeight = Math.max(160, window.innerHeight - r.bottom - 16) + "px";
      pauseEl.hidden = false;                                  // visible to measure its width: the centre of the menu is the centre of the button
      var w = pauseEl.offsetWidth || 300, centre = r.left + r.width / 2;
      var left = Math.max(8, Math.min(Math.round(centre - w / 2), window.innerWidth - w - 8));
      pauseEl.style.left = left + "px";
      pauseEl.style.transformOrigin = Math.round(centre - left) + "px top";
    }
    pauseEl.hidden = !open;
    liveEl.setAttribute("aria-expanded", String(open));
    if (open) { var f = pauseEl.querySelector(".menu-item"); if (f) f.focus(); }
  }
  liveEl.addEventListener("click", function (e) { e.stopPropagation(); togglePause(); });
  pauseEl.addEventListener("click", function (e) {
    var item = e.target.closest(".menu-item");
    if (!item) return;
    var req = item.dataset.resume
      ? api("/api/pause", { method: "DELETE" })
      : api("/api/pause", { method: "POST", json: { minutes: +item.dataset.pause } });
    togglePause(false);
    req.then(function (ev) {
      onPoll(ev);
    }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); });
  });
  document.addEventListener("click", function (e) {
    if (!pauseEl.hidden && !e.target.closest("#pause-menu")) togglePause(false);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !pauseEl.hidden) { togglePause(false); liveEl.focus(); }
  });
  window.addEventListener("resize", function () { if (!pauseEl.hidden) togglePause(false); });

  // ------------------------------------------------- ignored devices
  // Two origins: "Ignore" on a device found by a search (an entry of the list: MAC, IP or name) and "Ignore" on a device found on the network (its MAC).
  // Each row has a menu (three dots) with Restore and Forget. Both work with a countdown: the pressed item becomes "Undo" with a colour sliding
  // across it for 5 s; only Undo stops it; leaving the menu, the sheet or the window lets it run to the end, and it ends with a notice (no Undo).
  // Rows are independent (a countdown each); the two group buttons below are locked while any countdown runs, and lock the rows while theirs does.
  var ignDlg = $("ignored");
  var IGN_UNDO_MS = 5000;
  var ign = { rows: [], kind: "mac", pend: {}, bulk: null, menu: null, menuBtn: null, ui: null };

  function ignRowsFrom(g) {
    var rows = [];
    g.items.forEach(function (it) {
      rows.push({ id: "i" + it.id, api: { id: it.id }, source: "search", kind: it.kind, title: it.label || it.value,
        ip: it.kind === "ip" ? it.value : "", mac: it.kind === "mac" ? it.value : "", name: it.kind === "name" ? it.value : "", vendor: "" });
    });
    g.macs.forEach(function (m) {
      rows.push({ id: "m" + m.mac, api: { mac: m.mac }, source: "network", kind: "mac", title: m.hostname || m.vendor || m.ip || m.mac,
        ip: m.ip || "", mac: m.mac, name: m.hostname || "", vendor: m.vendor || "" });
    });
    return rows;
  }
  function ignIds(r) {
    var a = [r.ip, r.mac].filter(function (x) { return x && x !== r.title; });
    if (!a.length && r.vendor && r.vendor !== r.title) a = [r.vendor];
    if (!a.length) a = [t("js.ha.ign.kind_" + r.kind)];
    return a.join(" · ");
  }
  function ignRowHtml(r) {
    var net = r.source === "network", where = t(net ? "js.ha.ign.from_network" : "js.ha.ign.from_search"), ids = ignIds(r);
    var full = r.title + "\n" + [r.ip, r.mac, r.vendor].filter(Boolean).join(" · ") + " · " + where;
    return '<div class="ig-item" data-id="' + esc(r.id) + '"><div class="nd-row" title="' + esc(full) + '"><span class="nd-ic">' + icon("eye-off") + "</span>" +
      '<div class="nd-text"><div class="nd-name" title="' + esc(r.title) + '">' + esc(r.title) + '</div><div class="nd-sub"><span class="ids" title="' + esc(ids) + '">' + esc(ids) +
      '</span><span class="org" title="' + esc(where) + '">' + icon(net ? "lan" : "magnify") + '<span class="vh">' + esc(where) + "</span></span></div></div>" +
      '<div class="nd-actions"><button type="button" class="icon-btn rp" data-ign="more" aria-haspopup="menu" aria-expanded="false" aria-label="' + esc(t("js.ha.ign.more")) +
      '" title="' + esc(t("js.ha.ign.more")) + '">' + icon("dots-vertical") + "</button></div></div></div>";
  }
  function ignBuild() {
    ign.rows = ignRowsFrom(S.ign);
    ign.pend = {}; ign.bulk = null; ign.menu = null; ign.menuBtn = null;
    var kinds = ["mac", "ip", "name"].map(function (k) {
      return '<button type="button" class="pill" data-ign-kind="' + k + '" aria-pressed="' + (k === ign.kind) + '">' + esc(t(k === "name" ? "js.ha.ign.pill_name" : "js.ha.ign.kind_" + k)) + "</button>";
    }).join("");
    ignDlg.innerHTML = '<div class="mi"><div class="mi-header"><button type="button" class="icon-btn touch rp" data-ign="close" aria-label="' + esc(t("js.ha.more.close")) + '">' + icon("close") + "</button>" +
      '<div class="mi-titles"><h2 class="mi-title" id="ignored-title">' + esc(t("js.ha.menu.ignored")) + '</h2><div class="mi-sub">' + esc(t("js.ha.ign.sub")) + "</div></div>" +
      '<button type="button" class="icon-btn ig-add-btn rp" data-ign="toggle-add" aria-expanded="false" aria-controls="ig-add" title="' + esc(t("js.ha.ign.add")) + '" aria-label="' + esc(t("js.ha.ign.add")) + '">' + icon("plus") + "</button></div>" +
      '<div class="ig-body"><div class="ig-scroll" tabindex="-1"><div class="ig-inner">' +
      '<div class="ig-addwrap" id="ig-add"><div><form class="ig-add" novalidate><div class="ig-kinds" role="group" aria-label="' + esc(t("js.ha.ign.kind_label")) + '">' + kinds + "</div>" +
      '<div class="ig-line"><input class="ig-field" autocomplete="off" autocapitalize="off" spellcheck="false" aria-describedby="ig-err"><button type="submit" class="btn filled rp">' + esc(t("js.ha.ign.go")) + "</button></div>" +
      '<div class="ig-err hint" id="ig-err" aria-live="polite"></div></form></div></div>' +
      '<div class="ig-list">' + ign.rows.map(ignRowHtml).join("") + "</div>" +
      '<div class="ig-empty"><div class="empty-ic">' + icon("eye-off") + "</div><h3>" + esc(t("js.ha.ign.empty")) + "</h3></div></div></div></div>" +
      '<div class="mi-actions"><button type="button" class="btn text ig-all rp" data-ign="all" data-bulk="restore">' + esc(t("js.ha.ign.restore_all")) +
      '</button><button type="button" class="btn text ig-all danger rp" data-ign="all" data-bulk="forget">' + esc(t("js.ha.ign.forget_all")) + "</button></div>" +
      '<div class="vh" role="status" aria-live="polite" id="ig-live"></div></div>';
    ign.ui = { scroll: ignDlg.querySelector(".ig-scroll"), list: ignDlg.querySelector(".ig-list"), empty: ignDlg.querySelector(".ig-empty"), addWrap: ignDlg.querySelector(".ig-addwrap"),
      field: ignDlg.querySelector(".ig-field"), err: ignDlg.querySelector(".ig-err"), addBtn: ignDlg.querySelector(".ig-add-btn"), all: ignDlg.querySelectorAll(".ig-all"), live: ignDlg.querySelector("#ig-live") };
    ignSetKind(ign.kind);
    ignRefresh();
  }
  function ignBar() { if (ign.ui) ignDlg.style.setProperty("--ig-sb", (ign.ui.scroll.offsetWidth - ign.ui.scroll.clientWidth) + "px"); }   // the + sits above the dots: the right edge follows the scroll bar
  function ignRefresh() {
    var n = ign.rows.length;
    [].forEach.call(ign.ui.all, function (b) { b.hidden = !(n >= 2 || (ign.bulk && n >= 1)); });
    ign.ui.empty.classList.toggle("on", n === 0 && !ign.ui.list.querySelector(".ig-item"));
    ignBar();
  }
  function ignSay(s) { var l = ign.ui && ign.ui.live; if (!l) return; l.textContent = ""; setTimeout(function () { l.textContent = s; }, 30); }
  function ignRow(id) { for (var i = 0; i < ign.rows.length; i++) if (ign.rows[i].id === id) return ign.rows[i]; return null; }
  function ignEl(id) { return ign.ui.list.querySelector('.ig-item[data-id="' + id + '"]'); }

  // --- rows fold away and open
  function ignCollapse(el, done) {
    var fin = false;
    function end() { if (fin) return; fin = true; if (el.parentNode) el.parentNode.removeChild(el); if (done) done(); }
    el.style.height = el.offsetHeight + "px";
    void el.offsetHeight;
    el.classList.add("out");
    el.addEventListener("transitionend", function (e) { if (e.propertyName === "height") end(); });
    setTimeout(end, 320);
  }
  function ignExpand(el) {
    el.style.height = "0px"; el.classList.add("out"); void el.offsetHeight;
    el.classList.remove("out"); el.style.height = "60px";
    var f = false;
    function end() { if (f) return; f = true; el.style.height = ""; }
    el.addEventListener("transitionend", end); setTimeout(end, 320);
  }
  function ignInsert(r, flash) {
    var tmp = document.createElement("div"); tmp.innerHTML = ignRowHtml(r);
    var el = tmp.firstChild; ign.ui.list.insertBefore(el, ign.ui.list.firstChild);
    if (flash) el.firstChild.classList.add("fresh");
    ignExpand(el);
  }
  function ignDrop(id) {                 // the row leaves the list (the server is asked by the caller)
    var i = ign.rows.map(function (r) { return r.id; }).indexOf(id); if (i < 0) return null;
    var r = ign.rows.splice(i, 1)[0], el = ignEl(id);
    if (el) ignCollapse(el, ignRefresh);
    ignRefresh();
    return r;
  }

  // --- what the server is asked
  function ignCall(r, kind) {
    if (kind === "restore") {
      return r.api.id ? api("/api/ignored/" + encodeURIComponent(r.api.id), { method: "DELETE" }).then(function (x) { S.ign.items = (x && x.items) || []; })
        : api("/api/new-devices/unignore", { method: "POST", json: { mac: r.api.mac } }).then(function (x) { S.ign.macs = Array.isArray(x) ? x : []; });
    }
    return api("/api/ignored/forget", { method: "POST", json: r.api }).then(function (x) { S.ign.items = (x && x.items) || []; S.ign.macs = (x && x.macs) || []; });
  }
  function ignFailed() {
    snack(t("js.ha.toast.error"), { kind: "error" });
    Promise.all([api("/api/ignored"), api("/api/new-devices/ignored")]).then(function (res) {
      S.ign = { items: (res[0] && res[0].items) || [], macs: Array.isArray(res[1]) ? res[1] : [] };
      if (ignDlg.open) ignBuild();
    }).catch(function () { /* the next opening reads it again */ });
  }

  // --- ROWS: a countdown each
  function ignInner(kind) { return "<span>" + esc(t(kind === "restore" ? "js.ha.ign.restore" : "js.ha.ign.forget")) + "</span>" + icon(kind === "restore" ? "eye" : "delete-outline"); }
  function ignCounting(elapsed) { return '<span class="fill" style="animation-delay:-' + Math.round(elapsed) + 'ms"></span><span>' + esc(t("js.ha.cancel")) + "</span>" + icon("undo"); }
  function ignPaint(item, elapsed) { item.classList.add("counting"); item.innerHTML = ignCounting(elapsed); }
  function ignMenuRow() { return ign.menuBtn ? ign.menuBtn.closest(".ig-item").getAttribute("data-id") : null; }
  function ignRowsBusy() { return Object.keys(ign.pend).length > 0; }
  // what is on and what is off: the group buttons (off while any row or the other group runs), the open menu (off during a group; otherwise,
  // if this row has a countdown, only its Undo is on)
  function ignLock() {
    var rb = ignRowsBusy();
    if (ign.ui) [].forEach.call(ign.ui.all, function (x) { if ((rb || ign.bulk) && !x.classList.contains("counting")) x.setAttribute("aria-disabled", "true"); else x.removeAttribute("aria-disabled"); });
    if (ign.menu) {
      var mine = ign.pend[ignMenuRow()];
      [].forEach.call(ign.menu.querySelectorAll(".menu-item"), function (x) {
        if (!x.classList.contains("counting") && (ign.bulk || mine)) x.setAttribute("aria-disabled", "true"); else x.removeAttribute("aria-disabled");
      });
    }
  }
  function ignFinishRow(id, silent) {
    var f = ign.pend[id]; if (!f) return;
    delete ign.pend[id]; clearTimeout(f.timer);
    var el = ignEl(id), next = el && (el.nextElementSibling || el.previousElementSibling);
    if (ignMenuRow() === id) ignCloseMenu(false);
    var r = ignDrop(id); ignLock(); if (!r) return;
    ignCall(r, f.kind).catch(ignFailed);
    var said = t(f.kind === "restore" ? "js.ha.ign.restored" : "js.ha.ign.forgot") + ": " + r.title;
    if (!silent) {
      snack(said); ignSay(said);
      var fb = next && next.querySelector('[data-ign="more"]');
      if (!ign.menu) (fb || ign.ui.addBtn).focus();
    }
  }
  function ignFinishAllRows(silent) { Object.keys(ign.pend).forEach(function (id) { ignFinishRow(id, silent); }); }
  function ignCancelRow(id) {
    var f = ign.pend[id]; if (!f) return;
    delete ign.pend[id]; clearTimeout(f.timer);
    var it = ign.menu && ignMenuRow() === id && ign.menu.querySelector(".menu-item.counting");
    if (it) { it.classList.remove("counting"); it.innerHTML = ignInner(f.kind); it.focus(); }
    ignLock();
  }
  function ignStartRow(item) {
    var id = item.getAttribute("data-id"), kind = item.getAttribute("data-do");
    if (ign.bulk || ign.pend[id]) return;
    ignPaint(item, 0); item.focus();
    ignSay(t(kind === "restore" ? "js.ha.ign.restored" : "js.ha.ign.forgot") + ". " + t("js.ha.cancel") + "?");
    ign.pend[id] = { kind: kind, start: Date.now(), timer: setTimeout(function () { ignFinishRow(id, false); }, IGN_UNDO_MS) };
    ignLock();
  }

  // --- GROUP: "Restore all" / "Forget all"
  function ignBulkLabel(kind) { return t(kind === "restore" ? "js.ha.ign.restore_all" : "js.ha.ign.forget_all"); }
  function ignBulkReset() {
    [].forEach.call(ign.ui.all, function (b) { b.classList.remove("counting"); b.innerHTML = esc(ignBulkLabel(b.getAttribute("data-bulk"))); });
  }
  function ignFinishBulk(silent) {
    var f = ign.bulk; if (!f) return;
    ign.bulk = null; clearTimeout(f.timer);
    var rows = ign.rows.slice(), n = rows.length;
    rows.forEach(function (r) { ignDrop(r.id); });
    ignBulkReset(); ignLock();
    rows.reduce(function (p, r) { return p.then(function () { return ignCall(r, f.kind); }); }, Promise.resolve()).catch(ignFailed);
    if (!silent && n) { var said = t(f.kind === "restore" ? "js.ha.ign.restored_n" : "js.ha.ign.forgot_n", { n: n }); snack(said); ignSay(said); ign.ui.addBtn.focus(); }
  }
  function ignCancelBulk() {
    var f = ign.bulk; if (!f) return;
    ign.bulk = null; clearTimeout(f.timer);
    ignBulkReset(); ignLock();
  }
  function ignStartBulk(btn) {
    if (ign.bulk || ignRowsBusy()) return;
    var kind = btn.getAttribute("data-bulk");
    btn.classList.add("counting"); btn.innerHTML = '<span class="fill"></span><span>' + esc(t("js.ha.cancel")) + "</span>" + icon("undo");
    ignSay(ignBulkLabel(kind) + ". " + t("js.ha.cancel") + "?");
    ign.bulk = { kind: kind, timer: setTimeout(function () { ignFinishBulk(false); }, IGN_UNDO_MS) };
    ignLock();
  }

  // --- the menu of a row
  function ignCloseMenu(refocus) {
    if (!ign.menu) return;
    var b = ign.menuBtn;
    ign.menu.parentNode.removeChild(ign.menu); ign.menu = null; ign.menuBtn = null;
    if (b) { b.setAttribute("aria-expanded", "false"); if (refocus) b.focus(); }
  }
  function ignOpenMenu(btn) {
    ignCloseMenu(false);
    var id = btn.closest(".ig-item").getAttribute("data-id"), m = document.createElement("div");
    m.className = "menu ig-menu"; m.setAttribute("role", "menu"); m.setAttribute("aria-label", t("js.ha.ign.more"));
    m.innerHTML = '<button type="button" class="menu-item" role="menuitem" tabindex="-1" data-id="' + esc(id) + '" data-do="restore">' + ignInner("restore") + "</button>" +
      '<button type="button" class="menu-item danger" role="menuitem" tabindex="-1" data-id="' + esc(id) + '" data-do="forget">' + ignInner("forget") + "</button>";
    ignDlg.appendChild(m); ign.menu = m; ign.menuBtn = btn; btn.setAttribute("aria-expanded", "true");
    var f = ign.pend[id];
    if (f) ignPaint(m.querySelector('[data-do="' + f.kind + '"]'), Date.now() - f.start);
    ignLock();
    var r = btn.getBoundingClientRect(), mw = m.offsetWidth, mh = m.offsetHeight, vw = window.innerWidth, vh = window.innerHeight;
    var left = Math.max(8, Math.min(r.right - mw, vw - mw - 8)), top = r.bottom + 4;
    if (top + mh > vh - 8) top = Math.max(8, r.top - mh - 4);
    m.style.left = left + "px"; m.style.top = top + "px"; m.style.right = "auto"; m.style.transformOrigin = "top right";
    var first = m.querySelector(".counting") || m.querySelector(".menu-item"); first.focus();
  }

  // --- add by hand
  function ignHint() { return ign.kind === "mac" ? t("js.ha.ign.hint_mac") : ign.kind === "ip" ? t("js.ha.ign.hint_ip") : ""; }
  function ignErr(msg) {
    var u = ign.ui; u.err.textContent = msg || ignHint(); u.err.classList.toggle("hint", !msg);
    if (msg) u.field.setAttribute("aria-invalid", "true"); else u.field.removeAttribute("aria-invalid");
  }
  function ignSetKind(k) {
    var u = ign.ui; ign.kind = k;
    [].forEach.call(ignDlg.querySelectorAll(".ig-kinds .pill"), function (p) { p.setAttribute("aria-pressed", p.getAttribute("data-ign-kind") === k); });
    u.field.placeholder = t("js.ha.ign.ph_" + k); u.field.setAttribute("aria-label", t(k === "name" ? "js.ha.ign.pill_name" : "js.ha.ign.kind_" + k));
    u.field.inputMode = k === "ip" ? "decimal" : "text"; u.field.value = ""; ignErr("");
  }
  function ignToggleAdd(open) {
    var u = ign.ui; open = open === undefined ? !u.addWrap.classList.contains("open") : open;
    u.addWrap.classList.toggle("open", open); u.addBtn.setAttribute("aria-expanded", String(open));
    if (open) { u.scroll.scrollTop = 0; setTimeout(function () { u.field.focus({ preventScroll: true }); }, 60); } else { ignErr(""); u.field.value = ""; }
  }
  function ignSubmit() {
    var u = ign.ui, v = u.field.value.trim(), kind = ign.kind, value;
    if (kind === "mac") {
      var h = v.replace(/[:\-.]/g, "");
      if (!/^[0-9a-fA-F]{12}$/.test(h)) return ignErr(t("js.ha.ign.err_mac"));
      value = h.toUpperCase().match(/../g).join(":");
    } else if (kind === "ip") {
      var p = v.split(".");
      if (p.length !== 4 || !p.every(function (x) { return /^\d{1,3}$/.test(x) && +x <= 255; })) return ignErr(t("js.ha.ign.err_ip"));
      value = p.map(Number).join(".");
    } else {
      if (!v) return ignErr(t("js.ha.ign.err_name"));
      value = v;
    }
    var dup = ign.rows.some(function (r) { return r.source === "search" && r.kind === kind && ((r.mac || r.ip || r.name) + "").toLowerCase() === value.toLowerCase(); });
    if (dup) return ignErr(t("js.ha.ign.err_dup"));
    var before = {}; S.ign.items.forEach(function (x) { before[x.id] = 1; });
    api("/api/ignored", { method: "POST", json: { kind: kind, value: value, label: value } }).then(function (res) {
      S.ign.items = (res && res.items) || [];
      var added = S.ign.items.filter(function (x) { return !before[x.id]; })[0];
      ignToggleAdd(false);
      if (!added) return;
      var row = ignRowsFrom({ items: [added], macs: [] })[0];
      ign.rows.unshift(row); ignInsert(row, true); ignRefresh(); u.scroll.scrollTop = 0; u.addBtn.focus();
      ignSay(t("js.ha.ign.add") + ": " + row.title);
    }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); });
  }

  // --- opening and closing
  function openIgnored() {
    Promise.all([api("/api/ignored"), api("/api/new-devices/ignored")]).then(function (res) {
      S.ign = { items: (res[0] && res[0].items) || [], macs: Array.isArray(res[1]) ? res[1] : [] };
      ignBuild();
      if (!ignDlg.open) {
        if (typeof ignDlg.showModal === "function") ignDlg.showModal(); else ignDlg.setAttribute("open", "");
        if (snacksEl.children.length) raiseSnacks();
      }
      ignBar();
    }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); });
  }
  function closeIgnored() {
    ignFinishAllRows(true); ignFinishBulk(true); ignCloseMenu(false);        // what is counting ends in silence
    if (ignDlg.open && typeof ignDlg.close === "function") ignDlg.close(); else ignDlg.removeAttribute("open");
  }
  ignDlg.addEventListener("click", function (e) {
    if (e.target === ignDlg) return closeIgnored();
    var kb = e.target.closest("[data-ign-kind]");
    if (kb) { ignSetKind(kb.getAttribute("data-ign-kind")); ign.ui.field.focus(); return; }
    var mi = e.target.closest(".ig-menu .menu-item");
    if (mi) {
      if (mi.getAttribute("aria-disabled") === "true") return;
      if (mi.classList.contains("counting")) { ignCancelRow(mi.getAttribute("data-id")); return; }
      ignStartRow(mi);
      return;
    }
    var b = e.target.closest("[data-ign]"); if (!b) return;
    var a = b.getAttribute("data-ign");
    if (a === "close") closeIgnored();
    else if (a === "toggle-add") ignToggleAdd();
    else if (a === "more") { if (ign.menuBtn === b) ignCloseMenu(true); else ignOpenMenu(b); }
    else if (a === "all") {
      if (b.classList.contains("counting")) ignCancelBulk();
      else if (b.getAttribute("aria-disabled") !== "true") ignStartBulk(b);
    }
  });
  ignDlg.addEventListener("submit", function (e) { e.preventDefault(); ignSubmit(); });
  ignDlg.addEventListener("input", function (e) { if (ign.ui && e.target === ign.ui.field) { guidedInput(ign.ui.field, ign.kind); ignErr(""); } });
  ignDlg.addEventListener("keydown", function (e) {
    if (ign.ui && e.target === ign.ui.field && guidedKey(e, ign.ui.field, ign.kind)) { ignErr(""); return; }
    var b = e.target.closest && e.target.closest('[data-ign="more"]');
    if (b && (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ")) { e.preventDefault(); e.stopPropagation(); ignOpenMenu(b); return; }
    if (ign.menu && ign.menu.contains(e.target)) {
      var items = [].slice.call(ign.menu.querySelectorAll(".menu-item")), k = items.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); items[(k + 1) % items.length].focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); items[(k - 1 + items.length) % items.length].focus(); }
      else if (e.key === "Home") { e.preventDefault(); items[0].focus(); }
      else if (e.key === "End") { e.preventDefault(); items[items.length - 1].focus(); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); ignCloseMenu(true); }
      else if (e.key === "Tab") { ignCloseMenu(true); e.preventDefault(); }
      return;
    }
    if (e.key === "Escape" && ign.ui && ign.ui.addWrap.classList.contains("open")) { e.preventDefault(); e.stopPropagation(); ignToggleAdd(false); ign.ui.addBtn.focus(); }
  });
  ignDlg.addEventListener("cancel", function (e) {
    if (ign.menu) { e.preventDefault(); ignCloseMenu(true); }
    else if (ign.ui && ign.ui.addWrap.classList.contains("open")) { e.preventDefault(); ignToggleAdd(false); ign.ui.addBtn.focus(); }
    else { ignFinishAllRows(true); ignFinishBulk(true); }
  });
  document.addEventListener("pointerdown", function (e) { if (ign.menu && !ign.menu.contains(e.target) && !e.target.closest('[data-ign="more"]')) ignCloseMenu(false); }, true);
  ignDlg.addEventListener("scroll", function () { if (ign.menu) ignCloseMenu(false); }, true);
  window.addEventListener("resize", function () { if (ign.menu) ignCloseMenu(false); ignBar(); });

  // ------------------------------------------------- search methods (flows)
  // Same setting as the classic dashboard (/api/flows): for each type of search,
  // which functions to run. Saves on every switch.
  var flowsDlg = $("flows");
  function openFlows() {
    api("/api/flows").then(function (r) {
      S.fl = r;
      renderFlows();
      if (!flowsDlg.open) {
        if (typeof flowsDlg.showModal === "function") flowsDlg.showModal(); else flowsDlg.setAttribute("open", "");
        if (snacksEl.children.length) raiseSnacks();
      }
    }).catch(function () { snack(t("js.flows.load_failed"), { kind: "error" }); });
  }
  function closeFlows() {
    if (flowsDlg.open && typeof flowsDlg.close === "function") flowsDlg.close(); else flowsDlg.removeAttribute("open");
  }
  // The three searches are three tabs; under them the functions of the chosen search, grouped by risk, in panels that start closed.
  var FL_PROFILES = ["initial", "associative", "deep"], FL_RISKS = ["easy", "invasive", "risky"], flTab = "initial", flOpen = {};
  function flSteps(p) { return S.fl.steps.filter(function (s) { return s.flows.indexOf(p) >= 0; }); }
  function flLocked(s, p) { return s.locked_in.indexOf(p) >= 0; }
  function flOn(s, p) { return flLocked(s, p) || S.fl.flows[p].steps.indexOf(s.id) >= 0; }
  function flCount(p) {
    var c = { all: 0, easy: 0, invasive: 0, risky: 0 };
    flSteps(p).forEach(function (s) { if (flOn(s, p)) { c.all++; c[s.risk]++; } });
    return c;
  }
  function flChips(p) {
    var c = flCount(p);
    return '<span class="risk r-easy"><i></i>' + c.all + " " + esc(t("js.flows.n_on")) + "</span>" +
      '<span class="risk r-invasive' + (c.invasive ? "" : " zero") + '"><i></i>' + c.invasive + " " + esc(t("js.flows.n_inv")) + "</span>" +
      '<span class="risk r-risky' + (c.risky ? "" : " zero") + '"><i></i>' + c.risky + " " + esc(t("js.flows.n_risk")) + "</span>";
  }
  // Only the numbers change while the user switches functions: the boxes keep their size and place.
  function flRefresh() {
    var chips = flowsDlg.querySelector(".fl-chips");
    if (chips) chips.innerHTML = flChips(flTab);
    FL_RISKS.forEach(function (k) {
      var e = flowsDlg.querySelector('[data-gc="' + k + '"]');
      if (!e) return;
      var list = flSteps(flTab).filter(function (s) { return s.risk === k; });
      e.textContent = list.filter(function (s) { return flOn(s, flTab); }).length + "/" + list.length;
    });
  }
  function renderFlows(focusTab) {
    var r = S.fl, html = '<div class="mi-header"><button type="button" class="icon-btn touch rp" data-fl="close" aria-label="' +
      esc(t("js.ha.more.close")) + '">' + icon("close") + '</button><div class="mi-titles"><h2 class="mi-title" id="flows-title">' +
      esc(t("js.flows.title")) + '</h2><div class="mi-sub">' + esc(t("js.flows.hint")) + "</div></div></div>";
    html += '<div class="fl-top"><div class="fl-tabs" role="tablist">' + FL_PROFILES.map(function (p) {
      var prof = r.flows[p] || {};
      return '<button type="button" role="tab" class="pill rp" id="fl-tab-' + p + '" aria-label="' + esc(prof.label) + '" title="' + esc(prof.description) +
        '" aria-selected="' + (p === flTab) + '" aria-controls="fl-panel" tabindex="' + (p === flTab ? 0 : -1) + '" data-fl-tab="' + p + '"><span class="fl-long">' + esc(prof.label) +
        '</span><span class="fl-short">' + esc(t("js.flows.short_" + p)) + "</span></button>";
    }).join("") + '</div><div class="fl-chips" aria-live="polite"></div></div>';
    html += '<div class="fl-body" id="fl-panel" role="tabpanel" aria-labelledby="fl-tab-' + flTab + '">';
    FL_RISKS.forEach(function (k) {
      var list = flSteps(flTab).filter(function (s) { return s.risk === k; });
      if (!list.length) return;
      var info = (r.risks || {})[k] || { label: k, description: "" }, key = flTab + k, open = !!flOpen[key], id = "fl-g-" + k;
      html += '<section class="fl-grp r-' + k + '"><button type="button" class="fl-grp-h rp" data-fl-grp="' + key + '" aria-expanded="' + open + '" aria-controls="' + id +
        '"><span class="risk-dot r-' + k + '"></span><span class="fl-gt"><b>' + esc(info.label) + "</b><span>" + esc(info.description) + '</span></span><em data-gc="' + k + '"></em>' +
        icon("chevron-down") + '</button><div class="fl-grp-b" id="' + id + '"' + (open ? "" : " hidden") + ">";
      list.forEach(function (s) {
        var locked = flLocked(s, flTab);
        html += '<label class="fl-row' + (locked ? " locked" : "") + '"><span class="fl-text"><b>' + esc(s.label) +
          (locked ? '<span class="fl-req">' + icon("lock") + esc(t("js.flows.required")) + "</span>" : "") + "</b><span>" + esc(s.description) +
          '</span></span><input type="checkbox" class="fl-sw" data-p="' + flTab + '" data-step="' + esc(s.id) + '"' + (flOn(s, flTab) ? " checked" : "") + (locked ? " disabled" : "") + "></label>";
      });
      html += "</div></section>";
    });
    html += '</div><div class="card-actions"><button type="button" class="btn text rp" data-fl="reset">' + esc(t("js.flows.reset")) + "</button></div>";
    flowsDlg.innerHTML = html;
    flRefresh();
    if (focusTab) flowsDlg.querySelector("#fl-tab-" + flTab).focus();
  }
  flowsDlg.addEventListener("click", function (e) {
    if (e.target === flowsDlg || e.target.closest('[data-fl="close"]')) return closeFlows();
    var tab = e.target.closest("[data-fl-tab]");
    if (tab) { flTab = tab.dataset.flTab; renderFlows(true); return; }
    var grp = e.target.closest("[data-fl-grp]");
    if (grp) {
      var open = grp.getAttribute("aria-expanded") !== "true";
      flOpen[grp.dataset.flGrp] = open;
      grp.setAttribute("aria-expanded", String(open));
      grp.nextElementSibling.hidden = !open;
      return;
    }
    if (e.target.closest('[data-fl="reset"]')) {
      api("/api/flows/reset", { method: "POST" }).then(function (r) {
        S.fl = r; renderFlows();
      }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); });
    }
  });
  flowsDlg.addEventListener("keydown", function (e) {
    var tab = e.target.closest("[data-fl-tab]");
    if (!tab || ["ArrowLeft", "ArrowRight", "Home", "End"].indexOf(e.key) < 0) return;
    var i = FL_PROFILES.indexOf(flTab);
    i = e.key === "Home" ? 0 : e.key === "End" ? 2 : (i + (e.key === "ArrowRight" ? 1 : 2)) % 3;
    flTab = FL_PROFILES[i];
    renderFlows(true);
    e.preventDefault();
  });
  // a line under the header block appears only when the list is scrolled
  flowsDlg.addEventListener("scroll", function (e) {
    if (e.target.id === "fl-panel") flowsDlg.querySelector(".fl-top").classList.toggle("scrolled", e.target.scrollTop > 0);
  }, true);
  // Saving: one request at a time. A change made while a save is on its way waits for it and is then saved alone with the latest state,
  // so the server always ends with the last choice (requests sent together can arrive out of order).
  var flSaving = false, flAgain = false;
  function flSave() {
    if (flSaving) { flAgain = true; return; }
    flSaving = true;
    var out = {};
    FL_PROFILES.forEach(function (q) { out[q] = S.fl.flows[q].steps.slice(); });
    api("/api/flows", { method: "POST", json: { flows: out } }).then(function (r) {
      if (!flAgain) S.fl = r;
    }).catch(function (err) {
      flAgain = false;
      snack(err && err.message ? err.message : t("js.ha.toast.error"), { kind: "error" });
      return api("/api/flows").then(function (r) { S.fl = r; renderFlows(); });
    }).then(function () {
      flSaving = false;
      if (flAgain) { flAgain = false; flSave(); }
    });
  }
  flowsDlg.addEventListener("change", function (e) {
    if (!e.target.classList.contains("fl-sw")) return;
    var p = e.target.dataset.p, id = e.target.dataset.step, steps = S.fl.flows[p].steps, at = steps.indexOf(id);
    if (e.target.checked && at < 0) steps.push(id); else if (!e.target.checked && at >= 0) steps.splice(at, 1);
    flRefresh();
    flSave();
  });

  // ------------------------------------------------------------ filters
  // Chosen from the badges of the "Network" card (All, Online, Offline, Mobile).
  function matches(d) {
    var f = S.filter;
    if (f.status === "online" && !d.online) return false;
    if (f.status === "offline" && d.online) return false;
    if (f.status === "mobile" && !d.is_mobile) return false;
    if (f.type && d.type !== f.type) return false;
    if (f.q && d._hay.indexOf(f.q) < 0) return false;
    return true;
  }
  function counts() {
    var c = { total: S.list.length, online: 0, offline: 0, mobile: 0, types: {} };
    S.list.forEach(function (d) {
      if (d.online) c.online++; else c.offline++;
      if (d.is_mobile) c.mobile++;
      c.types[d.type] = (c.types[d.type] || 0) + 1;
    });
    return c;
  }
  function setFilter(kind, value) {
    if (kind === "status") S.filter.status = value;
    else S.filter.type = S.filter.type === value ? null : value;
    S.dirty.layout = true;
    S.dirty.net = true;
    schedule();
  }

  // ---------------------------------------------------------- "Network" card
  var netEl = $("card-network");
  var GAUGE_C = 2 * Math.PI * 52;
  // Number and ring advance together (same duration and same curve): a CSS
  // transition on the ring does not start on first draw, when the element is born already at its final value.
  function animateGauge(online, total) {
    var fill = $("g-fill"), val = $("g-val");
    var to = total ? online / total : 0;
    function paint(r, n) {
      fill._cur = r; val._cur = n;
      fill.setAttribute("stroke-dashoffset", (GAUGE_C * (1 - r)).toFixed(2));
      val.textContent = String(n);
    }
    if (REDUCED) { cancelAnimationFrame(fill._raf || 0); fill._r = to; val._v = online; paint(to, online); return; }
    // Same values as before: do not touch the animation possibly in progress
    // (the card is updated several times in a row as soon as it is drawn).
    if (fill._r === to && val._v === online) return;
    var from = fill._cur == null ? 0 : fill._cur, fromN = val._cur == null ? 0 : val._cur;
    fill._r = to;
    val._v = online;
    cancelAnimationFrame(fill._raf || 0);
    var start = performance.now(), dur = 700;
    (function step(now) {
      var p = Math.min(1, (now - start) / dur);
      var e = 1 - Math.pow(1 - p, 3);
      paint(from + (to - from) * e, Math.round(fromN + (online - fromN) * e));
      if (p < 1) fill._raf = requestAnimationFrame(step);
    })(start);
  }

  // The app name appears in the title only if HA does not show its bar
  // (wide window or page opened outside HA); with the HA bar it is already written there.
  var haBar = false;
  function renderNetTitle() {
    var title = $("net-title"), sub = $("net-sub");
    if (!title || !sub) return;
    var cnt = t("js.ha.devices_count", { n: S.list.length });
    title.textContent = haBar ? t("js.ha.network") : "Vedetta";
    sub.textContent = haBar ? cnt : t("js.ha.network") + " · " + cnt;
  }
  window.addEventListener("message", function (e) {
    if (e.source !== window.parent || !e.data || e.data.type !== "home-assistant/properties") return;
    var narrow = !!e.data.narrow;
    if (narrow !== haBar) { haBar = narrow; renderNetTitle(); }
  });
  if (window.parent !== window) {
    try { window.parent.postMessage({ type: "home-assistant/subscribe-properties" }, "*"); } catch (err) {}
  }

  // Search, real-time status and settings: nodes created only once (with their
  // handlers) and moved into the network card. If the card is rebuilt (resync
  // after a service restart or a roles change) they must be put in a safe place first, otherwise they
  // would vanish with the old content and the buttons would stop responding.
  var NET_PARTS = null;
  function buildNetwork() {
    if (!NET_PARTS) NET_PARTS = { live: $("live"), wrap: document.querySelector(".menu-wrap"), search: $("search-box") };
    var stash = document.createDocumentFragment();
    [NET_PARTS.live, NET_PARTS.wrap, NET_PARTS.search].forEach(function (n) { if (n) stash.appendChild(n); });
    netEl.innerHTML =
      '<div class="card-header"><div class="ch-text">' +
        '<div class="ch-title"><span class="net-dot" id="net-dot"></span><span id="net-title"></span></div>' +
        '<div class="ch-sub" id="net-sub"></div></div>' +
        '<div class="card-tools" id="card-tools">' +
        '<button type="button" class="icon-btn touch rp" id="btn-refresh" title="' + esc(t("js.ha.refresh")) + '" aria-label="' + esc(t("js.ha.refresh")) + '">' +
        icon("refresh") + "</button></div></div>" +
      '<div class="card-search" id="card-search"></div>' +
      '<div class="card-content">' +
        '<div class="gauge-row">' +
          '<div class="gauge" id="gauge" role="img">' +
            '<svg viewBox="0 0 120 120" aria-hidden="true"><circle class="g-track" cx="60" cy="60" r="52"></circle>' +
            '<circle class="g-fill" id="g-fill" cx="60" cy="60" r="52" stroke-dasharray="' + GAUGE_C.toFixed(2) + '" stroke-dashoffset="' + GAUGE_C.toFixed(2) + '" transform="rotate(-90 60 60)"></circle></svg>' +
            '<div class="gauge-center"><span class="gauge-value" id="g-val">0</span><span class="gauge-of" id="g-of"></span></div>' +
          "</div>" +
          '<div class="gauge-side">' +
            '<div class="scan-state"><span class="scan-ic" id="scan-ic">' + icon("history") + '</span><span class="scan-text" id="scan-text"></span></div>' +
            '<div class="split"><button type="button" class="btn outlined rp" id="btn-scan">' + icon("magnify") + "<span>" + esc(t("js.ha.scan")) + "</span></button>" +
            '<button type="button" class="btn outlined rp split-more" id="btn-deepmenu" aria-haspopup="true" aria-expanded="false" aria-label="' + esc(t("js.ha.deep.title")) + '">' + icon("chevron-down") + "</button></div>" +
          "</div>" +
        "</div>" +
        '<div class="badges" id="badges"></div>' +
        '<div class="brands" id="brands"></div>' +
      "</div>" +
      '<div class="progress" id="progress" aria-hidden="true"><div class="bar" id="progress-bar"></div></div>';
    // Search, real-time status and settings live inside this card: the already created
    // nodes (with their handlers) are moved here from the hidden container.
    var tools = $("card-tools");
    tools.insertBefore(NET_PARTS.live, tools.firstChild);
    tools.appendChild(NET_PARTS.wrap);
    $("card-search").appendChild(NET_PARTS.search);
    var holder = $("toolbar");
    if (holder) holder.remove();
    $("btn-refresh").addEventListener("click", doRefresh);
    $("btn-scan").addEventListener("click", doScan);
    $("badges").addEventListener("click", function (e) {
      var b = e.target.closest(".badge");
      if (!b) return;
      if (b.dataset.badge === "new") {
        var card = $("card-new");
        if (!card.hidden && card.scrollIntoView) card.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "nearest" });
        return;
      }
      setFilter("status", S.filter.status === b.dataset.badge ? "all" : b.dataset.badge);
    });
  }

  var BADGES = [
    ["all", "devices", "primary"],
    ["online", "check-circle", "success"],
    ["offline", "close-circle", "error"],
    ["mobile", "cellphone", "primary"],
    ["new", "plus-circle", "warning"]
  ];
  function updateNetwork() {
    var c = counts();
    var gauge = $("gauge");
    if (!gauge) return;
    updateDeepBadge();
    var ratio = c.total ? c.online / c.total : 0;
    var tone = !c.total ? "none" : ratio >= 0.8 ? "ok" : ratio >= 0.5 ? "warn" : "bad";
    gauge.className = "gauge " + tone;
    animateGauge(c.online, c.total);
    $("g-of").textContent = t("js.ha.gauge.of", { n: c.total });
    gauge.setAttribute("aria-label", t("js.ha.gauge.aria", { online: c.online, total: c.total }));
    renderNetTitle();

    var badges = $("badges");
    if (!badges.firstChild) {
      badges.innerHTML = BADGES.map(function (b) {
        return '<button type="button" class="badge rp touch tone-' + b[2] + '" data-badge="' + b[0] + '">' +
          '<span class="badge-ic">' + icon(b[1]) + '</span><span class="badge-val" data-v="0">0</span>' +
          '<span class="badge-lb">' + esc(t("js.ha.badge." + b[0])) + "</span></button>";
      }).join("");
    }
    var values = { all: c.total, online: c.online, offline: c.offline, mobile: c.mobile, "new": S.newDevices.count };
    var nodes = badges.querySelectorAll(".badge");
    for (var i = 0; i < nodes.length; i++) {
      var key = nodes[i].dataset.badge, v = values[key];
      var valEl = nodes[i].querySelector(".badge-val");
      if (valEl._v !== v) {
        var first = valEl._v == null;
        animateNumber(valEl, v);
        if (!first) { nodes[i].classList.remove("bump"); void nodes[i].offsetWidth; nodes[i].classList.add("bump"); }
      }
      nodes[i].setAttribute("aria-pressed", key === "new" ? "false" : String(S.filter.status === key));
      nodes[i].classList.toggle("dim", key === "new" && v === 0);
    }
    renderBrands();
  }

  var BRAND_COLORS = 8;
  // Short and honest text for those without a known brand: what is really known, i.e.
  // the MAC manufacturer and its role (chip, board, virtual machine).
  function chipText(d) {
    if (d.brand) return d.brand;
    if (d.vendor_role === "private") return t("js.ha.chip.private");
    if (!d.vendor) return "";
    var role = d.vendor_role === "component" || d.vendor_role === "virtual" || d.vendor_role === "dual" ? d.vendor_role : "brand";
    return t("js.ha.chip." + role, { vendor: d.vendor });
  }
  // MAC manufacturers of devices without a brand (tooltip of the "Unknown" entry).
  function batteryTitle(d) {
    return t("js.ha.battery.yes") + (d.battery_source ? " · " + t("js.ha.battery.src_" + d.battery_source) : "");
  }
  function renderBrands() {
    var el = $("brands");
    if (!el) return;
    var map = {};
    S.list.forEach(function (d) {
      // Brand of the PRODUCT, never the network card manufacturer (an
      // Espressif chip is not a brand). Those without a known brand do not appear.
      if (!d.brand) return;
      map[d.brand] = (map[d.brand] || 0) + 1;
    });
    var rows = Object.keys(map).map(function (k) { return { name: k, n: map[k] }; });
    rows.sort(function (a, b) { return b.n - a.n || a.name.localeCompare(b.name); });
    var shown = rows.slice(0, BRAND_COLORS);
    var rest = rows.slice(BRAND_COLORS).reduce(function (s, r) { return s + r.n; }, 0);
    if (rest) shown.push({ name: "\u0000other", n: rest });
    var total = rows.length;
    var sig = JSON.stringify(shown);
    if (el._sig === sig) return;
    el._sig = sig;
    if (!total) { el.innerHTML = ""; return; }
    var bar = "", legend = "";
    shown.forEach(function (r, i) {
      var label = r.name === "\u0000other" ? t("js.ha.brands.other") : r.name;
      var cls = r.name === "\u0000other" ? "c-other" : "c" + (i + 1);
      var tip = label + ": " + r.n;
      bar += '<i class="' + cls + '" style="flex-grow:' + r.n + '" title="' + esc(tip) + '"></i>';
      legend += '<li title="' + esc(tip) + '"><span class="dot ' + cls + '"></span><span class="b-name">' + esc(label) + '</span><span class="b-n">' + r.n + "</span></li>";
    });
    el.innerHTML = '<div class="brands-title">' + esc(t("js.ha.brands.title")) + '</div><div class="brand-bar">' + bar + "</div><ul>" + legend + "</ul>";
  }

  // Search status: text and bar (determinate = countdown to the
  // next cycle; indeterminate = something is working).
  // One line when the whole sentence fits, otherwise its two parts one under the other (measured, so the layout does not depend on it).
  function fitStatus(textEl) {
    var box = textEl.parentElement;
    if (!box || !box.clientWidth) return;
    var wanted = textEl.classList.contains("stack");
    textEl.classList.remove("stack");
    var parts = textEl.querySelectorAll(".st-part"), sep = textEl.querySelector(".st-sep"), need = 0;
    if (parts.length > 1) {
      for (var i = 0; i < parts.length; i++) need += parts[i].getBoundingClientRect().width;
      need += sep ? sep.getBoundingClientRect().width : 0;
      var free = box.clientWidth - (textEl.getBoundingClientRect().left - box.getBoundingClientRect().left);
      wanted = need > free + 0.5;
    } else wanted = false;
    textEl.classList.toggle("stack", wanted);
  }
  window.addEventListener("resize", function () { var el = $("scan-text"); if (el) fitStatus(el); });
  function updateScan() {
    var textEl = $("scan-text");
    if (!textEl) return;
    var busy = false, text;
    var rescanning = S.activity.rescanning.size;
    syncDeepBusy();
    if (S.activity.search) { text = t("js.ha.scan.searching"); busy = true; }
    else if (rescanning) { text = t("js.ha.scan.deep", { n: rescanning }); busy = true; }
    else if (S.refreshing) { text = t("js.ha.scan.refreshing"); busy = true; }
    else if (!S.poll.known) { text = t("js.ha.scan.waiting"); busy = true; }
    else if (S.poll.paused) {
      var pl = pauseLeft();
      text = pl === Infinity ? t("js.ha.pause.idle") : t("js.ha.pause.idle_left", { left: fmtLeft(pl) });
    } else {
      var remaining = Math.max(0, Math.ceil((S.poll.nextAt - Date.now()) / 1000));
      if (remaining === 0) { text = t("js.ha.scan.refreshing"); }
      else text = t("js.ha.scan.idle", { ago: ago((S.poll.nextAt - S.poll.interval) / 1000), s: remaining });
    }
    if (textEl.dataset.text !== text) {
      // The parts of the sentence ("Updated now" . "next check in 24 s") are kept whole: on a narrow screen the second goes under the first
      // (see the CSS) instead of the line breaking in the middle of a phrase.
      textEl.innerHTML = text.split(" · ").map(function (p) { return '<span class="st-part">' + esc(p) + "</span>"; }).join('<span class="st-sep"> · </span>');
      textEl.dataset.text = text; textEl.title = text;
    }
    fitStatus(textEl);
    renderLive();
    var prog = $("progress"), bar = $("progress-bar");
    prog.classList.toggle("indet", busy);
    // Pause: the bar is no longer the countdown to the next check. Timed pause = orange, it fills while the pause
    // runs and is full when the service resumes; stopped until resumed = solid red. A busy search keeps the moving bar.
    var pausedNow = S.poll.paused && !busy, pauseRest = pausedNow ? pauseLeft() : null;
    prog.classList.toggle("pause-timed", pausedNow && pauseRest !== Infinity);
    prog.classList.toggle("pause-stop", pausedNow && pauseRest === Infinity);
    if (pausedNow) {
      var pauseAll = S.poll.pausedTotal || Math.max(pauseRest === Infinity ? 0 : pauseRest, S.poll.pausedSeen || 0);
      S.poll.pausedSeen = pauseAll;
      var filled = pauseRest === Infinity || !pauseAll ? 1 : Math.min(1, Math.max(0, 1 - pauseRest / pauseAll));
      bar.style.transform = "scaleX(" + filled.toFixed(3) + ")";
    } else if (!busy) {
      S.poll.pausedSeen = 0;
      var pct = Math.min(1, Math.max(0, 1 - (S.poll.nextAt - Date.now()) / S.poll.interval));
      bar.style.transform = "scaleX(" + pct.toFixed(3) + ")";
    } else {
      bar.style.transform = "";
    }
    $("scan-ic").classList.toggle("busy", busy);
    var refreshBtn = $("btn-refresh");
    refreshBtn.classList.toggle("spinning", S.refreshing);
    var scanBtn = $("btn-scan");
    var scanning = S.activity.search || S.scanBusy;
    scanBtn.disabled = scanning;
    scanBtn.classList.toggle("busy", scanning);
    document.querySelectorAll(".empty-ic.scan").forEach(function (b) {
      b.disabled = scanning;
      b.classList.toggle("busy", scanning);
    });
  }

  function doRefresh() {
    if (S.refreshing) return;
    S.refreshing = true;
    S.refreshStart = Date.now();
    S.changedSince = 0;
    S.poll.nextAt = Date.now();
    updateScan();
    api("/api/refresh", { method: "POST" }).catch(function () {
      S.refreshing = false;
      updateScan();
      snack(t("js.ha.toast.refresh_failed"), { kind: "error" });
    });
    setTimeout(function () { if (S.refreshing) { S.refreshing = false; updateScan(); } }, 15000);
  }
  function refreshDone() {
    if (!S.refreshing) return;
    var wait = Math.max(0, 700 - (Date.now() - S.refreshStart));
    var changed = S.changedSince;
    setTimeout(function () {
      if (!S.refreshing) return;
      S.refreshing = false;
      updateScan();
      if (changed) snack(t("js.ha.toast.refresh_changes", { n: changed }), { kind: "success", ms: 3200 });
    }, wait);
  }

  function doScan() {
    if (S.scanBusy || S.activity.search) return;
    S.scanBusy = true;
    updateScan();
    api("/api/scan/quick", { method: "POST" }).then(function (list) {
      // An address appears only once in the acquisition list.
      var once = {};
      S.found = (Array.isArray(list) ? list : []).filter(function (h) {
        if (!h.ip || once[h.ip]) return false;
        once[h.ip] = true;
        return true;
      });
      var n = S.found.length;
      S.scanned = true;
      S.scanDone = true;
      S.dismissedNew = {};      // a search the user asks for shows again what the app had seen by itself
      try { localStorage.setItem("vedetta-ha-scanned", "1"); } catch (err) { /* ignore */ }
      renderNew();
      snack(n === 0 ? t("js.ha.toast.scan_none") : t("js.ha.toast.scan_found", { n: n }), { kind: "success" });
      // No scrolling: the card opens where it is, under the network card, and pushes the rest down (see renderNew).
    }).catch(function () {
      snack(t("js.ha.toast.scan_failed"), { kind: "error" });
    }).then(function () {
      S.scanBusy = false;
      updateScan();
    });
  }

