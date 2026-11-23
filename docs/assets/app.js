(function () {
  var T = window.T || function (s) { return s; };
  // Language menu: close when clicking elsewhere or pressing Escape
  var lm = document.querySelector("details.langs");
  if (lm) {
    document.addEventListener("click", function (e) { if (!e.target.closest("details.langs")) lm.open = false; });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") lm.open = false; });
  }

  // Global search box
  var q = document.getElementById("q"), box = document.getElementById("qres"), idx = null;
  function load(cb) {
    if (idx) return cb();
    fetch((window.AROOT || window.ROOT) + "assets/search.json").then(function (r) { return r.json(); })
      .then(function (j) { idx = j; cb(); }).catch(function () { idx = []; });
  }
  if (q) {
    q.addEventListener("input", function () {
      var v = q.value.trim().toLowerCase();
      if (!v) { box.hidden = true; return; }
      load(function () {
        var hits = idx.filter(function (x) { return x.n.toLowerCase().indexOf(v) !== -1; }).slice(0, 12);
        box.innerHTML = hits.map(function (h) {
          return '<a href="' + window.ROOT + h.u + '">' + h.n.replace(/</g, "&lt;") +
            "<small>" + T(h.t === "a" ? "analyst" : "stock") + "</small></a>";
        }).join("") || '<a>' + T("No matches") + '</a>';
        box.hidden = false;
      });
    });
    document.addEventListener("click", function (e) { if (!e.target.closest(".search")) box.hidden = true; });
  }

  // Table filters
  document.querySelectorAll(".filters").forEach(function (f) {
    var table = f.nextElementSibling && f.nextElementSibling.querySelector("table");
    if (!table) return;
    var tf = f.querySelector(".tf"), af = f.querySelector(".af");
    function apply() {
      var t = tf ? tf.value.toLowerCase() : "", a = af ? af.value : "";
      table.querySelectorAll("tbody tr").forEach(function (tr) {
        var ok = (!t || tr.textContent.toLowerCase().indexOf(t) !== -1) && (!a || tr.dataset.action === a);
        tr.style.display = ok ? "" : "none";
      });
    }
    if (tf) tf.addEventListener("input", apply);
    if (af) af.addEventListener("change", apply);
  });

  // Sortable tables
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th").forEach(function (th, i) {
      var asc = false;
      th.addEventListener("click", function () {
        asc = !asc;
        var rows = Array.prototype.slice.call(table.tBodies[0].rows);
        var num = th.hasAttribute("data-num");
        rows.sort(function (a, b) {
          var x = a.cells[i], y = b.cells[i];
          var vx = x.dataset.v || x.textContent.trim(), vy = y.dataset.v || y.textContent.trim();
          if (num) { vx = parseFloat(String(vx).replace(/[^0-9.\-]/g, "")) || 0; vy = parseFloat(String(vy).replace(/[^0-9.\-]/g, "")) || 0; }
          return (vx > vy ? 1 : vx < vy ? -1 : 0) * (asc ? 1 : -1);
        });
        rows.forEach(function (r) { table.tBodies[0].appendChild(r); });
      });
    });
  });
})();
