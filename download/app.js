// Small extras only; every download link and every word on the page works without this script.
(function () {
  // The page's head already marked the visitor's system and whether the page may move (before the first picture).
  var root = document.documentElement;
  var os = root.getAttribute("data-os") || "";
  root.classList.add("js");
  // Whatever was already on screen when this script ran stays as it is: no headline typed over a headline.
  var painted = !!(window.performance && performance.getEntriesByType &&
    performance.getEntriesByType("paint").some(function (e) { return e.name === "first-contentful-paint"; }));

  document.addEventListener("DOMContentLoaded", function () {
    // Put the visitor's own system first and give it the main colour (the page's styles already show it first).
    var mine = os && document.querySelector('.get-btn[data-os="' + os + '"]');
    if (mine) {
      mine.classList.add("mine");
      mine.parentNode.insertBefore(mine, mine.parentNode.firstChild);
    }
    if (navigator.clipboard) {
      document.querySelectorAll("button[data-copy]").forEach(function (button) {
        button.hidden = false;
        button.addEventListener("click", function () {
          navigator.clipboard.writeText(button.dataset.copy).then(function () {
            button.textContent = "Copied";
            setTimeout(function () { button.textContent = "Copy"; }, 1600);
          });
        });
      });
    }
    header();
    ways();
    questions();
    if (!root.classList.contains("motion")) return;
    if (!painted) typeHeadline();
    screens();
    studioRise();
  });

  // The header is see-through over the sky until the page scrolls, and marks the section being read.
  function header() {
    var top = document.querySelector(".top");
    if (!top) return;
    var onScroll = function () { top.classList.toggle("scrolled", window.scrollY > 12); };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    if (!("IntersectionObserver" in window)) return;
    var links = {};
    top.querySelectorAll('nav a[href^="#"]:not(.nav-get)').forEach(function (a) { links[a.hash.slice(1)] = a; });
    var current = null;
    var seen = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        var a = links[e.target.id];
        if (!a) return;
        if (e.isIntersecting) {
          if (current) current.classList.remove("here");
          current = a;
          a.classList.add("here");
        } else if (current === a) {
          a.classList.remove("here");
          current = null;
        }
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    Object.keys(links).forEach(function (id) {
      var el = document.getElementById(id);
      if (el) seen.observe(el);
    });
  }

  // The headline types itself out once, like the ship's console. Readers and search get the whole sentence at once.
  function typeHeadline() {
    var h1 = document.querySelector(".hero h1");
    if (!h1 || h1.children.length) return;
    var text = h1.textContent;
    h1.setAttribute("aria-label", text);
    h1.textContent = "";
    var words = text.split(/(\s+)/), at = 0, step = Math.min(22, 1100 / text.length);
    words.forEach(function (w) {
      if (/^\s+$/.test(w)) { h1.appendChild(document.createTextNode(w)); at += 1; return; }
      var word = document.createElement("span");
      word.style.whiteSpace = "nowrap";
      word.setAttribute("aria-hidden", "true");
      for (var i = 0; i < w.length; i++) {
        var ch = document.createElement("span");
        ch.className = "ch";
        ch.textContent = w[i];
        ch.style.animationDelay = (250 + at * step).toFixed(0) + "ms";
        ch.style.setProperty("--at", (250 + at * step).toFixed(0) + "ms");
        word.appendChild(ch);
        at += 1;
      }
      h1.appendChild(word);
    });
    h1.style.setProperty("--step", step.toFixed(0) + "ms");
    var caret = document.createElement("span");
    caret.className = "caret";
    caret.setAttribute("aria-hidden", "true");
    h1.appendChild(caret);
    setTimeout(function () { caret.classList.add("done"); h1.classList.add("typed"); }, 300 + at * step);
  }

  // Four ways to make something: tabs beside one big screen, instead of four screens one after another.
  function ways() {
    var box = document.querySelector(".ways");
    if (!box) return;
    var panels = Array.prototype.slice.call(box.querySelectorAll(":scope > article"));
    if (panels.length < 2) return;
    var list = document.createElement("div");
    list.className = "way-tabs";
    list.setAttribute("role", "tablist");
    list.setAttribute("aria-label", "Four ways to make something");
    var bar = document.createElement("span");
    bar.className = "way-bar";
    bar.setAttribute("aria-hidden", "true");
    list.appendChild(bar);
    var tabs = panels.map(function (panel, i) {
      var tab = document.createElement("button");
      tab.type = "button";
      tab.className = "way-tab";
      tab.id = "way-tab-" + i;
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", (panel.id = panel.id || "way-" + i));
      tab.textContent = panel.querySelector("h3").textContent;
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", tab.id);
      panel.tabIndex = 0;
      tab.addEventListener("click", function () { pick(i, false); });
      tab.addEventListener("keydown", function (e) {
        var to = e.key === "ArrowDown" || e.key === "ArrowRight" ? i + 1 : e.key === "ArrowUp" || e.key === "ArrowLeft"
          ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? panels.length - 1 : null;
        if (to === null) return;
        e.preventDefault();
        pick((to + panels.length) % panels.length, true);
      });
      list.appendChild(tab);
      return tab;
    });
    box.insertBefore(list, box.firstChild);
    box.classList.add("tabs");
    function place() {
      var on = tabs.filter(function (t) { return t.getAttribute("aria-selected") === "true"; })[0];
      if (on) { bar.style.top = on.offsetTop + "px"; bar.style.height = on.offsetHeight + "px"; }
    }
    function pick(n, focus) {
      tabs.forEach(function (tab, i) {
        var on = i === n;
        tab.setAttribute("aria-selected", on ? "true" : "false");
        tab.tabIndex = on ? 0 : -1;
        panels[i].classList.toggle("off", !on);
        panels[i].tabIndex = on ? 0 : -1;
        if (on) {
          panels[i].classList.remove("enter");
          void panels[i].offsetWidth;
          panels[i].classList.add("enter");
          var shot = panels[i].querySelector(".screen.reveal");
          if (shot) shot.classList.add("on");
        }
      });
      if (focus) tabs[n].focus();
      place();
    }
    pick(0, false);
    var queued = false;
    window.addEventListener("resize", function () {
      if (queued) return;
      queued = true;
      requestAnimationFrame(function () { queued = false; place(); });
    });
  }

  // Each answer opens and closes smoothly; the details element still works on its own.
  function questions() {
    document.querySelectorAll(".faq details").forEach(function (d) {
      var summary = d.querySelector("summary"), body = document.createElement("div");
      body.className = "answer";
      while (summary.nextSibling) body.appendChild(summary.nextSibling);
      d.appendChild(body);
      if (!root.classList.contains("motion") || !body.animate) return;
      var want = d.open, run = null;
      summary.addEventListener("click", function (e) {
        e.preventDefault();
        want = !want;
        var from = d.open ? body.getBoundingClientRect().height : 0, fade = getComputedStyle(body).opacity;
        if (run) { run.cancel(); run = null; }
        d.open = true;
        var to = want ? body.scrollHeight : 0;
        run = body.animate([{ height: from + "px", opacity: fade }, { height: to + "px", opacity: want ? 1 : 0 }],
          { duration: 320, easing: "cubic-bezier(0.2, 0.7, 0.2, 1)" });
        run.onfinish = function () { run = null; d.open = want; };
      });
    });
  }

  // Screens light up as they come into view.
  function screens() {
    var shots = document.querySelectorAll("main .screen:not(.hero-shot)");
    var seen = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        e.target.classList.add("on");
        seen.unobserve(e.target);
      });
    }, { rootMargin: "0px 0px -12% 0px" });
    shots.forEach(function (s) { s.classList.add("reveal"); seen.observe(s); });
  }

  // The Studio's screen lies back under the hero and stands up as the page scrolls to it.
  function studioRise() {
    var shot = document.querySelector(".hero-shot");
    if (!shot) return;
    var queued = false;
    function update() {
      queued = false;
      var box = shot.getBoundingClientRect(), vh = window.innerHeight || 1;
      // 0 while its top is at the bottom of the window, 1 once its top is a third of the way down
      var k = Math.max(0, Math.min(1, (vh - box.top) / (vh * 0.62)));
      var max = window.innerWidth < 720 ? 8 : 14;
      shot.style.setProperty("--tilt", (max * (1 - k)).toFixed(2) + "deg");
      shot.style.setProperty("--shrink", (0.94 + 0.06 * k).toFixed(4));
    }
    window.addEventListener("scroll", function () {
      if (!queued) { queued = true; requestAnimationFrame(update); }
    }, { passive: true });
    window.addEventListener("resize", update);
    update();
  }
})();
