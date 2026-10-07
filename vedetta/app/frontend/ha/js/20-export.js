  // ------------------------------------------------- export for analysis
  // One window, five moments: who is it for (the developer: masked and encrypted; me: my own data as it is) -> which days (two
  // taps on the columns, or a preset) -> the job runs (the server says each step) -> what could not be fixed is decided one by one
  // -> the file. The size is estimated from what the server says each day weighs.
  var exportDlg = $("exportdlg");
  var X = null;                                             // state of the open window (null = closed)
  var XP = { MIN: 2, MAXN: 20, W: 20, HOR: 90, SHOWN: 10 };
  function xpT(key, vars) { var v = t(key, vars); return v === key ? "" : v; }          // a text that may not exist
  function xpDay(a) { var d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() - a); return d; }
  function xpFmt(d, o) { try { return d.toLocaleDateString(LANG, o); } catch (e) { return d.toDateString(); } }
  function xpShort(a) { return xpFmt(xpDay(a), { day: "numeric", month: "short" }); }
  function xpLong(a) { return xpFmt(xpDay(a), { day: "numeric", month: "long" }); }
  function xpSize(bytes) { var mb = bytes / 1048576; return (mb < 0.1 ? "0.1" : mb.toFixed(1)).replace(".", LANG === "it" ? "," : ".") + " MB"; }
  function xpDays() { return X.from - X.to; }
  function xpIn(a) { return X.all || (a >= X.to && a <= X.from - 1); }
  function xpBytes(all) {
    var i = X.info;
    if (!i) return 0;
    var a0 = all || X.all ? i.horizon - 1 : X.from - 1, a1 = all || X.all ? 0 : X.to, sum = i.base;
    for (var a = a1; a <= a0; a++) sum += i.daily[a] || 0;
    return sum * i.ratio * (X.dest === "dev" ? i.seal_factor : 1);
  }
  function xpLimited() { return X.dest !== "me"; }
  function xpOver(all) { return !!(X.info && xpLimited() && xpBytes(all) > X.info.limit); }
  function xpClose() {
    if (X && X.job) { api("/api/export/jobs/" + X.job, { method: "DELETE" }).catch(function () {}); }
    if (X) clearTimeout(X.timer);
    X = null;
    if (exportDlg.open && typeof exportDlg.close === "function") exportDlg.close(); else exportDlg.removeAttribute("open");
  }
  function closeExport() { xpClose(); }

  function xpChart() {
    var i = X.info, max = 1, h = "", lab = "", a, k;
    if (i) i.daily.forEach(function (v) { if (v > max) max = v; });
    var w = XP.W, off = X.off, rows = [[], [], []];
    for (k = 0; k < w; k++) {
      a = off + w - 1 - k;
      var d = xpDay(a), nod = a >= XP.HOR, weekend = d.getDay() === 0 || d.getDay() === 6, isIn = xpIn(a);
      var height = nod ? 12 : Math.round(66 + 24 * (((i && i.daily[a]) || 0) / max) + 10 * Math.sin(k * 0.9));   // always full (easy to click), a light wave
      var edge = !X.all && (a === X.from - 1 || a === X.to);
      h += '<button type="button" class="xp-col' + (nod ? " nod" : "") + (isIn ? " in" : "") + (edge ? " edge" : "") + (X.pend === a ? " pend" : "") + '" data-xa="' + a + '"' + (nod ? " disabled" : "") +
        ' style="height:' + height + '%" aria-label="' + esc(xpFmt(d, { weekday: "long", day: "numeric", month: "long" })) + '"></button>';
      var cls = (isIn ? "in " : "") + (weekend ? "we " : "") + (a === 0 ? "today" : "");
      rows[0].push('<i class="' + cls + '">' + d.getDate() + "</i>");
      rows[1].push('<i class="m">' + ((d.getDate() === 1 || k === 0) ? esc(xpFmt(d, { month: "short" })) : "") + "</i>");
    }
    lab = '<div class="xp-lab">' + rows[0].join("") + '</div><div class="xp-lab">' + rows[1].join("") + "</div>";
    var i1 = off + w - 1 - (X.from - 1), i2 = off + w - 1 - X.to, finger = "";
    if (X.intro && !X.all) {
      var x1 = (i1 >= 0 && i1 < w ? (i1 + 0.5) / w : 0.15) * 100, x2 = (i2 >= 0 && i2 < w ? (i2 + 0.5) / w : 0.85) * 100;
      finger = '<span class="xp-finger" style="--x1:' + x1 + "%;--x2:" + x2 + '%"><i></i>' + icon("gesture-tap") + "</span>";
    }
    var caption = esc(xpShort(off + w - 1)) + " – " + (off === 0 ? esc(t("js.ha.export.today")) : esc(xpShort(off)));
    var pan = '<div class="xp-pan"><button type="button" data-xp="older"' + (off + w >= XP.HOR ? " disabled" : "") + ">" + icon("chevron-left") + "<span>" + esc(t("js.ha.export.older")) + "</span></button>" +
      '<span class="xp-cap">' + caption + '</span><button type="button" data-xp="newer"' + (off === 0 ? " disabled" : "") + "><span>" + esc(t("js.ha.export.newer")) + "</span>" + icon("chevron-right") + "</button></div>";
    return "<div>" + pan + '<div class="xp-days' + (X.intro ? " intro" : "") + '">' + h + finger + "</div>" + lab + "</div>";
  }
  function xpSummary() {
    var bytes = xpBytes(), over = xpOver(), lim = X.info ? xpSize(X.info.limit) : "";
    var head = X.all ? t("js.ha.export.sum_all")
      : X.to === 0 ? t("js.ha.export.sum_to_today", { from: xpLong(X.from - 1) }) : t("js.ha.export.sum_from_to", { from: xpLong(X.from - 1), to: xpLong(X.to) });
    var meter = xpLimited() && X.info ? '<div class="xp-meter' + (over ? " over" : "") + '"><i style="width:' + Math.min(100, bytes / X.info.limit * 100).toFixed(1) + '%"></i></div><div class="xp-sub">' +
      esc(over ? t("js.ha.export.limit_over", { size: lim }) : t("js.ha.export.limit_ok", { size: lim })) + "</div>" : "";
    return '<div><div class="xp-read"><b>' + esc(head) + "</b><span>" + esc(t("js.ha.export.sum_size", { n: X.all ? XP.HOR : xpDays(), size: xpSize(bytes) })) + "</span></div>" + meter +
      (X.note ? '<div class="xp-sub warn">' + esc(X.note) + "</div>" : "") + "</div>";
  }
  function xpPresets() {
    function p(n) { return '<button type="button" data-xp="p:' + n + '" aria-pressed="' + (!X.all && X.to === 0 && xpDays() === n) + '">' + esc(t("js.ha.export.days", { n: n })) + "</button>"; }
    var dis = xpOver(true);
    return '<div class="xp-segm" role="group">' + p(2) + p(7) + p(20) + '<button type="button" data-xp="all" aria-pressed="' + X.all + '"' + (dis ? ' disabled title="' + esc(t("js.ha.export.limit_over", { size: xpSize(X.info.limit) })) + '"' : "") + ">" + esc(t("js.ha.export.all")) + "</button></div>";
  }
  function xpDestCards() {
    function card(d, ic, title, text, tag) {
      return '<button type="button" class="xp-dcard" data-xp="dest:' + d + '"><span class="xp-dic">' + icon(ic) + "</span><span><b>" + esc(t(title)) + '</b><em class="xp-tag' + (d === "me" ? " warn" : "") + '">' + tag + '</em><span class="xp-sub">' + esc(t(text)) + "</span></span></button>";
    }
    return card("dev", "lock", "js.ha.export.dev_title", "js.ha.export.dev_text", ".txt") + card("me", "download", "js.ha.export.me_title", "js.ha.export.me_text", ".zip");
  }
  function xpSteps() {
    var s = X.snap || { steps: [], status: "running" }, ids = s.steps.slice(), out = "";
    var plan = X.dest === "me" ? ["collect", "prepare", "ready"] : ["collect", "mask", "check", "fix", "seal", "ready"];
    var shown = plan.filter(function (id) { return id !== "fix" || ids.indexOf("fix") >= 0; });
    shown.forEach(function (id, n) {
      var at = ids.indexOf(id), last = ids.length - 1, st = "wait";
      if (s.status === "done") st = "done";
      else if (at >= 0) st = at < last ? "done" : (s.status === "choose" && id === "fix") ? "bad" : s.status === "error" ? "bad" : "run";
      if (!ids.length && n === 0 && s.status === "running") st = "run";                 // before the first answer of the server
      var sub = xpT("js.ha.export.step_" + id + "_sub");
      if (id === "fix" && at >= 0) sub = s.status === "choose" ? t("js.ha.export.step_fix_left", { n: s.items_total }) : t("js.ha.export.step_fix_sub");
      out += '<div class="xp-step ' + st + '"><span class="xp-dot">' + (st === "done" ? icon("check") : st === "bad" ? icon("close") : n + 1) + "</span><div><b>" + esc(t("js.ha.export.step_" + id)) + "</b>" + (sub ? '<span class="xp-sub">' + esc(sub) + "</span>" : "") + "</div></div>";
    });
    return "<div>" + out + "</div>";
  }
  function xpChoose() {
    var s = X.snap, many = s.items_total > XP.SHOWN, rows = "";
    s.items.forEach(function (it) {
      var c = X.choice[it.id];
      rows += '<li><code>' + esc(it.value) + '</code><span>' + esc(it.file + (it.where ? " · " + it.where : "")) + '<div class="xp-rowact"><button type="button" class="rm" data-xp="rm:' + it.id + '" aria-pressed="' + (c === "rm") + '">' + esc(t("js.ha.export.rm")) +
        '</button><button type="button" data-xp="keep:' + it.id + '" aria-pressed="' + (c === "keep") + '">' + esc(t("js.ha.export.keep")) + "</button></div></span></li>";
    });
    return '<div class="xp-tone ' + (many ? "bad" : "warn") + '"><span>' + icon("alert") + "</span><div>" + esc(t(many ? "js.ha.export.choose_many" : "js.ha.export.choose_head", { n: s.items_total })) + "</div></div>" +
      '<div><div class="xp-bulk"><span>' + esc(t("js.ha.export.choose_note")) + '</span><button type="button" class="xp-link" data-xp="rmall">' + esc(t("js.ha.export.rmall")) + '</button></div><ul class="xp-fl">' + rows + "</ul>" +
      (many ? '<div class="xp-more">' + esc(t("js.ha.export.choose_more", { n: s.items_total - XP.SHOWN })) + "</div>" : "") + "</div>";
  }
  function xpDone() {
    var s = X.snap, me = X.dest === "me", sub = me ? t("js.ha.export.done_me", { size: xpSize(s.size || 0) }) : t("js.ha.export.done_dev", { size: xpSize(s.size || 0) });
    var extra = [];
    if (!me && s.fixed) extra.push(t("js.ha.export.done_fixed", { n: s.fixed }));
    if (X.decided) extra.push(t("js.ha.export.done_decided", { r: X.decided.rm, k: X.decided.keep }));
    return '<div class="xp-res"><div class="xp-rt"><span class="ok">' + icon("check-circle") + "</span><div><b>" + esc(t(me ? "js.ha.export.step_ready" : "js.ha.export.done_title")) + '</b><span class="xp-sub">' + esc(sub) + "</span></div></div></div>" +
      (extra.length ? '<div class="xp-sub">' + esc(extra.join(" ")) + "</div>" : "") + (me ? '<div class="xp-sub">' + esc(t("js.ha.export.done_me_note")) + "</div>" : "");
  }
  function xpFocusLine() {
    var n = 0;
    S.devices.forEach(function (x) { if (x.focus) n++; });
    return n ? '<div class="xp-flag">' + icon("flag") + "<span><b>" + esc(t("js.ha.export.focus_title", { n: n })) + "</b> " + esc(t("js.ha.export.focus_text")) + "</span></div>" : "";
  }
  function xpView() {
    var title = '<div class="mi-header"><div class="mi-titles"><h2 class="mi-title" id="exportdlg-title">' + esc(t("js.ha.export.title")) + "</h2></div></div>";
    var cancel = '<button type="button" class="btn text rp" data-xp="cancel">' + esc(t("js.ha.cancel")) + "</button>";
    var body, acts;
    if (X.stage === "dest") {
      body = '<div class="xp-sub">' + esc(t("js.ha.export.dest_q")) + "</div>" + xpDestCards() + xpFocusLine();
      acts = cancel;
    } else if (X.stage === "pick") {
      var over = xpOver();
      body = '<div class="xp-chosen"><span class="xp-tag' + (X.dest === "me" ? " warn" : "") + '">' + esc(t(X.dest === "me" ? "js.ha.export.chip_me" : "js.ha.export.chip_dev")) + "</span></div>" + xpChart() + xpSummary() + xpPresets();
      acts = cancel + '<button type="button" class="btn filled rp" data-xp="go"' + (over || !X.info ? " disabled" : "") + ">" + icon("download") + "<span>" + esc(t(X.dest === "me" ? "js.ha.export.go_me" : "js.ha.export.go_dev")) + "</span></button>";
    } else if (X.stage === "run") {
      body = xpSteps();
      acts = '<button type="button" class="btn text rp" data-xp="stop">' + esc(t("js.ha.export.stop")) + "</button>";
    } else if (X.stage === "choose") {
      body = xpSteps() + xpChoose();
      var ready = X.snap.items.every(function (it) { return X.choice[it.id]; });
      acts = cancel.replace("data-xp=\"cancel\"", "data-xp=\"stop\"") + '<button type="button" class="btn filled rp" data-xp="apply"' + (ready ? "" : " disabled") + "><span>" + esc(t("js.ha.export.continue")) + "</span></button>";
    } else if (X.stage === "done") {
      body = xpSteps() + xpDone();
      acts = '<button type="button" class="btn text rp" data-xp="finish">' + esc(t("js.ha.export.close")) + '</button><button type="button" class="btn filled rp" data-xp="save"' + (X.saved ? " disabled" : "") + ">" + icon("download") + "<span>" + esc(t(X.saved ? "js.ha.export.saved" : "js.ha.export.save")) + "</span></button>";
    } else {
      var code = X.error || "export_failed";
      body = '<div class="xp-tone bad"><span>' + icon("alert") + "</span><div>" + esc(code === "too_big" ? t("js.ha.export.err_too_big", { size: X.info ? xpSize(X.info.limit) : "20 MB" }) : code === "encryption_unavailable" ? t("js.ha.export.no_crypto") : code === "busy" ? t("js.ha.export.err_busy") : t("js.ha.export.failed")) + "</div></div>";
      acts = '<button type="button" class="btn text rp" data-xp="back">' + esc(t("js.ha.export.back")) + "</button>";
    }
    return '<div class="mi">' + title + '<div class="mi-body xp-body">' + body + '</div><div class="mi-actions">' + acts + "</div></div>";
  }
  function xpRender() {
    if (!X) return;
    exportDlg.innerHTML = xpView();
    X.intro = false;
  }
  function openExport() {
    X = { stage: "dest", dest: null, from: 7, to: 0, off: 0, all: false, pend: null, intro: false, note: "", info: null, job: null, snap: null, choice: {}, error: null, saved: false, decided: null, timer: null };
    xpRender();
    if (typeof exportDlg.showModal === "function") exportDlg.showModal(); else exportDlg.setAttribute("open", "");
    var mine = X;
    api("/api/export/info").then(function (i) { if (X === mine) { X.info = i; xpRender(); } }).catch(function () {});
  }
  function xpPick(a) {
    X.note = "";
    if (X.all) { X.all = false; X.pend = null; X.from = 7; X.to = 0; }
    if (X.pend === null) { X.pend = a; return; }
    var lo = Math.min(X.pend, a), hi = Math.max(X.pend, a);
    if (hi - lo + 1 > XP.MAXN) { X.note = t("js.ha.export.note_max", { n: XP.MAXN }); if (a > X.pend) hi = lo + XP.MAXN - 1; else lo = hi - XP.MAXN + 1; }
    X.from = hi + 1; X.to = lo; X.pend = null;
    if (xpDays() < XP.MIN) X.to = Math.max(0, X.from - XP.MIN);
  }
  function xpPoll() {
    clearTimeout(X.timer);
    var mine = X, fails = 0;
    (function tick() {
      mine.timer = setTimeout(function () {
        if (X !== mine || !mine.job) return;
        api("/api/export/jobs/" + mine.job).then(function (s) {
          if (X !== mine) return;
          mine.snap = s;
          if (s.status === "running") { xpRender(); tick(); return; }
          if (s.status === "choose") { mine.stage = "choose"; mine.choice = mine.choice || {}; }
          else if (s.status === "done") mine.stage = "done";
          else { mine.stage = "error"; mine.error = s.error; }
          xpRender();
        }).catch(function () { fails++; if (fails > 5) { mine.stage = "error"; mine.error = "export_failed"; xpRender(); } else tick(); });
      }, 600);
    })();
  }
  function xpGo() {
    var body = { dest: X.dest };
    if (X.all) body.all = true; else { body.from_day = X.from - 1; body.to_day = X.to; }
    var mine = X;
    mine.stage = "run"; mine.snap = { steps: [], status: "running", items: [], items_total: 0 }; mine.decided = null; mine.saved = false;
    xpRender();
    api("/api/export/jobs", { method: "POST", json: body }).then(function (s) {
      if (X !== mine) { api("/api/export/jobs/" + s.id, { method: "DELETE" }).catch(function () {}); return; }
      mine.job = s.id; mine.snap = s; xpPoll();
    }).catch(function (err) { if (X !== mine) return; mine.stage = "error"; mine.error = /already running/.test(err && err.message || "") ? "busy" : "export_failed"; xpRender(); });
  }
  function xpSave() {
    var mine = X, id = mine.job;
    fetch("/api/export/jobs/" + id + "/file", { method: "POST", headers: { "X-Lang": LANG }, cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      var m = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") || "");
      return r.blob().then(function (blob) { return { blob: blob, name: m ? m[1] : "vedetta-export" }; });
    }).then(function (f) {
      var a = document.createElement("a");
      a.href = URL.createObjectURL(f.blob); a.download = f.name;
      document.body.appendChild(a); a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 4000);
      mine.job = null; mine.saved = true;
      snack(t(mine.dest === "me" ? "js.ha.export.done_plain" : "js.ha.export.done"), { kind: "success" });
      if (X === mine) xpRender();
    }).catch(function () { snack(t("js.ha.export.failed"), { kind: "error" }); });
  }
  exportDlg.addEventListener("click", function (e) {
    if (!X) return;
    if (e.target === exportDlg) return xpClose();
    var col = e.target.closest("[data-xa]");
    if (col && X.stage === "pick" && !col.disabled) { xpPick(parseInt(col.dataset.xa, 10)); xpRender(); return; }
    var b = e.target.closest("[data-xp]");
    if (!b || b.disabled) return;
    var act = b.dataset.xp;
    if (act.indexOf("dest:") === 0) { X.dest = act.slice(5); X.stage = "pick"; X.intro = true; X.all = false; X.pend = null; X.note = ""; }
    else if (act === "cancel") { if (X.stage === "pick") { X.stage = "dest"; X.pend = null; X.note = ""; } else return xpClose(); }
    else if (act === "older") X.off = Math.min(XP.HOR - XP.W, X.off + 10);
    else if (act === "newer") X.off = Math.max(0, X.off - 10);
    else if (act.indexOf("p:") === 0) { X.all = false; X.from = parseInt(act.slice(2), 10); X.to = 0; X.off = 0; X.pend = null; X.note = ""; }
    else if (act === "all") { X.all = true; X.from = XP.HOR; X.to = 0; X.pend = null; X.note = ""; }
    else if (act === "go") return xpGo();
    else if (act === "stop" || act === "back") {
      if (X.job) { api("/api/export/jobs/" + X.job, { method: "DELETE" }).catch(function () {}); X.job = null; }
      clearTimeout(X.timer); X.stage = "pick"; X.snap = null; X.error = null;
    }
    else if (act.indexOf("rm:") === 0) X.choice[parseInt(act.slice(3), 10)] = "rm";
    else if (act.indexOf("keep:") === 0) X.choice[parseInt(act.slice(5), 10)] = "keep";
    else if (act === "rmall") X.snap.items.forEach(function (it) { X.choice[it.id] = "rm"; });
    else if (act === "apply") {
      var mine = X, choices = {}, rm = 0, keep = 0;
      for (var n = 0; n < mine.snap.items_total; n++) { var c = mine.choice[n] || "rm"; choices[n] = c; if (c === "keep") keep++; else rm++; }
      mine.decided = { rm: rm, keep: keep };
      mine.stage = "run"; mine.snap = Object.assign({}, mine.snap, { status: "running" });
      xpRender();
      api("/api/export/jobs/" + mine.job + "/choices", { method: "POST", json: { choices: choices } }).then(function (s) { if (X === mine) { mine.snap = s; xpPoll(); } })
        .catch(function () { if (X === mine) { mine.stage = "error"; mine.error = "export_failed"; xpRender(); } });
      return;
    }
    else if (act === "save") return xpSave();
    else if (act === "finish") return xpClose();
    xpRender();
  });
  exportDlg.addEventListener("close", function () { if (X) xpClose(); });

