/* Applies the saved palette, accent, spacing and text size before the first paint (ClipForge is dark only; a Light or
   System choice saved by an older version is ignored). Loaded as a same-origin file because the page allows no
   inline scripts. The account copy, loaded by the app, stays the record. */
(function () {
  var allowed = {
    palette: ["studio", "midnight", "graphite", "plum"],
    accent: ["violet", "teal", "blue", "coral", "green", "pink"],
    density: ["comfortable", "compact"],
    text: ["standard", "large", "larger"]
  };
  var root = document.documentElement;
  try {
    var saved = JSON.parse(window.localStorage.getItem("clipforge.appearance") || "{}") || {};
    var pick = function (key, value) { if (allowed[key].indexOf(value) >= 0) root.setAttribute("data-" + key, value); };
    pick("palette", saved.palette);
    pick("accent", saved.accent);
    pick("density", saved.density);
    pick("text", saved.text_size);
  } catch (e) {
    /* no storage: the default dark palette */
  }
})();
