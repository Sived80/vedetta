  // ------------------------------------------------- "More info" dialog
  var dlg = $("more");
  function openMore(id) {
    if (!S.devices.has(id)) return;
    S.open = id;
    S.mi.moreOpen = false;   // "Other attributes" always starts closed
    S.mi.range = 24;
    S.mi.view = "main";
    S.mi.win = {};
    renderMore();
    if (!dlg.open) {
      if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
      if (snacksEl.children.length) raiseSnacks();
    }
  }
  function closeMore() {
    if (dlg.open && typeof dlg.close === "function") dlg.close(); else dlg.removeAttribute("open");
    S.open = null;
  }
  dlg.addEventListener("close", function () { S.open = null; });
  dlg.addEventListener("click", function (e) { if (e.target === dlg) closeMore(); });

  function miHeader(d, title, back) {
    return '<div class="mi-header"><button type="button" class="icon-btn touch rp" data-act="' + (back ? "back" : "close") + '" aria-label="' +
      esc(t("js.ha.more.close")) + '">' + icon("close") + '</button><div class="mi-titles"><div class="mi-name-row"><h2 class="mi-title" id="more-title">' + esc(title) +
      "</h2>" + (d ? '<button type="button" class="icon-btn small touch rp" data-act="rename" title="' + esc(t("js.ha.act.rename")) +
      '" aria-label="' + esc(t("js.ha.act.rename")) + '">' + icon("pencil") + "</button>" +
      '<button type="button" class="icon-btn small touch rp" data-act="ignore" title="' + esc(t("js.ha.act.ignore")) +
      '" aria-label="' + esc(t("js.ha.act.ignore")) + '">' + icon("eye-off") + "</button>" : "") + "</div>" + (d ? '<div class="mi-sub" id="mi-sub">' + esc(miSub(d)) + "</div>" : "") + "</div></div>";
  }
  function miSub(d) { return [chipText(d), typeLabel(d.type)].filter(Boolean).join(" · "); }

  function renderMore() {
    var d = S.devices.get(S.open);
    if (!d) return closeMore();
    if (S.mi.view === "rename") return renderRename(d);
    if (S.mi.view === "brand") return renderBrandEdit(d);
    if (S.mi.view === "focus") return renderFocus(d);
    if (S.mi.view === "ignore") return renderIgnore(d);
    if (S.mi.view === "deep") return renderDeep(d);
    dlg.innerHTML = '<div class="mi">' + miHeader(d, d.name, false) +
      '<div class="mi-body"><div class="mi-hero" id="mi-hero"></div>' +
      '<section class="mi-section"><div class="mi-sec-head"><h3>' + esc(t("js.ha.more.history")) + '</h3><div class="seg" role="group">' +
      '<button type="button" class="rp" data-range="24" aria-pressed="true">' + esc(t("js.ha.more.range24")) + "</button>" +
      '<button type="button" class="rp" data-range="168" aria-pressed="false">' + esc(t("js.ha.more.range7")) + "</button></div></div>" +
      '<div class="mi-graph" id="mi-graph"><div class="skeleton sk-graph"></div></div></section>' +
      '<section class="mi-section attrs"><dl class="attr-list" id="mi-attrs"></dl></section><div id="mi-debug"></div></div>' +
      '<div class="mi-actions" id="mi-actions"></div></div>';
    miHero(d);
    miAttrs(d);
    miDebug(d);
    miActions(d);
    loadGraph();
  }

  function miHero(d) {
    brandSheetSync(d);
    var el = $("mi-hero");
    if (!el) return;
    el.className = "mi-hero " + (d.online ? "online" : "offline");
    el.innerHTML = '<span class="hero-ic">' + icon(devIcon(d)) + '</span><div><div class="hero-state">' +
      esc(d.online ? t("js.ha.state.online") : t("js.ha.state.offline")) + '</div><div class="hero-sub">' + esc(heroSub(d)) + "</div></div>" +
      (canWake(d) ? '<button type="button" class="icon-btn small touch rp hero-wake" data-act="wake" title="' + esc(t("js.ha.act.wake")) +
        '" aria-label="' + esc(t("js.ha.act.wake")) + '">' + icon("power") + "</button>" : "");
  }
  function heroSub(d) {
    if (d.online) return d.uptime != null ? t("js.ha.more.up_for", { uptime: fmtUptime(d.uptime) }) : "";
    return d.last_seen ? t("js.ha.more.seen_at", { ago: ago(d.last_seen), time: fmtStamp(d.last_seen, true) }) : "";
  }

  // Text of a translation keyed by a technical value; the value itself if there is no translation.
  function evKey(prefix, raw) {
    var key = prefix + String(raw || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    var text = t(key);
    return text === key ? String(raw || "") : text;
  }
  var EV_CLUES = [[/^ruolo di rete$/, "role"], [/^porta (\d+)$/, "port"], [/^parola nel testo$/, "words"], [/^parola: (.+)$/, "word"],
    [/^marca: (.+)$/, "brand"], [/^firma (.+)$/, "sig"], [/^integrazione HA (.+)$/, "ha"], [/^piattaforma IoT$/, "platform"], [/^solo porte IoT$/, "iotports"]];
  function evClue(src) {
    for (var i = 0; i < EV_CLUES.length; i++) {
      var m = EV_CLUES[i][0].exec(src);
      if (m) return t("js.ha.ev.clue." + EV_CLUES[i][1], { n: m[1], k: m[1] });
    }
    return src;    // mDNS, UPnP, API names are the technical names
  }
  // Evidence on the rows Name, Brand and Type: a thin bar and the certainty next to the (i) that opens a small pop-up with
  // what decided it and what was rejected. The numbers come from the server (/evidence); the rows are drawn without them and
  // only filled in later, so nothing moves when they arrive or change.
  var evData = { id: null, at: 0, sig: "", data: null };
  var EV_KEYS = ["name", "brand", "group"];
  function evLevel(n) { return n >= 70 ? "high" : n >= 40 ? "mid" : "low"; }
  function evRowCells(key, label) {
    var info = esc(t("js.ha.ev.info", { what: label }));
    return '<span class="ev-cell"><span class="ev-v" data-ev-v="' + key + '"></span><span class="ev-meter">' +
      '<span class="ev-bar" data-ev-bar="' + key + '" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><i></i></span>' +
      '<span class="ev-pct" data-ev-pct="' + key + '">\u2014</span>' +
      '<button type="button" class="ev-i" data-ev-i="' + key + '" aria-haspopup="dialog" aria-expanded="false" title="' + info + '" aria-label="' + info + '">' +
      icon("information-outline") + "</button></span></span>";
  }
  function evText(x, key) {
    var e = x[key], why = "", rej = [];
    if (key === "group") {
      var clues = (e.clues || []).map(function (c) { return evClue(c.source) + " +" + c.points; }).join(", ");
      why = e.basis === "manual" ? t("js.ha.ev.g.manual") : e.basis === "mobile" ? t("js.ha.ev.g.mobile", { reason: evKey("js.ha.ev.reason.", e.reason) })
        : e.basis === "scored" ? t("js.ha.ev.g.scored", { clues: clues || "-" }) : t("js.ha.ev.g." + e.basis);
      rej = (e.rejected || []).map(function (r) {
        return typePlural(r.value) + " \u2014 " + t("js.ha.ev.points", { n: r.points }) + ": " + t("js.ha.ev.why." + r.why, { chosen: typePlural(e.value) });
      });
    } else if (key === "brand") {
      why = e.basis === "manual" ? t("js.ha.ev.b.manual") : e.basis === "found" ? t("js.ha.ev.b.found", { source: evKey("js.ha.ev.bsrc.", e.source) }) : t("js.ha.ev.b.none");
      rej = (e.rejected || []).map(function (r) {
        return r.value + ": " + (r.kind === "vendor" ? t("js.ha.ev.vendor", { role: evKey("js.ha.ev.role.", r.role || "other") }) : t("js.ha.ev.declared"));
      });
    } else {
      why = e.basis === "ip" ? t("js.ha.ev.n.ip") : e.basis === "manual" ? t("js.ha.ev.n.manual") : e.basis === "placeholder" ? t("js.ha.ev.n.placeholder")
        : e.basis === "brand" ? t("js.ha.ev.n.brand") : e.basis === "source" ? t("js.ha.ev.n.source", { source: evKey("js.ha.ev.nsrc.", e.source) }) : t("js.ha.ev.n.unknown");
      rej = (e.rejected || []).map(function (r) {
        return evKey("js.ha.ev.nsrc.", r.source) + ": " + r.value + " \u2014 " + t(r.cleaned ? "js.ha.ev.n.lower" : "js.ha.ev.n.technical");
      });
    }
    return { why: why, rej: rej, certainty: e.certainty };
  }
  function evPaint(x) {
    var root = $("mi-attrs");
    if (!root || !x) return;
    EV_KEYS.forEach(function (key) {
      var n = x[key].certainty, pct = root.querySelector('[data-ev-pct="' + key + '"]'), bar = root.querySelector('[data-ev-bar="' + key + '"]');
      if (!pct || !bar) return;
      pct.textContent = n > 0 ? n + "%" : "\u2014";
      bar.className = "ev-bar" + (n > 0 ? " lvl-" + evLevel(n) : "");
      bar.setAttribute("aria-valuenow", String(n));
      bar.firstChild.style.width = n + "%";
    });
  }
  function evApply(d) {
    var sig = [d.name, d.brand, d.type, d.type_user, d.brand_user].join("|");
    if (evData.id !== d.id || evData.sig !== sig) evData.data = null;       // the value changed: the old numbers are not for it
    if (evData.data) evPaint(evData.data);
    if (evData.id === d.id && evData.sig === sig && Date.now() - evData.at < 5000) return;
    evData.id = d.id; evData.sig = sig; evData.at = Date.now();
    api("/api/ha/devices/" + encodeURIComponent(d.id) + "/evidence").then(function (x) {
      evData.data = x;
      if (S.open === d.id) evPaint(x);
    }).catch(function () { /* the numbers are extra: the rows work without them */ });
  }
  // The pop-up: small, inside the sheet, closed by pressing anywhere outside it (or Escape, or scrolling the sheet).
  var evPop = { el: null, key: null, btn: null };
  function evPopClose() {
    if (!evPop.el) return;
    evPop.el.remove();
    if (evPop.btn) evPop.btn.setAttribute("aria-expanded", "false");
    evPop.el = evPop.key = evPop.btn = null;
    document.removeEventListener("pointerdown", evPopOutside, true);
    document.removeEventListener("mousedown", evPopOutside, true);
    document.removeEventListener("keydown", evPopKey, true);
  }
  function evPopOutside(e) {
    if (evPop.el && !evPop.el.contains(e.target) && !(evPop.btn && evPop.btn.contains(e.target))) evPopClose();
  }
  function evPopKey(e) {
    if (e.key === "Escape" && evPop.el) { e.preventDefault(); e.stopPropagation(); evPopClose(); }
  }
  function evPopOpen(key, btn) {
    var x = evData.data, host = dlg.querySelector(".mi");
    if (!x || !host) return;
    evPopClose();
    var info = evText(x, key), label = btn.closest(".attr").querySelector("dt").textContent;
    var el = document.createElement("div");
    el.className = "ev-pop"; el.id = "ev-pop"; el.setAttribute("role", "dialog"); el.setAttribute("aria-label", label);
    el.innerHTML = '<div class="ev-pop-h"><b>' + esc(label) + "</b><span>" + (info.certainty > 0 ? esc(t("js.ha.ev.sure", { n: info.certainty })) : "\u2014") + "</span></div>" +
      "<p>" + esc(info.why) + "</p>" +
      (info.rej.length ? '<div class="ev-pop-r">' + esc(t("js.ha.ev.rejected", { n: info.rej.length })) + "</div><ul>" + info.rej.map(function (r) { return "<li>" + esc(r) + "</li>"; }).join("") + "</ul>" : "");
    host.appendChild(el);
    var hr = host.getBoundingClientRect(), br = btn.getBoundingClientRect(), w = Math.min(300, hr.width - 16);
    el.style.width = w + "px";
    el.style.left = Math.round(Math.max(8, Math.min(br.right - hr.left - w + 12, hr.width - w - 8))) + "px";
    // The same rule on every screen: it opens below the button, or above it when there is more room there, and never taller than the
    // room (the visible part of the window sheet); what does not fit scrolls inside it.
    var seenTop = Math.max(hr.top, 0), seenBottom = Math.min(hr.bottom, window.innerHeight || hr.bottom), gap = 6, edge = 10;
    var below = seenBottom - br.bottom - gap - edge, above = br.top - seenTop - gap - edge, need = el.scrollHeight;
    var up = need > below && above > below, room = Math.max(120, up ? above : below);
    el.style.maxHeight = Math.round(room) + "px";
    var h = Math.min(need, room);
    el.style.top = Math.round((up ? br.top - hr.top - gap - h : br.bottom - hr.top + gap)) + "px";
    evPop.el = el; evPop.key = key; evPop.btn = btn;
    btn.setAttribute("aria-expanded", "true");
    document.addEventListener("pointerdown", evPopOutside, true);
    document.addEventListener("mousedown", evPopOutside, true);
    document.addEventListener("keydown", evPopKey, true);
  }
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-ev-i]");
    if (!btn) return;
    if (evPop.btn === btn) evPopClose(); else evPopOpen(btn.getAttribute("data-ev-i"), btn);
  });
  dlg.addEventListener("cancel", function (e) { if (evPop.el) { e.preventDefault(); evPopClose(); } });
  dlg.addEventListener("close", evPopClose);
  dlg.addEventListener("scroll", function (e) { if (evPop.el && evPop.el.contains(e.target)) return; evPopClose(); }, true);   // scrolling the pop-up itself does not close it

  // Debug mode: why the device has this type, name and brand (data from the server, not in the normal list).
  var dbgFetch = { id: null, at: 0, data: null };
  function miDebug(d) {
    var el = $("mi-debug");
    if (!el) return;
    if (!DEBUG) { el.innerHTML = ""; return; }
    function fmt(o) {
      return Object.keys(o || {}).map(function (k) { return k + " " + o[k]; }).join(", ") || "-";
    }
    function draw(x) {
      if (!x) return;
      var rows = [
        [t("js.ha.dbg.type"), (x.type.manual ? x.type.chosen + " (" + t("js.ha.type.manual") + ")" : x.type.chosen) + " | " + fmt(x.type.scores) + " | min " + x.type.min_score],
        [t("js.ha.dbg.kinds"), fmt(x.type.kinds)],
        [t("js.ha.dbg.evidence"), (x.type.evidence || []).map(function (e) {
          return e.group + ": " + e.source + " [" + e.family + "] " + e.pts + (e.counted ? "" : " (ripetuto)");
        }).join("; ") || "-"],
        [t("js.ha.dbg.name"), (x.name.shown || "-") + " | " + (x.name.source || "-") + (x.name.placeholder ? " | placeholder" : "")],
        [t("js.ha.dbg.candidates"), x.name.candidates.map(function (c) { return c.source + ": " + c.raw + (c.cleaned === c.raw ? "" : " -> " + (c.cleaned || "x")); }).join("; ") || "-"],
        [t("js.ha.dbg.brand"), (x.brand.brand || "-") + " | " + (x.brand.source || "-") + " / " + (x.brand.evidence || "-") + " / " + (x.brand.confidence || "-") +
          " | " + (x.brand.vendor || "-") + " (" + (x.brand.vendor_role || "-") + ")" + (x.brand.manual ? " | manual" : "")],
        [t("js.ha.dbg.mobile"), String(x.mobile.is_mobile) + " | mode " + (x.mobile.mode === undefined || x.mobile.mode === null ? "auto" : x.mobile.mode) +
          " | private MAC " + x.mobile.private_mac + " | DHCP " + (x.mobile.dhcp_os_family || "-") + " | churn " + x.mobile.churn_7d +
          " | battery " + (x.mobile.battery || "-") + "/" + (x.mobile.battery_source || "-")],
        [t("js.ha.dbg.dhcp"), fmt(x.dhcp)],
        [t("js.ha.dbg.roles"), (x.roles.roles.join(", ") || "-") + " | UPnP " + (x.roles.upnp_types.join(", ") || "-")],
        [t("js.ha.dbg.scan"), fmt(x.scan)],
        ["WoL", x.wol.ok ? "ok" : "-"]
      ];
      el.innerHTML = '<section class="mi-section dbg"><div class="mi-sec-head"><h3>' + esc(t("js.ha.debug.badge")) + "</h3></div><dl class=\"attr-list\">" +
        rows.map(function (r) { return '<div class="attr"><dt>' + esc(r[0]) + '</dt><dd><span class="attr-val mono">' + esc(r[1]) + "</span></dd></div>"; }).join("") + "</dl></section>";
    }
    if (dbgFetch.id === d.id && dbgFetch.data) draw(dbgFetch.data);
    if (dbgFetch.id === d.id && Date.now() - dbgFetch.at < 5000) return;
    dbgFetch.id = d.id; dbgFetch.at = Date.now();
    api("/api/ha/devices/" + encodeURIComponent(d.id) + "/debug").then(function (x) {
      dbgFetch.data = x;
      if (S.open === d.id && DEBUG) draw(x);
    }).catch(function () { /* debug must never cause errors */ });
  }

  function miAttrs(d) {
    var el = $("mi-attrs");
    if (!el) return;
    // Always visible: IP, MAC, response time, ports. The rest is in the "Other attributes" dropdown.
    var rows = [], fixedRows = [];
    function row(label, value, extra, fixed, cls) { (fixed ? fixedRows : rows).push({ label: label, html: value, extra: extra || "", cls: cls || "" }); }
    row(t("js.ha.attr.name"), evRowCells("name", t("js.ha.attr.name")), '<button type="button" class="icon-btn small touch rp" data-act="rename" title="' + esc(t("js.ha.act.rename")) +
      '" aria-label="' + esc(t("js.ha.act.rename")) + '">' + icon("pencil") + "</button>", true, "ev-attr");
    row(t("js.ha.attr.ip"), esc(d.ip + (d.port && d.port !== 80 ? ":" + d.port : "")),
      d.url && canOpen(d) ? '<a class="icon-btn small touch rp" href="' + esc(d.url) + '" target="_blank" rel="noopener" title="' + esc(t("js.ha.act.open")) +
        '" aria-label="' + esc(t("js.ha.act.open")) + '">' + icon("open-in-new") + "</a>" : "", true);
    if (d.mac) row(t("js.ha.attr.mac"), '<span class="mono">' + esc(d.mac) + "</span>",
      '<button type="button" class="icon-btn small touch rp" data-copy="' + esc(d.mac) + '" title="' + esc(t("js.ha.act.copy_mac")) + '" aria-label="' + esc(t("js.ha.act.copy_mac")) + '">' + icon("content-copy") + "</button>", true);
    // Two levels: product brand (with the source) and MAC manufacturer (chip/board).
    var ev = DEBUG && d.brand_evidence ? '<span class="ev ev-' + esc(d.brand_evidence) + '">' + esc(t("js.ha.ev." + d.brand_evidence)) + "</span>" : "";
    var brandShown = d.brand
      ? esc(d.brand) + (DEBUG && d.brand_source ? ' <span class="dbg-txt">· ' + esc(t("js.ha.brand_src." + d.brand_source)) + "</span>" : "") + ev
      : d.brand_declared
        ? '<span style="opacity:.75">' + esc(t("js.ha.brand_declared", { value: d.brand_declared })) + "</span>"
        : '<span style="opacity:.65">' + esc(t("js.ha.brand_unknown")) + "</span>";
    row(t("js.ha.attr.brand"), evRowCells("brand", t("js.ha.attr.brand")),
      '<button type="button" class="icon-btn small touch rp" data-act="brand-edit" title="' + esc(t("js.ha.act.edit_brand")) +
        '" aria-label="' + esc(t("js.ha.act.edit_brand")) + '">' + icon("pencil") + "</button>", true, "ev-attr");
    if (DEBUG && d.name_source) row(t("js.ha.attr.name_src"), esc(d.name_source), "", false, "dbg");
    var rr = (S.roles.by_ip || {})[d.ip];
    if (rr) row(t("js.ha.attr.roles"), Object.keys(rr).map(function (k) {
      return esc(t("js.ha.role." + k)) + ' <span style="opacity:.65">(' + esc(t("js.ha.role_src." + rr[k])) + ")</span>";
    }).join(", "));
    if ((S.roles.via || {})[d.ip]) row(t("js.ha.attr.via"), esc(viaText(d.ip, false)));
    var net = S.roles.internet;
    if (net && rr && rr.gateway) {
      var np = [];
      if (net.public_ip) np.push(t("js.ha.net.public", { ip: net.public_ip }));
      np.push(net.cgnat ? t("js.ha.net.cgnat") : net.double_nat ? t("js.ha.net.double", { ips: (net.private_hops || []).join(" \u2192 ") }) : t("js.ha.net.direct"));
      row(t("js.ha.attr.internet"), esc(np.join(" \u00b7 ")));
    }
    (S.roles.dhcp || []).filter(function (o) { return o.server === d.ip; }).forEach(function (o) {
      var parts = [];
      if (o.router) parts.push(t("js.ha.dhcp.router", { v: o.router.join(", ") }));
      if (o.dns) parts.push(t("js.ha.dhcp.dns", { v: o.dns.join(", ") }));
      if (o.domain) parts.push(t("js.ha.dhcp.domain", { v: o.domain }));
      if (o.lease) parts.push(t("js.ha.dhcp.lease", { v: o.lease }));
      if (parts.length) row(t("js.ha.attr.dhcp_gives"), esc(parts.join(" \u00b7 ")));
    });
    if (d.vendor && d.vendor !== d.brand) row(t("js.ha.attr.chip"), esc(chipText({ vendor: d.vendor, vendor_role: d.vendor_role })));
    if (DEBUG && d.battery === "yes") row(t("js.ha.attr.battery"), '<span class="batt-line">' + icon("battery") + "<span>" + esc(batteryTitle(d)) + "</span></span>", "", false, "dbg");
    var typeShown = esc(typeLabel(d.type)) + (d.type_user ? ' <span style="opacity:.65">· ' + esc(t("js.ha.type.manual")) + "</span>" : "");
    row(t("js.ha.attr.type"), evRowCells("group", t("js.ha.attr.type")),
      '<button type="button" class="icon-btn small touch rp" data-act="type-menu" aria-haspopup="true" title="' + esc(t("js.ha.act.edit_type")) +
        '" aria-label="' + esc(t("js.ha.act.edit_type")) + '">' + icon("chevron-down") + "</button>", true, "ev-attr");
    if (d.signal) {
      row(t("js.ha.attr.signal"), '<span class="sig sig-' + esc(d.signal.color || "none") + '">' + icon(d.signal.kind === "wifi" ? "wifi" : "lan") + "</span> " +
        esc(d.signal.display) + (d.signal.text ? " · " + esc(d.signal.text) : ""));
    }
    if (d.online && d.latency_ms != null) row(t("js.ha.attr.latency"), '<span class="lat lat-' + esc(d.latency_color || "none") + '">' + esc(d.latency_ms + " ms") + "</span>", "", true);
    if (d.uptime != null && d.online) row(t("js.ha.attr.uptime"), esc(fmtUptime(d.uptime)));
    if (!d.online && d.last_seen) row(t("js.ha.attr.last_seen"), esc(ago(d.last_seen) + " · " + fmtStamp(d.last_seen, true)));
    if (d.scanned_at) row(t("js.ha.attr.scanned"), esc(ago(d.scanned_at)));
    else if (d.deep_empty_at) row(t("js.ha.attr.scanned_empty"), esc(ago(d.deep_empty_at)));
    (d.attrs || []).forEach(function (a) { row(a.label, esc(a.value)); });
    if (d.ports && d.ports.length) {
      var ports = d.ports.map(function (p) { return { p: p, cat: portCategory(p), n: parseInt(p.label, 10) || 0 }; });
      ports.sort(function (a, b) { return PORT_CATS.indexOf(a.cat) - PORT_CATS.indexOf(b.cat) || a.n - b.n; });
      row(t("js.ha.attr.ports"), '<span class="pills">' + ports.map(function (x) {
        var p = Object.assign({}, x.p, { category: x.cat });
        // Service not certain (nmap only inferred it from the number): only the port is shown.
        var label = p.confirmed ? p.label : String(p.label || "").split(" · ")[0];
        return '<span class="pill cat-' + esc(p.category) + (p.confirmed ? "" : " guess") + '" title="' + esc(label) + '">' + esc(label) + "</span>";
      }).join("") + "</span>", "", true);
    }
    fixedRows.sort(function (a, b) { return (a.cls === "ev-attr" ? 0 : 1) - (b.cls === "ev-attr" ? 0 : 1); });    // stable: name, brand, type first
    function html(list) {
      return list.map(function (r) {
        return '<div class="attr' + (r.cls ? " " + r.cls : "") + '"><dt>' + esc(r.label) + '</dt><dd><span class="attr-val">' + r.html + "</span>" + r.extra + "</dd></div>";
      }).join("");
    }
    // Dropdown closed initially; if opened it stays open when the data updates.
    el.innerHTML = html(fixedRows) + (rows.length
      ? '<details class="attr-more" id="attr-more"' + (S.mi.moreOpen ? " open" : "") + "><summary><span>" + esc(t("js.ha.attr.more", { n: rows.length })) +
        '</span><span class="icon-btn small touch attr-chev" aria-hidden="true">' + icon("chevron-down") + "</span></summary>" + html(rows) + "</details>"
      : "");
    var det = $("attr-more");
    if (det) det.addEventListener("toggle", function () { S.mi.moreOpen = det.open; });
    // the values of the three rows (kept out of the string above: they are text, not markup) and then the numbers
    var vals = { name: d.name, brand: null, group: typeLabel(d.type) + (d.type_user ? " \u00b7 " + t("js.ha.type.manual") : "") };
    EV_KEYS.forEach(function (key) {
      var cell = el.querySelector('[data-ev-v="' + key + '"]');
      if (!cell) return;
      if (key === "brand") cell.innerHTML = brandShown; else cell.textContent = vals[key];
    });
    evApply(d);
  }

  // All actions are inline (pencil and eye next to the name, power on next to the
  // status, open next to the IP, copy next to the MAC): no button is left below.
  // Port categories (same rules as scanner._PORT_CATEGORY_RULES), also computed
  // here from the number: they apply immediately to ports saved before the new categories too.
  var PORT_CATS = ["web", "media", "remote", "iot", "file", "print", "db", "infra", "vpn", "mail", "other"];
  var PORT_NUM = {
    media: [554, 1935, 7000, 8008, 8009, 1400, 8060, 32400, 8096, 8200],
    print: [631, 9100, 515], vpn: [1194, 51820, 500, 4500, 1701, 1723], mail: [25, 465, 587, 110, 995, 143, 993],
    web: [80, 443, 3000, 8080, 8081, 8443, 8888, 9000, 9090, 8123, 8006],
    remote: [22, 23, 3389, 5900, 5555, 5985, 5986], iot: [1883, 8883, 5683, 6053],
    infra: [53, 67, 68, 111, 123, 137, 138, 139, 161, 162, 389, 5353, 5355], file: [21, 445, 548, 2049],
    db: [3306, 5432, 6379, 27017, 1433]
  };
  function portCategory(p) {
    var n = parseInt(p.label, 10);
    for (var i = 0; i < PORT_CATS.length; i++) {
      var c = PORT_CATS[i];
      if (PORT_NUM[c] && PORT_NUM[c].indexOf(n) >= 0) return c;
    }
    return p.category && PORT_CATS.indexOf(p.category) >= 0 ? p.category : "other";
  }
  function miActions(d) {
    var el = $("mi-actions");
    if (!el) return;
    var html = "";
    // Sharing with Home Assistant (MQTT): only if the link exists. Shared = HA sees the device as a
    // sub-device of "Vedetta"; "Remove" takes it out of HA.
    if (d) {
      var shareTip = S.mqtt && S.mqtt.active ? "" : ' title="' + esc(t("js.ha.share.pending")) + '"';
      html += '<button type="button" class="btn ' + (d.ha_share ? "outlined" : "tonal") + ' rp" data-act="share"' + shareTip + '>' + icon("home-assistant") +
        "<span>" + esc(t(d.ha_share ? "js.ha.share.remove" : "js.ha.share.add")) + "</span></button>";
    }
    var flagTip = esc(t(d && d.focus ? "js.ha.focus.edit" : "js.ha.focus.add"));
    var flag = '<button type="button" class="icon-btn small mi-flag rp' + (d && d.focus ? " on" : "") + '" data-act="focus" title="' + flagTip + '" aria-label="' + flagTip + '" aria-pressed="' + !!(d && d.focus) + '">' + icon("flag") + "</button>";
    el.innerHTML = flag + html + '<button type="button" class="btn tonal rp" data-act="deep"' + (deepOneBusy(d && d.id) ? ' disabled title="' + esc(t("js.ha.deep.busy")) + '"' : "") + ">" + icon("magnify") + "<span>" + esc(t("js.ha.deep.title")) + "</span></button>";
  }

  function updateMore() {
    if (!S.open || !dlg.open || S.mi.view !== "main") return;
    var d = S.devices.get(S.open);
    if (!d) return closeMore();
    var title = $("more-title");
    if (title && title.textContent !== d.name) title.textContent = d.name;
    var sub = $("mi-sub");
    if (sub) sub.textContent = miSub(d);
    miHero(d);
    miAttrs(d);
    miDebug(d);
    miActions(d);
  }

  // History chart: a single segmented band (online / offline / no data)
  // like the HA history bar, with tooltip on hover or touch.
  function loadGraph() {
    var id = S.open, hours = S.mi.range;
    var cached = S.mi.win[hours];
    if (cached && Date.now() - cached.at < 30000) { S.mi.token++; return paintGraph(cached.data, hours); }
    var graph = $("mi-graph");
    if (graph && !cached) graph.innerHTML = '<div class="skeleton sk-graph"></div>';
    var token = ++S.mi.token;
    api("/api/ha/history/" + encodeURIComponent(id) + "?hours=" + hours).then(function (data) {
      if (token !== S.mi.token || S.open !== id) return;
      S.mi.win[hours] = { at: Date.now(), data: data };
      if (hours === S.mi.range) paintGraph(data, hours);
    }).catch(function () {
      if (token !== S.mi.token) return;
      var g = $("mi-graph");
      if (g) g.innerHTML = '<div class="graph-msg">' + esc(t("js.ha.more.history_failed")) + "</div>";
    });
  }

  // Timeline strokes: online/offline segments plus the "no data" gaps,
  // clipped to the window. No intermediate state.
  function bucketsFor(win) {
    var segs = win.segments.slice().sort(function (x, y) { return x.from - y.from; });
    var out = [], cur = win.from;
    segs.forEach(function (s) {
      var a = Math.max(s.from, win.from), b = Math.min(s.to, win.to);
      if (b <= a) return;
      if (a > cur) out.push({ a: cur, b: a, st: "nodata" });
      out.push({ a: a, b: b, st: s.online ? "on" : "off" });
      cur = Math.max(cur, b);
    });
    if (cur < win.to) out.push({ a: cur, b: win.to, st: "nodata" });
    return out;
  }

  // Small line chart (SVG) of the response time: series already reduced by the
  // server to ~120 points [ts, ms]. Empty if there is no data.
  function latencyChart(lat) {
    var pts = lat && lat.points ? lat.points : [];
    if (pts.length < 2) return "";
    var W = 300, H = 56, pad = 3, span = Math.max(1, lat.to - lat.from);
    var max = 1;
    pts.forEach(function (p) { if (p[1] > max) max = p[1]; });
    var line = pts.map(function (p, i) {
      var x = (p[0] - lat.from) / span * W, y = H - pad - p[1] / max * (H - 2 * pad);
      return (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
    }).join(" ");
    var lastX = ((pts[pts.length - 1][0] - lat.from) / span * W).toFixed(1), firstX = ((pts[0][0] - lat.from) / span * W).toFixed(1);
    var area = line + " L" + lastX + " " + H + " L" + firstX + " " + H + " Z";
    return '<div class="lat-chart"><div class="lat-head"><span>' + esc(t("js.ha.more.latency_title")) + "</span><span>" +
      esc(t("js.ha.more.latency_stats", { avg: Math.round(lat.avg), max: Math.round(lat.max) })) + "</span></div>" +
      '<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" role="img" aria-label="' + esc(t("js.ha.more.latency_aria")) + '">' +
      '<path class="lat-area" d="' + area + '"></path><path class="lat-line" d="' + line + '"></path></svg></div>';
  }

  function paintGraph(win, hours) {
    var el = $("mi-graph");
    if (!el) return;
    var latHtml = latencyChart(win.latency);
    if (!win.segments || !win.segments.length) {
      el.innerHTML = '<div class="graph-msg">' + icon("history") + "<span>" + esc(t("js.ha.more.nodata")) + "</span></div>" + latHtml;
      return;
    }
    var from = win.from, to = win.to, span = to - from, longRange = hours > 24;
    var outages = win.segments.filter(function (s) { return !s.online; }).length;
    var label = { on: t("js.ha.more.tip_online_seg"), off: t("js.ha.more.tip_offline_seg"), nodata: t("js.ha.more.nodata") };
    var strip = bucketsFor(win).map(function (b) {
      var left = (b.a - from) / span * 100, w = Math.max(0.4, (b.b - b.a) / span * 100);
      var tip = label[b.st] + "\n" + fmtStamp(b.a, longRange) + " – " + fmtStamp(b.b, longRange);
      return '<i class="' + b.st + '" style="left:' + left.toFixed(2) + "%;width:" + w.toFixed(2) + '%" data-tip="' + esc(tip) + '"></i>';
    }).join("");
    var ticks = [];
    if (!longRange) { for (var h = 0; h <= 24; h += 6) ticks.push(h === 24 ? t("js.ha.more.now") : fmtClock(from + h * 3600)); }
    else {
      for (var d = 0; d < 7; d++) ticks.push(new Date((from + d * 86400) * 1000).toLocaleDateString(LANG, { weekday: "short" }));
      ticks.push(t("js.ha.more.now"));
    }
    var pct = win.online_pct;
    el.innerHTML =
      '<div class="stats">' +
      '<div class="stat"><span class="stat-v">' + outages + '</span><span class="stat-l">' + esc(t("js.ha.more.outages", { n: outages })) + "</span></div></div>" +
      '<div class="chart" role="img" aria-label="' + esc(t("js.ha.more.chart_aria")) + '">' +
        '<div class="tl">' + strip + "</div>" +
        '<div class="axis">' + ticks.map(function (x) { return "<span>" + esc(x) + "</span>"; }).join("") + "</div>" +
        '<div class="tip" id="tip" hidden></div></div>' + latHtml;
  }

  // Single chart tooltip.
  var tipTimer = null;
  function tipFor(e) {
    var chart = e.target.closest ? e.target.closest(".chart") : null;
    if (!chart) {
      var stray = dlg.querySelector(".tip");
      if (stray && !stray.hidden && e.pointerType !== "touch") stray.hidden = true;
      return;
    }
    var tip = chart.querySelector(".tip");
    var target = e.target.closest("[data-tip]");
    if (!target) { tip.hidden = true; return; }
    tip.textContent = target.dataset.tip;
    tip.hidden = false;
    var cr = chart.getBoundingClientRect();
    var x = e.clientX - cr.left;
    var w = tip.offsetWidth;
    x = Math.max(w / 2 + 4, Math.min(cr.width - w / 2 - 4, x));
    tip.style.left = x + "px";
    clearTimeout(tipTimer);
    if (e.pointerType === "touch") tipTimer = setTimeout(function () { tip.hidden = true; }, 1800);
  }
  dlg.addEventListener("pointermove", tipFor);
  dlg.addEventListener("pointerdown", tipFor);
  dlg.addEventListener("pointerleave", function (e) {
    var tip = dlg.querySelector(".tip");
    if (tip && e.pointerType !== "touch") tip.hidden = true;
  });

  function renderRename(d) {
    var mode = d.mobile_mode || "auto";
    dlg.innerHTML = '<div class="mi">' + miHeader(null, t("js.ha.rename.title"), true) +
      '<form class="mi-body" id="rename-form" autocomplete="off">' +
      '<label class="field"><input id="rn-name" type="text" maxlength="80" required placeholder=" " value="' + esc(d.name) + '"><span class="field-label">' + esc(t("js.ha.rename.name")) + "</span></label>" +
      '<div class="field-group"><div class="field-caption">' + esc(t("js.ha.rename.mobile")) + '</div><div class="seg wide" role="radiogroup" id="rn-mode">' +
      ["auto", "yes", "no"].map(function (m) {
        return '<button type="button" role="radio" class="rp" data-mode="' + m + '" aria-checked="' + (m === mode) + '" aria-pressed="' + (m === mode) + '">' + esc(t("js.ha.rename.mode_" + m)) + "</button>";
      }).join("") + '</div><div class="field-hint">' + esc(t("js.ha.rename.mobile_hint")) + "</div></div>" +
      '<div class="mi-actions"><button type="button" class="btn text rp" data-act="back">' + esc(t("js.ha.cancel")) + '</button>' +
      '<button type="submit" class="btn filled rp">' + esc(t("js.ha.save")) + "</button></div></form></div>";
    var input = $("rn-name");
    if (input) { input.focus(); input.select(); }
  }
  // Flag the device for the report: its card, history and this note go in the export for analysis.
  function renderFocus(d) {
    dlg.innerHTML = '<div class="mi">' + miHeader(null, t("js.ha.focus.title"), true) +
      '<form class="mi-body" id="focus-form" autocomplete="off">' +
      '<label class="field"><textarea id="fc-note" rows="4" maxlength="500" placeholder=" ">' + esc(d.focus_note || "") + '</textarea><span class="field-label">' + esc(t("js.ha.focus.label")) + "</span></label>" +
      '<div class="field-hint">' + esc(t("js.ha.focus.hint")) + "</div>" +
      '<div class="mi-actions"><button type="button" class="btn text rp" data-act="back">' + esc(t("js.ha.cancel")) + "</button>" +
      (d.focus ? '<button type="button" class="btn outlined rp" data-act="focus-off">' + esc(t("js.ha.focus.remove")) + "</button>" : "") +
      '<button type="submit" class="btn filled rp">' + esc(t("js.ha.focus.save")) + "</button></div></form></div>";
    var input = $("fc-note");
    if (input) input.focus();
  }
  function renderBrandEdit(d) {
    dlg.innerHTML = '<div class="mi">' + miHeader(null, t("js.ha.brand.title"), true) +
      '<form class="mi-body" id="brand-form" autocomplete="off">' +
      '<label class="field"><input id="br-name" type="text" maxlength="40" placeholder=" " value="' + esc(d.brand_user || d.brand || "") + '"><span class="field-label">' + esc(t("js.ha.brand.label")) + "</span></label>" +
      '<div class="field-hint">' + esc(t("js.ha.brand.hint")) + "</div>" +
      '<div class="mi-actions"><button type="button" class="btn text rp" data-act="back">' + esc(t("js.ha.cancel")) + '</button>' +
      '<button type="submit" class="btn filled rp">' + esc(t("js.ha.save")) + "</button></div></form></div>";
    var input = $("br-name");
    if (input) { input.focus(); input.select(); }
  }
  // Manual choice of brand or type: stays until switching back to automatic.
  function saveOverride(d, body) {
    return api("/api/devices/" + encodeURIComponent(d.id) + "/override", { method: "POST", json: body }).then(function () {
      // the choice is shown at once (the server sends the card again when it has re-read the device); no full reload, which
      // rebuilt every tile and played all their animations again
      Object.assign(d, body);
      S.dirty.ids.add(d.id);
      S.dirty.more = true;
      S.dirty.net = true;
      schedule();
    }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); });
  }
  // Type dropdown menu: inside the dialog (it is modal), with the same rules as the other
  // menus (closes with Esc, click outside and scroll; opening one closes the others).
  var typeMenu = null;
  function closeTypeMenu() {
    if (typeMenu) { typeMenu.remove(); typeMenu = null; }
  }
  function openTypeMenu(btn, d) {
    if (typeMenu) { closeTypeMenu(); return; }
    closePopups();
    var m = document.createElement("div");
    m.className = "menu type-menu"; m.setAttribute("role", "menu");
    var cur = d.type_user || "";
    var items = [["", t("js.ha.type.auto")]].concat(TYPE_ORDER.map(function (k) { return [k, typeLabel(k)]; }));
    m.innerHTML = items.map(function (it) {
      return '<button type="button" class="menu-item rp" role="menuitemradio" data-type="' + esc(it[0]) + '" aria-checked="' + (it[0] === cur) + '">' +
        (it[0] ? icon(I.typeIcon[it[0]]) : icon("auto-fix")) + "<span>" + esc(it[1]) + "</span></button>";
    }).join("");
    var r = btn.getBoundingClientRect();
    m.style.top = Math.round(r.bottom + 4) + "px";
    m.style.right = Math.max(8, Math.round(window.innerWidth - r.right)) + "px";
    m.style.maxHeight = Math.max(160, window.innerHeight - r.bottom - 16) + "px";
    dlg.appendChild(m);
    typeMenu = m;
    m.addEventListener("click", function (e) {
      var b = e.target.closest("[data-type]");
      if (!b) return;
      closeTypeMenu();
      saveOverride(d, { type: b.dataset.type || null });
    });
  }
  document.addEventListener("click", function (e) {
    if (typeMenu && !e.target.closest(".type-menu") && !e.target.closest('[data-act="type-menu"]')) closeTypeMenu();
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && typeMenu) { closeTypeMenu(); } });
  window.addEventListener("scroll", function (e) { if (typeMenu && !typeMenu.contains(e.target)) closeTypeMenu(); }, true);
  function renderDeep(d) {
    dlg.innerHTML = '<div class="mi">' + miHeader(null, t("js.ha.deep.title"), true) +
      '<div class="mi-body"><div class="confirm"><span class="confirm-ic info">' + icon("magnify") + "</span><p>" + esc(t("js.ha.deep.one_text", { name: d.name })) + "</p></div>" +
      '<label class="fl-row"><span class="fl-text"><b>' + esc(t("js.ha.deep.skip")) + '</b></span><input type="checkbox" class="fl-sw" id="deep-skip"></label></div>' +
      '<div class="mi-actions"><button type="button" class="btn text rp" data-act="back">' + esc(t("js.ha.cancel")) + "</button>" +
      '<button type="button" class="btn filled rp" data-act="deep-confirm">' + esc(t("js.ha.deep.start")) + "</button></div></div>";
  }
  function renderIgnore(d) {
    dlg.innerHTML = '<div class="mi">' + miHeader(null, t("js.ha.ignore.title", { name: d.name }), true) +
      '<div class="mi-body"><div class="confirm"><span class="confirm-ic">' + icon("eye-off") + "</span><p>" + esc(t("js.ha.ignore.text")) + "</p></div></div>" +
      '<div class="mi-actions"><button type="button" class="btn text rp" data-act="back">' + esc(t("js.ha.cancel")) + "</button>" +
      '<button type="button" class="btn filled danger rp" data-act="ignore-confirm">' + esc(t("js.ha.act.ignore")) + "</button></div></div>";
  }

  function copyText(text) {
    function fallback() {
      // With a modal dialog open the rest of the page is "inert": the support
      // field must be inside the dialog, otherwise it cannot be selected and
      // the copy fails silently (happens on HTTP, where the clipboard API is missing).
      var host = document.querySelector("dialog[open]") || document.body;
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("aria-hidden", "true");
      ta.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;font-size:16px";
      host.appendChild(ta);
      ta.focus();
      ta.select();
      try { ta.setSelectionRange(0, text.length); } catch (err) { /* ignore */ }
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
      host.removeChild(ta);
      return ok;
    }
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return fallback(); });
    }
    return Promise.resolve(fallback());
  }

  function wakeDevice(id) {
    var d = S.devices.get(id);
    if (!d) return;
    api("/api/devices/" + encodeURIComponent(id) + "/wake", { method: "POST" }).then(function () {
      snack(t("js.ha.toast.wake_sent", { name: d.name }), { kind: "success" });
    }).catch(function (err) {
      snack(err.message && err.message.indexOf("HTTP") !== 0 ? err.message : t("js.ha.toast.wake_failed"), { kind: "error" });
    });
  }

  // Opening an external page (the device's web interface, classic
  // dashboard): a link with target="_blank" inside the iframe of the HA mobile app
  // may be ignored. It is opened with window.open from a user gesture; if the
  // browser blocks it, the address is copied and a notice is shown.
  function openExternal(url) {
    var w = null;
    try { w = window.open(url, "_blank"); } catch (err) { w = null; }
    if (w) { try { w.opener = null; } catch (err) { /* ignore */ } return; }
    function copyFallback() {
      copyText(url).then(function (ok) {
        snack(t("js.ha.toast.open_blocked"), { kind: ok ? "success" : "error", ms: 4500 });
      });
    }
    // In the HA mobile app the iframe cannot open windows: the upper level
    // (the app) is asked to navigate, which opens an external address in the default
    // browser. If the page does not go to the background within a moment, it did not
    // succeed and the fallback is copying the address.
    var inApp = window.top !== window && /home\s?assistant/i.test(navigator.userAgent || "");
    if (!inApp) { copyFallback(); return; }
    var left = false;
    function onHide() { if (document.hidden) left = true; }
    document.addEventListener("visibilitychange", onHide);
    try { window.open(url, "_top"); } catch (err) { /* ignore */ }
    setTimeout(function () {
      document.removeEventListener("visibilitychange", onHide);
      if (!left) copyFallback();
    }, 900);
  }
  document.addEventListener("click", function (e) {
    var a = e.target.closest ? e.target.closest('a[target="_blank"]') : null;
    if (!a || e.defaultPrevented || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    openExternal(a.href);
  });

  dlg.addEventListener("click", function (e) {
    var copy = e.target.closest("[data-copy]");
    if (copy) {
      copyText(copy.dataset.copy).then(function (ok) {
        snack(ok ? t("js.ha.toast.mac_copied") : t("js.ha.toast.copy_failed"), { kind: ok ? "success" : "error", ms: 2200 });
      });
      return;
    }
    var range = e.target.closest("[data-range]");
    if (range) {
      S.mi.range = parseInt(range.dataset.range, 10);
      dlg.querySelectorAll("[data-range]").forEach(function (b) { b.setAttribute("aria-pressed", String(b === range)); });
      loadGraph();
      return;
    }
    var mode = e.target.closest("[data-mode]");
    if (mode) {
      dlg.querySelectorAll("[data-mode]").forEach(function (b) {
        b.setAttribute("aria-checked", String(b === mode));
        b.setAttribute("aria-pressed", String(b === mode));
      });
      return;
    }
    var act = e.target.closest("[data-act]");
    if (!act) return;
    var d = S.devices.get(S.open);
    switch (act.dataset.act) {
      case "close": closeMore(); break;
      case "back": S.mi.view = "main"; renderMore(); break;
      case "rename": S.mi.view = "rename"; renderMore(); break;
      case "brand-edit": S.mi.view = "brand"; renderMore(); break;
      case "focus": S.mi.view = "focus"; renderMore(); break;
      case "focus-off": if (d) saveOverride(d, { focus: false }).then(function () { S.mi.view = "main"; renderMore(); snack(t("js.ha.focus.removed"), { kind: "success" }); }); break;
      case "type-menu": if (d) openTypeMenu(act, d); break;
      case "ignore": S.mi.view = "ignore"; renderMore(); break;
      case "deep":
        if (d && deepOneBusy(d.id)) break;
        // Once the search has started, return to the dashboard: progress is visible on the card.
        if (d && skipDeepConfirm()) { runDeep([d.id]); closeMore(); break; }
        S.mi.view = "deep"; renderMore(); break;
      case "deep-confirm":
        if (d) {
          var skip = $("deep-skip");
          if (skip && skip.checked) { try { localStorage.setItem(SKIP_DEEP_KEY, "1"); } catch (err) { /* ignore */ } }
          runDeep([d.id]);
        }
        S.mi.view = "main"; closeMore(); break;
      case "wake": if (d) wakeDevice(d.id); break;
      case "share": if (d) saveOverride(d, { ha_share: !d.ha_share }).then(function () { snack(t(d.ha_share ? "js.ha.share.removed" : "js.ha.share.added"), { kind: "success" }); }); break;
      case "ignore-confirm": if (d) ignoreDevice(d, act); break;
    }
  });
  dlg.addEventListener("submit", function (e) {
    e.preventDefault();
    var d = S.devices.get(S.open);
    if (!d) return;
    if (e.target.id === "focus-form") {
      var flagged = 0;
      S.devices.forEach(function (x) { if (x.focus && x.id !== d.id) flagged++; });
      if (flagged >= 5) { snack(t("js.ha.focus.too_many"), { kind: "warning" }); return; }
      var submitF = e.target.querySelector('[type="submit"]');
      if (submitF) submitF.disabled = true;
      saveOverride(d, { focus: true, focus_note: $("fc-note").value.trim() || null }).then(function () { S.mi.view = "main"; renderMore(); snack(t("js.ha.focus.saved"), { kind: "success" }); });
      return;
    }
    if (e.target.id === "brand-form") {
      var submitB = e.target.querySelector('[type="submit"]');
      if (submitB) submitB.disabled = true;
      saveOverride(d, { brand: $("br-name").value.trim() || null }).then(function () { S.mi.view = "main"; renderMore(); });
      return;
    }
    var name = $("rn-name").value.trim();
    if (!name) return;
    var selected = dlg.querySelector('[data-mode][aria-checked="true"]');
    var m = selected ? selected.dataset.mode : "auto";
    var body = { name: name };
    if (m === "yes") body.mobile = true;
    else if (m === "no") body.mobile = false; // "auto": missing field = the heuristic decides again
    var submit = e.target.querySelector('[type="submit"]');
    if (submit) submit.disabled = true;
    api("/api/devices/" + encodeURIComponent(d.id) + "/rename", { method: "POST", json: body }).then(function () {

      S.mi.view = "main";
      renderMore();
    }).catch(function (err) {
      if (submit) submit.disabled = false;
      snack(err.message && err.message.indexOf("HTTP") !== 0 ? err.message : t("js.ha.toast.save_failed"), { kind: "error" });
    });
  });
  function ignoreDevice(d, btn) {
    btn.disabled = true;
    api("/api/devices/" + encodeURIComponent(d.id) + "?ignore=true", { method: "DELETE" }).then(function () {

      closeMore();
    }).catch(function () {
      btn.disabled = false;
      snack(t("js.ha.toast.ignore_failed"), { kind: "error" });
    });
  }

