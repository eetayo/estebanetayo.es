/* estebanetayo.es · interacciones: tema, cabecera, sonda topográfica, línea de tiempo,
   mapa de proyectos, filtros del blog, progreso de lectura, apariciones y visor. */
(function () {
  "use strict";
  var root = document.documentElement;
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var $ = function (s, el) { return (el || document).querySelector(s); };
  var $$ = function (s, el) { return Array.prototype.slice.call((el || document).querySelectorAll(s)); };
  var setParam = function (key, value) {
    try {
      var url = new URL(location.href);
      if (value) url.searchParams.set(key, value); else url.searchParams.delete(key);
      history.replaceState(null, "", url);
    } catch (_) {}
  };

  /* ---------- Tema claro / oscuro ---------- */
  var toggle = $(".theme-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var dark = root.dataset.theme
        ? root.dataset.theme === "dark"
        : window.matchMedia("(prefers-color-scheme: dark)").matches;
      root.dataset.theme = dark ? "light" : "dark";
      try { localStorage.setItem("tema", root.dataset.theme); } catch (_) {}
    });
  }

  /* ---------- Cabecera: se esconde al bajar en móvil ---------- */
  var mast = $(".mast");
  if (mast && window.matchMedia("(max-width: 620px)").matches) {
    var lastY = window.scrollY;
    window.addEventListener("scroll", function () {
      var y = window.scrollY;
      mast.classList.toggle("is-hidden", y > lastY && y > 120);
      lastY = y;
    }, { passive: true });
  }

  /* ---------- Atajo «/» para buscar ---------- */
  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "/" || ev.metaKey || ev.ctrlKey || ev.altKey) return;
    var t = ev.target;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    var q = $("#q");
    ev.preventDefault();
    if (q) { q.focus(); q.select(); }
    else {
      var link = $(".icon-btn");
      if (link) location.href = link.href;
    }
  });

  /* ---------- Sonda topográfica en la portada ----------
     Lee la curva de nivel bajo el puntero y muestra coordenadas y cota aproximadas. */
  var hero = $("[data-probe]");
  var heroSvg = hero && $("svg.topo", hero);
  if (hero && heroSvg && window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    var probe = $(".probe", hero);
    var px = $(".probe-x", hero), py = $(".probe-y", hero), read = $(".probe-read", hero);
    var paths = $$("path", heroSvg);
    var SUMMITS = [2314, 650];      /* Moncayo y Bardenas, en metros */
    var BASE = 270;                 /* la Ribera, en metros */
    var hot = null, raf = 0, last = null;
    var dms = function (v, pos, neg) {
      var a = Math.abs(v), d = Math.floor(a), m = Math.floor((a - d) * 60), s = Math.round(((a - d) * 60 - m) * 60);
      if (s === 60) { s = 0; m += 1; }
      return d + "°" + String(m).padStart(2, "0") + "′" + String(s).padStart(2, "0") + "″" + (v >= 0 ? pos : neg);
    };
    var update = function () {
      raf = 0;
      if (!last) return;
      var rect = hero.getBoundingClientRect();
      var fx = (last.clientX - rect.left) / rect.width;
      var fy = (last.clientY - rect.top) / rect.height;
      px.textContent = dms(42.12 - fy * 0.42, "N", "S");
      py.textContent = dms(-2.02 + fx * 0.62, "E", "W");
      probe.style.transform = "translate(" + (last.clientX - rect.left) + "px," + (last.clientY - rect.top) + "px)";
      var pt = heroSvg.createSVGPoint();
      pt.x = last.clientX; pt.y = last.clientY;
      var ctm = heroSvg.getScreenCTM();
      if (!ctm) return;
      var local = pt.matrixTransform(ctm.inverse());
      var best = null, bestElev = BASE;
      paths.forEach(function (p) {
        if (!p.isPointInFill || !p.isPointInFill(local)) return;
        var n = +p.dataset.n, l = +p.dataset.l, summit = SUMMITS[+p.dataset.p] || 900;
        var elev = summit - (summit - BASE) * l / (n + 1);
        if (elev > bestElev) { bestElev = elev; best = p; }
      });
      if (hot !== best) {
        if (hot) hot.classList.remove("hot");
        if (best) best.classList.add("hot");
        hot = best;
      }
      read.textContent = "cota " + Math.round(bestElev / 10) * 10 + " m";
      if (!reduced) heroSvg.style.transform = "translate(" + (fx - 0.5) * -14 + "px," + (fy - 0.5) * -10 + "px)";
    };
    hero.addEventListener("pointermove", function (ev) {
      last = ev;
      hero.classList.add("probing");
      if (!raf) raf = requestAnimationFrame(update);
    });
    hero.addEventListener("pointerleave", function () {
      hero.classList.remove("probing");
      if (hot) { hot.classList.remove("hot"); hot = null; }
      heroSvg.style.transform = "";
    });
  }

  /* ---------- Línea de tiempo con pestañas ---------- */
  $$(".tl").forEach(function (tl) {
    var tabs = $$('[role="tab"]', tl);
    var select = function (tab, focus) {
      tabs.forEach(function (t) {
        var on = t === tab;
        t.setAttribute("aria-selected", String(on));
        t.tabIndex = on ? 0 : -1;
        var panel = document.getElementById(t.getAttribute("aria-controls"));
        if (panel) panel.hidden = !on;
      });
      if (focus) tab.focus();
    };
    tabs.forEach(function (tab, i) {
      tab.addEventListener("click", function (ev) {
        if (tab.getAttribute("aria-selected") !== "true") { ev.preventDefault(); select(tab); }
      });
      tab.addEventListener("mouseenter", function () { select(tab); });
      tab.addEventListener("keydown", function (ev) {
        var next = null;
        if (ev.key === "ArrowRight" || ev.key === "ArrowDown") next = tabs[(i + 1) % tabs.length];
        if (ev.key === "ArrowLeft" || ev.key === "ArrowUp") next = tabs[(i - 1 + tabs.length) % tabs.length];
        if (ev.key === "Home") next = tabs[0];
        if (ev.key === "End") next = tabs[tabs.length - 1];
        if (next) { ev.preventDefault(); select(next, true); }
      });
    });
  });

  /* ---------- Proyectos: filtro por estado y vista lista / mapa ---------- */
  var stateChips = $$("[data-filter]");
  if (stateChips.length || $$("[data-view]").length) {
    var items = $$("#proyectos .prow, .summit");
    var applyState = function (f) {
      stateChips.forEach(function (c) { c.setAttribute("aria-pressed", String(c.dataset.filter === f)); });
      items.forEach(function (r) {
        var live = r.dataset.state === "activo" || r.dataset.state === "pausa";
        r.hidden = f === "live" ? !live : f === "past" ? live : false;
      });
      setParam("estado", f === "all" ? "" : f);
    };
    stateChips.forEach(function (c) { c.addEventListener("click", function () { applyState(c.dataset.filter); }); });
    var viewChips = $$("[data-view]");
    var list = $("#proyectos"), map = $("#mapa");
    var applyView = function (v) {
      viewChips.forEach(function (c) { c.setAttribute("aria-pressed", String(c.dataset.view === v)); });
      if (list) list.hidden = v === "mapa";
      if (map) map.hidden = v !== "mapa";
      setParam("vista", v === "mapa" ? "mapa" : "");
    };
    viewChips.forEach(function (c) { c.addEventListener("click", function () { applyView(c.dataset.view); }); });
    var params = new URLSearchParams(location.search);
    if (params.get("estado") === "live" || params.get("estado") === "past") applyState(params.get("estado"));
    if (params.get("vista") === "mapa" || location.hash === "#mapa") applyView("mapa");
  }

  /* ---------- Blog: búsqueda + año + tema, todo combinado ---------- */
  var input = $("#q");
  var strata = $$(".stratum");
  if (input && strata.length) {
    var norm = function (s) {
      return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
    };
    var count = $(".result-count"), empty = $(".empty");
    var bar = $(".filters-bar"), barLabel = $(".filters-label"), clear = $(".filters-bar .clear");
    var yearBtns = $$(".histo [data-year]"), topicChips = $$("[data-topic]");
    var state = { q: "", year: "", topic: "" };
    var index = null;
    var load = function () {
      if (index) return Promise.resolve(index);
      return fetch("indice.json").then(function (r) { return r.json(); }).then(function (data) {
        index = {};
        data.forEach(function (d) { index[d.u.replace(/^\/|\/$/g, "")] = norm(d.x); });
        return index;
      }).catch(function () { index = {}; return index; });
    };
    var titles = $$(".erow .etitle");
    titles.forEach(function (t) { t.dataset.raw = t.textContent; });
    var esc = function (s) { return s.replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };
    var highlight = function (el, terms) {
      var raw = el.dataset.raw;
      if (!terms.length) { el.textContent = raw; return; }
      var plain = norm(raw), marks = [];
      terms.forEach(function (t) {
        var i = plain.indexOf(t);
        while (i !== -1) { marks.push([i, i + t.length]); i = plain.indexOf(t, i + t.length); }
      });
      if (!marks.length) { el.textContent = raw; return; }
      marks.sort(function (a, b) { return a[0] - b[0]; });
      var out = "", pos = 0;
      marks.forEach(function (m) {
        if (m[0] < pos) return;
        out += esc(raw.slice(pos, m[0])) + "<mark>" + esc(raw.slice(m[0], m[1])) + "</mark>";
        pos = m[1];
      });
      el.innerHTML = out + esc(raw.slice(pos));
    };
    var topicName = function (slug) {
      var c = topicChips.filter(function (x) { return x.dataset.topic === slug; })[0];
      return c ? c.firstChild.textContent.trim() : slug;
    };
    var run = function () {
      var terms = norm(state.q).split(/\s+/).filter(Boolean);
      yearBtns.forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.year === state.year)); });
      topicChips.forEach(function (c) { c.setAttribute("aria-pressed", String(c.dataset.topic === state.topic)); });
      setParam("q", state.q.trim());
      setParam("año", state.year);
      setParam("tema", state.topic);
      (terms.length ? load() : Promise.resolve(index || {})).then(function (idx) {
        var shown = 0;
        strata.forEach(function (s) {
          var any = false;
          $$(".erow", s).forEach(function (row) {
            var hay = idx[row.dataset.id] || norm(row.textContent);
            var ok = terms.every(function (t) { return hay.indexOf(t) !== -1; })
              && (!state.year || row.dataset.year === state.year)
              && (!state.topic || (" " + row.dataset.topics + " ").indexOf(" " + state.topic + " ") !== -1);
            row.hidden = !ok;
            if (ok) { any = true; shown += 1; highlight($(".etitle", row), terms); }
          });
          s.hidden = !any;
        });
        var active = terms.length || state.year || state.topic;
        if (count) count.textContent = active ? shown + (shown === 1 ? " entrada" : " entradas") : "";
        if (empty) empty.hidden = shown !== 0;
        if (bar) {
          var parts = [];
          if (state.year) parts.push("Año " + state.year);
          if (state.topic) parts.push("Tema: " + topicName(state.topic));
          if (terms.length) parts.push("«" + state.q.trim() + "»");
          barLabel.textContent = parts.join(" · ");
          bar.hidden = !active;
        }
      });
    };
    yearBtns.forEach(function (b) {
      b.addEventListener("click", function () { state.year = state.year === b.dataset.year ? "" : b.dataset.year; run(); });
    });
    topicChips.forEach(function (c) {
      c.addEventListener("click", function (ev) {
        ev.preventDefault();
        state.topic = state.topic === c.dataset.topic ? "" : c.dataset.topic;
        run();
      });
    });
    if (clear) clear.addEventListener("click", function () { state = { q: "", year: "", topic: "" }; input.value = ""; run(); input.focus(); });
    var params0 = new URLSearchParams(location.search);
    state.q = params0.get("q") || "";
    state.year = params0.get("año") || "";
    state.topic = params0.get("tema") || "";
    input.value = state.q;
    if (state.q || state.year || state.topic) run();
    if (location.hash === "#buscar") input.focus();
    var timer;
    input.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () { state.q = input.value; run(); }, 120);
    });
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") { input.value = ""; state.q = ""; run(); }
    });
    input.form.addEventListener("submit", function (ev) { ev.preventDefault(); state.q = input.value; run(); });
  }

  /* ---------- Barra de progreso de lectura en las entradas ---------- */
  var prose = $(".post .prose");
  if (prose && document.body.classList.contains("is-post")) {
    var progress = document.createElement("div");
    progress.className = "progress";
    progress.setAttribute("aria-hidden", "true");
    document.body.appendChild(progress);
    var onScroll = function () {
      var r = prose.getBoundingClientRect();
      var total = r.height - window.innerHeight * 0.6;
      var done = Math.min(1, Math.max(0, (-r.top + window.innerHeight * 0.3) / Math.max(total, 1)));
      progress.style.transform = "scaleX(" + done + ")";
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  /* ---------- Aparición suave de filas al hacer scroll (solo lo que está por debajo) ---------- */
  if (!reduced && "IntersectionObserver" in window) {
    var targets = $$(".prow, .pcard, .picks li, .stratum, .topic-list li, .miles li");
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
      });
    }, { rootMargin: "0px 0px -8% 0px" });
    targets.forEach(function (el, i) {
      if (el.getBoundingClientRect().top > window.innerHeight) {
        el.classList.add("reveal");
        el.style.transitionDelay = (i % 4) * 50 + "ms";
        io.observe(el);
      }
    });
  }

  /* ---------- Vídeo: se carga el reproductor sin cookies solo al pulsar ---------- */
  var ownSite = /(^|\.)estebanetayo\.es$|\.pages\.dev$|^localhost$|^127\.0\.0\.1$/.test(location.hostname);
  if (ownSite) {
    $$(".video-card[data-video]").forEach(function (card) {
      card.addEventListener("click", function (ev) {
        ev.preventDefault();
        var frame = document.createElement("div");
        frame.className = "video-frame";
        var iframe = document.createElement("iframe");
        iframe.src = "https://www.youtube-nocookie.com/embed/" + encodeURIComponent(card.dataset.video) + "?autoplay=1&rel=0";
        iframe.title = (card.querySelector("strong") || {}).textContent || "Vídeo";
        iframe.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
        iframe.allowFullscreen = true;
        frame.appendChild(iframe);
        card.replaceWith(frame);
      });
    });
  }

  /* ---------- Visor de imágenes ---------- */
  var links = $$(".prose a").filter(function (a) {
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
  var img = $("img", dlg), cap = $(".cap", dlg), cur = 0;
  var show = function (i) {
    cur = (i + links.length) % links.length;
    var a = links[cur], thumb = $("img", a);
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
