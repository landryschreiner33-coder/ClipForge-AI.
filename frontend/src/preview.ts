/**
 * The Studio preview on Settings → Appearance is this app inside a frame (`/?preview=studio#/`, the space studio,
 * 2026-11-19). In the frame the app shows the appearance the page sends it and never saves one; the page makes the
 * frame inert, so nothing in it can be clicked or reached with the keyboard.
 */
export const PREVIEW_MESSAGE = "clipforge:preview-appearance";

export const IN_PREVIEW = (() => {
  try {
    return window.parent !== window && new URLSearchParams(window.location.search).get("preview") === "studio";
  } catch {
    return false;  // a frame from another site: not our preview
  }
})();

// lets the preview hide its scroll bars (space.css) before the first paint
if (IN_PREVIEW) document.documentElement.dataset.preview = "studio";
