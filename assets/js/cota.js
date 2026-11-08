/* estebanetayo.es · interacciones mínimas: tema, cabecera, filtros, búsqueda y visor. */
(function () {
  "use strict";
  var root = document.documentElement;

  /* Tema claro / oscuro, recordado si el navegador deja guardar. */
  var toggle = document.querySelector(".theme-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var dark = root.dataset.theme
        ? root.dataset.theme === "dark"
        : window.matchMedia("(prefers-color-scheme: dark)").matches;
      root.dataset.theme = dark ? "light" : "dark";
      try { localStorage.setItem("tema", root.dataset.theme); } catch (_) {}
    });
  }

  /* La cabecera se esconde al bajar y vuelve al subir (solo en móvil). */
  var mast = document.querySelector(".mast");
  if (mast && window.matchMedia("(max-width: 620px)").matches) {
    var last = window.scrollY;
    window.addEventListener("scroll", function () {
      var y = window.scrollY;
      mast.classList.toggle("is-hidden", y > last && y > 120);
      last = y;
    }, { passive: true });
  }

  /* Filtro de proyectos por estado. */
  var chips = document.querySelectorAll("[data-filter]");
  if (chips.length) {
    var rows = document.querySelectorAll("#proyectos .prow");
    var apply = function (f) {
      chips.forEach(function (c) { c.setAttribute("aria-pressed", String(c.dataset.filter === f)); });
      rows.forEach(function (r) {
        var live = r.dataset.state === "activo" || r.dataset.state === "pausa";
        r.hidden = f === "live" ? !live : f === "past" ? live : false;
      });
      var url = new URL(location.href);
      if (f === "all") url.searchParams.delete("estado"); else url.searchParams.set("estado", f);
      history.replaceState(null, "", url);
    };
    chips.forEach(function (c) { c.addEventListener("click", function () { apply(c.dataset.filter); }); });
    var initial = new URLSearchParams(location.search).get("estado");
    if (initial === "live" || initial === "past") apply(initial);
  }

  /* Búsqueda en el blog: título, texto completo, temas y etiquetas; sin acentos. */
  var input = document.querySelector("#q");
  var strata = document.querySelectorAll(".stratum");
  if (input && strata.length) {
    var norm = function (s) {
      return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
    };
    var count = document.querySelector(".result-count");
    var empty = document.querySelector(".empty");
    var index = null;
    var load = function () {
      if (index) return Promise.resolve(index);
      return fetch("indice.json").then(function (r) { return r.json(); }).then(function (data) {
        index = {};
        data.forEach(function (d) { index[d.u.replace(/^\/|\/$/g, "")] = norm(d.x); });
        return index;
      }).catch(function () { index = {}; return index; });
    };
    var run = function (q) {
      var terms = norm(q).split(/\s+/).filter(Boolean);
      load().then(function (idx) {
        var shown = 0;
        strata.forEach(function (s) {
          var any = false;
          s.querySelectorAll(".erow").forEach(function (row) {
            var hay = idx[row.dataset.id] || norm(row.textContent);
            var ok = terms.every(function (t) { return hay.indexOf(t) !== -1; });
            row.hidden = !ok;
            if (ok) { any = true; shown += 1; }
          });
          s.hidden = !any;
        });
        if (count) count.textContent = terms.length ? shown + (shown === 1 ? " entrada encontrada" : " entradas encontradas") : "";
        if (empty) empty.hidden = shown !== 0;
      });
    };
    var start = new URLSearchParams(location.search).get("q");
    if (start) { input.value = start; run(start); }
    if (location.hash === "#buscar") input.focus({ preventScroll: false });
    var timer;
    input.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        var v = input.value.trim();
        var url = new URL(location.href);
        if (v) url.searchParams.set("q", v); else url.searchParams.delete("q");
        history.replaceState(null, "", url);
        run(v);
      }, 120);
    });
    input.form.addEventListener("submit", function (ev) { ev.preventDefault(); run(input.value); });
  }

  /* Visor de imágenes con botón de cierre, pie y navegación. */
  var links = Array.prototype.filter.call(document.querySelectorAll(".prose a"), function (a) {
    return /\.(png|jpe?g|gif|webp)(\?.*)?$/i.test(a.getAttribute("href") || "");
  });
  if (!links.length || !window.HTMLDialogElement) return;
  var dlg = document.createElement("dialog");
  dlg.className = "lightbox";
  dlg.setAttribute("aria-label", "Imagen ampliada");
  dlg.innerHTML = '<img alt=""><p><span class="cap"></span><span>' +
    '<button type="button" data-step="-1" aria-label="Imagen anterior">←</button> ' +
    '<button type="button" data-step="1" aria-label="Imagen siguiente">→</button> ' +
    '<button type="button" data-close>Cerrar</button></span></p>';
  document.body.appendChild(dlg);
  var img = dlg.querySelector("img");
  var cap = dlg.querySelector(".cap");
  var cur = 0;
  var show = function (i) {
    cur = (i + links.length) % links.length;
    var a = links[cur];
    var thumb = a.querySelector("img");
    img.src = a.href;
    img.alt = thumb ? thumb.alt : "";
    cap.textContent = (cur + 1) + " / " + links.length + (thumb && thumb.alt ? " · " + thumb.alt : "");
  };
  links.forEach(function (a, i) {
    a.addEventListener("click", function (ev) { ev.preventDefault(); show(i); dlg.showModal(); });
  });
  dlg.addEventListener("click", function (ev) {
    var t = ev.target;
    if (t.dataset.step) show(cur + Number(t.dataset.step));
    else if (t === dlg || t.hasAttribute("data-close")) dlg.close();
  });
  dlg.addEventListener("keydown", function (ev) {
    if (ev.key === "ArrowRight") show(cur + 1);
    if (ev.key === "ArrowLeft") show(cur - 1);
  });
})();
