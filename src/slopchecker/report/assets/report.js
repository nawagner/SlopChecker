(function () {
  var rail = document.querySelector(".rail");
  var layoutEl = document.querySelector(".layout");
  var docEl = document.querySelector(".doc");
  var annos = Array.prototype.slice.call(document.querySelectorAll(".anno"));
  function wide() { return window.matchMedia("(min-width: 901px)").matches; }

  // A finding may render as several <mark> segments when spans overlap or
  // cross a paragraph break; data-anno is a space-separated id list.
  function marksFor(a) {
    var id = a.id.replace("anno-", "");
    return Array.prototype.slice.call(
      document.querySelectorAll('mark[data-anno~="' + id + '"]'));
  }

  // Place every card at its passage's height, pushing down to avoid overlap.
  // Returns the bottom of the stack so the caller can detect overflow.
  function place() {
    var items = annos.map(function (a) {
      var m = marksFor(a)[0];
      return { a: a, top: m ? m.getBoundingClientRect().top - layoutEl.getBoundingClientRect().top : 0 };
    }).sort(function (x, y) { return x.top - y.top; });
    var prev = 0;
    items.forEach(function (it) {
      it.a.style.position = "absolute";
      it.a.style.left = "0";
      it.a.style.right = "0";
      var t = Math.max(it.top, prev);
      it.a.style.top = t + "px";
      prev = t + it.a.offsetHeight + 10;
    });
    return prev;
  }

  function layout() {
    if (!wide()) {
      rail.classList.remove("condensed");
      annos.forEach(function (a) { a.style.position = "static"; });
      return;
    }
    rail.classList.remove("condensed");
    var bottom = place();
    if (bottom > docEl.offsetHeight + 60) {  // too many at once: condense to one-liners
      rail.classList.add("condensed");
      place();
    }
  }

  function toggle(a) {
    a.classList.toggle("expanded");
    marksFor(a).forEach(function (m) {
      m.classList.toggle("active", a.classList.contains("expanded") && rail.classList.contains("condensed"));
    });
    var wasCondensed = rail.classList.contains("condensed");
    layout();
    if (wasCondensed && a.classList.contains("expanded")) {
      rail.classList.add("condensed");  // keep condensed mode sticky once triggered
      place();
    }
  }

  annos.forEach(function (a) {
    a.addEventListener("click", function () { toggle(a); });
  });

  // A mark click toggles every card it belongs to (overlapping spans).
  Array.prototype.slice.call(document.querySelectorAll("mark[data-anno]")).forEach(function (m) {
    m.addEventListener("click", function () {
      (m.getAttribute("data-anno") || "").split(/\s+/).forEach(function (id) {
        var a = document.getElementById("anno-" + id);
        if (!a) return;
        toggle(a);
        if (!wide()) a.scrollIntoView({ block: "nearest", behavior: "smooth" });
      });
    });
  });

  window.addEventListener("resize", layout);
  window.addEventListener("load", layout);
  layout();
})();
