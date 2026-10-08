/**
 * The office cast: one stable identity per role (the backend's clipfoundry/office/roles.py has the same ids; a test
 * compares them). Everything role-specific the office draws lives here, so pages never branch on a role id:
 * palette, silhouette parts, equipment, signature work animation, home station and manager.
 *
 * Sprites are drawn from these parts by sprites.ts on a 48×64 pixel cell (see design/robots/README.md).
 */

export type Rank = "director" | "manager" | "worker";
export type Dir = "down" | "up" | "left" | "right";
export type RoomId = "lounge" | "boss" | "brain" | "discover" | "analyze" | "studio" | "caption" | "workspace"
  | "schedule" | "dock" | "system";
export type Dept = "boss" | "discover" | "analyze" | "studio" | "caption" | "schedule" | "dock" | "system" | "brain";

export type Head = "rounded-square" | "radar-arch" | "trapezoid" | "director-helmet" | "keycap" | "clock-ring"
  | "cargo" | "hex" | "dome" | "oval" | "book" | "angular" | "jaw" | "round" | "soft-rect" | "swept" | "wide"
  | "monitor" | "slim-trapezoid" | "square" | "steel-hex" | "box" | "fin-round" | "cap" | "beacon";
export type Body = "jacket" | "manager" | "box" | "shield" | "round" | "pear" | "stocky" | "cart" | "slim" | "torso";
export type Visor = "wide-cyan" | "binocular" | "split" | "horizontal" | "bracket" | "dial" | "slit" | "lenses"
  | "linked-dots" | "round-lenses" | "equalizer" | "level" | "cyclops" | "panels" | "angled" | "visor-band"
  | "monitor-face" | "narrow" | "inspection" | "lock" | "square-eyes" | "display" | "soft" | "goggles";
export type Top = "crest" | "radar-arch" | "bar-antennae" | "brim" | "none" | "side-dial" | "mast" | "crown3"
  | "long-antenna" | "zigzag" | "star" | "spine" | "fins" | "ear-cups" | "key-tabs" | "pencil" | "uplink" | "bar-fins"
  | "forked" | "beacon";
export type Gear = "command-tablet" | "map-tablet" | "graph-badge" | "clapper" | "proof-tablet" | "ticket-tablet"
  | "checklist" | "tool-belt" | "cartridge" | "radar-pack" | "satchel" | "graph-slate" | "stamp" | "waveform"
  | "storyboard" | "curve-tablet" | "reel-pack" | "keyboard" | "printer" | "scanner" | "id-reader" | "parcel"
  | "notebook" | "node-pattern" | "wrench";
export type Work = "observe" | "map" | "compare" | "scrub" | "proofread" | "slot" | "signal" | "inspect" | "evaluate"
  | "sweep" | "pages" | "plot" | "weigh" | "markers" | "arrange" | "curve" | "render" | "type" | "draft" | "scan"
  | "verify" | "load" | "collect" | "connect" | "repair";

export interface Palette {
  shell: string;   // pale metal
  shade: string;
  trim: string;    // the role's accent
  trimDark: string;
  visor: string;   // dark face panel
  eye: string;     // illuminated eyes
  gear: string;    // equipment main color
  gearDark: string;
}

export interface Character {
  id: string;
  name: string;
  title: string;
  job: string;
  rank: Rank;
  dept: Dept;
  room: RoomId;
  manager: string;          // "" for the Director
  palette: Palette;
  head: Head;
  body: Body;
  visor: Visor;
  top: Top;
  gear: Gear;
  work: Work;
  /** legs, or wheels for DOCK */
  base?: "legs" | "wheels";
  /** the hand that holds the gear (kept on the correct side when facing left or right) */
  hand?: "left" | "right" | "both";
  /** frame length of the working loop in ms (2-4 frames) */
  workMs?: number;
}

const metal = { shell: "#dfe4ec", shade: "#a6b0c2", visor: "#18223a" };
const pal = (trim: string, trimDark: string, eye: string, gear: string, gearDark: string, extra: Partial<Palette> = {})
  : Palette => ({ ...metal, trim, trimDark, eye, gear, gearDark, ...extra });

export const DEPARTMENTS: Record<Exclude<Dept, "boss">, { name: string; manager: string; accent: string }> = {
  discover: { name: "Discover", manager: "tracker", accent: "#a6e94b" },
  analyze: { name: "Analyze", manager: "vector", accent: "#4f7dff" },
  studio: { name: "Clip Studio", manager: "frame", accent: "#ff3dad" },
  caption: { name: "Caption", manager: "script", accent: "#9a6bff" },
  schedule: { name: "Schedule", manager: "clock", accent: "#ffab45" },
  dock: { name: "Upload Dock", manager: "harbor", accent: "#57eea0" },
  system: { name: "System", manager: "switch", accent: "#ffc23d" },
  brain: { name: "Brain Room", manager: "curator", accent: "#c4a8ff" },
};

export const ROOM_NAMES: Record<RoomId, string> = {
  lounge: "Lounge", boss: "Boss Hub", brain: "Brain Room", discover: "Discover", analyze: "Analyze",
  studio: "Clip Studio", caption: "Caption", workspace: "Team Workspace", schedule: "Schedule",
  dock: "Upload Dock", system: "System",
};

export const CAST: Character[] = [
  { id: "command", name: "COMMAND", title: "Director", rank: "director", dept: "boss", room: "boss", manager: "",
    job: "Records the go or no-go at each checkpoint (source, clip, quality check, upload) from the rules' results.",
    palette: pal("#ffc94a", "#b9862a", "#28d9ff", "#ffab45", "#c46f1c", { visor: "#0f1730" }),
    head: "rounded-square", body: "jacket", visor: "wide-cyan", top: "crest", gear: "command-tablet", work: "observe",
    hand: "both", workMs: 600 },
  // managers
  { id: "tracker", name: "TRACKER", title: "Discovery Manager", rank: "manager", dept: "discover", room: "discover",
    manager: "command", job: "Reviews what the scouts found and reports the candidates to COMMAND.",
    palette: pal("#a6e94b", "#5f9a1e", "#7dff5a", "#5fd35a", "#2f7a2a"),
    head: "radar-arch", body: "manager", visor: "binocular", top: "radar-arch", gear: "map-tablet", work: "map",
    hand: "both", workMs: 500 },
  { id: "vector", name: "VECTOR", title: "Analysis Manager", rank: "manager", dept: "analyze", room: "analyze",
    manager: "command", job: "Compares the evidence about a video and submits the scored source report.",
    palette: pal("#4f7dff", "#2a47a8", "#9fd2ff", "#4f7dff", "#2a47a8"),
    head: "trapezoid", body: "manager", visor: "split", top: "bar-antennae", gear: "graph-badge", work: "compare",
    hand: "both", workMs: 500 },
  { id: "frame", name: "FRAME", title: "Clip Studio Manager", rank: "manager", dept: "studio", room: "studio",
    manager: "command", job: "Checks the cut and the render and signs off the clip package.",
    palette: pal("#ff3dad", "#a81f6f", "#ffd1ec", "#2b2f3d", "#ff3dad"),
    head: "director-helmet", body: "manager", visor: "horizontal", top: "brim", gear: "clapper", work: "scrub",
    hand: "both", workMs: 450 },
  { id: "script", name: "SCRIPT", title: "Caption Manager", rank: "manager", dept: "caption", room: "caption",
    manager: "command", job: "Reads the captions and post text and sends a correction back when something is wrong.",
    palette: pal("#9a6bff", "#5e3cc0", "#e2d4ff", "#f3eedf", "#9a6bff"),
    head: "keycap", body: "manager", visor: "bracket", top: "none", gear: "proof-tablet", work: "proofread",
    hand: "both", workMs: 550 },
  { id: "clock", name: "CLOCK", title: "Schedule Manager", rank: "manager", dept: "schedule", room: "schedule",
    manager: "command", job: "Puts approved clips into posting slots and moves them when a plan changes.",
    palette: pal("#ffab45", "#b8651a", "#ffe2b8", "#ffab45", "#b8651a"),
    head: "clock-ring", body: "manager", visor: "dial", top: "side-dial", gear: "ticket-tablet", work: "slot",
    hand: "both", workMs: 500 },
  { id: "harbor", name: "HARBOR", title: "Publish Manager", rank: "manager", dept: "dock", room: "dock",
    manager: "command", job: "Confirms the destination and audience are allowed, then signals the upload.",
    palette: pal("#57eea0", "#1f9c5e", "#c9ffe3", "#e9f2ec", "#57eea0"),
    head: "cargo", body: "manager", visor: "slit", top: "mast", gear: "checklist", work: "signal", hand: "both",
    workMs: 500 },
  { id: "switch", name: "SWITCH", title: "System Manager", rank: "manager", dept: "system", room: "system",
    manager: "command", job: "Reads the health checks, visits a failed station and reports recovery once verified.",
    palette: pal("#ffc23d", "#a5791a", "#ffdd85", "#ffc23d", "#3a3f4b", { shell: "#7d8494", shade: "#545a68" }),
    head: "hex", body: "manager", visor: "lenses", top: "none", gear: "tool-belt", work: "inspect", hand: "both",
    workMs: 450 },
  { id: "curator", name: "CURATOR", title: "Learning Manager", rank: "manager", dept: "brain", room: "brain",
    manager: "command", job: "Reviews result evidence and presents an accepted or inconclusive strategy evaluation.",
    palette: pal("#c4a8ff", "#7c5ccc", "#efe6ff", "#c4a8ff", "#7c5ccc"),
    head: "dome", body: "manager", visor: "linked-dots", top: "crown3", gear: "cartridge", work: "evaluate",
    hand: "both", workMs: 600 },
  // workers
  { id: "radar", name: "RADAR", title: "Scout", rank: "worker", dept: "discover", room: "discover", manager: "tracker",
    job: "Searches for new videos and carries each candidate to TRACKER.",
    palette: pal("#a6e94b", "#5f9a1e", "#d9ff7a", "#a6e94b", "#5f9a1e"),
    head: "oval", body: "slim", visor: "goggles", top: "long-antenna", gear: "radar-pack", work: "sweep",
    hand: "right", workMs: 300 },
  { id: "archive", name: "ARCHIVE", title: "Researcher", rank: "worker", dept: "discover", room: "discover",
    manager: "tracker", job: "Reads the source's details and gets the video file where access is allowed.",
    palette: pal("#2fd1c5", "#16877f", "#c8fff9", "#a07a4f", "#6b4f2f"),
    head: "book", body: "torso", visor: "round-lenses", top: "none", gear: "satchel", work: "pages", hand: "right",
    workMs: 450 },
  { id: "pulse", name: "PULSE", title: "Trend Analyst", rank: "worker", dept: "analyze", room: "analyze",
    manager: "vector", job: "Compares time-stamped view counts and updates the trend line.",
    palette: pal("#4f7dff", "#2a47a8", "#7cf3ff", "#22304f", "#4f7dff"),
    head: "angular", body: "slim", visor: "equalizer", top: "zigzag", gear: "graph-slate", work: "plot",
    hand: "left", workMs: 350 },
  { id: "gavel", name: "GAVEL", title: "Source Judge", rank: "worker", dept: "analyze", room: "analyze",
    manager: "vector", job: "Weighs the rights evidence and stamps the real accept or reject.",
    palette: pal("#ffab45", "#b8651a", "#ffe2b8", "#8a5a33", "#5a3a1f"),
    head: "jaw", body: "torso", visor: "level", top: "none", gear: "stamp", work: "weigh", hand: "right",
    workMs: 400 },
  { id: "spark", name: "SPARK", title: "Moment Finder", rank: "worker", dept: "studio", room: "studio",
    manager: "frame", job: "Scans the transcript and marks the moments that make complete clips.",
    palette: pal("#ffe14a", "#b39a14", "#4fb4ff", "#ffe14a", "#b39a14"),
    head: "round", body: "round", visor: "cyclops", top: "star", gear: "waveform", work: "markers", hand: "right",
    workMs: 300 },
  { id: "story", name: "STORY", title: "Story Editor", rank: "worker", dept: "studio", room: "studio",
    manager: "frame", job: "Arranges hook, context and payoff into the clip plan.",
    palette: pal("#ff7a6b", "#b2463a", "#ffd6cf", "#fff1df", "#ff7a6b"),
    head: "soft-rect", body: "torso", visor: "panels", top: "spine", gear: "storyboard", work: "arrange",
    hand: "both", workMs: 500 },
  { id: "boost", name: "BOOST", title: "Viral Analyst", rank: "worker", dept: "analyze", room: "analyze",
    manager: "vector", job: "Scores how strong a video's moments are (estimates, labeled as such).",
    palette: pal("#22e3d0", "#118a7e", "#c4fff8", "#22304f", "#22e3d0"),
    head: "swept", body: "slim", visor: "angled", top: "fins", gear: "curve-tablet", work: "curve", hand: "left",
    workMs: 400 },
  { id: "splice", name: "SPLICE", title: "Video Editor", rank: "worker", dept: "studio", room: "studio",
    manager: "frame", job: "Renders the clip (crop, cuts, captions) and reports measured progress.",
    palette: pal("#ff3dad", "#a81f6f", "#ffd1ec", "#ff8a2a", "#a8501a"),
    head: "wide", body: "torso", visor: "visor-band", top: "ear-cups", gear: "reel-pack", work: "render",
    hand: "both", workMs: 300 },
  { id: "glyph", name: "GLYPH", title: "Caption Agent", rank: "worker", dept: "caption", room: "caption",
    manager: "script", job: "Writes the timed captions for the current clip.",
    palette: pal("#9a6bff", "#5e3cc0", "#e2d4ff", "#2b2f3d", "#9a6bff"),
    head: "monitor", body: "torso", visor: "monitor-face", top: "key-tabs", gear: "keyboard", work: "type",
    hand: "both", workMs: 200 },
  { id: "quill", name: "QUILL", title: "Title Agent", rank: "worker", dept: "caption", room: "caption",
    manager: "script", job: "Drafts the title, description and hashtags from words said in the clip.",
    palette: pal("#ff7fae", "#b44a75", "#ffe0ec", "#f3eedf", "#ff7fae"),
    head: "slim-trapezoid", body: "slim", visor: "narrow", top: "pencil", gear: "printer", work: "draft",
    hand: "right", workMs: 450 },
  { id: "check", name: "CHECK", title: "Quality Control", rank: "worker", dept: "system", room: "system",
    manager: "switch", job: "Checks the exact rendered file and shows pass or fail only after the check.",
    palette: pal("#57eea0", "#1f9c5e", "#c9ffe3", "#57eea0", "#1f9c5e"),
    head: "square", body: "shield", visor: "inspection", top: "none", gear: "scanner", work: "scan", hand: "right",
    workMs: 250 },
  { id: "lock", name: "LOCK", title: "Audience Verification", rank: "worker", dept: "dock", room: "dock",
    manager: "harbor", job: "Checks the account and who may watch, then shows verified or blocked.",
    palette: pal("#7fa6d9", "#3f638f", "#d6e9ff", "#3f638f", "#1d2e48", { shell: "#b9c8dc", shade: "#8396b0" }),
    head: "steel-hex", body: "shield", visor: "lock", top: "none", gear: "id-reader", work: "verify", hand: "right",
    workMs: 400 },
  { id: "dock", name: "DOCK", title: "Publisher", rank: "worker", dept: "dock", room: "dock", manager: "harbor",
    job: "Loads the clip onto the upload during a real transfer.",
    palette: pal("#ff8a2a", "#a8501a", "#fff1df", "#c08a52", "#7d5530", { shell: "#ffb066", shade: "#d07a2c" }),
    head: "box", body: "cart", visor: "square-eyes", top: "uplink", gear: "parcel", work: "load", base: "wheels",
    hand: "both", workMs: 350 },
  { id: "metric", name: "METRIC", title: "Analytics Agent", rank: "worker", dept: "brain", room: "brain",
    manager: "curator", job: "Collects new result readings and files each with the time it was true.",
    palette: pal("#3fe0f0", "#178c99", "#c8faff", "#f3eedf", "#3fe0f0"),
    head: "fin-round", body: "torso", visor: "display", top: "bar-fins", gear: "notebook", work: "collect",
    hand: "left", workMs: 450 },
  { id: "synapse", name: "SYNAPSE", title: "Learning Agent", rank: "worker", dept: "brain", room: "brain",
    manager: "curator", job: "Compares results by audience and carries a strategy proposal to CURATOR.",
    palette: pal("#d3a8ff", "#8a5cc7", "#f4e6ff", "#d3a8ff", "#8a5cc7"),
    head: "cap", body: "pear", visor: "soft", top: "forked", gear: "node-pattern", work: "connect", hand: "both",
    workMs: 550 },
  { id: "patch", name: "PATCH", title: "System Guardian", rank: "worker", dept: "system", room: "system",
    manager: "switch", job: "Runs the health checks and the maintenance that recovers stopped work.",
    palette: pal("#ff8a2a", "#a8501a", "#ffd9a8", "#9aa3b5", "#545a68", { shell: "#5d6371", shade: "#3d424e" }),
    head: "beacon", body: "stocky", visor: "goggles", top: "beacon", gear: "wrench", work: "repair",
    hand: "right", workMs: 400 },
];

export const CORE = { id: "core", name: "CORE", title: "Brain Core",
  job: "Memory and strategy settings. It cannot override privacy, credentials, cost limits, stop controls or the "
    + "safety checks." };

export const BY_ID: Record<string, Character> = Object.fromEntries(CAST.map((c) => [c.id, c]));

/** Same rule as the backend registry: exactly 1 Director, 8 managers, 16 workers (CORE is an object, not a robot). */
export function validateCast(): string[] {
  const problems: string[] = [];
  const count = (r: Rank) => CAST.filter((c) => c.rank === r).length;
  if (count("director") !== 1 || count("manager") !== 8 || count("worker") !== 16)
    problems.push(`expected 1+8+16 robots, found ${count("director")}+${count("manager")}+${count("worker")}`);
  if (new Set(CAST.map((c) => c.id)).size !== CAST.length) problems.push("ids must be unique");
  const looks = new Set(CAST.map((c) => `${c.head}|${c.visor}|${c.top}|${c.gear}`));
  if (looks.size !== CAST.length) problems.push("two robots share the same head, visor, top and gear");
  for (const c of CAST) if (c.manager && !BY_ID[c.manager]) problems.push(`${c.name} has no manager`);
  return problems;
}
