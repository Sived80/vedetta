  // --------------------------------------------------------------- log
  var logEl = $("card-log");
  function dayLabel(ts) {
    var d = new Date(ts * 1000), n = new Date();
    var key = function (x) { return x.getFullYear() * 400 + x.getMonth() * 32 + x.getDate(); };
    var y = new Date(n.getTime() - 86400000);
    if (key(d) === key(n)) return t("js.ha.day.today");
    if (key(d) === key(y)) return t("js.ha.day.yesterday");
    return d.toLocaleDateString(LANG, { weekday: "long", day: "numeric", month: "long" });
  }
  var LOG_LEVELS = ["min", "normal", "detail"];
  function renderLog(onlyRows) {
    if (COMPACT) { logEl.hidden = true; return; }
    logEl.hidden = false;
    var all = S.log.events, html = "", lastDay = "";
    var prev = S.log.ids;
    // Search: on text, name and IP (lowercase), without reloading from the server.
    var q = (S.log.q || "").trim().toLowerCase();
    var ev = q ? all.filter(function (e) {
      return [e.message, e.name, e.ip, typeLabel(e.type)].join(" ").toLowerCase().indexOf(q) >= 0;
    }) : all;
    // Only consecutive state changes of the same device are grouped.
    var IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/;
    var groups = [];
    ev.forEach(function (e) {
      var last = groups[groups.length - 1];
      var key = e.kind === "event" ? e.id : (e.device_id || e.name);
      if (e.kind !== "event" && last && last.key === key && dayLabel(last.e.ts) === dayLabel(e.ts)) last.n++;
      else groups.push({ key: key, e: e, n: 1 });
    });
    groups.forEach(function (g) {
      var e = g.e, day = dayLabel(e.ts);
      if (day !== lastDay) { lastDay = day; html += '<div class="log-day">' + esc(day) + "</div>"; }
      var fresh = prev && !prev.has(e.id) ? " fresh" : "";
      if (e.kind === "event") {
        var tone = e.icon === "alert" ? " warn" : "";
        html += '<div class="log-row svc' + fresh + '"><span class="log-ic svc' + tone + '">' + icon(e.icon || "history") + "</span>" +
          '<span class="log-text"><span class="log-msg">' + esc(e.message) + '</span><span class="log-ago" data-ts="' + e.ts + '">' + esc(ago(e.ts)) +
          "</span></span>" + '<span class="log-time">' + esc(fmtClock(e.ts)) + "</span></div>";
        return;
      }
      var cls = e.online ? "on" : "off";
      var name = IPV4.test(e.name || "") && e.type && e.type !== "generic" ? typeLabel(e.type) + " " + e.name : e.name;
      var msg = g.n > 1 ? t("js.ha.log.flap", { n: g.n, state: t(e.online ? "js.ha.state.online" : "js.ha.state.offline") }) : e.message;
      html += '<' + (e.known ? 'button type="button"' : 'div') + ' class="log-row' + (e.known ? " rp" : "") + fresh + '"' + (e.known ? ' data-id="' + esc(e.device_id) + '"' : "") + ">" +
        '<span class="log-ic ' + cls + '">' + icon(e.dev_icon && I.paths[e.dev_icon] ? e.dev_icon : typeIcon(e.type)) + "</span>" +
        '<span class="log-text"><span class="log-msg"><b>' + esc(name) + "</b> " + esc(msg) + '</span><span class="log-ago" data-ts="' + e.ts + '">' + esc(ago(e.ts)) + "</span></span>" +
        '<span class="log-time">' + esc(fmtClock(e.ts)) + "</span></" + (e.known ? "button" : "div") + ">";
    });
    if (!ev.length) {
      html = q
        ? '<div class="log-empty">' + icon("magnify") + "<div><b>" + esc(t("js.ha.log.nomatch")) + "</b></div></div>"
        : '<div class="log-empty">' + icon("history") + "<div><b>" + esc(t("js.ha.log.empty")) + "</b><span>" + esc(t("js.ha.log.empty_hint")) + "</span></div></div>";
    }
    if (onlyRows && S.log.open && $("log-rows")) {
      // While typing only the list is updated: the field does not lose the cursor.
      $("log-rows").innerHTML = html;
      var subEl = logEl.querySelector(".ch-sub");
      if (subEl) subEl.textContent = t("js.ha.log.level_" + S.log.level) + " · " + t("js.ha.log.today", { n: all.filter(function (e) { return dayLabel(e.ts) === dayLabel(Date.now() / 1000); }).length });
      S.log.ids = new Set(all.map(function (e) { return e.id; }));
      return;
    }
    var more = all.length >= S.log.limit && S.log.limit < 200
      ? '<div class="card-actions"><button type="button" class="btn text rp" id="log-more">' + esc(t("js.ha.log.more")) + "</button></div>" : "";
    var today = dayLabel(Date.now() / 1000);
    var nToday = all.filter(function (e) { return dayLabel(e.ts) === today; }).length;
    var sub = t("js.ha.log.level_" + S.log.level) + " · " + t("js.ha.log.today", { n: nToday });
    logEl.innerHTML = '<div class="card-header log-head rp" id="log-toggle" role="button" tabindex="0" aria-expanded="' + S.log.open + '">' +
      '<div class="ch-text"><div class="ch-title">' + esc(t("js.ha.log.title")) + '</div><div class="ch-sub">' + esc(sub) + "</div></div>" +
      '<span class="log-chev">' + icon("chevron-down") + "</span></div>" +
      (S.log.open ? '<div class="log-search"><label class="search">' + icon("magnify", "search-icon") +
        '<input type="search" id="log-q" autocomplete="off" placeholder="' + esc(t("js.ha.log.search")) + '" value="' + esc(S.log.q) + '"></label>' +
        // Log level: next to the search, in a column with the title arrow
        '<button type="button" class="icon-btn touch rp" id="log-level-btn" aria-haspopup="true" aria-expanded="false" title="' + esc(t("js.ha.log.level")) +
        '" aria-label="' + esc(t("js.ha.log.level")) + '">' + icon("format-list-bulleted-type") + "</button></div>" +
        '<div class="log-list" id="log-rows">' + html + "</div>" + more : "");
    logEl.classList.toggle("is-open", S.log.open);
    S.log.ids = new Set(all.map(function (e) { return e.id; }));
  }
  // Log level menu: same buttons as the dashboard menu.
  var logMenuEl = $("log-menu");
  function buildLogMenu() {
    logMenuEl.innerHTML = menuGroup(t("js.ha.log.level"), LOG_LEVELS.map(function (l) {
      return pill("md", "loglevel", l, l === S.log.level, t("js.ha.log.level_" + l));
    }).join("")) + '<div class="menu-hint">' + esc(t("js.ha.log.hint_" + S.log.level)) + "</div>";
  }
  function toggleLogMenu(open) {
    if (open === undefined) open = logMenuEl.hidden;
    var btn = $("log-level-btn");
    if (open && btn) {
      closePopups("log");
      buildLogMenu();
      var r = btn.getBoundingClientRect();
      logMenuEl.style.top = Math.round(r.bottom + 4) + "px";
      logMenuEl.style.left = "auto";
      logMenuEl.style.right = Math.max(8, Math.round(window.innerWidth - r.right)) + "px";
    }
    logMenuEl.hidden = !open;
    if (btn) btn.setAttribute("aria-expanded", String(open));
  }
  logMenuEl.addEventListener("click", function (e) {
    var item = e.target.closest("[data-loglevel]");
    if (!item) return;
    S.log.level = item.dataset.loglevel;
    try { localStorage.setItem("vedetta-ha-loglevel", S.log.level); } catch (err) { /* ignore */ }
    toggleLogMenu(false);
    S.log.open = true;
    fetchLog();
  });
  document.addEventListener("click", function (e) {
    if (!logMenuEl.hidden && !e.target.closest("#log-menu") && !e.target.closest("#log-level-btn")) toggleLogMenu(false);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !logMenuEl.hidden) toggleLogMenu(false);
  });
  window.addEventListener("resize", function () { if (!logMenuEl.hidden) toggleLogMenu(false); });
  logEl.addEventListener("click", function (e) {
    if (e.target.closest("#log-level-btn")) { e.stopPropagation(); toggleLogMenu(); return; }
    if (e.target.closest("#log-toggle")) { S.log.open = !S.log.open; if (!S.log.open) S.log.q = ""; renderLog(); return; }
    if (e.target.closest("#log-more")) {
      S.log.limit = Math.min(200, S.log.limit + 30);
      fetchLog();
      return;
    }
    var row = e.target.closest("[data-id]");
    if (row) openMore(row.dataset.id);
  });
  logEl.addEventListener("input", function (e) {
    if (e.target.id !== "log-q") return;
    S.log.q = e.target.value;
    renderLog(true);
  });
  logEl.addEventListener("keydown", function (e) {
    if ((e.key === "Enter" || e.key === " ") && e.target.id === "log-toggle") { e.preventDefault(); S.log.open = !S.log.open; renderLog(); }
  });
  function fetchLog() {
    return api("/api/ha/logbook?limit=" + S.log.limit + "&level=" + S.log.level).then(function (r) {
      S.log.events = r.events || [];
      // With the log open only the rows are updated: search and scroll stay.
      renderLog(S.log.open && !!$("log-rows"));
    }).catch(function () { /* the log is secondary: retry at the next change */ });
  }
  var fetchLogSoon = debounce(fetchLog, 1500);

  function fetchHist() {
    return api("/api/ha/history?hours=24").then(function (r) {
      Object.keys(r.devices || {}).forEach(function (id) { S.hist.set(id, r.devices[id]); });
      S.tiles.forEach(function (el, id) { renderHbar(id); });
    }).catch(function () { /* without history the bars stay empty */ });
  }
  // A live state change extends/closes the last segment without requesting anything.
  function histPush(id, online) {
    var h = S.hist.get(id), now = Math.floor(nowSec());
    if (!h) { h = { from: now - 86400, to: now, segments: [], online_pct: null }; S.hist.set(id, h); }
    var last = h.segments[h.segments.length - 1];
    if (last) last.to = now;
    h.segments.push({ from: now, to: now, online: online });
    h.to = now;
  }

