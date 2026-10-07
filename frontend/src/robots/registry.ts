/**
 * Robot crew registry: the single source of truth for who is on the ClipFoundry team.
 *
 * Every identity here is fixed. Nothing is random: the same role id always produces the
 * same name, palette, silhouette and animation timing. The pixel art for each role lives in
 * `art/` (see `ART_SOURCES`) and is looked up by the same id.
 *
 * tests/test_robot_registry.py reads this file as text, so keep each role's fields in the order
 * id, name, job, rank, department, managerId, and keep the field names below unchanged.
 */

export type RoleId =
  | "command"
  | "tracker"
  | "vector"
  | "frame"
  | "script"
  | "clock"
  | "harbor"
  | "switch"
  | "curator"
  | "radar"
  | "archive"
  | "pulse"
  | "gavel"
  | "spark"
  | "story"
  | "boost"
  | "splice"
  | "glyph"
  | "quill"
  | "check"
  | "lock"
  | "dock"
  | "metric"
  | "synapse"
  | "patch";

export type Rank = "director" | "manager" | "worker";

export type DepartmentId =
  "boss_hub" | "discover" | "analyze" | "clip_studio" | "caption" | "schedule" | "upload_dock" | "system" | "brain";

/** Facing. "down" is the front view, "up" is the back view, "left"/"right" are profiles. */
export type Direction = "down" | "up" | "left" | "right";

export type AnimState =
  | "idle"
  | "walk"
  | "work"
  | "carry"
  | "review"
  | "waiting"
  | "approved"
  | "revise"
  | "error"
  | "retrying"
  | "paused"
  | "unavailable";

export const DIRECTIONS: readonly Direction[] = ["down", "up", "left", "right"];

export const ANIM_STATES: readonly AnimState[] = [
  "idle",
  "walk",
  "work",
  "carry",
  "review",
  "waiting",
  "approved",
  "revise",
  "error",
  "retrying",
  "paused",
  "unavailable",
];

/** Frame count and per-frame duration (ms). `ms` has one entry per frame. */
export interface AnimTiming {
  frames: number;
  ms: number[];
}

export interface RolePalette {
  /** Role trim colour: shoulder tabs, feet, visor frame, role symbol. */
  trim: string;
  /** Secondary accent: equipment, tablet, satchel... */
  accent: string;
  /** Main shell metal. Pale for most of the family; graphite/charcoal/orange where the sheet says so. */
  shell: string;
  /** Dark face panel / visor glass. */
  face: string;
  /** Eye glow. */
  eye: string;
}

export interface RobotRole {
  id: RoleId;
  /** Display name, CAPS. */
  name: string;
  /** Plain-language job title. */
  job: string;
  /** One plain sentence: what this robot does. */
  duty: string;
  department: DepartmentId;
  rank: Rank;
  /** Worker -> its manager; manager -> "command"; command -> null. */
  managerId: RoleId | null;
  palette: RolePalette;
  /** Short description of the outline you should recognise without colour. */
  silhouette: string;
  equipment: string[];
  /** Signature work motion, plain words. */
  workMotion: string;
  /** Body size relative to a worker: 1.35 director, 1.15 managers, 1 workers. */
  scale: number;
  directions: Direction[];
  anim: Record<AnimState, AnimTiming>;
}

const t = (frames: number, ms: number | number[]): AnimTiming => ({
  frames,
  ms: Array.isArray(ms) ? ms : Array.from({ length: frames }, () => ms),
});

/** Shared timing. Only `work` differs per role (2-4 frames). */
function anim(workFrames: number, workMs = 220): Record<AnimState, AnimTiming> {
  return {
    idle: t(2, [1500, 220]),
    walk: t(4, 150),
    work: t(workFrames, workMs),
    carry: t(4, 160),
    review: t(2, 900),
    waiting: t(3, 420),
    approved: t(2, 320),
    revise: t(2, 380),
    error: t(2, 450),
    retrying: t(4, 160),
    paused: t(1, 1000),
    unavailable: t(1, 1000),
  };
}

const SCALE: Record<Rank, number> = { director: 1.35, manager: 1.15, worker: 1 };

export const ROLES: RobotRole[] = [
  // ---- Director -------------------------------------------------------------------------
  {
    id: "command",
    name: "COMMAND",
    job: "Boss",
    rank: "director",
    department: "boss_hub",
    managerId: null,
    duty: "Sets the day's goals, hands work to each manager and signs off on what ships.",
    palette: { trim: "#F5C542", accent: "#FF8A2A", shell: "#E3E8F1", face: "#0C1838", eye: "#28D9FF" },
    silhouette: "Largest body; broad rounded-square head with gold three-fin crest; broad shoulders and jacket tails.",
    equipment: ["gold three-fin crest", "gold-trimmed jacket and tie", "wide orange command tablet", "crown badge"],
    workMotion: "Taps the command tablet and points to delegate.",
    scale: SCALE.director,
    directions: ["down", "up", "left", "right"],
    anim: anim(4, 240),
  },
  // ---- Managers -------------------------------------------------------------------------
  {
    id: "tracker",
    name: "TRACKER",
    job: "Discovery Manager",
    rank: "manager",
    department: "discover",
    managerId: "command",
    duty: "Plans where to look for new source videos and checks what the scouts bring back.",
    palette: { trim: "#8EE83A", accent: "#2FBF5A", shell: "#E4E9F0", face: "#111A2B", eye: "#B4FF4A" },
    silhouette: "Tall radar arch over the head like headphones; wide binocular visor; walkie aerial on the shoulder.",
    equipment: ["radar-arch headpiece", "binocular visor", "compass badge", "map tablet"],
    workMotion: "Arch dish pings while the map tablet pin blinks.",
    scale: SCALE.manager,
    directions: ["down", "up", "left", "right"],
    anim: anim(3, 260),
  },
  {
    id: "vector",
    name: "VECTOR",
    job: "Analysis Manager",
    rank: "manager",
    department: "analyze",
    managerId: "command",
    duty: "Decides which findings are worth turning into clips and ranks them.",
    palette: { trim: "#2F6BFF", accent: "#28D9FF", shell: "#E4E9F2", face: "#0E1834", eye: "#3FB8FF" },
    silhouette: "Broad trapezoid head wider at the top with two short bar antennae; split visor.",
    equipment: ["split analytical visor (bar chart | pie)", "two bar antennae", "graph badge", "chart tablet"],
    workMotion: "Visor bars rise and the pie slice turns.",
    scale: SCALE.manager,
    directions: ["down", "up", "left", "right"],
    anim: anim(4, 220),
  },
  {
    id: "frame",
    name: "FRAME",
    job: "Clip Studio Manager",
    rank: "manager",
    department: "clip_studio",
    managerId: "command",
    duty: "Runs the clip studio and approves each cut before captions are added.",
    palette: { trim: "#FF3DAD", accent: "#B24DFF", shell: "#ECE6F0", face: "#1A0F2E", eye: "#FF7AD9" },
    silhouette: "Square director helmet with a film reel on one shoulder; magenta body; horizontal play visor.",
    equipment: ["film-reel shoulder", "play-icon visor", "clapperboard tablet", "crown badge"],
    workMotion: "Clapperboard snaps shut and the reel turns.",
    scale: SCALE.manager,
    directions: ["down", "up", "left", "right"],
    anim: anim(2, 260),
  },
  {
    id: "script",
    name: "SCRIPT",
    job: "Caption Manager",
    rank: "manager",
    department: "caption",
    managerId: "command",
    duty: "Oversees captions and titles and proofreads them before they go out.",
    palette: { trim: "#9A6BFF", accent: "#7B3DFF", shell: "#ECEAF4", face: "#150E2C", eye: "#C9A8FF" },
    silhouette: "Tall rounded keycap head; eyes drawn as [ ] brackets; CC chest plate.",
    equipment: ["keycap head", "bracket eye surround", "CC badge", "proofreading tablet"],
    workMotion: "Bracket eyes blink like a text cursor while ticking the tablet.",
    scale: SCALE.manager,
    directions: ["down", "up", "left", "right"],
    anim: anim(2, 300),
  },
  {
    id: "clock",
    name: "CLOCK",
    job: "Schedule Manager",
    rank: "manager",
    department: "schedule",
    managerId: "command",
    duty: "Picks the best posting times and keeps the release calendar on track.",
    palette: { trim: "#FFAB45", accent: "#FF7A1A", shell: "#EEE9E2", face: "#141A2C", eye: "#7FE8FF" },
    silhouette: "Round clock-face head inside a thick outer ring; small dial on one side; boxy calendar backpack.",
    equipment: ["clock-ring head", "side dial", "calendar backpack", "ticket tablet"],
    workMotion: "Clock hand ticks around while the ticket tablet updates.",
    scale: SCALE.manager,
    directions: ["down", "up", "left", "right"],
    anim: anim(4, 250),
  },
  {
    id: "harbor",
    name: "HARBOR",
    job: "Publish Manager",
    rank: "manager",
    department: "upload_dock",
    managerId: "command",
    duty: "Signs off each upload and makes sure every post reaches the right account.",
    palette: { trim: "#2FCB6B", accent: "#1E9E50", shell: "#E6ECEA", face: "#0F1D1A", eye: "#6CFFA8" },
    silhouette: "Broad cargo helmet; single uplink mast with a dish; big green cargo backpack with up arrow.",
    equipment: ["cargo helmet", "uplink mast dish", "shield clasp", "shipping checklist", "cargo backpack"],
    workMotion: "Uplink dish blinks while checklist ticks fill.",
    scale: SCALE.manager,
    directions: ["down", "up", "left", "right"],
    anim: anim(3, 260),
  },
  {
    id: "switch",
    name: "SWITCH",
    job: "System Manager",
    rank: "manager",
    department: "system",
    managerId: "command",
    duty: "Keeps the machines healthy and decides when something needs a repair.",
    palette: { trim: "#FFB020", accent: "#FF7A1A", shell: "#6E7688", face: "#12151D", eye: "#FF9A1F" },
    silhouette: "Graphite hexagonal head with paired round lenses; hazard-striped chin; tool belt.",
    equipment: ["hexagonal head", "round diagnostic lenses", "hazard panels", "tool belt", "alert tablet"],
    workMotion: "Lenses focus and the tablet gear spins.",
    scale: SCALE.manager,
    directions: ["down", "up", "left", "right"],
    anim: anim(4, 200),
  },
  {
    id: "curator",
    name: "CURATOR",
    job: "Learning Manager",
    rank: "manager",
    department: "brain",
    managerId: "command",
    duty: "Decides what the team should remember from past results.",
    palette: { trim: "#B79CFF", accent: "#8F6BFF", shell: "#E9E5F7", face: "#160F33", eye: "#C07BFF" },
    silhouette: "Rounded glass-dome head with a three-node crown; linked-dot visor.",
    equipment: ["glass dome", "three-node crown", "linked-dot visor", "memory-cartridge tablet"],
    workMotion: "Crown nodes light up one after another.",
    scale: SCALE.manager,
    directions: ["down", "up", "left", "right"],
    anim: anim(3, 280),
  },
  // ---- Workers --------------------------------------------------------------------------
  {
    id: "radar",
    name: "RADAR",
    job: "Scout",
    rank: "worker",
    department: "discover",
    managerId: "tracker",
    duty: "Searches the web for fresh videos that match your topics.",
    palette: { trim: "#9BE33A", accent: "#3DDC6B", shell: "#E6EBF1", face: "#121A2A", eye: "#9BFF4A" },
    silhouette: "Slim oval head with one long ball antenna; binocular eyes; round radar dish backpack.",
    equipment: ["ball antenna", "binocular eyes", "radar backpack", "map card"],
    workMotion: "Radar dish sweep line circles.",
    scale: SCALE.worker,
    directions: ["down", "up", "left", "right"],
    anim: anim(4, 180),
  },
  {
    id: "archive",
    name: "ARCHIVE",
    job: "Researcher",
    rank: "worker",
    department: "discover",
    managerId: "tracker",
    duty: "Collects the facts and context behind each source video.",
    palette: { trim: "#2EC4B6", accent: "#9A6034", shell: "#E7EAEE", face: "#10202A", eye: "#7FF4FF" },
    silhouette: "Boxy book-shaped head with spine ridges; round glasses; satchel on the hip; magnifier.",
    equipment: ["book head", "round glasses", "document satchel", "magnifier"],
    workMotion: "Magnifier sweeps across the page.",
    scale: SCALE.worker,
    directions: ["down", "up", "left", "right"],
    anim: anim(4, 220),
  },
  {
    id: "pulse",
    name: "PULSE",
    job: "Trend Analyst",
    rank: "worker",
    department: "analyze",
    managerId: "vector",
    duty: "Watches what is trending and flags rising topics.",
    palette: { trim: "#3A6BFF", accent: "#28D9FF", shell: "#E4E9F3", face: "#0D1730", eye: "#48C8FF" },
    silhouette: "Narrow angular wedge head with a zigzag antenna; equalizer visor.",
    equipment: ["zigzag antenna", "equalizer visor", "graph slate"],
    workMotion: "Equalizer bars bounce.",
    scale: SCALE.worker,
    directions: ["down", "up", "left", "right"],
    anim: anim(4, 160),
  },
  {
    id: "gavel",
    name: "GAVEL",
    job: "Source Judge",
    rank: "worker",
    department: "analyze",
    managerId: "vector",
    duty: "Checks that each source is usable and safe before work starts.",
    palette: { trim: "#FFB52E", accent: "#E8423B", shell: "#E8E8EA", face: "#1B1714", eye: "#FFD15C" },
    silhouette: "Squared head with a heavy jaw and thin level visor; amber chest plate; stamp arm.",
    equipment: ["level visor", "amber chest plate", "stamp arm", "checklist"],
    workMotion: "Stamp arm comes down: thunk.",
    scale: SCALE.worker,
    directions: ["down", "up", "left", "right"],
    anim: anim(3, 200),
  },
  {
    id: "spark",
    name: "SPARK",
    job: "Moment Finder",
    rank: "worker",
    department: "clip_studio",
    managerId: "frame",
    duty: "Finds the most exciting moments inside long videos.",
    palette: { trim: "#FFD43B", accent: "#FFB000", shell: "#ECEDF2", face: "#111830", eye: "#3FA9FF" },
    silhouette: "Compact round ball body; star-tipped antenna; one big circular camera lens.",
    equipment: ["star antenna", "big lens eye", "waveform marker"],
    workMotion: "Lens focuses and the marker flashes.",
    scale: SCALE.worker,
    directions: ["down", "up", "left", "right"],
    anim: anim(2, 240),
  },
  {
    id: "story",
    name: "STORY",
    job: "Story Editor",
    rank: "worker",
    department: "clip_studio",
    managerId: "frame",
    duty: "Arranges moments into a clear beginning, middle and end.",
    palette: { trim: "#FF6F61", accent: "#FFB4A8", shell: "#ECE9E8", face: "#1E1418", eye: "#FF8A7A" },
    silhouette: "Wide soft-rectangle head with a book-spine side ridge; three storyboard cards across the chest.",
    equipment: ["book-spine ridge", "paired panel eyes", "three-card storyboard"],
    workMotion: "Storyboard cards shuffle.",
    scale: SCALE.worker,
    directions: ["down", "up", "left", "right"],
    anim: anim(3, 260),
  },
  {
    id: "boost",
    name: "BOOST",
    job: "Viral Analyst",
    rank: "worker",
    department: "analyze",
    managerId: "vector",
    duty: "Predicts how well a clip will do and suggests what to change.",
    palette: { trim: "#2EE6C8", accent: "#1FB5A0", shell: "#E5EEF0", face: "#0D1A22", eye: "#5CF2FF" },
    silhouette: "Swept-back helmet with fins; upward-angled eye frame; leaning-forward stance.",
    equipment: ["swept fin helmet", "angled eye frame", "response-curve tablet"],
    workMotion: "Curve on the tablet climbs.",
    scale: SCALE.worker,
    directions: ["down", "up", "left", "right"],
    anim: anim(4, 200),
  },
  {
    id: "splice",
    name: "SPLICE",
    job: "Video Editor",
    rank: "worker",
    department: "clip_studio",
    managerId: "frame",
    duty: "Cuts and crops the chosen moment into a vertical clip.",
    palette: { trim: "#FF3DAD", accent: "#FF8A2A", shell: "#E9E7EE", face: "#120F24", eye: "#5CD6FF" },
    silhouette: "Wide rectangular head with oversized ear cups; film reel pack; control pad.",
    equipment: ["orange ear cups", "magenta torso", "film reel pack", "editing control pad"],
    workMotion: "Scrubs the control pad; reel spins.",
    scale: SCALE.worker,
    directions: ["down", "up", "left", "right"],
    anim: anim(4, 170),
  },
  {
    id: "glyph",
    name: "GLYPH",
    job: "Caption Agent",
    rank: "worker",
    department: "caption",
    managerId: "script",
    duty: "Writes the on-screen captions and times them to the speech.",
    palette: { trim: "#9A6BFF", accent: "#C08BFF", shell: "#ECEAF3", face: "#140F2A", eye: "#C9A8FF" },
    silhouette: "Rounded monitor head with key-shaped CC side tabs; CC chest tile; mini keyboard.",
    equipment: ["monitor head", "CC key tabs", "CC chest tile", "mini keyboard"],
    workMotion: "Types on the mini keyboard.",
    scale: SCALE.worker,
    directions: ["down", "up", "left", "right"],
    anim: anim(4, 140),
  },
  {
    id: "quill",
    name: "QUILL",
    job: "Title Agent",
    rank: "worker",
    department: "caption",
    managerId: "script",
    duty: "Writes the post title, description and hashtags.",
    palette: { trim: "#FF5C8A", accent: "#FFC2D4", shell: "#EEE9EC", face: "#1E0F18", eye: "#FF6FA0" },
    silhouette: "Slim trapezoid head with a pencil antenna; narrow bright eyes; label printer.",
    equipment: ["pencil antenna", "narrow eyes", "title-label printer (Aa)"],
    workMotion: "Prints an Aa label strip.",
    scale: SCALE.worker,
    directions: ["down", "up", "left", "right"],
    anim: anim(3, 220),
  },
  {
    id: "check",
    name: "CHECK",
    job: "Quality Control",
    rank: "worker",
    department: "system",
    managerId: "switch",
    duty: "Inspects each finished clip for problems before it is posted.",
    palette: { trim: "#57EEA0", accent: "#2FD27A", shell: "#E6ECEB", face: "#0E1A22", eye: "#49C6FF" },
    silhouette: "Broad shield-shaped torso; square inspection visor; check paddle.",
    equipment: ["shield torso", "square inspection visor", "scanner", "check paddle"],
    workMotion: "Scanner beam passes, then the paddle flips to a check.",
    scale: SCALE.worker,
    directions: ["down", "up", "left", "right"],
    anim: anim(4, 200),
  },
  {
    id: "lock",
    name: "LOCK",
    job: "Audience Verification",
    rank: "worker",
    department: "upload_dock",
    managerId: "harbor",
    duty: "Confirms each post goes to the right account and audience.",
    palette: { trim: "#3E8BFF", accent: "#7FB2FF", shell: "#C9D6E6", face: "#0D1830", eye: "#5CC8FF" },
    silhouette: "Steel-blue hexagonal head with a lock-shaped face; shield chest; ID card.",
    equipment: ["hex head", "lock face surround", "shield chest", "account-ID reader card"],
    workMotion: "Shackle clicks shut as the ID card is read.",
    scale: SCALE.worker,
    directions: ["down", "up", "left", "right"],
    anim: anim(2, 300),
  },
  {
    id: "dock",
    name: "DOCK",
    job: "Publisher",
    rank: "worker",
    department: "upload_dock",
    managerId: "harbor",
    duty: "Uploads the finished clip to each platform.",
    palette: { trim: "#FF8A2A", accent: "#C98A44", shell: "#FF9B3D", face: "#151A2A", eye: "#9FE8FF" },
    silhouette: "Orange box body on a wheel base (no legs); uplink antenna; parcel carrier.",
    equipment: ["wheel base", "two square eyes", "uplink antenna", "parcel carrier"],
    workMotion: "Conveyor rollers load the parcel.",
    scale: SCALE.worker,
    directions: ["down", "up", "left", "right"],
    anim: anim(4, 170),
  },
  {
    id: "metric",
    name: "METRIC",
    job: "Analytics Agent",
    rank: "worker",
    department: "brain",
    managerId: "curator",
    duty: "Collects views and likes after posting and reports what worked.",
    palette: { trim: "#22D3EE", accent: "#0EA5C6", shell: "#E5ECF2", face: "#0B1828", eye: "#3FE6FF" },
    silhouette: "Round head with three unequal bar fins on top; round display visor; data notebook.",
    equipment: ["three bar fins", "circular bar display", "data notebook"],
    workMotion: "Display bars rise; pen ticks.",
    scale: SCALE.worker,
    directions: ["down", "up", "left", "right"],
    anim: anim(4, 200),
  },
  {
    id: "synapse",
    name: "SYNAPSE",
    job: "Learning Agent",
    rank: "worker",
    department: "brain",
    managerId: "curator",
    duty: "Turns results into lessons the team uses next time.",
    palette: { trim: "#C69CFF", accent: "#9A6BFF", shell: "#ECE8F6", face: "#150F30", eye: "#B98CFF" },
    silhouette: "Pear-shaped body; translucent rounded head cap with nodes; forked node antenna.",
    equipment: ["glass head cap", "forked node antenna", "node shoulder pattern", "brain card"],
    workMotion: "Nodes in the cap light up in a chain.",
    scale: SCALE.worker,
    directions: ["down", "up", "left", "right"],
    anim: anim(4, 220),
  },
  {
    id: "patch",
    name: "PATCH",
    job: "System Guardian",
    rank: "worker",
    department: "system",
    managerId: "switch",
    duty: "Watches for errors and fixes the machinery when something breaks.",
    palette: { trim: "#FF8A1F", accent: "#FFB020", shell: "#4C5463", face: "#12141A", eye: "#FFC93C" },
    silhouette: "Stocky industrial body; beacon cap on top; wrench arm; diagnostic pack.",
    equipment: ["rotating beacon cap", "orange safety strips", "wrench arm", "diagnostic pack"],
    workMotion: "Beacon rotates while the wrench turns.",
    scale: SCALE.worker,
    directions: ["down", "up", "left", "right"],
    anim: anim(4, 160),
  },
];

/** CORE is the brain chamber: a stationary object, not a robot and not counted in ROLES. */
export type CoreActivity = "idle" | "lookup" | "evaluating" | "updating";
export const CORE = {
  id: "core",
  name: "CORE",
  job: "Brain Core",
  duty: "Stores what the team has learned so every robot can look it up.",
  department: "brain" as DepartmentId,
  palette: { glass: "#9A6BFF", glow: "#28D9FF", base: "#2A3350", brain: "#E7C8FF" },
  activities: ["idle", "lookup", "evaluating", "updating"] as CoreActivity[],
  anim: { frames: 4, ms: 260 },
} as const;

export interface Department {
  id: DepartmentId;
  label: string;
  color: string;
  managerId: RoleId;
  workerIds: RoleId[];
}

export const DEPARTMENTS: Department[] = [
  { id: "boss_hub", label: "Boss Hub", color: "#F5C542", managerId: "command", workerIds: [] },
  { id: "discover", label: "Discover", color: "#8EE83A", managerId: "tracker", workerIds: ["radar", "archive"] },
  { id: "analyze", label: "Analyze", color: "#2F6BFF", managerId: "vector", workerIds: ["pulse", "gavel", "boost"] },
  {
    id: "clip_studio",
    label: "Clip Studio",
    color: "#FF3DAD",
    managerId: "frame",
    workerIds: ["spark", "story", "splice"],
  },
  { id: "caption", label: "Captions", color: "#9A6BFF", managerId: "script", workerIds: ["glyph", "quill"] },
  { id: "schedule", label: "Schedule", color: "#FFAB45", managerId: "clock", workerIds: [] },
  { id: "upload_dock", label: "Upload Dock", color: "#2FCB6B", managerId: "harbor", workerIds: ["lock", "dock"] },
  { id: "system", label: "System", color: "#FFB020", managerId: "switch", workerIds: ["check", "patch"] },
  { id: "brain", label: "Brain", color: "#B79CFF", managerId: "curator", workerIds: ["metric", "synapse"] },
];

const BY_ID = new Map<string, RobotRole>(ROLES.map((r) => [r.id, r]));

export function roleById(id: string): RobotRole | undefined {
  return BY_ID.get(id);
}

export function departmentById(id: DepartmentId): Department | undefined {
  return DEPARTMENTS.find((d) => d.id === id);
}

/**
 * Fallback rules used by the sprite renderer. Kept here so callers can reason about them:
 * - unknown direction -> "down"
 * - unknown state -> "idle"
 * - frame index wraps modulo the state's frame count (negative counts from the end)
 */
export function resolveDirection(dir: string | undefined): Direction {
  return (DIRECTIONS as readonly string[]).includes(dir ?? "") ? (dir as Direction) : "down";
}
export function resolveState(state: string | undefined): AnimState {
  return (ANIM_STATES as readonly string[]).includes(state ?? "") ? (state as AnimState) : "idle";
}

/** Returns a list of human-readable problems; empty means the registry is consistent. */
export function validateRegistry(roles: RobotRole[] = ROLES, departments: Department[] = DEPARTMENTS): string[] {
  const problems: string[] = [];
  const count = (rank: Rank) => roles.filter((r) => r.rank === rank).length;
  if (count("director") !== 1) problems.push(`expected exactly 1 director, found ${count("director")}`);
  if (count("manager") !== 8) problems.push(`expected 8 managers, found ${count("manager")}`);
  if (count("worker") !== 16) problems.push(`expected 16 workers, found ${count("worker")}`);
  if (roles.length !== 25) problems.push(`expected 25 roles, found ${roles.length}`);
  const ids = new Set<string>();
  const byId = new Map<string, RobotRole>();
  for (const r of roles) {
    if (ids.has(r.id)) problems.push(`duplicate id ${r.id}`);
    ids.add(r.id);
    byId.set(r.id, r);
  }
  if (ids.has("core")) problems.push("CORE must not be a role");
  for (const r of roles) {
    for (const d of DIRECTIONS) if (!r.directions.includes(d)) problems.push(`${r.id} missing direction ${d}`);
    for (const s of ANIM_STATES) {
      const a = r.anim[s];
      if (!a || a.frames < 1 || a.ms.length !== a.frames) problems.push(`${r.id} has bad timing for ${s}`);
    }
    if (r.anim.work.frames < 2 || r.anim.work.frames > 4) problems.push(`${r.id} work must have 2-4 frames`);
    if (r.rank === "director" && r.managerId !== null) problems.push(`${r.id} director must have no manager`);
    if (r.rank === "manager" && r.managerId !== "command") problems.push(`${r.id} manager must report to command`);
    if (r.rank === "worker") {
      const m = r.managerId ? byId.get(r.managerId) : undefined;
      if (!m) problems.push(`${r.id} manager ${r.managerId} does not exist`);
      else {
        if (m.rank !== "manager") problems.push(`${r.id} manager ${m.id} is not a manager`);
        if (m.department !== r.department)
          problems.push(`${r.id} is in ${r.department} but ${m.id} runs ${m.department}`);
      }
    }
  }
  for (const d of departments) {
    const m = byId.get(d.managerId);
    if (!m || m.department !== d.id) problems.push(`department ${d.id} manager ${d.managerId} mismatch`);
    for (const w of d.workerIds) {
      const r = byId.get(w);
      if (!r || r.department !== d.id || r.managerId !== d.managerId)
        problems.push(`department ${d.id} worker ${w} mismatch`);
    }
  }
  for (const r of roles) {
    if (r.rank === "worker" && !departments.some((d) => d.workerIds.includes(r.id)))
      problems.push(`${r.id} not listed in a department`);
  }
  return problems;
}
