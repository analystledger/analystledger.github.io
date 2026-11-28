/* Stocks > Historical tab: period table (month-end consensus) and a per-stock chart. */
(function () {
  var L = window.HL || {}, COMP = window.HCOMP || {};
  var BASE = (window.AROOT || "../") + "data/hist/";
  var $ = function (id) { return document.getElementById(id); };
  var from = $("h-from"), to = $("h-to"), quick = $("h-quick"), q = $("h-q"), stock = $("h-stock");
  var CONS = null, consLoading = false, cache = {}, current = null;

  // ---------- helpers
  function iso(d) { return d.toISOString().slice(0, 10); }
  function ago(m) { var d = new Date(); d.setMonth(d.getMonth() - m); return iso(d); }
  function money(v) { return v || v === 0 ? "$" + Number(v).toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2}) : "—"; }
  function pct(v) { return v === null || v === undefined || isNaN(v) ? "—" : (v >= 0 ? "+" : "") + v.toFixed(1) + "%"; }
  function cls(v) { return v === null || v === undefined || isNaN(v) ? "" : v >= 0 ? "up" : "down"; }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]; }); }
  function slug(t) { return t.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""); }
  function range() {
    var s = from.value || "2000-01-01", e = to.value || iso(new Date());
    return s > e ? [e, s] : [s, e];
  }
  var BULL = /^(buy|strong buy|outperform|overweight|accumulate|positive|add|market outperform|sector outperform|top pick|conviction buy|long-term buy|moderate buy|speculative buy)$/i;
  var BEAR = /^(sell|strong sell|underperform|underweight|reduce|negative|market underperform|sector underperform|moderate sell)$/i;
  function stance(r) { r = (r || "").trim(); return !r ? null : BULL.test(r) ? 1 : BEAR.test(r) ? -1 : 0; }

  // ---------- defaults
  to.value = iso(new Date()); from.value = ago(12);
  to.max = from.max = iso(new Date());

  // ---------- table
  var waiting = [];
  function loadCons(cb) {
    if (CONS) return cb();
    waiting.push(cb);
    if (consLoading) return;
    consLoading = true;
    $("h-sum").textContent = L.loading;
    fetch(BASE + "consensus.json", {cache: "no-cache"}).then(function (r) { if (!r.ok) throw 0; return r.json(); })
      .then(function (j) { CONS = j; from.min = to.min = j.months[0] + "-01"; waiting.splice(0).forEach(function (f) { f(); }); })
      .catch(function () { $("h-sum").textContent = L.noData; consLoading = false; waiting = []; });
  }
  function monthIdx(d) {  // last month-end on or before d (months are YYYY-MM)
    var m = d.slice(0, 7), i = CONS.months.indexOf(m);
    if (i === -1) return m < CONS.months[0] ? -1 : CONS.months.length - 1;
    return i;
  }
  function drawTable() {
    if (!CONS) return loadCons(drawTable);
    var r = range(), mi = monthIdx(r[1]), ms = Math.max(0, monthIdx(r[0])), last = CONS.months.length - 1;
    var rows = [], tot = 0, f = q.value.toLowerCase();
    Object.keys(CONS.t).forEach(function (t) {
      var a = CONS.t[t]; if (mi < 0 || !a[mi]) return;
      var s = a[mi], n = 0;
      for (var i = ms; i <= mi; i++) n += (a[i] && a[i][5]) || 0;
      var nowPx = null; for (var k = last; k >= 0 && nowPx === null; k--) nowPx = a[k] ? a[k][4] : null;
      if (!s[0] && !s[1] && !s[2] && !n && !s[4]) return;
      tot += n;
      var c = COMP[t] || "";
      if (f && (t + " " + c).toLowerCase().indexOf(f) === -1) return;
      rows.push({t: t, c: c, b: s[0], nn: s[1], r: s[2], tg: s[3], px: s[4], now: nowPx, n: n,
                 up: s[3] && s[4] ? (s[3] / s[4] - 1) * 100 : null, ret: s[4] && nowPx ? (nowPx / s[4] - 1) * 100 : null});
    });
    rows.sort(function (a, b) { return b.n - a.n || (b.b + b.nn + b.r) - (a.b + a.nn + a.r); });
    $("h-table").tBodies[0].innerHTML = rows.map(function (x) {
      return '<tr><td><a class="tk hc-pick" href="#" data-t="' + esc(x.t) + '">' + esc(x.t) + '</a></td><td>' + esc(x.c) +
        '</td><td class="r-bullish">' + x.b + '</td><td class="r-neutral">' + x.nn + '</td><td class="r-bearish">' + x.r +
        '</td><td data-v="' + (x.px || 0) + '">' + money(x.px) + '</td><td data-v="' + (x.tg || 0) + '">' + money(x.tg) +
        '</td><td data-v="' + (x.up === null ? -9999 : x.up) + '" class="' + cls(x.up) + '">' + pct(x.up) +
        '</td><td data-v="' + (x.now || 0) + '">' + money(x.now) +
        '</td><td data-v="' + (x.ret === null ? -9999 : x.ret) + '" class="' + cls(x.ret) + '">' + pct(x.ret) +
        '</td><td>' + x.n + '</td></tr>';
    }).join("");
    $("h-sum").textContent = (L.sum || "").replace("{n}", rows.length).replace("{a}", tot).replace("{s}", r[0]).replace("{e}", r[1]);
  }

  // ---------- chart
  function openStock(t) {
    t = (t || "").trim().toUpperCase(); if (!t) return;
    current = t; stock.value = t;
    $("h-chart").hidden = false; $("hc-title").textContent = t + (COMP[t] ? " · " + COMP[t] : "");
    $("hc-sub").textContent = L.loading; $("hc-svg").innerHTML = ""; $("hc-kpis").innerHTML = "";
    var go = function () { loadCons(function () { if (current === t) drawChart(t, cache[t]); }); };
    if (cache[t] !== undefined) return go();
    fetch(BASE + slug(t) + ".json", {cache: "no-cache"}).then(function (r) { if (!r.ok) throw 0; return r.json(); })
      .then(function (j) { cache[t] = j; go(); })
      .catch(function () { cache[t] = null; go(); });
    if (history.replaceState) history.replaceState(null, "", "#history-" + t);
  }
  function svgEl(tag, attrs, text) {
    var e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function drawChart(t, H) {
    var svg = $("hc-svg"); svg.innerHTML = "";
    if (!H) { $("hc-sub").textContent = L.none; return; }
    var r = range();
    var P = H.p.filter(function (p) { return p[0] >= r[0] && p[0] <= r[1]; });
    var A = H.a.filter(function (a) { return a[0] >= r[0] && a[0] <= r[1]; }).reverse();  // oldest first
    if (!P.length) { $("hc-sub").textContent = L.none; return; }
    $("hc-sub").textContent = P[0][0] + " → " + P[P.length - 1][0];
    $("hc-src").textContent = (L.src || "").replace("{s}", H.src || "");

    // running average target: each firm's latest target within the prior 12 months
    var all = H.a.slice().reverse(), tg = [];
    function avgTarget(d) {
      var cut = new Date(d); cut.setFullYear(cut.getFullYear() - 1); cut = iso(cut);
      var seen = {}, s = 0, n = 0;
      for (var i = all.length - 1; i >= 0; i--) {
        var a = all[i]; if (a[0] > d || a[0] < cut || seen[a[1]]) continue;
        seen[a[1]] = 1; if (a[5]) { s += a[5]; n++; }
      }
      return n ? s / n : null;
    }
    var step = Math.max(1, Math.floor(P.length / 120));
    for (var i = 0; i < P.length; i += step) tg.push([i, avgTarget(P[i][0])]);
    tg.push([P.length - 1, avgTarget(P[P.length - 1][0])]);

    // monthly consensus bars from the table data (or computed here)
    var bars = [];
    if (CONS && CONS.t[t]) {
      CONS.months.forEach(function (m, k) {
        if (m >= r[0].slice(0, 7) && m <= r[1].slice(0, 7) && CONS.t[t][k]) bars.push([m, CONS.t[t][k]]);
      });
    }

    var W = 900, X0 = 56, X1 = W - 12, Y0 = 14, Y1 = 250, B0 = 282, B1 = 360;
    var vals = P.map(function (p) { return p[1]; }).concat(tg.map(function (x) { return x[1]; }).filter(Boolean));
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), pad = (hi - lo) * 0.08 || 1;
    lo = Math.max(0, lo - pad); hi += pad;
    var x = function (i) { return X0 + (X1 - X0) * (P.length === 1 ? 0.5 : i / (P.length - 1)); };
    var y = function (v) { return Y1 - (Y1 - Y0) * (v - lo) / (hi - lo); };
    var idx = {}; P.forEach(function (p, i) { idx[p[0]] = i; });
    function nearest(d) { if (idx[d] !== undefined) return idx[d]; for (var i = 0; i < P.length; i++) if (P[i][0] >= d) return i; return P.length - 1; }

    // grid + axis labels
    for (var g = 0; g <= 4; g++) {
      var v = lo + (hi - lo) * g / 4, yy = y(v);
      svg.appendChild(svgEl("line", {x1: X0, x2: X1, y1: yy, y2: yy, class: "hc-grid"}));
      svg.appendChild(svgEl("text", {x: X0 - 6, y: yy + 4, "text-anchor": "end", class: "hc-ax"}, "$" + (v >= 1000 ? Math.round(v).toLocaleString("en-US") : v.toFixed(v < 10 ? 2 : 0))));
    }
    var ticks = 6;
    for (var k = 0; k <= ticks; k++) {
      var ii = Math.round((P.length - 1) * k / ticks);
      svg.appendChild(svgEl("text", {x: x(ii), y: Y1 + 16, "text-anchor": k === 0 ? "start" : k === ticks ? "end" : "middle", class: "hc-ax"}, P[ii][0].slice(0, 7)));
    }
    // target line
    var tp = tg.filter(function (z) { return z[1]; }).map(function (z) { return x(z[0]).toFixed(1) + "," + y(z[1]).toFixed(1); });
    if (tp.length > 1) svg.appendChild(svgEl("polyline", {points: tp.join(" "), class: "hc-target"}));
    // price line + area
    var pts = P.map(function (p, i) { return x(i).toFixed(1) + "," + y(p[1]).toFixed(1); });
    svg.appendChild(svgEl("polygon", {points: X0 + "," + Y1 + " " + pts.join(" ") + " " + x(P.length - 1).toFixed(1) + "," + Y1, class: "hc-area"}));
    svg.appendChild(svgEl("polyline", {points: pts.join(" "), class: "hc-price"}));
    // analyst markers
    var byDay = {};
    A.forEach(function (a) {
      var i = nearest(a[0]); (byDay[i] = byDay[i] || []).push(a);
      var px = x(i), py = y(P[i][1]), act = a[4];
      if (act === "upgrade") svg.appendChild(svgEl("path", {d: "M" + px + "," + (py - 13) + " l-5,8 h10z", class: "hc-m up"}));
      else if (act === "downgrade") svg.appendChild(svgEl("path", {d: "M" + px + "," + (py + 13) + " l-5,-8 h10z", class: "hc-m down"}));
      else if (act === "initiate") svg.appendChild(svgEl("circle", {cx: px, cy: py, r: 4, class: "hc-m init"}));
      else if (A.length <= 160) svg.appendChild(svgEl("circle", {cx: px, cy: py, r: 2.6, class: "hc-m oth"}));
    });
    // consensus bars
    if (bars.length) {
      var maxN = Math.max.apply(null, bars.map(function (b) { return b[1][0] + b[1][1] + b[1][2]; })) || 1;
      var bw = (X1 - X0) / bars.length;
      svg.appendChild(svgEl("text", {x: X0 - 6, y: B0 + 8, "text-anchor": "end", class: "hc-ax"}, maxN));
      bars.forEach(function (b, k) {
        var h0 = B1, parts = [[b[1][2], "bear"], [b[1][1], "neu"], [b[1][0], "bull"]];
        parts.forEach(function (pt) {
          var h = (B1 - B0) * pt[0] / maxN; if (!h) return;
          var rect = svgEl("rect", {x: X0 + k * bw + bw * 0.12, y: h0 - h, width: Math.max(1, bw * 0.76), height: h, class: "hc-" + pt[1]});
          rect.appendChild(svgEl("title", {}, b[0] + ": " + b[1][0] + " / " + b[1][1] + " / " + b[1][2]));
          svg.appendChild(rect); h0 -= h;
        });
      });
    }
    // hover
    var cross = svgEl("line", {y1: Y0, y2: Y1, class: "hc-cross", visibility: "hidden"}), dot = svgEl("circle", {r: 4, class: "hc-dot", visibility: "hidden"});
    svg.appendChild(cross); svg.appendChild(dot);
    var tip = $("hc-tip");
    function move(ev) {
      var box = svg.getBoundingClientRect(), cx = (ev.touches ? ev.touches[0].clientX : ev.clientX) - box.left;
      var sx = cx * W / box.width, i = Math.round((sx - X0) / (X1 - X0) * (P.length - 1));
      if (i < 0 || i >= P.length) return hide();
      // snap to a nearby analyst action
      for (var d = 0; d <= step * 2; d++) { if (byDay[i + d]) { i += d; break; } if (byDay[i - d]) { i -= d; break; } }
      var px = x(i), py = y(P[i][1]);
      cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", px); dot.setAttribute("cy", py); dot.setAttribute("visibility", "visible");
      var h = "<b>" + P[i][0] + "</b> · " + money(P[i][1]);
      (byDay[i] || []).slice(0, 6).forEach(function (a) {
        h += "<br><span class='" + (a[4] === "upgrade" ? "up" : a[4] === "downgrade" ? "down" : "") + "'>" + esc(a[1]) + "</span>: " +
          esc(a[2] && a[2] !== a[3] ? a[2] + " → " + a[3] : a[3]) + (a[5] ? " · " + money(a[5]) : "");
      });
      tip.innerHTML = h; tip.hidden = false;
      var left = px / W * box.width;
      tip.style.left = Math.min(Math.max(left - 110, 0), box.width - 230) + "px";
      tip.style.top = Math.max(py / 380 * box.height - 20 - tip.offsetHeight, 0) + "px";
    }
    function hide() { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tip.hidden = true; }
    svg.onmousemove = move; svg.ontouchstart = move; svg.ontouchmove = move; svg.onmouseleave = hide;

    // KPIs
    var chg = (P[P.length - 1][1] / P[0][1] - 1) * 100;
    var nu = A.filter(function (a) { return a[4] === "upgrade"; }).length, nd = A.filter(function (a) { return a[4] === "downgrade"; }).length;
    var lastT = tg.length ? tg[tg.length - 1][1] : null;
    $("hc-kpis").innerHTML = '<div><b class="' + cls(chg) + '">' + pct(chg) + '</b><span>' + esc(L.chg) + '</span></div>' +
      '<div><b class="up">' + nu + '</b><span>' + esc(L.up) + '</span></div><div><b class="down">' + nd + '</b><span>' + esc(L.down) + '</span></div>' +
      '<div><b>' + money(lastT) + '</b><span>' + esc(L.tgt) + '</span></div>' +
      '<div><a href="' + slug(t) + '.html">' + esc(L.page) + ' →</a></div>';
    // action list
    $("hc-acts-sum").textContent = (L.acts || "").replace("{n}", A.length);
    $("hc-acts").innerHTML = A.slice().reverse().slice(0, 300).map(function (a) {
      return "<tr><td class='nw'>" + a[0] + "</td><td>" + esc(a[1]) + "</td><td class='" + (a[4] === "upgrade" ? "up" : a[4] === "downgrade" ? "down" : "") + "'>" + esc(a[4]) +
        "</td><td>" + esc(a[2] && a[2] !== a[3] ? a[2] + " → " + a[3] : a[3]) + "</td><td>" + (a[6] && a[5] && a[6] !== a[5] ? money(a[6]) + " → " : "") + money(a[5]) + "</td></tr>";
    }).join("");
  }

  // ---------- tabs and events
  var tabs = document.querySelectorAll(".subtabs button");
  function show(name) {
    tabs.forEach(function (b) { var on = b.dataset.tab === name; b.classList.toggle("on", on); b.setAttribute("aria-selected", on); });
    $("tab-current").hidden = name !== "current";
    $("tab-history").hidden = name !== "history";
    if (name === "history") { drawTable(); if (!/^#history/.test(location.hash)) history.replaceState(null, "", "#history"); }
    else history.replaceState(null, "", location.pathname);
  }
  tabs.forEach(function (b) { b.addEventListener("click", function () { show(b.dataset.tab); }); });
  function redraw() { drawTable(); if (current && cache[current] !== undefined) drawChart(current, cache[current]); }
  [from, to].forEach(function (el) { el.addEventListener("change", function () { quick.value = ""; redraw(); }); });
  q.addEventListener("input", drawTable);
  quick.addEventListener("change", function () {
    var v = quick.value; if (!v) return;
    to.value = iso(new Date()); from.value = ago(v[0] === "m" ? +v.slice(1) : 12 * +v.slice(1)); redraw();
  });
  stock.addEventListener("change", function () { openStock(stock.value); });
  stock.addEventListener("keydown", function (e) { if (e.key === "Enter") openStock(stock.value); });
  $("h-table").addEventListener("click", function (e) {
    var a = e.target.closest(".hc-pick"); if (!a) return;
    e.preventDefault(); openStock(a.dataset.t);
    $("h-chart").scrollIntoView({behavior: "smooth", block: "start"});
  });
  $("hc-close").addEventListener("click", function () { $("h-chart").hidden = true; current = null; stock.value = ""; history.replaceState(null, "", "#history"); });
  var m = location.hash.match(/^#history(?:-(.+))?$/);
  if (m) { show("history"); if (m[1]) openStock(decodeURIComponent(m[1])); }
})();
