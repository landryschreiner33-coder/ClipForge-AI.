// Small extras only; every download link works without this script.
(function () {
  var ua = navigator.userAgent || "";
  var platform = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
  var os = /iPhone|iPad|iPod|Android/i.test(ua) ? "mobile"
    : /Mac/i.test(platform) || /Macintosh/i.test(ua) ? "mac"
    : /Win/i.test(platform) || /Windows/i.test(ua) ? "windows" : "";
  if (os) document.documentElement.dataset.os = os;

  document.addEventListener("DOMContentLoaded", function () {
    // Put the visitor's own system first and give it the main colour.
    var mine = os && document.querySelector('.get-btn[data-os="' + os + '"]');
    if (mine) {
      mine.classList.add("mine");
      mine.parentNode.insertBefore(mine, mine.parentNode.firstChild);
    }
    if (!navigator.clipboard) return;
    document.querySelectorAll("button[data-copy]").forEach(function (button) {
      button.hidden = false;
      button.addEventListener("click", function () {
        navigator.clipboard.writeText(button.dataset.copy).then(function () {
          button.textContent = "Copied";
          setTimeout(function () { button.textContent = "Copy"; }, 1600);
        });
      });
    });
  });
})();
