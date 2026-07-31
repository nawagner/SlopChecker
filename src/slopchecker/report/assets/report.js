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

  // Place every anchored card at its passage's height, pushing down to avoid
  // overlap. Cards whose quote never landed a highlight stack after the
  // anchored ones — at top 0 they used to pile on the first paragraph,
  // looking connected to text they had nothing to do with.
  // Returns the bottom of the stack so the caller can detect overflow.
  function place() {
    var anchored = [], loose = [];
    annos.forEach(function (a) {
      var m = marksFor(a)[0];
      if (m) {
        anchored.push({ a: a, top: m.getBoundingClientRect().top - layoutEl.getBoundingClientRect().top });
      } else {
        loose.push(a);
      }
    });
    anchored.sort(function (x, y) { return x.top - y.top; });
    var prev = 0;
    function put(a, top) {
      a.style.position = "absolute";
      a.style.left = "0";
      a.style.right = "0";
      a.style.top = top + "px";
      prev = top + a.offsetHeight + 10;
    }
    anchored.forEach(function (it) { put(it.a, Math.max(it.top, prev)); });
    loose.forEach(function (a) { put(a, prev); });
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
