/** Words and times, the same way on every page. */

/** "1 clip", "3 clips", "1 person", "2 people" */
export const plural = (n: number, one: string, many?: string) => `${n} ${n === 1 ? one : many || `${one}s`}`;

function zoneOf(tz?: string): string | undefined {
  if (!tz) return undefined;
  try {
    new Intl.DateTimeFormat([], { timeZone: tz });
    return tz;
  } catch {
    return undefined;
  }
}

/** "Today, 4:20 PM", "Tomorrow, 9:05 AM", "Yesterday, 8:00 PM" or "Fri, Oct 3, 9:05 AM", in a time zone. */
export function when(ts: number | null | undefined, tz?: string): string {
  if (!ts) return "Time not chosen yet";
  const zone = zoneOf(tz);
  const d = new Date(ts * 1000);
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", timeZone: zone });
  const day = (x: Date) => x.toLocaleDateString("en-CA", { timeZone: zone });
  const now = Date.now();
  if (day(d) === day(new Date(now))) return `Today, ${time}`;
  if (day(d) === day(new Date(now + 86_400_000))) return `Tomorrow, ${time}`;
  if (day(d) === day(new Date(now - 86_400_000))) return `Yesterday, ${time}`;
  const date = d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric", timeZone: zone });
  return `${date}, ${time}`;
}

/** "Today, 5:25 PM" → "today at 5:25 PM", for use inside a sentence. */
export function at(ts: number | null | undefined, tz?: string): string {
  const w = when(ts, tz);
  const m = /^([^,]+), (.+)$/.exec(w);
  if (!m) return w;
  const [, dayPart, rest] = m;
  if (/^(Today|Tomorrow|Yesterday)$/.test(dayPart)) return `${dayPart.toLowerCase()} at ${rest}`;
  const n = /^(.+), (\d{1,2}:\d{2}\s?[AP]M)$/i.exec(rest);
  return n ? `${dayPart}, ${n[1]} at ${n[2]}` : `${dayPart}, ${rest}`;
}

/** The time zone once per list: "Times are Central Time (America/Chicago)." */
export function zoneLine(tz?: string): string {
  const zone = zoneOf(tz);
  if (!zone) return "Times are in this computer's time zone.";
  let name = "";
  try {
    name = new Intl.DateTimeFormat("en-US", { timeZone: zone, timeZoneName: "long" }).formatToParts(new Date())
      .find((p) => p.type === "timeZoneName")?.value || "";
  } catch {
    /* the zone id alone */
  }
  return name ? `Times are ${name} (${zone}).` : `Times are in ${zone}.`;
}

/** A number the way people read it, or "—" when it was not reported (never estimated). */
export const num = (n: number | null | undefined) => (n === null || n === undefined ? "—" : n.toLocaleString("en-US"));
