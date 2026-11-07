(function () {
  var input = document.querySelector(".finder input");
  var entries = Array.prototype.slice.call(document.querySelectorAll(".entry"));
  var years = Array.prototype.slice.call(document.querySelectorAll(".year"));
  var empty = document.querySelector(".empty");
  var count = document.querySelector(".result-count");

  function norm(value) {
    return (value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase();
  }

  function apply(query) {
    if (!entries.length) return;
    var q = norm(query);
    var shown = 0;
    entries.forEach(function (el) {
      var hay = norm(el.getAttribute("data-search") || "");
      var ok = !q || hay.indexOf(q) !== -1;
      el.hidden = !ok;
      if (ok) shown += 1;
    });
    years.forEach(function (year) {
      var node = year.nextElementSibling;
      var any = false;
      while (node && !node.classList.contains("year")) {
        if (node.classList.contains("entry") && !node.hidden) any = true;
        node = node.nextElementSibling;
      }
      year.hidden = !any;
    });
    if (empty) empty.hidden = shown !== 0;
    if (count) {
      count.textContent = q ? shown + (shown === 1 ? " entrada" : " entradas") : "";
    }
  }

  if (input && entries.length) {
    var params = new URLSearchParams(window.location.search);
    var initial = params.get("q") || "";
    if (initial) {
      input.value = initial;
      apply(initial);
    }
    input.addEventListener("input", function () {
      var value = input.value;
      var url = new URL(window.location.href);
      if (value.trim()) url.searchParams.set("q", value.trim());
      else url.searchParams.delete("q");
      window.history.replaceState(null, "", url);
      apply(value);
    });
    var form = input.form;
    if (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        apply(input.value);
      });
    }
  }

  var dialog = document.getElementById("lightbox");
  var dialogImg = dialog ? dialog.querySelector("img") : null;
  if (!dialog || !dialogImg) return;

  document.querySelectorAll(".prose a").forEach(function (link) {
    var href = link.getAttribute("href") || "";
    if (!/\.(png|jpe?g|gif|webp)(\?.*)?$/i.test(href)) return;
    link.addEventListener("click", function (event) {
      event.preventDefault();
      var image = link.querySelector("img");
      dialogImg.src = link.href;
      dialogImg.alt = image ? image.alt : "";
      dialog.showModal();
    });
  });

  dialog.addEventListener("click", function () {
    dialog.close();
  });
})();
