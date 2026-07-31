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

  // Place every anchored card at its passage's height. Cards whose quote
  // never landed a highlight stack after the anchored ones — at top 0 they
  // used to pile on the first paragraph, looking connected to text they had
  // nothing to do with.
  // Returns the bottom of the stack so the caller can detect overflow.
  var GAP = 10;
  function place() {
    var anchored = [], loose = [];
    annos.forEach(function (a) {
      var m = marksFor(a)[0];
      if (m) {
        anchored.push({ a: a, ideal: m.getBoundingClientRect().top - layoutEl.getBoundingClientRect().top });
      } else {
        loose.push(a);
      }
    });
    anchored.sort(function (x, y) { return x.ideal - y.ideal; });

    // Down pass: no overlaps, every card at or below its passage.
    var prev = 0;
    anchored.forEach(function (it) {
      it.h = it.a.offsetHeight;
      it.p = Math.max(it.ideal, prev);
      prev = it.p + it.h + GAP;
    });

    // Balance pass: a dense run (nine metadata cards anchored in one
    // references section) pushes its tail far below the passages it refers
    // to. Shift each contiguous cluster of touching cards up by its mean
    // displacement — bounded by the cluster above — so the run straddles
    // its passages instead of accumulating downward.
    var bound = 0, i = 0;
    while (i < anchored.length) {
      var j = i;
      while (j + 1 < anchored.length &&
             anchored[j + 1].p - (anchored[j].p + anchored[j].h + GAP) < 0.5) j++;
      var disp = 0;
      for (var k = i; k <= j; k++) disp += anchored[k].p - anchored[k].ideal;
      var shift = Math.max(0, Math.min(disp / (j - i + 1), anchored[i].p - bound));
      for (k = i; k <= j; k++) anchored[k].p -= shift;
      bound = anchored[j].p + anchored[j].h + GAP;
      i = j + 1;
    }

    var bottom = 0;
    function put(a, top) {
      a.style.position = "absolute";
      a.style.left = "0";
      a.style.right = "0";
      a.style.top = top + "px";
      bottom = Math.max(bottom, top + a.offsetHeight + GAP);
    }
    anchored.forEach(function (it) { put(it.a, it.p); });
    loose.forEach(function (a) { put(a, bottom); });
    return bottom;
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
    // Hovering a card lights its passage — the "what does this refer to?"
    // answer without a click.
    a.addEventListener("mouseenter", function () {
      marksFor(a).forEach(function (m) { m.classList.add("active"); });
    });
    a.addEventListener("mouseleave", function () {
      if (a.classList.contains("expanded") && rail.classList.contains("condensed")) return;
      marksFor(a).forEach(function (m) { m.classList.remove("active"); });
    });
  });

  function cardsFor(m) {
    return (m.getAttribute("data-anno") || "").split(/\s+/).map(function (id) {
      return document.getElementById("anno-" + id);
    }).filter(Boolean);
  }

  Array.prototype.slice.call(document.querySelectorAll("mark[data-anno]")).forEach(function (m) {
    // A mark click toggles every card it belongs to (overlapping spans).
    m.addEventListener("click", function () {
      cardsFor(m).forEach(function (a) {
        toggle(a);
        if (!wide()) a.scrollIntoView({ block: "nearest", behavior: "smooth" });
      });
    });
    // Hovering a highlight outlines its card(s) — the other direction.
    m.addEventListener("mouseenter", function () {
      cardsFor(m).forEach(function (a) { a.classList.add("linked"); });
    });
    m.addEventListener("mouseleave", function () {
      cardsFor(m).forEach(function (a) { a.classList.remove("linked"); });
    });
  });

  window.addEventListener("resize", layout);
  window.addEventListener("load", layout);
  layout();
})();
