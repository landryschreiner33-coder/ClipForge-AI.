/**
 * Calls `on` whenever the window moves to a screen of another pixel density (a Mac window dragged from an external
 * monitor to the Retina screen, say). The window keeps its size in CSS pixels, so no resize happens, but a canvas
 * then needs more or fewer pixels to stay sharp. Returns the way to stop listening.
 */
export function onPixelRatioChange(on: () => void): () => void {
  if (typeof window.matchMedia !== "function") return () => undefined;
  let query: MediaQueryList | null = null;
  const watch = () => {
    query?.removeEventListener("change", changed);
    query = window.matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`);
    query.addEventListener("change", changed);
  };
  // the query matches one density only: ask again for the new one, then tell
  function changed() {
    watch();
    on();
  }
  watch();
  return () => query?.removeEventListener("change", changed);
}
