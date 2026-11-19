/** The black hole in the studio's sky: a picture with a light that travels along its disk. The light is decoration
 * only: it stops when motion is reduced or the page is hidden (space.css reads html[data-motion] and
 * html[data-page-hidden]). */
export function BlackHole({ size = "small", className = "" }: { size?: "small" | "large"; className?: string }) {
  return (
    <div className={`black-hole ${size}${className ? ` ${className}` : ""}`} aria-hidden="true">
      <span className="glint" />
    </div>
  );
}
