/* AIGP dashboard: expand/collapse rows, lazy-load assessment reports, auto-submit filters. No dependencies. */
(function () {
  function detailOf(row) { return row.nextElementSibling; }

  function load(row, d) {
    var url = row.dataset.detailUrl;
    if (!url || d.dataset.loaded) return;
    d.dataset.loaded = "1";
    fetch(url).then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) { d.querySelector(".detail-body").innerHTML = html; })
      .catch(function () { delete d.dataset.loaded; d.querySelector(".detail-body").textContent = "Could not load the report. Collapse and expand to retry."; });
  }

  function toggle(row, open) {
    var d = detailOf(row);
    if (!d) return;
    if (open === undefined) open = d.hidden;
    d.hidden = !open;
    row.classList.toggle("open", open);
    var b = row.querySelector(".chev-btn");
    if (b) b.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) load(row, d);
  }

  document.addEventListener("click", function (e) {
    if (e.target.closest("a, input, select, textarea, label")) return;
    var row = e.target.closest("tr.row");
    if (row) { toggle(row); return; }
    if (e.target.closest("[data-expand-all]")) document.querySelectorAll("tr.row").forEach(function (r) { toggle(r, true); });
    if (e.target.closest("[data-collapse-all]")) document.querySelectorAll("tr.row").forEach(function (r) { toggle(r, false); });
  });

  document.addEventListener("change", function (e) {
    if (e.target.matches("select[data-autosubmit]")) e.target.form.submit();
  });

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("tr.row.open").forEach(function (r) { toggle(r, true); });
    var f = document.querySelector("tr.row.focus");
    if (f) f.scrollIntoView({ block: "center" });
  });
})();
