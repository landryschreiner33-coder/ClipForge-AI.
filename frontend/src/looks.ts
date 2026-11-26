/** The picture's looks and colour notes (config.LOOKS; pipeline/grade.py LOOKS and LOOK_WORDS say the same). */
export const LOOKS: { value: string; label: string; what: string }[] = [
  { value: "natural", label: "Natural", what: "Colours corrected, no added style." },
  { value: "bright", label: "Clean and bright", what: "Lifted mid-tones and a little more colour, for an airy picture." },
  { value: "warm", label: "Warm", what: "A warmer, golden picture." },
  { value: "cool", label: "Cool", what: "A cooler, bluer picture." },
  { value: "film", label: "Film", what: "A soft film curve, gentle highlights, slightly muted colour." },
  { value: "teal_orange", label: "Teal and orange", what: "Blue-green shadows and warm highlights; skin left alone." },
  { value: "moody", label: "Moody", what: "Darker mid-tones, muted colour and cool shadows." },
  { value: "vintage", label: "Vintage", what: "Faded blacks, soft highlights and a warm, yellowed tint." },
  { value: "mono", label: "Black and white", what: "Black and white with a little extra contrast." },
];

export const lookOf = (value?: unknown) => LOOKS.find((l) => l.value === value) || LOOKS[0];

/** What a render did to one recording's colour (render_info.colour). */
export type ColourReport = { hdr?: string | null; corrected?: boolean; look?: string; strength?: number;
  notes?: string[]; denoise?: boolean };

/** One line in plain words: what was changed, or that nothing was. */
export function colourLine(c?: ColourReport | null): string {
  if (!c) return "";
  const parts = [...(c.notes || [])];
  if (c.denoise) parts.push("Grain cleaned up");
  if (c.look && c.look !== "natural" && (c.strength ?? 1) > 0) {
    const pct = Math.round((c.strength ?? 1) * 100);
    parts.push(`${lookOf(c.look).label} look${pct < 100 ? ` at ${pct} %` : ""}`);
  }
  return parts.length ? parts.join("; ") + "." : "The colours needed no change.";
}
