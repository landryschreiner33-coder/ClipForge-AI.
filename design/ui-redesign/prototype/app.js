/*
 * ClipFoundry redesign prototype (sample data only).
 * No network requests, no app APIs, no file system access: every action changes this page's memory and says so.
 * Plain browser JavaScript so the prototype opens from disk with a double-click (no build step, no dependencies).
 */
(function () {
  "use strict";

  // ================================================================== tiny HTML helpers
  const RAW = Symbol("raw");
  const raw = (s) => ({ [RAW]: String(s) });
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  function val(v) {
    if (v === null || v === undefined || v === false || v === true) return "";
    if (Array.isArray(v)) return v.map(val).join("");
    if (typeof v === "object" && RAW in v) return v[RAW];
    return esc(v);
  }
  function h(strings, ...vals) {
    let out = "";
    strings.forEach((s, i) => { out += s; if (i < vals.length) out += val(vals[i]); });
    return raw(out);
  }
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many || one + "s"}`;
  const fmt = (sec) => {
    const s = Math.max(0, Math.round(sec)); const m = Math.floor(s / 60); const r = s % 60;
    return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`;
  };
  const fmtPrecise = (sec) => { const m = Math.floor(sec / 60); return `${m}:${(sec - m * 60).toFixed(1).padStart(4, "0")}`; };
  // "Today, 5:25 PM" -> "today at 5:25 PM" for use inside a sentence.
  const at = (when) => { const m = /^([^,]+), (.+)$/.exec(when || ""); return m ? `${/^(Today|Tomorrow|Yesterday)$/.test(m[1]) ? m[1].toLowerCase() : m[1]} at ${m[2]}` : when; };
  const num = (n) => (n === null || n === undefined ? "—" : n.toLocaleString("en-US"));

  // ================================================================== icons (one stroke style, 24px grid)
  const PATHS = {
    home: "M4 11l8-7 8 7M6 9.5V20h12V9.5M10 20v-6h4v6",
    autopilot: "M12 3a9 9 0 1 0 9 9M12 7v5l3 2M17 3h4v4M21 3l-5 5",
    library: "M4 5h6v14H4zM14 5l6 1.5-3 13-6-1.5",
    posts: "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4M8 14h3v3H8z",
    settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
    plus: "M12 5v14M5 12h14",
    upload: "M12 16V4M7 9l5-5 5 5M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2",
    play: "M8 5l11 7-11 7z",
    pause: "M8 5h3v14H8zM13 5h3v14h-3z",
    edit: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
    download: "M12 4v12M7 11l5 5 5-5M4 20h16",
    trash: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13",
    check: "M5 12l5 5 9-10",
    x: "M6 6l12 12M18 6L6 18",
    refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6",
    film: "M4 4h16v16H4zM8 4v16M16 4v16M4 8h4M4 12h4M4 16h4M16 8h4M16 12h4M16 16h4",
    link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
    cpu: "M7 7h10v10H7zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4",
    back: "M15 5l-7 7 7 7",
    scissors: "M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM8.1 7.9L20 20M8.1 16.1L20 4",
    stop: "M6 6h12v12H6z",
    shield: "M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6zM9 12l2 2 4-4",
    alert: "M12 4l9 16H3zM12 10v4M12 17.5v.5",
    info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v6M12 7.5v.5",
    clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
    folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
    moon: "M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z",
    menu: "M4 7h16M4 12h16M4 17h16",
    more: "M5 12h.01M12 12h.01M19 12h.01",
    chev: "M9 6l6 6-6 6",
    external: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
    offline: "M3 3l18 18M8.5 16.5a5 5 0 0 1 7 0M5 12.5a10 10 0 0 1 4-2.4M19 12.5a10 10 0 0 0-3.3-2.1M2 8.8a15 15 0 0 1 4.5-2.9M22 8.8A15 15 0 0 0 12 5M12 20h.01",
    question: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.5V14M12 17.5v.5",
    dot: "M12 12h.01",
    spark: "M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2z",
    user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
    sliders: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4",
  };
  const icon = (name, cls = "") => raw(`<svg class="icon ${cls}" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="${PATHS[name]}"/></svg>`);
  const TONE_ICON = { good: "check", warn: "alert", bad: "alert", info: "info", neutral: "info", accent: "spark" };
  const pill = (tone, text, ic) => h`<span class="pill ${tone === "good" && lost() ? "neutral" : tone}">${icon(ic || TONE_ICON[tone] || "info")}${text}</span>`;
  const PNAME = { youtube: "YouTube", tiktok: "TikTok" };
  const platform = (p, extra = "") => h`<span class="platform"><span class="pmark ${p}" aria-hidden="true">${p === "youtube" ? "YT" : "TT"}</span>${PNAME[p]}${extra ? raw(` <span class="muted">${esc(extra)}</span>`) : ""}</span>`;

  // ================================================================== sample "video" pictures (drawn, not photos)
  let gid = 0;
  const SCENES = [
    { bg: ["#3b2a22", "#17110e"], light: "#ffb36b", body: "#0f0c0b", extra: "mic" },      // warm podcast studio
    { bg: ["#4a3a2e", "#1c1612"], light: "#ffd9a0", body: "#140f0c", extra: "window" },   // kitchen table
    { bg: ["#1f2747", "#0d1020"], light: "#7aa8ff", body: "#090b16", extra: "screen" },   // livestream
    { bg: ["#2f4a36", "#101a13"], light: "#cfe8a8", body: "#0b120d", extra: "hill" },     // trail
    { bg: ["#40263a", "#170d15"], light: "#ff9fc4", body: "#100a0f", extra: "mic" },
    { bg: ["#233a44", "#0c171c"], light: "#8fe0e8", body: "#081013", extra: "window" },
  ];
  function scene(seed, vertical, captions) {
    const sc = SCENES[(seed || 0) % SCENES.length];
    const id = `g${++gid}`;
    const W = vertical ? 90 : 160; const H = vertical ? 160 : 90;
    const cx = vertical ? 45 : 64 + ((seed * 7) % 20);
    const headY = vertical ? 70 : 38; const headR = vertical ? 13 : 9;
    let extra = "";
    if (sc.extra === "mic") extra = `<rect x="${cx + (vertical ? 10 : 14)}" y="${headY + 8}" width="${vertical ? 6 : 5}" height="${vertical ? 14 : 11}" rx="3" fill="#2b2b2b"/><rect x="${cx + (vertical ? 12.5 : 16)}" y="${headY + 20}" width="1.5" height="${vertical ? 40 : 30}" fill="#222"/>`;
    if (sc.extra === "window") extra = `<rect x="${vertical ? 8 : 18}" y="${vertical ? 18 : 12}" width="${vertical ? 30 : 34}" height="${vertical ? 40 : 26}" rx="2" fill="${sc.light}" opacity=".18"/><rect x="0" y="${vertical ? 118 : 70}" width="${W}" height="${vertical ? 42 : 20}" fill="#2a2018" opacity=".9"/>`;
    if (sc.extra === "screen") extra = `<rect x="${vertical ? 10 : 96}" y="${vertical ? 14 : 14}" width="${vertical ? 70 : 50}" height="${vertical ? 34 : 30}" rx="2" fill="${sc.light}" opacity=".28"/>`;
    if (sc.extra === "hill") extra = `<path d="M0 ${H * 0.62} Q ${W * 0.35} ${H * 0.45} ${W * 0.7} ${H * 0.6} T ${W} ${H * 0.55} V ${H} H 0z" fill="#1d3223"/><path d="M${W * 0.45} ${H} L ${W * 0.55} ${H * 0.62} L ${W * 0.62} ${H} z" fill="#6b5a44" opacity=".6"/>`;
    const second = !vertical && sc.extra !== "hill" ? `<circle cx="${cx - 40}" cy="${headY + 4}" r="${headR * 0.85}" fill="${sc.body}" opacity=".85"/><path d="M${cx - 58} 90 Q ${cx - 40} ${headY + 12} ${cx - 22} 90z" fill="${sc.body}" opacity=".85"/>` : "";
    const cap = captions ? `<rect x="14" y="112" width="62" height="7" rx="2" fill="#fff" opacity=".92"/><rect x="22" y="121" width="46" height="7" rx="2" fill="${captions === "hl" ? "#ffe500" : "#fff"}" opacity=".92"/>` : "";
    return raw(`<svg class="scene" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">
      <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${sc.bg[0]}"/><stop offset="1" stop-color="${sc.bg[1]}"/></linearGradient>
      <radialGradient id="${id}l" cx=".7" cy=".25" r=".6"><stop offset="0" stop-color="${sc.light}" stop-opacity=".35"/><stop offset="1" stop-color="${sc.light}" stop-opacity="0"/></radialGradient></defs>
      <rect width="${W}" height="${H}" fill="url(#${id})"/><rect width="${W}" height="${H}" fill="url(#${id}l)"/>${extra}${second}
      <circle cx="${cx}" cy="${headY}" r="${headR}" fill="${sc.body}"/><path d="M${cx - headR * 2.2} ${H} Q ${cx} ${headY + headR * 0.8} ${cx + headR * 2.2} ${H}z" fill="${sc.body}"/>${cap}</svg>`);
  }
  function thumb(seed, { vertical = false, label = "", corner = "", captions = false, overlay = null, alt = "" } = {}) {
    const missing = ui.demo.noThumbs;
    return h`<span class="thumb ${vertical ? "v" : ""}" ${alt ? raw(`role="img" aria-label="${esc(alt)}"`) : raw('aria-hidden="true"')}>
      ${missing ? h`<span class="missing">${icon("film")}<span>No preview yet</span></span>` : scene(seed, vertical, captions)}
      ${label ? h`<span class="corner-l">${label}</span>` : ""}
      ${corner ? h`<span class="corner tnum">${corner}</span>` : ""}
      ${overlay ? h`<span class="overlay">${overlay}</span>` : ""}</span>`;
  }

  // ================================================================== state
  const SAMPLE = window.CF_SAMPLE;
  let S = SAMPLE.build("ready");
  const ui = {
    scenario: "ready",
    demo: { longNames: false, noThumbs: false, loading: false, panel: false },
    drawer: false,
    menu: null,              // id of the open row menu
    libFilter: "all", libQuery: "",
    selected: new Set(["c1", "c2"]),
    edit: null,              // clip editor draft
    add: { file: null, progress: null, url: "", tab: "file" },
    setup: { how: "", topics: ["podcasts", "interviews", "comedy"] },
    postsAll: false,
    settings: null,          // settings draft
    settingsErrors: {},
    review: {},              // per post: form state
    replaceSecret: {},
  };
  let timers = [];

  function applyDemoOverrides() {
    if (ui.demo.longNames) {
      const p1 = S.projects.find((p) => p.id === "p1");
      if (p1) p1.name = "Sample: Morning Mic podcast, episode 12 with three guests, the listener mailbag and the unedited bonus segment (2026-09-28 FINAL final v3)";
      const c1 = S.clips.find((c) => c.id === "c1");
      if (c1) c1.title = "You don't need expensive gear, a sound booth or a big audience to start a podcast that people actually finish";
      if (S.accounts.youtube.name) S.accounts.youtube.name = "Sample channel · Morning Mic Podcast Network, clips and highlights";
    }
  }
  function load(scenario) {
    ui.scenario = scenario;
    S = SAMPLE.build(scenario);
    applyDemoOverrides();
    ui.selected = new Set(S.clips.filter((c) => c.selected).map((c) => c.id));
    ui.edit = null; ui.settings = null; ui.review = {}; ui.add = { file: null, progress: null, url: "", tab: "file" };
    stopTimers();
    startSimulations();
  }

  const project = (id) => S.projects.find((p) => p.id === id);
  const clip = (id) => S.clips.find((c) => c.id === id);
  const post = (id) => S.posts.find((p) => p.id === id);
  const clipsOf = (pid) => S.clips.filter((c) => c.projectId === pid);
  const postsOf = (cid) => S.posts.filter((p) => p.clipId === cid);
  const lost = () => S.connection === "lost";
  const accOk = (p) => S.accounts[p].state === "connected";

  // ------------------------------------------------------------------ post status words (exact, never softened)
  function postStatus(p) {
    switch (p.status) {
      case "awaiting_approval": return p.needsNewOk ? ["warn", "Needs a new OK: the video changed", "alert"] : ["warn", "Needs your OK", "clock"];
      case "approved": return p.approvedBy === "automatic" ? ["good", "Approved automatically", "shield"] : ["good", "Approved by you", "check"];
      case "publishing": return ["info", "Uploading now", "upload"];
      case "published": return p.onPlatform ? ["info", "Uploaded, waiting for its time", "clock"] : ["good", "Published", "check"];
      case "reconciling": return ["warn", "Upload not confirmed", "question"];
      case "failed": return ["bad", "Failed", "alert"];
      case "blocked": return ["bad", "Blocked by the final check", "shield"];
      case "action_needed": return ["info", "Finish in the TikTok app", "info"];
      case "canceled": return ["neutral", "Canceled", "x"];
      case "replaced": return ["neutral", "Replaced by a stronger clip", "refresh"];
      default: return ["neutral", p.status, "info"];
    }
  }
  const VIEW_OF = {
    review: (p) => p.status === "awaiting_approval",
    scheduled: (p) => p.status === "approved" || p.status === "publishing" || (p.status === "published" && p.onPlatform),
    published: (p) => p.status === "published" && !p.onPlatform,
    history: (p) => (p.status === "published" && !p.onPlatform) || ["canceled", "replaced"].includes(p.status),
    problems: (p) => ["reconciling", "failed", "blocked", "action_needed"].includes(p.status),
  };
  const postsIn = (view) => S.posts.filter(VIEW_OF[view]);

  // ------------------------------------------------------------------ what needs you (same order as autopilot/home.py)
  function needsYou() {
    if (lost()) return [];
    const items = [];
    for (const p of ["youtube", "tiktok"]) {
      const a = S.accounts[p];
      if (a.state === "expired") {
        const planned = S.posts.filter((x) => x.platform === p && ["awaiting_approval", "approved", "publishing"].includes(x.status)).length;
        items.push({ key: `account:${p}`, tone: "bad", icon: "link", title: `Sign in to ${PNAME[p]} again`,
          detail: `${PNAME[p]} stopped accepting ClipFoundry's sign-in, so ${planned ? plural(planned, "planned post") + " can't go out" : "Autopilot can't post there"}.`,
          actions: [{ label: `Reconnect ${PNAME[p]}`, action: "reconnect", id: p, primary: true }] });
      }
    }
    if (S.autopilot.enabled && S.autopilot.keepAwake === "failed") {
      items.push({ key: "sleep", tone: "bad", icon: "moon", title: "Your PC may go to sleep and stop Autopilot",
        detail: "ClipFoundry asked Windows to keep this PC awake, but Windows said no. While the PC sleeps, Autopilot finds, clips and posts nothing.",
        steps: ["Open Windows Settings, then System.", "Choose Power & sleep (Windows 10) or Power & battery (Windows 11).",
          "Set the sleep time for “When plugged in” to Never.", "Keep the PC plugged in and a laptop's lid open."],
        after: "ClipFoundry tries again every minute. This message goes away by itself once Windows agrees." });
    }
    if (S.autopilot.gpu.state === "problem") {
      items.push({ key: "gpu", tone: "bad", icon: "cpu", title: "GPU transcription is not working", detail: S.autopilot.gpu.detail,
        fix: S.autopilot.gpu.fix, actions: [{ label: "Open GPU settings", href: "#/settings/advanced", primary: false }] });
    }
    const waiting = postsIn("review");
    if (waiting.length) {
      items.push({ key: "approve", tone: "warn", icon: "clock", title: `${plural(waiting.length, "post is", "posts are")} waiting for your OK`,
        detail: S.autopilot.autoPublish.youtube.enabled ? "TikTok needs your OK on each post (its rules)." :
          "TikTok needs your OK on each post. YouTube does too while automatic publishing is off.",
        actions: [{ label: "Review posts", href: "#/posts/review", primary: true }] });
    }
    const probs = postsIn("problems");
    if (probs.length) {
      const unconfirmed = probs.filter((p) => p.status === "reconciling").length;
      items.push({ key: "publish", tone: unconfirmed ? "warn" : "bad", icon: unconfirmed ? "question" : "alert",
        title: unconfirmed ? `An upload was not confirmed${probs.length > 1 ? `, and ${plural(probs.length - 1, "more post needs", "more posts need")} attention` : ""}` : `${plural(probs.length, "post needs", "posts need")} attention`,
        detail: unconfirmed ? "ClipFoundry won't upload it again by itself, so it can never post twice. Check YouTube, then tell it what you found." : "Open Problems to see what went wrong and what to do.",
        actions: [{ label: "Open problems", href: "#/posts/problems", primary: false }] });
    }
    const usable = S.projects.some((p) => p.status === "processing") || S.autopilot.working || S.myVideos.videos > 0;
    if (S.setupDone && S.autopilot.enabled && !usable) {
      items.push({ key: "videos", tone: "info", icon: "folder", title: "Autopilot needs videos to work with",
        detail: `${S.autopilot.skipped24h ? `The ${plural(S.autopilot.skipped24h, "video")} it found online belong to other people, so it skipped them. ` : ""}Put videos you made in your videos folder, and Autopilot turns them into clips by itself.`,
        actions: [{ label: "Open videos folder", action: "open-folder", primary: true }, { label: "Add a video yourself", href: "#/create" }] });
    }
    for (const p of S.projects.filter((x) => x.status === "error")) {
      items.push({ key: `err:${p.id}`, tone: "bad", icon: "alert", title: `“${p.name}” could not be made into clips`, detail: p.error,
        actions: [{ label: "Open video", href: `#/project/${p.id}` }] });
    }
    return items;
  }

  function apState() {
    if (lost()) return { word: "Unknown", tone: "neutral", icon: "offline", detail: `No answer from ClipFoundry since ${S.lastUpdate}` };
    if (!S.setupDone && !S.autopilot.enabled) return { word: "Not set up", tone: "neutral", icon: "info", detail: "Set it up when you're ready" };
    if (S.autopilot.stopped) return { word: "Stopped", tone: "bad", icon: "stop", detail: "All jobs are on hold until you resume them" };
    if (!S.autopilot.enabled) return { word: "Paused", tone: "warn", icon: "pause", detail: "Nothing new is found, clipped or posted" };
    return { word: "On", tone: "good", icon: "check", detail: S.autopilot.currently };
  }

  const SLEEP = {
    on: ["good", "check", "Kept awake", "Windows agreed to keep this PC from sleeping while Autopilot is on. A laptop still sleeps if you close its lid."],
    pending: ["neutral", "clock", "Asking Windows", "ClipFoundry is asking Windows to keep this PC awake. This is not confirmed yet."],
    failed: ["bad", "alert", "Windows said no", "Windows did not let ClipFoundry keep this PC awake. Turn off sleep yourself: see Needs you."],
    off: ["neutral", "moon", "Not kept awake", "“Keep the PC awake” is off in Settings. Turn off sleep in the PC's power settings, or Autopilot stops when the PC sleeps."],
    unsupported: ["neutral", "moon", "Not available on this computer", "Turn off sleep in the PC's power settings, or Autopilot stops when the PC sleeps."],
  };
  function sleepFact() {
    if (lost()) return ["neutral", "offline", "Unknown", `No answer since ${S.lastUpdate}`];
    if (!S.autopilot.enabled || S.autopilot.stopped) return ["neutral", "moon", "Not kept awake", "Only while Autopilot is on."];
    return SLEEP[S.autopilot.keepAwake];
  }
  function gpuFact() {
    const g = S.autopilot.gpu;
    if (lost()) return ["neutral", "offline", "Unknown", `No answer since ${S.lastUpdate}`];
    if (g.state === "problem") return ["bad", "alert", "GPU found, transcription not working", "Autopilot pauses instead of switching to the slower CPU. See Needs you."];
    if (g.state === "cpu") return ["warn", "cpu", "CPU (slower) for the last video", "The RTX 3050 is installed, but the last transcription fell back to the CPU: CUDA could not start. Manual videos may do this; Autopilot waits instead."];
    if (g.state === "none") return ["neutral", "cpu", "CPU (no NVIDIA GPU found)", "Transcription works, more slowly."];
    return ["good", "cpu", "GPU · RTX 3050", `Transcription runs on the GPU (${g.model}).`];
  }

  // ================================================================== routing (old addresses keep working)
  const ALIASES = [
    [/^projects\/?$/, "library"],
    [/^publish-center\/?$/, "posts/review"],
    [/^publish-center\/upcoming$/, "posts/review"],
    [/^publish-center\/problems$/, "posts/problems"],
    [/^publish-center\/published$/, "posts/published"],
    [/^publish-center\/history$/, "posts/history"],
    [/^publish-center\/.*$/, "posts/review"],
    [/^autopilot\/overview$/, "autopilot/system"],
    [/^settings\/general$/, "settings"],
    [/^posts\/?$/, "posts/review"],
  ];
  const alias = (path) => { for (const [re, to] of ALIASES) if (re.test(path)) return to; return path; };
  let current = { path: null, parts: [] };
  let pendingLeave = null;

  function readPath() {
    let path = decodeURIComponent(location.hash.replace(/^#\/?/, "")).replace(/\/+$/, "");
    const to = alias(path);
    if (to !== path) { history.replaceState(null, "", `#/${to}`); path = to; }
    return path;
  }
  function onRoute() {
    const path = readPath();
    if (current.parts[0] === "clip" && ui.edit && ui.edit.dirty.size && path !== current.path && !pendingLeave) {
      const target = path;
      history.replaceState(null, "", `#/${current.path}`);
      askLeave(target);
      return;
    }
    pendingLeave = null;
    const changed = path !== current.path && current.path !== null;
    current = { path, parts: path.split("/").filter(Boolean) };
    ui.menu = null; ui.drawer = false;
    render({ focusHeading: changed });
    if (changed) window.scrollTo(0, 0);
  }
  const go = (path) => { location.hash = `#/${path}`; };

  // ================================================================== shell
  function navItems() {
    const review = postsIn("review").length; const probs = postsIn("problems").length;
    const st = apState();
    const sec = current.parts[0] || "";
    const active = { "": "home", setup: "home", autopilot: "autopilot", library: "library", project: "library", clip: "library",
      publish: "library", create: "library", posts: "posts", post: "posts", settings: "settings" }[sec] || "home";
    const item = (key, href, label, ic, extra) => h`<a href="${href}" ${active === key ? raw('aria-current="page"') : ""}>${icon(ic)}<span>${label}</span>${extra || ""}</a>`;
    return h`
      ${item("home", "#/", "Home", "home")}
      ${item("autopilot", "#/autopilot", "Autopilot", "autopilot", h`<span class="state ${st.tone === "good" ? "on" : st.tone}"><span class="sr-only">, </span>${st.word === "Not set up" ? "Off" : st.word}</span>`)}
      ${item("library", "#/library", "Library", "library")}
      ${item("posts", "#/posts/review", "Posts", "posts", review || probs ? h`<span class="count" title="${review} to review, ${probs} with problems"><span class="sr-only">, </span>${review || probs}<span class="sr-only"> ${review ? "to review" : "with problems"}</span></span>` : "")}
      <div class="nav-sep"></div>
      ${item("settings", "#/settings", "Settings", "settings")}`;
  }
  function shell() {
    document.getElementById("root").innerHTML = val(h`
      <a class="skip-link" href="#main" data-action="skip">Skip to content</a>
      <div class="demo-strip" role="note">
        <span class="demo-tag">Prototype</span>
        <span><b>Sample data.</b><span class="long"> Nothing here touches your videos, accounts or posts. Buttons marked “demo” only change this page.</span></span>
        <span class="spacer"></span>
        <button class="btn btn-small" type="button" data-action="demo-panel" aria-expanded="false" aria-controls="demo-panel">${icon("sliders")}<span class="long">Prototype controls</span><span class="short">Controls</span></button>
      </div>
      <header class="topbar">
        <button class="btn btn-small" type="button" data-action="drawer" aria-expanded="false" aria-controls="drawer">${icon("menu")}Menu</button>
        <a class="brand" href="#/">${logo(28)}<span class="brand-name">Clip<span>Foundry</span></span></a>
        <span class="spacer"></span>
        <span id="top-state"></span>
      </header>
      <div class="app">
        <aside class="sidebar" aria-label="ClipFoundry">
          <a class="brand" href="#/">${logo(32)}<span class="brand-name">Clip<span>Foundry</span></span></a>
          <nav class="nav" aria-label="Main" id="nav"></nav>
          <div class="sidebar-foot">
            <span>Runs on this computer. Publishing is optional and uses the official YouTube and TikTok APIs.</span>
            <span><button class="linkish" type="button" data-action="demo-note" data-note="In the app this opens the Terms page.">Terms</button> · <button class="linkish" type="button" data-action="demo-note" data-note="In the app this opens the Privacy page.">Privacy</button></span>
          </div>
        </aside>
        <main class="main" id="main" tabindex="-1"></main>
      </div>
      <div id="drawer-root"></div>
      <div id="dialog-root"></div>
      <div id="demo-root"></div>
      <div id="toast-root"></div>
      <div class="sr-only" id="live" role="status" aria-live="polite"></div>`);
  }
  function logo(size) {
    return raw(`<svg width="${size}" height="${size}" viewBox="0 0 64 64" role="img" aria-label="ClipFoundry logo"><defs><linearGradient id="lg${size}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffb13b"/><stop offset=".55" stop-color="#ff6a2b"/><stop offset="1" stop-color="#ff3d7f"/></linearGradient></defs><rect width="64" height="64" rx="16" fill="#1b1a24"/><path d="M22 14h20a4 4 0 0 1 4 4v28a4 4 0 0 1-4 4H22a4 4 0 0 1-4-4V18a4 4 0 0 1 4-4z" fill="none" stroke="url(#lg${size})" stroke-width="4"/><path d="M28 25l11 7-11 7z" fill="url(#lg${size})"/></svg>`);
  }

  // ================================================================== render
  function keyOf(el) {
    if (!el || el === document.body) return null;
    return el.id ? `#${el.id}` : [el.tagName, el.dataset.action, el.dataset.id, el.getAttribute("href"), el.name, el.value && el.type === "radio" ? el.value : ""].join("|");
  }
  function render(opts = {}) {
    const active = document.activeElement;
    const key = opts.focusHeading ? null : keyOf(active);
    const sel = active && "selectionStart" in active ? [active.selectionStart, active.selectionEnd] : null;
    document.getElementById("nav").innerHTML = val(navItems());
    const st = apState();
    document.getElementById("top-state").innerHTML = val(h`<a class="pill ${st.tone} plain" href="#/autopilot">${icon(st.icon)}Autopilot: ${st.word}</a>`);
    const main = document.getElementById("main");
    main.innerHTML = val(ui.demo.loading ? loadingPage() : page());
    renderDrawer();
    const h1 = main.querySelector("h1");
    document.title = `${h1 ? h1.textContent.trim() : "ClipFoundry"} · ClipFoundry prototype`;
    if (opts.focusHeading) {
      if (h1) { h1.setAttribute("tabindex", "-1"); h1.focus({ preventScroll: true }); }
    } else if (key) {
      const again = [...document.querySelectorAll("#root *")].find((el) => keyOf(el) === key);
      if (again) { again.focus({ preventScroll: true }); if (sel && "setSelectionRange" in again) try { again.setSelectionRange(sel[0], sel[1]); } catch (e) { /* not a text field */ } }
    }
    afterRender();
  }
  function page() {
    const [sec, a, b] = current.parts;
    switch (sec || "") {
      case "": return pageHome();
      case "setup": return pageSetup(a || "videos");
      case "autopilot": return pageAutopilot(a || "", b);
      case "library": return pageLibrary();
      case "create": return pageAdd();
      case "project": return project(a) ? pageProject(project(a)) : notFound("This video is not in your library", "#/library", "Open Library");
      case "clip": return clip(a) ? pageEditor(clip(a)) : notFound("This clip does not exist anymore", "#/library", "Open Library");
      case "publish": return clip(a) ? pagePrepare(clip(a)) : notFound("This clip does not exist anymore", "#/library", "Open Library");
      case "posts": return pagePosts(a || "review");
      case "post": return post(a) ? pageReview(post(a)) : notFound("This post does not exist anymore", "#/posts/review", "Open Posts");
      case "settings": return pageSettings(a || "accounts");
      default: return pageHome(true);
    }
  }
  function notFound(title, href, label) {
    return h`<div class="page narrow"><div class="page-head"><div><h1>${title}</h1><p class="muted">It may have been deleted, or the link is from an older version.</p></div></div>
      <div><a class="btn" href="${href}">${label}</a></div></div>`;
  }
  function loadingPage() {
    return h`<div class="page" aria-busy="true"><div class="page-head"><div><h1>Loading…</h1><p class="muted">Getting the latest from ClipFoundry.</p></div></div>
      <div class="skel" style="height:140px"></div><div class="cols-2"><div class="skel" style="height:220px"></div><div class="skel" style="height:220px"></div></div></div>`;
  }
  function connectionBanner() {
    if (!lost()) return "";
    return h`<div class="banner warn" role="alert">${icon("offline")}<div class="grow"><b>ClipFoundry isn't answering</b>
      <span class="small">The last update was at ${S.lastUpdate}, so what you see may be out of date. Check that the black ClipFoundry window is still open. If you closed it, start ClipFoundry again with start.bat.</span>
      <div class="actions"><button class="btn btn-small" type="button" data-action="reconnect-app">${icon("refresh")}Try again <span class="demo-mark">demo</span></button></div></div></div>`;
  }

  // ================================================================== HOME
  function pageHome(unknownRoute) {
    const items = needsYou();
    const st = apState();
    let lead;
    if (lost()) {
      lead = { tone: "warn", kicker: pill("neutral", "Status unknown", "offline"), sentence: "ClipFoundry isn't answering, so this page can't say what it's doing.",
        detail: `The last update was at ${S.lastUpdate}. Check that the black ClipFoundry window is still open.`,
        actions: [{ label: "Try again", action: "reconnect-app", primary: true, demo: true }] };
    } else if (!S.setupDone) {
      lead = { tone: "", kicker: pill("accent", "Welcome", "spark"), sentence: "Start by adding a video you made. ClipFoundry finds its best moments and turns them into short vertical clips.",
        detail: "Everything runs on this computer. Posting to YouTube or TikTok is optional and can wait.",
        actions: [{ label: "Get started", href: "#/setup/videos", primary: true }, { label: "Add a video now", href: "#/create" }] };
    } else if (items.length) {
      const it = items[0];
      lead = { tone: it.tone, kicker: pill(it.tone, "Needs you", it.icon), sentence: it.title, detail: it.detail, steps: it.steps, after: it.after, fix: it.fix, actions: it.actions || [] };
    } else if (S.autopilot.working && S.autopilot.enabled && !S.autopilot.stopped) {
      const w = S.autopilot.working;
      lead = { tone: "info", kicker: pill("info", "Working", "refresh"), sentence: `Autopilot is ${w.stage.toLowerCase()} in “${w.title}”.`,
        detail: "Nothing needs you. New clips show up in your Library, and posts that need your OK show up in Posts.",
        actions: [{ label: "See what it's doing", href: "#/autopilot", primary: true }] };
    } else if (S.projects.some((p) => p.status === "processing")) {
      const p = S.projects.find((x) => x.status === "processing");
      lead = { tone: "info", kicker: pill("info", "Working", "refresh"), sentence: `“${p.name}” is being turned into clips: ${p.message.toLowerCase()}.`,
        detail: "You can leave this page. The clips appear in your Library when they're ready.", actions: [{ label: "Open video", href: `#/project/${p.id}`, primary: true }] };
    } else if (S.clips.length) {
      const p = S.projects.find((x) => x.status === "ready" && clipsOf(x.id).length);
      lead = { tone: "good", kicker: pill("good", "All caught up", "check"), sentence: `Nothing needs you. Your newest clips are from “${p ? p.name : "your videos"}”.`,
        detail: S.autopilot.enabled ? "Autopilot keeps looking for videos it may use." : "Autopilot is paused, so nothing new starts by itself.",
        actions: [p ? { label: "See the clips", href: `#/project/${p.id}`, primary: true } : null, { label: "Add a video", href: "#/create" }].filter(Boolean) };
    } else {
      lead = { tone: "", kicker: pill("neutral", "All caught up", "check"), sentence: "Nothing needs you. Add a video to make clips.", actions: [{ label: "Add a video", href: "#/create", primary: true }] };
    }
    const also = S.setupDone && !lost() ? items.slice(1) : [];
    const recent = S.projects.slice(0, 4);
    const upcoming = [...postsIn("review"), ...postsIn("scheduled")].slice(0, 4);
    return h`<div class="page">
      ${unknownRoute ? h`<div class="banner info" role="status">${icon("info")}<div class="grow"><span class="small">That address doesn't exist in ClipFoundry, so you're on Home.</span></div></div>` : ""}
      ${connectionBanner()}
      <div class="page-head"><div><h1>Home</h1>
        <p class="muted small"><a class="textlink" href="#/autopilot">Autopilot: ${st.word}</a>${st.detail ? ` · ${st.detail}` : ""}</p></div>
        <div class="actions"><a class="btn" href="#/create">${icon("plus")}Add video</a></div></div>
      <section class="lead ${lead.tone}" aria-labelledby="lead-title">
        <div class="lead-top"><div class="grow">
          <div>${lead.kicker}</div>
          <h2 class="lead-sentence" id="lead-title">${lead.sentence}</h2>
          ${lead.detail ? h`<p class="muted">${lead.detail}</p>` : ""}
          ${lead.steps ? h`<ol class="steps-list">${lead.steps.map((s) => h`<li>${s}</li>`)}</ol>` : ""}
          ${lead.fix ? h`<p class="small"><b>What to do:</b> ${lead.fix}</p>` : ""}
          ${lead.after ? h`<p class="small faint">${lead.after}</p>` : ""}
        </div></div>
        ${lead.actions && lead.actions.length ? h`<div class="lead-actions">${lead.actions.map(actionBtn)}</div>` : ""}
        ${also.length ? h`<hr class="divider"><div class="also"><h3 class="small muted">Also needs you (${also.length})</h3>
          ${also.map((it) => h`<div class="also-item">${pill(it.tone, it.tone === "bad" ? "Problem" : it.tone === "warn" ? "Waiting" : "Info", it.icon)}<span class="also-title">${it.title}</span>${(it.actions || []).slice(0, 1).map((a) => actionBtn({ ...a, primary: false, small: true }))}${!it.actions ? h`<a class="btn btn-small" href="#/autopilot">See how to fix it</a>` : ""}</div>`)}</div>` : ""}
      </section>
      <div class="cols-main">
        <section class="panel" aria-labelledby="recent-title">
          <div class="panel-head"><h2 id="recent-title">Recent videos and clips</h2><a class="btn btn-quiet btn-small" href="#/library">Open Library</a></div>
          ${recent.length ? h`<div class="rows">${recent.map(recentRow)}</div>` : h`<div class="empty">${icon("film", "lg")}<p class="muted">No videos yet. Clips you make show up here.</p></div>`}
        </section>
        <section class="panel" aria-labelledby="up-title">
          <div class="panel-head"><h2 id="up-title">Coming up</h2><a class="btn btn-quiet btn-small" href="#/posts/scheduled">All posts</a></div>
          ${upcoming.length ? h`<div class="rows">${upcoming.map(upcomingRow)}</div><p class="tiny faint">Times in ${S.timezone} (${S.tzAbbr}).</p>` : h`<p class="muted small">No posts planned. ${S.setupDone ? "When clips are ready, planned posts show up here." : "Posting is optional: you can export clips and post them yourself."}</p>`}
        </section>
      </div>
    </div>`;
  }
  function actionBtn(a) {
    if (!a) return "";
    const cls = `btn ${a.primary ? "btn-primary" : ""} ${a.small ? "btn-small" : ""}`;
    if (a.href) return h`<a class="${cls}" href="${a.href}">${a.label}</a>`;
    return h`<button class="${cls}" type="button" data-action="${a.action}" data-id="${a.id || ""}">${a.label}${a.demo ? h` <span class="demo-mark">demo</span>` : ""}</button>`;
  }
  function recentRow(p) {
    const cs = clipsOf(p.id).slice(0, 5);
    return h`<div class="stack-3" style="padding:12px 0">
      <div class="row top"><a href="#/project/${p.id}" style="width:132px;flex:none" aria-hidden="true" tabindex="-1">${thumb(p.seed, { corner: p.duration })}</a>
        <div class="stack grow"><a class="post-title clamp-2" href="#/project/${p.id}">${p.name}</a>${projectStatusLine(p)}<span class="tiny faint">${p.origin} · ${p.created}</span></div></div>
      ${cs.length ? h`<div class="mini-clips" role="list" aria-label="Clips from ${p.name}">${cs.map((c) => h`<a class="mini" role="listitem" href="#/clip/${c.id}" aria-label="Edit clip: ${c.title}">${thumb(c.seed, { vertical: true, corner: fmt(c.duration), captions: true })}</a>`)}</div>` : ""}
    </div>`;
  }
  function upcomingRow(p) {
    const c = clip(p.clipId); const [tone, word, ic] = postStatus(p);
    return h`<div class="upcoming-row"><span class="when">${p.when.replace("Today, ", "")}</span>
      <span class="stack" style="gap:4px;min-width:0"><a class="post-title clamp-2 small" href="#/post/${p.id}">${c ? c.title : p.title}</a><span class="meta">${platform(p.platform)}${pill(tone, word, ic)}</span></span></div>`;
  }
  function projectStatusLine(p) {
    if (p.status === "processing") return /^Waiting/.test(p.message) ? pill("warn", p.message, "clock") : h`<span class="pill info">${icon("refresh")}${p.message}</span>`;
    if (p.status === "error") return pill("bad", "Couldn't make clips", "alert");
    if (p.status === "uploading") return pill("info", "Copying into ClipFoundry", "upload");
    const n = clipsOf(p.id).length;
    return n ? pill("good", `Ready · ${plural(n, "clip")}`, "check") : pill("neutral", "Ready · no clip passed the quality bar", "info");
  }

  // ================================================================== AUTOPILOT
  function pageAutopilot(sub, sub2) {
    const tabs = [["", "Overview"], ["activity", "Activity"], ["sources", "Permissions & sources"], ["system", "Advanced"]];
    const adv = ["system", "jobs", "learning"].includes(sub);
    const tabBar = h`<nav class="tabs" aria-label="Autopilot sections">${tabs.map(([k, l]) => h`<a href="#/autopilot${k ? "/" + k : ""}" ${(k === sub || (k === "system" && adv)) ? raw('aria-current="page"') : ""}>${l}</a>`)}</nav>`;
    let body;
    if (sub === "activity") body = apActivity();
    else if (sub === "sources") body = apSources();
    else if (adv) body = apAdvanced(sub);
    else body = apOverview();
    return h`<div class="page">${connectionBanner()}
      <div class="page-head"><div><h1>Autopilot</h1><p class="muted">Finds videos you may use, makes clips, checks them and plans posts. It never posts without an OK.</p></div></div>
      ${tabBar}${body}</div>`;
  }
  function apOverview() {
    const st = apState();
    const a = S.autopilot;
    if (!S.setupDone && !a.enabled) {
      return h`<section class="panel" aria-labelledby="ap-off"><h2 id="ap-off">Autopilot is not set up</h2>
        <p class="muted">Autopilot clips videos you made (from your videos folder) and videos it may use, like public-domain ones. It skips other people's videos. Nothing is posted without an OK.</p>
        <div class="row wrap"><a class="btn btn-primary" href="#/setup/mode">Set up Autopilot</a><a class="btn" href="#/create">Make clips yourself instead</a></div></section>`;
    }
    const [st1, si1, sw1, sd1] = sleepFact(); const [gt, gi, gw, gd] = gpuFact();
    const items = needsYou();
    const w = a.working;
    const up = [...postsIn("review"), ...postsIn("scheduled")].slice(0, 5);
    const blocking = items.filter((it) => it.tone === "bad").length;
    const on = st.word === "On";
    const headline = on && blocking ? `Autopilot is on, but ${plural(blocking, "problem needs", "problems need")} you` : `Autopilot is ${st.word.toLowerCase()}`;
    const dot = on ? (blocking ? "warn" : "on pulse") : st.tone === "bad" ? "bad" : st.tone === "warn" ? "warn" : "";
    return h`
      ${a.stopped ? h`<div class="banner bad" role="alert">${icon("stop")}<div class="grow"><b>All jobs are stopped.</b><span class="small">Nothing runs or posts until you resume. Work that was queued was canceled; running jobs stopped at a safe point.</span>
        <div class="actions"><button class="btn btn-primary" type="button" data-action="resume">Resume jobs <span class="demo-mark">demo</span></button></div></div></div>` : ""}
      <section class="panel" aria-labelledby="ap-state">
        <div class="ap-status">
          <div class="grow stack">
            <h2 class="big" id="ap-state"><span class="dot ${dot}"></span>${headline}</h2>
            <p class="muted">${st.detail}${on && w ? ` in “${w.title}”` : ""}</p>
          </div>
          ${!a.stopped && !lost() ? (a.enabled
            ? h`<button class="btn" type="button" data-action="pause">${icon("pause")}Pause Autopilot <span class="demo-mark">demo</span></button>`
            : h`<button class="btn btn-primary" type="button" data-action="start">${icon("play")}Start Autopilot <span class="demo-mark">demo</span></button>`) : ""}
        </div>
        <div class="facts">
          ${fact("This PC", st1, si1, sw1, sd1)}
          ${fact("Processing", gt, gi, gw, gd)}
          ${fact("Next online search", "neutral", "clock", lost() || !a.enabled || a.stopped ? "Not planned" : a.nextLook, "Looks online for videos it may use (every 3 hours).")}
          ${fact("Your videos folder", "neutral", "folder", lost() || !a.enabled || a.stopped ? "Not being checked" : "Checked every 3 minutes", "New videos you put there are picked up by themselves.")}
        </div>
        <p class="note">${icon("info")}<span>Keep this PC on and leave the black ClipFoundry window open: Autopilot only works while ClipFoundry runs.</span></p>
      </section>

      <section class="panel" aria-labelledby="ap-needs">
        <div class="panel-head"><h2 id="ap-needs">Needs you${items.length ? ` (${items.length})` : ""}</h2></div>
        ${lost() ? h`<p class="muted">Unknown: ClipFoundry hasn't answered since ${S.lastUpdate}.</p>` :
          items.length ? h`<div class="rows">${items.map((it, i) => needRow(it, i === 0))}</div>` : h`<p class="muted">Nothing right now. Autopilot asks here only when it really needs you.</p>`}
      </section>

      <div class="cols-2">
        <section class="panel" aria-labelledby="ap-now">
          <h2 id="ap-now">Working on</h2>
          ${w && a.enabled && !a.stopped ? h`<div class="row top"><div style="width:168px;flex:none">${thumb(w.seed, { corner: "Source video" })}</div>
            <div class="stack grow"><b class="clamp-2">${w.title}</b>
              <span class="small">${w.waiting ? pill("warn", w.waiting, "clock") : h`Now: <b>${w.stage}</b>`}</span>
              ${w.progress !== null && w.progress !== undefined && !w.waiting ? h`<div class="bar" role="progressbar" aria-label="${w.stage}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(w.progress * 100)}" data-live="ap-progress"><span style="width:${Math.round(w.progress * 100)}%"></span></div><span class="tiny faint" data-live="ap-progress-text">${Math.round(w.progress * 100)}% of this step, as the job reports it. No time estimate is available.</span>` : h`<span class="tiny faint">This step doesn't report progress.</span>`}
            </div></div>
            <ol class="stages" aria-label="Steps for this video">${w.stages.map((s, i) => h`<li class="${i < w.stageIndex ? "done" : i === w.stageIndex ? "now" : ""}" ${i === w.stageIndex ? raw('aria-current="step"') : ""}>${icon(i < w.stageIndex ? "check" : i === w.stageIndex ? "refresh" : "dot")}${s}</li>`)}</ol>`
          : h`<p class="muted">${a.enabled && !a.stopped ? "Nothing right now. It looks for new videos in your folder every 3 minutes and online every 3 hours." : "Nothing: Autopilot is " + (a.stopped ? "stopped." : "paused.")}</p>`}
          <hr class="divider">
          <div class="stack" aria-labelledby="myv"><h3 id="myv">Your videos</h3>
            <p class="small muted">Put videos you made here. Autopilot turns them into clips by itself.</p>
            <div class="row wrap"><button class="btn" type="button" data-action="open-folder">${icon("folder")}Open videos folder <span class="demo-mark">demo</span></button>
              <span class="small">${plural(S.myVideos.videos, "video")} · ${S.myVideos.watching ? pill("good", "Watched", "check") : pill("warn", "Not watched (turned off under Advanced)", "alert")}</span></div>
            <details class="plain"><summary>${icon("chev", "chev sm")}Show folder location</summary><div class="more-body"><code class="break">${S.myVideos.path}</code></div></details>
          </div>
        </section>
        <section class="panel" aria-labelledby="ap-up">
          <div class="panel-head"><h2 id="ap-up">Coming up</h2><a class="btn btn-quiet btn-small" href="#/posts/scheduled">All posts</a></div>
          ${up.length ? h`<div class="rows">${up.map(upcomingRow)}</div>` : h`<p class="muted small">No posts planned yet. Finished clips show up here with their posting time.</p>`}
          <hr class="divider">
          <h3>How posts go out</h3>
          ${autoPublishLines()}
        </section>
      </div>
      <p class="small muted">${S.autopilot.skipped24h ? `${plural(S.autopilot.skipped24h, "video")} skipped in the last 24 hours (not covered, no allowed way to get the file, too short or a repeat). ` : ""}<a class="textlink" href="#/autopilot/activity">See Activity</a> for what it did with each video it found.</p>
      <section class="panel tight" aria-labelledby="ap-stop">
        <h2 id="ap-stop" style="font-size:var(--fs-h3)">Pause or stop everything</h2>
        <div class="estop"><div class="grow stack small muted">
            <span><b>Pause Autopilot</b> (at the top) stops new work: nothing new is found, clipped or posted, and what's queued waits. Posts already uploaded to YouTube with a publish time still go public then, because YouTube does that itself.</span>
            <span><b>Stop all jobs</b> is the emergency stop: queued work is canceled and running jobs stop at their next safe point. Nothing starts again until you press Resume jobs.</span></div>
          ${a.stopped ? h`<button class="btn btn-primary" type="button" data-action="resume">Resume jobs <span class="demo-mark">demo</span></button>` : h`<button class="btn btn-danger" type="button" data-action="stop-all" ${lost() ? raw("disabled") : ""}>${icon("stop")}Stop all jobs…</button>`}</div>
      </section>`;
  }
  function fact(k, tone, ic, v, d) {
    return h`<div class="fact"><span class="k">${k}</span><span class="v ${tone}">${icon(ic)}<span>${v}</span></span>${d ? h`<span class="d">${d}</span>` : ""}</div>`;
  }
  function needRow(it, first) {
    return h`<div class="need ${it.tone}">${icon(it.icon)}<div class="need-body"><span class="need-title">${it.title}</span>
      ${it.detail ? h`<span class="small muted">${it.detail}</span>` : ""}
      ${it.steps ? h`<ol class="steps-list">${it.steps.map((s) => h`<li>${s}</li>`)}</ol>` : ""}
      ${it.fix ? h`<span class="small"><b>What to do:</b> ${it.fix}</span>` : ""}
      ${it.after ? h`<span class="tiny faint">${it.after}</span>` : ""}
      </div>${it.actions ? h`<div class="need-actions">${it.actions.map((a) => actionBtn({ ...a, primary: a.primary && first, small: true }))}</div>` : ""}</div>`;
  }
  function autoPublishLines() {
    const yt = S.autopilot.autoPublish.youtube;
    return h`<div class="stack-3">
      <div class="row wrap">${platform("youtube")}${yt.enabled ? pill("good", `Posts by itself: ${yt.visibility}, up to ${yt.dailyLimit} a day, ${yt.start}:00–${yt.end}:00`, "shield") : pill("neutral", "Waits for your OK on each post", "clock")}
        ${yt.enabled ? h`<button class="btn btn-small" type="button" data-action="autopub-off">Turn off</button>` : h`<button class="btn btn-small" type="button" data-action="autopub-dialog" ${accOk("youtube") ? "" : raw("disabled")}>Let YouTube posts go out without asking…</button>`}</div>
      ${!accOk("youtube") && !yt.enabled ? h`<p class="tiny faint">Connect YouTube first (Settings, Accounts).</p>` : ""}
      <div class="row wrap">${platform("tiktok")}${pill("neutral", "Your OK on each post", "clock")}<span class="tiny faint">${S.autopilot.autoPublish.tiktok.note}</span></div>
      <p class="tiny faint">Connecting an account never lets ClipFoundry post by itself. Automatic publishing is a separate permission that you turn on here.</p></div>`;
  }

  function apActivity() {
    return h`<section class="panel" aria-labelledby="found"><div class="panel-head"><h2 id="found">What Autopilot found</h2><span class="tiny faint">Scores are ClipFoundry's estimates, not platform numbers.</span></div>
        ${S.opportunities.length ? h`<div class="rows">${S.opportunities.map((o) => h`<div class="row wrap" style="padding:12px 0"><span class="score"><b>${o.score}</b>estimate</span><span class="grow stack" style="gap:0"><b>${o.title}</b><span class="tiny faint">${o.channel}</span></span>${pill(/made/.test(o.stage) ? "good" : "info", o.stage, /made/.test(o.stage) ? "check" : "refresh")}</div>`)}</div>` : h`<p class="muted small">Nothing it may use yet.</p>`}</section>
      <section class="panel" aria-labelledby="act"><div class="panel-head"><h2 id="act">Activity</h2><span class="small muted">What it did with each video it found, newest first</span></div>
        ${S.activity.length ? h`<div class="rows">${S.activity.map((x) => h`<div class="row top wrap" style="padding:12px 0">${x.used ? pill("good", x.stage, "check") : pill("neutral", "Skipped", "x")}
          <span class="grow stack" style="gap:2px"><b>${x.title}</b><span class="tiny faint">${x.channel} · ${x.rights}</span>${x.why ? h`<span class="small">${x.why}</span>` : ""}</span>
          <span class="tiny faint">${x.at}</span>${x.canAddFile ? h`<button class="btn btn-small" type="button" data-action="add-file">Add the file…</button>` : ""}</div>`)}</div>` : h`<p class="muted small">Nothing yet.</p>`}
        <p class="small muted">Videos from creators you have an agreement with are used without asking. Record agreements under <a class="textlink" href="#/autopilot/sources">Permissions &amp; sources</a>.</p></section>`;
  }
  function apSources() {
    return h`<section class="panel" aria-labelledby="agr"><div class="panel-head"><h2 id="agr">Creator agreements</h2><button class="btn" type="button" data-action="agreement-dialog">${icon("plus")}Record an agreement…</button></div>
        <p class="small muted">A creator who allows you to clip their videos: record it once, with what shows it and its conditions, and every video it covers is used without asking. It covers the creator's own material only, unless you say it also covers other people's music or footage.</p>
        ${S.agreements.length ? h`<div class="rows">${S.agreements.map((g) => h`<div class="row top wrap" style="padding:12px 0"><span class="grow stack" style="gap:2px"><b>${g.creator}</b><span class="tiny faint">${g.channels.join(", ")}</span>
          <span class="small">${g.commercial ? "Commercial use allowed" : "No commercial use"} · only on ${g.platforms.join(", ")} · credit: “${g.attribution}”</span><span class="tiny faint">Evidence: ${g.evidence}</span></span>
          <button class="btn btn-small btn-danger" type="button" data-action="confirm-remove" data-note="Remove this agreement? Videos it covers are no longer used automatically.">${icon("trash")}Remove…</button></div>`)}</div>` : h`<p class="small muted">None yet. Without agreements, Autopilot uses your own videos and videos with a free license (public domain, CC0, CC BY).</p>`}
      </section>
      <div class="cols-2">
        <section class="panel" aria-labelledby="feeds"><div class="panel-head"><h2 id="feeds">Where videos come from</h2><button class="btn btn-small" type="button" data-action="add-content">${icon("plus")}Add…</button></div>
          <div class="rows">${S.feeds.map((f, i) => h`<div class="row wrap" style="padding:10px 0"><span class="grow stack" style="gap:0"><b>${f.name}</b><span class="tiny faint break">${f.kind} · ${f.where}</span></span>${toggle(`feed-${i}`, f.enabled, `Use ${f.name}`)}</div>`)}${!S.feeds.length ? h`<p class="small muted">None yet.</p>` : ""}</div></section>
        <section class="panel" aria-labelledby="rules"><div class="panel-head"><h2 id="rules">Permission rules</h2><button class="btn btn-small" type="button" data-action="demo-note" data-note="In the app this opens “Add a rights rule”: a channel, folder or link prefix, its status and the basis.">${icon("plus")}Add rule…</button></div>
          <div class="rows">${S.rules.map((r) => h`<div class="row wrap" style="padding:10px 0">${pill(r.status === "Owned" ? "good" : "info", r.status, "shield")}<span class="grow stack" style="gap:0"><b>${r.label}</b><span class="tiny faint">${r.scope} · ${r.basis}</span></span></div>`)}${!S.rules.length ? h`<p class="small muted">No rules yet: videos nothing covers are skipped.</p>` : ""}</div></section>
      </div>
      <section class="panel" aria-labelledby="srcs"><div class="panel-head"><h2 id="srcs">Found videos and their permission</h2>
          <label class="sr-only" for="src-filter">Show</label><select id="src-filter" style="width:auto"><option>All videos</option><option>Needs permission</option><option>Needs the file</option><option>Being clipped</option><option>Skipped</option></select></div>
        <div class="rows">${S.sources.map((x) => h`<div class="row top wrap" style="padding:12px 0">${pill(x.rights === "Not covered" ? "neutral" : "good", x.rights, "shield")}<span class="grow stack" style="gap:2px"><b>${x.title}</b><span class="tiny faint">${x.basis} · ${x.status}</span></span>
          <span class="small">Source Score <b>${x.score}</b> <span class="faint">(estimate, ≈ ${x.expected} strong clips)</span></span></div>`)}</div>
        <p class="tiny faint">Only confirm permission you actually have. Being public, trending or downloadable does not make a video reusable.</p></section>`;
  }
  function apAdvanced(which) {
    const sub = h`<nav class="tabs" aria-label="Advanced">${[["system", "System"], ["jobs", "Jobs"], ["learning", "Learning"]].map(([k, l]) => h`<a href="#/autopilot/${k}" ${k === which ? raw('aria-current="page"') : ""}>${l}</a>`)}</nav>`;
    let body;
    if (which === "jobs") {
      body = h`<section class="panel" aria-labelledby="jobs"><div class="panel-head"><h2 id="jobs">Jobs</h2><label class="sr-only" for="job-filter">Show</label><select id="job-filter" style="width:auto"><option>Active and failed</option><option>All (latest 150)</option><option>Completed</option><option>Canceled</option></select></div>
        <div class="rows">${S.jobs.map((j) => h`<div class="row top wrap" style="padding:12px 0">${pill(j.status === "failed" ? "bad" : j.status === "running" ? "info" : "neutral", j.status, j.status === "failed" ? "alert" : "refresh")}
          <span class="grow stack" style="gap:2px"><b>${j.kind}</b><span class="tiny faint">${j.worker} · attempt ${j.attempt}</span><span class="small">${j.message}</span>${j.fix ? h`<span class="small"><b>What to do:</b> ${j.fix}</span>` : ""}</span>
          <button class="btn btn-small" type="button" data-action="demo-note" data-note="In the app this shows the job's log.">Log</button>${j.status === "failed" ? h`<button class="btn btn-small" type="button" data-action="demo-note" data-note="Retry would queue the job again (demo: nothing changes).">Retry</button>` : h`<button class="btn btn-small btn-quiet" type="button" data-action="demo-note" data-note="Cancel would stop this job at its next safe point (demo: nothing changes).">Cancel</button>`}</div>`)}${!S.jobs.length ? h`<p class="small muted">No jobs.</p>` : ""}</div></section>`;
    } else if (which === "learning") {
      body = h`<div class="cols-2"><section class="panel"><div class="panel-head"><h2>What your results show</h2><button class="btn btn-small" type="button" data-action="demo-note" data-note="Learn now would start the learning job.">Learn now</button></div>
          <p class="small">Nothing learned yet.</p><p class="small muted">Posts with real numbers: 1 (needs 20). No conclusions are drawn until there is enough data from your own posts. Posting times are spread evenly until then.</p></section>
        <section class="panel"><h2>How the scores are weighted</h2><p class="small muted">Default weights (not enough results to adjust them).</p></section></div>`;
    } else {
      const g = S.autopilot.gpu; const [gt, gi, gw, gd] = gpuFact();
      body = h`<div class="cols-2">
        <section class="panel" aria-labelledby="wk"><div class="panel-head"><h2 id="wk">Workers</h2><span class="small muted">${lost() ? "Unknown" : S.autopilot.workersAlive ? "Running in their own process" : "Not running"}</span></div>
          <div class="rows">${S.workers.map(([n, s, m]) => h`<div class="row" style="padding:8px 0">${pill(s === "Working" ? "info" : s === "Waiting" ? "warn" : "neutral", lost() ? "Unknown" : s, s === "Working" ? "refresh" : s === "Waiting" ? "clock" : "dot")}<b class="small" style="width:110px;flex:none">${n}</b><span class="tiny faint grow clamp-1">${lost() ? "" : m}</span></div>`)}</div></section>
        <section class="panel" aria-labelledby="gpu"><h2 id="gpu">GPU</h2>
          <dl class="kv"><dt>Device</dt><dd>${g.state === "none" ? "No CUDA GPU detected" : g.name}</dd><dt>Transcription</dt><dd>${fact("", gt, gi, gw, "")}</dd>
            <dt>Model</dt><dd>${g.model || "large-v3-turbo"} · ${g.compute || "int8_float16"}</dd><dt>Memory</dt><dd>2.9 / 4.0 GB used · 61% busy (sample)</dd><dt>Now</dt><dd>${S.autopilot.working ? "transcription · Saturday livestream Q&A" : "free"}</dd>
            <dt>CPU fallback in Autopilot</dt><dd>Off: Autopilot pauses instead (Settings, Advanced)</dd></dl>
          ${gd ? h`<p class="small muted">${gd}</p>` : ""}${g.fix ? h`<p class="small"><b>What to do:</b> ${g.fix}</p>` : ""}</section>
        <section class="panel" aria-labelledby="quota"><h2 id="quota">YouTube API quota</h2><p class="tiny faint">Counted by ClipFoundry. Resets at 2:00 AM.</p>
          ${S.quota.map(([l, u, b]) => h`<div class="stack"><span class="row small"><span class="grow">${l}</span><span class="tnum">${u} / ${b}</span></span><div class="bar"><span style="width:${Math.round((100 * u) / b)}%"></span></div></div>`)}</section>
        <section class="panel" aria-labelledby="ev"><h2 id="ev">Recent events</h2><div class="rows">${S.events.map(([t, m]) => h`<div class="row top" style="padding:8px 0"><span class="tiny faint nowrap" style="width:80px">${t}</span><span class="small">${m}</span></div>`)}${!S.events.length ? h`<p class="small muted">Nothing yet.</p>` : ""}</div></section>
      </div>
      <section class="panel"><h2>All action items and daily numbers</h2><p class="small muted">Today: 5 clips processed, 0 published, 3 scheduled (unique clips) · 4 platform posts scheduled. Daily target ${S.autopilot.dailyTarget} (a target, not a quota).</p>
        <p class="small muted">Trend opportunities, provider status and “Scan now” also live here, as today.</p></section>`;
    }
    return h`${sub}${body}`;
  }
  function toggle(id, on, label, action = "toggle") {
    return h`<button class="switch" type="button" role="switch" id="${id}" aria-checked="${on ? "true" : "false"}" data-action="${action}" data-id="${id}"><span class="track"></span><span class="state-word">${on ? "On" : "Off"}</span><span class="sr-only">${label}</span></button>`;
  }

  // ================================================================== LIBRARY
  function pageLibrary() {
    const f = ui.libFilter; const q = ui.libQuery.trim().toLowerCase();
    const match = (p) => (f === "all" || (f === "working" && ["processing", "uploading"].includes(p.status)) || (f === "ready" && p.status === "ready") || (f === "problems" && p.status === "error"))
      && (!q || p.name.toLowerCase().includes(q));
    const list = S.projects.filter(match);
    const counts = { all: S.projects.length, working: S.projects.filter((p) => ["processing", "uploading"].includes(p.status)).length, ready: S.projects.filter((p) => p.status === "ready").length, problems: S.projects.filter((p) => p.status === "error").length };
    return h`<div class="page">${connectionBanner()}
      <div class="page-head"><div><h1>Library</h1><p class="muted">Your source videos and the clips made from them. Everything is stored on this computer.</p></div>
        <div class="actions"><a class="btn btn-primary" href="#/create">${icon("plus")}Add video</a></div></div>
      ${S.projects.length ? h`<div class="row wrap" style="gap:12px">
        <div class="field" style="width:min(320px,100%)"><label for="lib-q" class="sr-only">Find a video by name</label><input id="lib-q" type="search" placeholder="Find a video by name" value="${ui.libQuery}" data-bind="libQuery"></div>
        <div class="chips" role="group" aria-label="Show">${[["all", "All"], ["working", "Working"], ["ready", "Ready"], ["problems", "Problems"]].map(([k, l]) => h`<button class="chip" type="button" aria-pressed="${String(!!(f === k))}" data-action="lib-filter" data-id="${k}">${l} (${counts[k]})</button>`)}</div></div>
        ${list.length ? h`<div class="grid-cards">${list.map(projectCard)}</div>` : h`<p class="muted">No video matches. <button class="linkish" type="button" data-action="lib-clear">Show all videos</button></p>`}`
      : h`<div class="empty">${icon("library", "lg")}<h2>Your library is empty</h2><p class="muted">Add a video to make clips yourself, or put videos you made in your videos folder and Autopilot makes clips from them.</p>
        <div class="row wrap"><a class="btn btn-primary" href="#/create">${icon("plus")}Add video</a><button class="btn" type="button" data-action="open-folder">${icon("folder")}Open videos folder <span class="demo-mark">demo</span></button></div></div>`}
    </div>`;
  }
  function projectCard(p) {
    const busy = ["processing", "uploading"].includes(p.status);
    return h`<article class="pcard" aria-labelledby="pc-${p.id}">
      ${thumb(p.seed, { corner: p.duration, overlay: busy ? h`${icon("refresh")}<span>${p.message}</span>` : null })}
      <div class="stack"><a class="title-link clamp-2" id="pc-${p.id}" href="#/project/${p.id}">${p.name}</a>
        <div class="pcard-meta">${projectStatusLine(p)}</div>
        <div class="pcard-foot"><span class="tiny faint">${p.origin} · ${p.created}</span>
          ${menu(`pm-${p.id}`, `More for ${p.name}`, [
            busy ? { label: "Cancel processing", action: "cancel-processing", id: p.id } : null,
            { label: "Delete video and clips…", action: "delete-project", id: p.id, danger: true, disabled: busy, why: busy ? "Cancel processing first" : "" },
          ].filter(Boolean))}</div></div></article>`;
  }
  function menu(id, label, items, up) {
    const open = ui.menu === id;
    return h`<div class="menu-wrap"><button class="btn btn-icon btn-quiet" type="button" data-action="menu" data-id="${id}" aria-expanded="${String(!!(open))}" ${open ? raw(`aria-controls="${id}"`) : ""} aria-label="${label}">${icon("more")}</button>
      ${open ? h`<div class="menu ${up ? "up" : ""}" id="${id}" role="group" aria-label="${label}">${items.map((it) => it.sep ? raw("<hr>") : it.href ? h`<a href="${it.href}">${it.label}</a>` :
        h`<button type="button" class="${it.danger ? "danger" : ""}" data-action="${it.action}" data-id="${it.id || ""}" ${it.disabled ? raw(`disabled aria-disabled="true" title="${esc(it.why || "")}"`) : ""}>${it.label}${it.disabled && it.why ? h` <span class="tiny faint">(${it.why})</span>` : ""}</button>`)}</div>` : ""}</div>`;
  }

  // ------------------------------------------------------------------ project (source video) page
  const P_STAGES = ["Prepare", "Transcribe", "Find moments", "Score & hooks", "Render 9:16"];
  function pageProject(p) {
    const cs = clipsOf(p.id);
    const busy = ["processing", "uploading"].includes(p.status);
    const sel = cs.filter((c) => ui.selected.has(c.id));
    return h`<div class="page">${connectionBanner()}
      <nav class="crumbs" aria-label="Breadcrumb"><a href="#/library">Library</a><span aria-hidden="true">/</span><span aria-current="page" class="clamp-1" style="max-width:60ch">${p.name}</span></nav>
      <div class="page-head"><div><span class="kind-label">Source video</span><h1 class="break">${p.name}</h1><p class="small muted">${p.duration} · ${p.format} · ${p.origin} · ${p.created}</p></div>
        <div class="actions">${projectStatusLine(p)}
          ${busy ? h`<button class="btn" type="button" data-action="cancel-processing" data-id="${p.id}">Cancel processing <span class="demo-mark">demo</span></button>` : ""}
          ${menu(`pp-${p.id}`, "More for this video", [
            { label: "Make clips again…", action: "regenerate", id: p.id, disabled: busy, why: "Wait until processing ends" },
            { sep: true },
            { label: "Delete video and clips…", action: "delete-project", id: p.id, danger: true, disabled: busy, why: "Cancel processing first" },
          ])}</div></div>
      ${p.status === "error" ? h`<div class="banner bad" role="alert">${icon("alert")}<div class="grow"><b>ClipFoundry couldn't make clips from this video.</b><span class="small">${p.error}</span><span class="small"><b>What to do:</b> ${p.fix}</span>
        <div class="actions"><button class="btn btn-small" type="button" data-action="regenerate" data-id="${p.id}">${icon("refresh")}Try again…</button><a class="btn btn-small" href="#/create">Add a different video</a></div></div></div>` : ""}
      <section class="panel" aria-labelledby="src-h">
        <div class="row top wrap" style="gap:24px"><div style="width:min(360px,100%)">${thumb(p.seed, { corner: p.duration, alt: `Source video: ${p.name}` })}</div>
          <div class="stack-3 grow" style="min-width:260px"><h2 id="src-h" class="sr-only">About this video</h2>
            ${busy ? h`<div class="stack"><b>${p.message}</b>
              <ol class="stages" aria-label="Steps">${P_STAGES.map((s, i) => h`<li class="${i < p.stageIndex ? "done" : i === p.stageIndex ? "now" : ""}" ${i === p.stageIndex ? raw('aria-current="step"') : ""}>${icon(i < p.stageIndex ? "check" : i === p.stageIndex ? "refresh" : "dot")}${s}</li>`)}</ol>
              ${p.progress !== null && p.progress !== undefined ? h`<div class="bar" role="progressbar" aria-label="Progress of this video" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(p.progress * 100)}" data-live="p-progress-${p.id}"><span style="width:${Math.round(p.progress * 100)}%"></span></div>` : h`<span class="tiny faint">Waiting: no progress until the GPU is free.</span>`}
              <span class="tiny faint">You can leave this page; the clips appear here when they're ready.</span></div>` : ""}
            <dl class="kv">${p.transcribed ? h`<dt>Transcript</dt><dd>${p.transcribed}</dd>` : ""}
              ${p.status === "ready" ? h`<dt>Clips</dt><dd>${cs.length} of ${p.candidates} moments passed the quality bar (${p.requested} requested, minimum Viral Potential ${p.minScore}). Weak moments are never added to reach the count.</dd>` : ""}</dl>
            ${p.status === "ready" ? h`<details class="plain"><summary>${icon("chev", "chev sm")}How clips are ranked</summary><div class="more-body small muted">Clips are ranked by Viral Potential: hook strength, curiosity, emotion, information density, payoff, standalone context, opening, pacing, uniqueness, speaker clarity and retention. It is an estimate from the clip's transcript and audio, used to rank clips, and never a promise of views.</div></details>` : ""}
          </div></div></section>
      ${cs.length ? h`<section class="stack-4" aria-labelledby="clips-h">
        <div class="panel-head"><div class="section-title"><h2 id="clips-h">Clips made from it (${cs.length})</h2><span class="small muted">Each clip is its own 9:16 video. Posts are made from clips.</span></div>
          <div class="row wrap"><span class="small muted" aria-live="polite">${sel.length} selected</span>
            <button class="btn btn-small btn-quiet" type="button" data-action="select-all" data-id="${p.id}">${sel.length === cs.length ? "Clear selection" : "Select all"}</button>
            <button class="btn btn-small" type="button" data-action="zip" data-id="selected" ${sel.length ? "" : raw("disabled")}>${icon("download")}Download selected (ZIP) <span class="demo-mark">demo</span></button>
            <button class="btn btn-small" type="button" data-action="zip" data-id="all">${icon("download")}Download all (ZIP) <span class="demo-mark">demo</span></button></div></div>
        <div class="clip-grid">${cs.map(clipCard)}</div></section>`
      : p.status === "ready" ? h`<div class="empty">${icon("scissors", "lg")}<h2>No moment passed the quality bar</h2><p class="muted">ClipFoundry doesn't pad the results with weak clips. Try a different clip length with “Make clips again”, or lower the minimum Viral Potential in Settings to see weaker moments too.</p><button class="btn" type="button" data-action="regenerate" data-id="${p.id}">${icon("refresh")}Make clips again…</button></div>` : ""}
    </div>`;
  }
  function clipCard(c) {
    const ps = postsOf(c.id);
    const rendering = c.status === "rendering";
    return h`<article class="ccard" aria-labelledby="cc-${c.id}"><div style="position:relative">
        ${thumb(c.seed, { vertical: true, captions: true, corner: fmt(c.duration), overlay: rendering ? h`${icon("refresh")}<span>Rendering ${Math.round((c.progress || 0) * 100)}%</span>` : null })}
        <label class="sel"><input type="checkbox" data-action="select" data-id="${c.id}" ${ui.selected.has(c.id) ? raw("checked") : ""} aria-label="Select ${c.title}">Select</label></div>
      <div class="ccard-body"><h3 class="clamp-2" id="cc-${c.id}" style="font-size:var(--fs-body)">${c.title}</h3>
        <span class="score" title="An estimate used to rank clips. Not a promise of views."><b>${c.score}</b>Viral Potential (estimate)</span>
        <span class="tiny faint">${c.category} · from ${fmt(c.start)} in the source</span>
        ${ps.length ? h`<span class="tiny">${ps.slice(0, 2).map((p) => h`<a class="textlink" href="#/post/${p.id}">${PNAME[p.platform]}: ${postStatus(p)[1].toLowerCase()}</a> `)}</span>` : h`<span class="tiny faint">No posts yet</span>`}
        <div class="ccard-actions">
          <a class="btn btn-small" href="#/clip/${c.id}">${icon("edit")}Edit clip</a>
          <button class="btn btn-small" type="button" data-action="export" data-id="${c.id}" ${rendering ? raw("disabled") : ""}>${icon("download")}Export</button>
          <a class="btn btn-small btn-primary" href="#/publish/${c.id}" ${rendering ? raw('aria-disabled="true"') : ""}>${icon("upload")}Prepare post</a></div></div></article>`;
  }

  // ================================================================== ADD VIDEO
  function pageAdd() {
    const a = ui.add;
    const s = S.settings;
    return h`<div class="page narrow">${connectionBanner()}
      <nav class="crumbs" aria-label="Breadcrumb"><a href="#/library">Library</a><span aria-hidden="true">/</span><span aria-current="page">Add video</span></nav>
      <div class="page-head"><div><h1>Add video</h1><p class="muted">Choose a long video on this computer. ClipFoundry copies it into its data folder, finds the best moments and makes captioned vertical clips.</p></div></div>
      ${a.progress !== null ? h`<section class="file-chip" aria-labelledby="up-h">${icon("film", "lg")}<div class="grow stack"><b id="up-h" class="break">${a.file.name}</b><span class="small muted">${a.file.size}</span>
          <div class="bar" role="progressbar" aria-label="Copying the video into ClipFoundry" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(a.progress * 100)}" data-live="upload"><span style="width:${Math.round(a.progress * 100)}%"></span></div>
          <span class="small" data-live="upload-text">Copying into ClipFoundry: ${Math.round(a.progress * 100)}%</span></div></section>`
      : a.file ? h`<section class="file-chip" aria-label="Chosen video">${icon("film", "lg")}<div class="grow stack"><b class="break">${a.file.name}</b><span class="small muted">${a.file.size}${a.file.sample ? " · sample file" : ""}</span></div><button class="btn btn-quiet" type="button" data-action="add-clear">Choose another</button></section>`
      : h`<div class="drop" id="drop" data-drop="1"><span>${icon("upload", "lg")}</span><h2>Drop a video here</h2>
          <p class="muted small">MP4, MOV, MKV, WEBM or M4V. Only videos you made or may use.</p>
          <div class="row wrap" style="justify-content:center"><label class="btn btn-primary" for="file-in">Choose a video</label><button class="btn" type="button" data-action="add-sample">Use a sample video</button></div>
          <input id="file-in" type="file" accept=".mp4,.mov,.mkv,.webm,.m4v" class="sr-only" data-action="file-pick">
          <p class="tiny faint">Prototype: a chosen file is never read or uploaded; only its name and size are shown.</p></div>`}
      <details class="more"><summary>${icon("chev", "icon chev")}Import from a link instead</summary><div class="more-body">
        <div class="field"><label for="url-in">Video link</label><input id="url-in" type="url" placeholder="https://…" value="${a.url}" data-bind="addUrl"></div>
        <p class="hint">For publicly reachable videos you have the rights to use (it uses yt-dlp). ClipFoundry doesn't get around DRM, paywalls, logins or other access controls, and some sites don't allow downloads at all.</p></div></details>
      <details class="more"><summary>${icon("chev", "icon chev")}More options <span class="tiny faint">clips per video, length, captions, framing</span></summary><div class="more-body">
        ${settingRow("Clips", "At most; weak moments are skipped", seg("opt-count", [3, 5, 10].map((n) => [n, String(n)]), s.clip_count))}
        ${settingRow("Clip length", "", seg("opt-len", [["short", "15–30 s"], ["standard", "15–60 s"], ["long", "30–90 s"]], s.length))}
        ${settingRow("Caption style", "", captionStyles("opt-style", s.caption_style))}
        ${settingRow("Framing", "How the 9:16 crop follows the action", h`<div class="stack"><select id="opt-track" aria-label="Tracking"><option>Auto</option><option>Center</option><option>Face</option><option>Active speaker</option><option>Screen content</option></select>${seg("opt-layout", [["fill", "Fill (crop)"], ["fit", "Fit (blurred background)"]], s.layout)}</div>`)}
        ${settingRow("Silence cleanup", "", seg("opt-sil", [["off", "Off"], ["light", "Light"], ["aggressive", "Strong"]], s.silence))}
        ${settingRow("Extras", "", h`<div class="stack">${checkbox("opt-zoom", "Subtle auto-zoom", s.auto_zoom)}${checkbox("opt-hook", "On-screen hook in the first seconds", s.hook_overlay)}</div>`)}
        ${settingRow("Transcript", "Optional .srt, .vtt or .json; skips Whisper", h`<button class="btn btn-small" type="button" data-action="demo-note" data-note="In the app this opens a file picker for a transcript.">Attach a transcript…</button>`)}
      </div></details>
      <div class="row wrap" style="justify-content:flex-end"><span class="small muted grow">Next: ClipFoundry transcribes the video on this computer and shows the clips on the video's page.</span>
        <button class="btn btn-primary" type="button" data-action="add-start" ${(a.file || /^https?:\/\//.test(a.url)) && a.progress === null ? "" : raw("disabled")}>${icon("scissors")}Make clips <span class="demo-mark">demo</span></button></div>
    </div>`;
  }
  function settingRow(label, hint, control, forId) {
    return h`<div class="setting"><div class="stack" style="gap:2px">${forId ? h`<label class="label" for="${forId}">${label}</label>` : h`<span class="label">${label}</span>`}${hint ? h`<span class="hint">${hint}</span>` : ""}</div><div style="min-width:0">${control}</div></div>`;
  }
  function seg(name, options, value, label) {
    return h`<div class="seg" role="radiogroup" ${label ? raw(`aria-label="${esc(label)}"`) : ""}>${options.map(([v, l]) => h`<label><input type="radio" name="${name}" value="${v}" ${String(v) === String(value) ? raw("checked") : ""} data-bind="${name}">${l}</label>`)}</div>`;
  }
  function checkbox(id, label, on) {
    return h`<label class="choice" for="${id}"><input type="checkbox" id="${id}" ${on ? raw("checked") : ""} data-bind="${id}"><span>${label}</span></label>`;
  }
  function captionStyles(name, value) {
    const st = [["clean", "Clean", "this is clean"], ["bold", "Bold", "BIG BOLD"], ["high_energy", "High energy", "HYPE!"], ["minimal", "Minimal", "a quiet line"]];
    return h`<div class="style-cards" role="radiogroup" aria-label="Caption style">${st.map(([v, l, d]) => h`<label class="style-card"><input type="radio" name="${name}" value="${v}" ${v === value ? raw("checked") : ""} data-bind="${name}"><span class="demo-text">${d}</span><span class="tiny faint">${l}</span></label>`)}</div>`;
  }

  // ================================================================== CLIP EDITOR
  const EDIT_TABS = [["trim", "Trim"], ["text", "Captions"], ["layout", "Layout"], ["audio", "Audio"], ["post", "Post text"]];
  function draftFor(c) {
    if (!ui.edit || ui.edit.clipId !== c.id) {
      const base = { start: c.start, end: c.end, captions: true, style: "bold", position: "bottom", size: 1, emphasis: false, highlight: true,
        hook: c.hook, hookOn: true, hookSecs: 3, tracking: "auto", layout: "fill", zoom: 1, autoZoom: true, gain: 0, normalize: true,
        silence: "light", fillers: true, speed: 1, title: c.title, caption: c.hook + " " + (c.hashtags || []).join(" ") };
      ui.edit = { clipId: c.id, saved: { ...base }, draft: { ...base }, dirty: new Set(), tab: "trim", view: "clip", playing: false,
        t: 0, clickMode: "start", render: null, savedNotRendered: false, version: c.version, rendered: c.rendered };
    }
    return ui.edit;
  }
  function wordsIn(start, end) { return S.words.filter((w) => w.end > start && w.start < end); }
  function pageEditor(c) {
    const p = project(c.projectId); const e = draftFor(c); const d = e.draft;
    const dur = d.end - d.start; const rendering = !!e.render;
    const versions = S.versions[c.id] || [{ id: "", label: "Original", description: "The clip as edited.", status: "ready", duration: c.duration }];
    return h`<div class="page">${connectionBanner()}
      <nav class="crumbs" aria-label="Breadcrumb"><a href="#/library">Library</a><span aria-hidden="true">/</span><a class="clamp-1" style="max-width:40ch" href="#/project/${p.id}">${p.name}</a><span aria-hidden="true">/</span><span aria-current="page">Edit clip</span></nav>
      <div class="page-head"><div><span class="kind-label">Clip</span><h1 class="break">${c.title}</h1>
          <p class="small muted tnum">${dur.toFixed(1)} s · from ${fmtPrecise(d.start)} to ${fmtPrecise(d.end)} of the source video · <span title="An estimate used to rank clips">Viral Potential ${c.score} (estimate)</span></p></div>
        <div class="actions"><button class="btn" type="button" data-action="export" data-id="${c.id}">${icon("download")}Export</button><a class="btn" href="#/publish/${c.id}">${icon("upload")}Prepare post</a></div></div>
      <div class="editor">
        <div class="stage-area">
          <div class="player-wrap">
            <div class="seg" role="radiogroup" aria-label="Preview">${[["clip", `Rendered clip (version ${e.version})`], ["source", "Source range (before rendering)"]].map(([v, l]) => h`<label><input type="radio" name="ed-view" value="${v}" ${e.view === v ? raw("checked") : ""} data-bind="ed-view">${l}</label>`)}</div>
            ${playerBox(c, e)}
            <div class="player-controls"><button class="btn btn-small" type="button" data-action="play" aria-pressed="${String(!!(e.playing))}">${icon(e.playing ? "pause" : "play")}${e.playing ? "Pause" : "Play"}</button>
              <span class="small tnum" data-live="ed-time">${fmtPrecise(e.t)} / ${fmtPrecise(e.view === "clip" ? c.duration : dur)}</span>
              <span class="tiny faint grow">${e.view === "clip" ? (e.savedNotRendered || e.dirty.size ? "Shows the last render. Your changes appear after you render." : `Shows version ${e.version}, ${e.rendered.toLowerCase()}.`) : "Shows the source with your current start and end. Captions and layout appear after rendering."}</span></div>
          </div>
          <section class="timeline" aria-labelledby="tl-h"><div class="panel-head"><h2 id="tl-h" style="font-size:var(--fs-h3)">Timeline</h2><span class="tiny faint tnum">Source ${fmtPrecise(d.start - 6)} – ${fmtPrecise(d.end + 6)}</span></div>
            ${timeline(c, e)}
          </section>
          <section class="timeline" aria-labelledby="ver-h"><div class="panel-head"><h2 id="ver-h" style="font-size:var(--fs-h3)">Versions</h2>
              <div class="row wrap"><button class="btn btn-small" type="button" data-action="demo-note" data-note="In the app this renders three alternatives: faster pacing, an alternative hook and an alternative caption style.">${icon("spark")}Create versions…</button><button class="btn btn-small" type="button" data-action="demo-note" data-note="In the app this plays the versions side by side or one after another." ${versions.length < 2 ? raw("disabled") : ""}>Compare</button></div></div>
            <div class="versions" role="radiogroup" aria-label="Version used for export and posting">${versions.map((v, i) => h`<label class="version ${i === 0 ? "on" : ""}"><span class="row"><input type="radio" name="ed-version" ${i === 0 ? raw("checked") : ""} data-bind="ed-version"><b class="small">${v.label}</b></span><span class="tiny faint">${v.description} ${fmt(v.duration)}</span>${i === 0 ? h`<span class="tiny">Used for export and posts</span>` : ""}</label>`)}</div>
          </section>
        </div>
        <section class="edit-panel" aria-label="Edit">
          <div class="tabs" role="tablist" aria-label="Edit groups">${EDIT_TABS.map(([k, l]) => h`<button type="button" role="tab" id="tab-${k}" ${e.tab === k ? raw(`aria-controls="panel-${k}"`) : ""} aria-selected="${String(!!(e.tab === k))}" tabindex="${e.tab === k ? "0" : "-1"}" data-action="ed-tab" data-id="${k}">${l}${e.dirty.has(k) ? h`<span class="sr-only"> (changed)</span><span aria-hidden="true" class="faint">•</span>` : ""}</button>`)}</div>
          <div class="tabpanel" role="tabpanel" id="panel-${e.tab}" aria-labelledby="tab-${e.tab}">${editTab(c, e)}</div>
        </section>
      </div>
      <div class="savebar" role="region" aria-label="Save and render">
        <div class="grow"><b class="small" data-live="ed-status">${editStatus(e)}</b><span class="tiny faint">Saving keeps your edits. Rendering makes a new video file, which gets a new final check. Posts already approved for this clip then need your OK again.</span></div>
        <button class="btn btn-quiet" type="button" data-action="ed-discard" ${e.dirty.size && !rendering ? "" : raw("disabled")}>Discard changes</button>
        <button class="btn" type="button" data-action="ed-save" ${e.dirty.size && !rendering ? "" : raw("disabled")}>Save</button>
        <button class="btn btn-primary" type="button" data-action="ed-render" ${(e.dirty.size || e.savedNotRendered) && !rendering ? "" : raw("disabled")}>${icon("refresh")}Save and render <span class="demo-mark">demo</span></button>
      </div></div>`;
  }
  function editStatus(e) {
    if (e.render) return `Rendering version ${e.version + 1}… ${Math.round(e.render.progress * 100)}%`;
    if (e.dirty.size) return `Unsaved changes: ${[...e.dirty].map((k) => EDIT_TABS.find((t) => t[0] === k)[1]).join(", ")}`;
    if (e.savedNotRendered) return `Saved, not rendered yet. The video is still version ${e.version}.`;
    if (e.justRendered) return `Rendered version ${e.version}. It gets a new final check before it can be posted.`;
    return `No changes. Showing version ${e.version}.`;
  }
  function playerBox(c, e) {
    const d = e.draft;
    const src = e.view === "source";
    const t0 = src ? d.start : (e.saved.start);
    const words = wordsIn(t0 + e.t - 1.2, t0 + e.t + 0.6).slice(-5);
    const now = S.words.find((w) => w.start <= t0 + e.t && w.end >= t0 + e.t);
    const cap = (src || !e.saved.captions) ? "" : h`<div class="cap ${e.saved.position}" style="--hl:#ffe500;font-size:calc(clamp(14px, 2.2vh, 22px) * ${e.saved.size})" data-live="ed-cap">${words.map((w) => (now && w === now && e.saved.highlight) ? h`<em>${w.w} </em>` : h`${w.w} `)}</div>`;
    const hook = !src && e.saved.hookOn && e.t < e.saved.hookSecs ? h`<div class="hookline">${e.saved.hook}</div>` : "";
    return h`<div class="player ${src ? "wide" : ""}" role="img" aria-label="${src ? "Source video preview" : `Clip preview, version ${e.version}`}">${ui.demo.noThumbs ? h`<span class="thumb" style="height:100%;aspect-ratio:auto"><span class="missing">${icon("film")}<span>No preview yet</span></span></span>` : scene(c.seed, !src, false)}${cap}${hook}
      <span class="badge-version">${src ? "Source" : `Version ${e.version}`}</span></div>`;
  }
  function timeline(c, e) {
    const d = e.draft; const lo = d.start - 6; const hi = d.end + 6; const span = hi - lo;
    const pct = (x) => `${((100 * (x - lo)) / span).toFixed(2)}%`;
    const words = S.words.filter((w) => w.end > lo && w.start < hi);
    const bars = Array.from({ length: 64 }, (_, i) => 20 + Math.round(60 * Math.abs(Math.sin(i * 1.7 + c.seed))));
    const headAt = (e.view === "source" ? d.start : e.saved.start) + e.t;
    return h`<div class="tl-track" aria-hidden="true"><div class="tl-wave">${bars.map((b) => raw(`<i style="height:${b}%"></i>`))}</div>
        <div class="tl-range" style="left:${pct(d.start)};width:calc(${pct(d.end)} - ${pct(d.start)})"></div><div class="tl-head" data-live="ed-head" style="left:${pct(headAt)}"></div></div>
      <div class="tl-ticks" aria-hidden="true"><span>${fmtPrecise(lo)}</span><span>${fmtPrecise((lo + hi) / 2)}</span><span>${fmtPrecise(hi)}</span></div>
      <div class="row wrap"><div class="field" style="flex:1 1 180px"><label for="ed-start">Start <span class="tnum faint">${fmtPrecise(d.start)}</span></label><input id="ed-start" type="range" min="${(lo).toFixed(1)}" max="${(d.end - 1).toFixed(1)}" step="0.1" value="${d.start}" data-bind="ed-start" aria-valuetext="${fmtPrecise(d.start)}"></div>
        <div class="field" style="flex:1 1 180px"><label for="ed-end">End <span class="tnum faint">${fmtPrecise(d.end)}</span></label><input id="ed-end" type="range" min="${(d.start + 1).toFixed(1)}" max="${(hi).toFixed(1)}" step="0.1" value="${d.end}" data-bind="ed-end" aria-valuetext="${fmtPrecise(d.end)}"></div></div>
      <div class="row wrap"><span class="small muted">Click a word to set the</span>${seg("ed-click", [["start", "start"], ["end", "end"]], e.clickMode, "Word click sets")}<span class="grow"></span><button class="btn btn-small btn-quiet" type="button" data-action="ed-reset-trim">Reset to the suggested cut</button></div>
      <div class="words" role="group" aria-label="Transcript words. Choose one to set the ${e.clickMode}.">${words.map((w, i) => {
        const inside = w.end > d.start && w.start < d.end;
        const edge = inside && (!(words[i - 1] && words[i - 1].end > d.start && words[i - 1].start < d.end) || !(words[i + 1] && words[i + 1].end > d.start && words[i + 1].start < d.end));
        return h`<button type="button" class="${edge ? "edge" : inside ? "in" : ""}" data-action="ed-word" data-id="${S.words.indexOf(w)}" title="${fmtPrecise(w.start)}">${w.w}</button>`;
      })}</div>
      <p class="tiny faint">Cuts snap into the pauses around the words you pick. Use “Source range” above to check a cut before rendering.</p>`;
  }
  function editTab(c, e) {
    const d = e.draft;
    switch (e.tab) {
      case "trim": return h`<p class="small muted">Change where the clip starts and ends on the timeline, or type exact times.</p>
        <div class="row wrap"><div class="field" style="flex:1 1 140px"><label for="ed-start-n">Start (seconds)</label><input id="ed-start-n" type="number" step="0.1" value="${d.start.toFixed(2)}" data-bind="ed-start"></div>
          <div class="field" style="flex:1 1 140px"><label for="ed-end-n">End (seconds)</label><input id="ed-end-n" type="number" step="0.1" value="${d.end.toFixed(2)}" data-bind="ed-end"></div></div>
        <p class="small tnum">Length: <b>${(d.end - d.start).toFixed(1)} s</b></p>`;
      case "text": return h`
        ${settingToggle("ed-captions", "Burn captions into the video", d.captions)}
        <div class="field"><span class="label" id="lbl-style">Caption style</span>${captionStyles("ed-style", d.style)}</div>
        <div class="field"><span class="label">Position</span>${seg("ed-pos", [["top", "Top"], ["middle", "Middle"], ["bottom", "Bottom"]], d.position, "Caption position")}</div>
        <div class="field"><label for="ed-size">Size <span class="faint tnum">${Math.round(d.size * 100)}%</span></label><input id="ed-size" type="range" min="0.6" max="1.6" step="0.05" value="${d.size}" data-bind="ed-size"></div>
        ${checkbox("ed-emph", "Key words (numbers, strong words, the clip's keywords) in their own color", d.emphasis)}
        ${checkbox("ed-hl", "Highlight each word as it is spoken", d.highlight)}
        <div class="field"><label for="ed-captext">Caption text <span class="hint">fix misheard words; the timing is kept</span></label><textarea id="ed-captext" rows="4" data-bind="ed-captext">${wordsIn(d.start, d.end).map((w) => w.w).join(" ")}</textarea></div>
        <hr class="divider"><h3>On-screen hook</h3>
        <fieldset><legend class="sr-only">Hook</legend>${[c.hook, ...c.hooksAlt].map((hk, i) => h`<label class="hook-opt"><input type="radio" name="ed-hook" value="${hk}" ${d.hook === hk ? raw("checked") : ""} data-bind="ed-hook"><span class="small">${hk}${i === 0 ? h` <span class="pill accent">Suggested</span>` : ""}</span></label>`)}</fieldset>
        <div class="row wrap">${checkbox("ed-hookon", "Show the hook on screen for", d.hookOn)}<input type="number" min="1" max="15" step="0.5" value="${d.hookSecs}" style="width:90px" aria-label="Seconds the hook shows" data-bind="ed-hooksecs"><span class="small">seconds</span></div>
        <p class="hint">Hooks come from the clip's own words and never add facts that aren't in the clip.</p>`;
      case "layout": return h`
        <div class="field"><label for="ed-track">Framing follows</label><select id="ed-track" data-bind="ed-track">${[["auto", "Auto"], ["center", "Center"], ["face", "Face"], ["speaker", "Active speaker"], ["screen", "Screen content"], ["manual", "Manual position"]].map(([v, l]) => h`<option value="${v}" ${d.tracking === v ? raw("selected") : ""}>${l}</option>`)}</select></div>
        <div class="field"><span class="label">Layout</span>${seg("ed-layout", [["fill", "Fill (crop)"], ["fit", "Fit (blurred background)"]], d.layout, "Layout")}</div>
        <div class="field"><label for="ed-zoom">Zoom <span class="faint tnum">${d.zoom.toFixed(2)}×</span></label><input id="ed-zoom" type="range" min="1" max="2" step="0.05" value="${d.zoom}" data-bind="ed-zoom"></div>
        ${checkbox("ed-autozoom", "Subtle push-in on sentences with an emphasized word", d.autoZoom)}
        <p class="hint">Last render: face framing, 1 face track, no scene cuts.</p>`;
      case "audio": return h`
        <div class="field"><label for="ed-gain">Volume <span class="faint tnum">${d.gain > 0 ? "+" : ""}${d.gain} dB</span></label><input id="ed-gain" type="range" min="-12" max="12" step="0.5" value="${d.gain}" data-bind="ed-gain"></div>
        ${checkbox("ed-norm", "Normalize loudness to −14 LUFS (the social media standard)", d.normalize)}
        <div class="field"><span class="label">Silence cleanup</span>${seg("ed-sil", [["off", "Off"], ["light", "Light"], ["aggressive", "Strong"]], d.silence, "Silence cleanup")}</div>
        ${checkbox("ed-fillers", "Cut “um” and “uh” with the pause around them", d.fillers)}
        <div class="field"><label for="ed-speed">Pacing <span class="faint tnum">${d.speed.toFixed(2)}× (voice pitch unchanged)</span></label><input id="ed-speed" type="range" min="1" max="1.15" step="0.01" value="${d.speed}" data-bind="ed-speed"></div>
        <p class="hint">Last render removed 2.4 s of pauses and 3 filler words.</p>`;
      case "post": return h`<p class="small muted">The title, caption and hashtags used when you post this clip. They are not part of the video, so changing them doesn't need a render.</p>
        <div class="field"><label for="ed-title">Title <span class="hint tnum">${d.title.length}/100</span></label><input id="ed-title" type="text" value="${d.title}" data-bind="ed-title" ${d.title.length > 100 ? raw('aria-invalid="true"') : ""}></div>
        <div class="field"><label for="ed-caption">Caption <span class="hint tnum">${d.caption.length}/2200</span></label><textarea id="ed-caption" rows="4" data-bind="ed-caption">${d.caption}</textarea></div>
        <p class="hint">Suggestions come only from this clip's own words: no invented facts, names, numbers or claims. What you type is kept as you wrote it, with a note if it adds something the clip doesn't say.</p>
        <button class="btn btn-small" type="button" data-action="demo-note" data-note="In the app this writes a new post package from the transcript (your edits are replaced after you confirm).">${icon("refresh")}Write new suggestions…</button>`;
    }
    return "";
  }
  function settingToggle(id, label, on) { return h`<div class="row">${toggle(id, on, label, "ed-toggle")}<span class="small">${label}</span></div>`; }

  // ================================================================== PREPARE POST (manual publishing: #/publish/:clip)
  function pagePrepare(c) {
    const p = project(c.projectId); const ps = postsOf(c.id); const pubs = S.publications[c.id] || [];
    return h`<div class="page">${connectionBanner()}
      <nav class="crumbs" aria-label="Breadcrumb"><a href="#/library">Library</a><span aria-hidden="true">/</span><a class="clamp-1" style="max-width:36ch" href="#/project/${p.id}">${p.name}</a><span aria-hidden="true">/</span><a class="clamp-1" style="max-width:30ch" href="#/clip/${c.id}">${c.title}</a><span aria-hidden="true">/</span><span aria-current="page">Prepare post</span></nav>
      <div class="page-head"><div><h1>Prepare post</h1><p class="muted">Post this clip yourself, now. Nothing goes out until you press a platform's button and confirm. Posts Autopilot planned are in <a class="textlink" href="#/posts/review">Posts</a>.</p></div>
        <div class="actions"><a class="btn" href="#/clip/${c.id}">${icon("edit")}Edit clip</a><button class="btn" type="button" data-action="export" data-id="${c.id}">${icon("download")}Export</button></div></div>
      <div class="review">
        <div class="stack-3"><div class="player-wrap">${playerBox(c, draftFor(c))}</div>
          <p class="small muted">Posting version: <b>Original</b> · ${fmt(c.duration)} · 1080×1920 · ${c.rendered}</p>
          <p class="small"><span class="score"><b>${c.score}</b>Viral Potential (estimate)</span></p></div>
        <div class="stack-4">
          ${ps.length ? h`<section class="panel tight" aria-labelledby="pp-posts"><h2 id="pp-posts" style="font-size:var(--fs-h3)">Posts of this clip</h2><div class="rows">${ps.map((x) => h`<div class="row wrap" style="padding:8px 0">${platform(x.platform)}<span class="small faint">${x.when} ${S.tzAbbr}</span><span class="grow"></span>${pill(...(() => { const [t, w, i] = postStatus(x); return [t, w, i]; })())}<a class="btn btn-small" href="#/post/${x.id}">Open</a></div>`)}</div></section>` : ""}
          <section class="panel" aria-labelledby="pp-text"><h2 id="pp-text">Post text</h2><p class="tiny faint">Used for both platforms · written from the clip's transcript · edit anything</p>
            <div class="field"><label for="pp-title">Title <span class="hint tnum">${c.title.length}/100</span></label><input id="pp-title" type="text" value="${c.title}"></div>
            <div class="chips" aria-label="Title suggestions">${[c.title, c.hook].filter((x, i, a) => a.indexOf(x) === i).map((t, i) => h`<button class="chip" type="button" aria-pressed="${String(!!(i === 0))}" data-action="demo-note" data-note="Picks this suggestion as the title.">${i === 0 ? "★ " : ""}${t}</button>`)}</div>
            <div class="field"><label for="pp-cap">Description or caption</label><textarea id="pp-cap" rows="3">${c.hook}</textarea></div>
            <div class="field"><label for="pp-tags">Hashtags</label><input id="pp-tags" type="text" value="${(c.hashtags || []).join(" ")}"></div></section>
          ${platformPanel("youtube", c)}
          ${platformPanel("tiktok", c)}
          <section class="panel tight" aria-labelledby="pp-status"><h2 id="pp-status" style="font-size:var(--fs-h3)">Uploads you started here</h2>
            ${pubs.length ? h`<div class="rows">${pubs.map((u) => h`<div class="row wrap" style="padding:8px 0">${platform(u.platform)}${pill(u.status === "done" ? "good" : "info", u.status === "done" ? "Done" : u.status, u.status === "done" ? "check" : "upload")}<span class="small grow">${u.message}</span><span class="tiny faint">${u.when}</span></div>`)}</div>` : h`<p class="small muted">None yet.</p>`}</section>
        </div></div></div>`;
  }
  function platformPanel(pf, c) {
    const a = S.accounts[pf]; const ok = accOk(pf);
    const acct = a.state === "connected" ? pill("good", `Connected: ${a.name}`, "check") : a.state === "expired" ? pill("bad", "Sign-in expired", "alert") : pill("neutral", a.configured ? "Not connected" : "Not set up", "link");
    const yt = pf === "youtube";
    return h`<section class="panel" aria-labelledby="pp-${pf}"><div class="panel-head"><h2 id="pp-${pf}">${yt ? "YouTube Shorts" : "TikTok"}</h2><div class="row wrap">${acct}${!ok ? h`<button class="btn btn-small" type="button" data-action="reconnect" data-id="${pf}">${a.state === "expired" ? "Reconnect" : "Connect"} <span class="demo-mark">demo</span></button>` : ""}</div></div>
      ${!a.configured ? h`<p class="small muted">Set up ${PNAME[pf]} once in <a class="textlink" href="#/settings">Settings, Accounts</a> (your own free developer app), then connect.</p>` : ""}
      ${yt ? h`<div class="field"><span class="label">Who can see it</span>${seg(`pp-${pf}-priv`, [["public", "Public"], ["unlisted", "Unlisted"], ["private", "Private"]], "private", "YouTube privacy")}</div>
          ${a.restriction ? h`<p class="small"><span class="pill warn">${icon("alert")}Note</span> ${a.restriction}</p>` : ""}
          <fieldset><legend class="label">Made for kids <span class="hint">(YouTube requires an answer)</span></legend><label class="choice"><input type="radio" name="pp-kids"> <span>No, it's not made for kids</span></label><label class="choice"><input type="radio" name="pp-kids"> <span>Yes, it's made for kids</span></label></fieldset>
          ${checkbox(`pp-shorts`, "Add #Shorts to the description (optional; vertical videos up to 3 minutes are Shorts anyway)", false)}`
      : h`<p class="small">Posting as <b>${a.name || "your TikTok account"}</b> (read fresh from TikTok before posting)</p>
          <fieldset><legend class="label">How to post</legend><label class="choice"><input type="radio" name="pp-tt-mode" checked> <span><b>Post directly</b> to your profile</span></label><label class="choice"><input type="radio" name="pp-tt-mode"> <span><b>Send to TikTok inbox</b> as a draft: finish and post it in the TikTok app. Works without TikTok's app audit.</span></label></fieldset>
          <div class="field"><label for="pp-tt-priv">Who can see it</label><select id="pp-tt-priv"><option value="" selected disabled>Choose…</option><option disabled>Everyone (needs TikTok's app audit)</option><option disabled>Friends (needs TikTok's app audit)</option><option>Only me</option></select></div>
          ${a.restriction ? h`<p class="small"><span class="pill warn">${icon("alert")}Note</span> ${a.restriction}</p>` : ""}
          <fieldset><legend class="label">Allow viewers to</legend><div class="row wrap">${checkbox("pp-tt-c", "Comment", false)}${checkbox("pp-tt-d", "Duet", false)}${checkbox("pp-tt-s", "Stitch", false)}</div></fieldset>
          ${checkbox("pp-tt-disc", "This video promotes a brand, product or service (disclose commercial content)", false)}
          <p class="tiny faint">By posting, you agree to TikTok's Music Usage Confirmation.</p>`}
      <div class="row wrap"><span class="small muted grow">${ok ? `To publish: ${yt ? "answer “made for kids”" : "choose who can see it"}.` : `Connect ${PNAME[pf]} to publish.`}</span>
        <button class="btn btn-primary" type="button" data-action="publish-now-manual" data-id="${pf}" ${ok ? "" : raw("disabled")}>${icon("upload")}${yt ? "Publish to YouTube now…" : "Post to TikTok now…"}</button></div>
      ${!yt ? h`<details class="plain"><summary>${icon("chev", "chev sm")}Can't post through the API? Upload it yourself</summary><div class="more-body small"><ol class="steps-list"><li>Export the clip or download the MP4.</li><li>Copy the caption (text and hashtags).</li><li>Open TikTok Studio, Upload (official), choose the MP4, paste the caption, choose privacy and post.</li></ol></div></details>` : ""}
    </section>`;
  }

  // ================================================================== POSTS
  function pagePosts(view) {
    const views = [["review", "Needs review"], ["scheduled", "Scheduled"], ["published", "Published"], ["problems", "Problems"], ["results", "Results"]];
    const v = views.some(([k]) => k === view) || view === "history" ? view : "review";
    const shownTab = v === "history" ? "published" : v;
    const count = (k) => k === "results" ? 0 : postsIn(k).length;
    return h`<div class="page">${connectionBanner()}
      <div class="page-head"><div><h1>Posts</h1><p class="muted">Every planned and published post. One clip can have a YouTube post and a TikTok post. Times are in ${S.timezone} (${S.tzAbbr}).</p></div></div>
      <nav class="tabs" aria-label="Posts">${views.map(([k, l]) => h`<a href="#/posts/${k}" ${k === shownTab ? raw('aria-current="page"') : ""}>${l}${count(k) && (k === "review" || k === "problems") ? h`<span class="count ${k === "problems" ? "bad" : ""}">${count(k)}</span>` : k !== "results" && count(k) ? h`<span class="faint tiny">${count(k)}</span>` : ""}</a>`)}</nav>
      ${v === "results" ? postsResults() : postsList(v)}
    </div>`;
  }
  const VIEW_INTRO = {
    review: "Nothing is posted until it's approved. TikTok needs your OK on every post; YouTube does too unless you turned on automatic publishing.",
    scheduled: "Approved posts go out at their time by themselves. You can still change or cancel them.",
    published: "Posts that are live on YouTube or TikTok.",
    history: "Published, canceled and replaced posts.",
    problems: "Posts that could not go out, or where ClipFoundry needs you to check something. Nothing here is retried behind your back.",
  };
  function postsList(v) {
    const list = postsIn(v);
    const groups = v === "problems" ? [["reconciling", "Upload not confirmed"], ["failed", "Failed"], ["blocked", "Blocked"], ["action_needed", "Finish in the TikTok app"]] : null;
    return h`<p class="small muted">${VIEW_INTRO[v]}</p>
      ${v === "published" || v === "history" ? h`<div class="row">${checkbox("posts-all", "Also show canceled and replaced posts", v === "history")}</div>` : ""}
      ${!list.length ? h`<div class="empty">${icon("posts", "lg")}<p class="muted">${{ review: "Nothing waits for your OK.", scheduled: "Nothing is scheduled.", published: "Nothing published yet.", history: "No history yet.", problems: "No problems." }[v]}</p>${v === "review" && !S.setupDone ? h`<a class="btn" href="#/setup/mode">Set up Autopilot</a>` : ""}</div>` :
        groups ? groups.map(([st, label]) => { const g = list.filter((x) => x.status === st); return g.length ? h`<section class="panel tight" aria-label="${label}"><h2 style="font-size:var(--fs-h3)">${label} (${g.length})</h2><div class="rows">${g.map(postRow)}</div></section>` : ""; })
        : h`<section class="panel tight"><h2 class="sr-only">${VIEW_INTRO[v]}</h2><div class="rows">${list.map(postRow)}</div></section>`}`;
  }
  function postRow(x) {
    const c = clip(x.clipId); const [tone, word, ic] = postStatus(x);
    const acc = S.accounts[x.platform];
    const main = { awaiting_approval: ["Review", "#/post/" + x.id], reconciling: ["Resolve", "#/post/" + x.id], failed: ["See what to do", "#/post/" + x.id], blocked: ["See why", "#/post/" + x.id], action_needed: ["Link the post", "#/post/" + x.id] }[x.status] || ["Open", "#/post/" + x.id];
    return h`<div class="post-row"><a href="#/post/${x.id}" tabindex="-1" aria-hidden="true">${thumb(c ? c.seed : 1, { vertical: true, captions: true })}</a>
      <div class="post-main"><a class="post-title clamp-2" href="#/post/${x.id}">${c ? c.title : x.title}</a>
        <div class="post-meta">${platform(x.platform, acc.name ? `· ${acc.name}` : "")}<span class="tnum">${x.when} ${S.tzAbbr}</span>${pill(tone, word, ic)}</div>
        ${x.statusNote ? h`<span class="small ${tone === "bad" ? "" : "muted"}">${x.statusNote}</span>` : ""}
        ${x.status === "awaiting_approval" ? h`<span class="tiny faint">Rights: ${x.rights.label} (${x.rights.basis.toLowerCase()}) · Final check: ${x.quality.status === "passed" ? (x.quality.warnings.length ? `passed, ${plural(x.quality.warnings.length, "warning")}` : "passed") : x.quality.status === "pending" ? "not done yet" : "failed"}</span>` : ""}
        ${x.stats ? h`<span class="tiny faint">${x.stats.views === null ? "Views: — (not reported)" : `${num(x.stats.views)} views · ${num(x.stats.likes)} likes`}</span>` : ""}</div>
      <div class="post-actions"><a class="btn btn-small" href="${main[1]}">${main[0]}</a>
        ${menu(`rm-${x.id}`, `More for this ${PNAME[x.platform]} post`, [
          ["awaiting_approval", "approved", "failed"].includes(x.status) ? { label: "Change text or time…", href: `#/post/${x.id}` } : null,
          { label: "Open the clip", href: `#/clip/${x.clipId}` },
          x.url ? { label: `Open on ${PNAME[x.platform]}`, action: "demo-note", id: `This opens the post on ${PNAME[x.platform]}.` } : null,
          ["awaiting_approval", "approved", "failed", "action_needed"].includes(x.status) ? { sep: true } : null,
          ["awaiting_approval", "approved", "failed", "action_needed"].includes(x.status) ? { label: "Cancel this post…", action: "cancel-post", id: x.id, danger: true } : null,
        ].filter(Boolean))}</div></div>`;
  }
  function postsResults() {
    const pubd = S.posts.filter((p) => p.status === "published" && !p.onPlatform);
    const sum = (k) => { const vals = pubd.map((p) => p.stats && p.stats[k]).filter((x) => x !== null && x !== undefined); return vals.length ? [vals.reduce((a, b) => a + b, 0), vals.length] : [null, 0]; };
    const tot = (k, l) => { const [v, n] = sum(k); return h`<div class="total"><b>${v === null ? "—" : num(v)}</b><span>${l}${v === null ? " · not reported yet" : n < pubd.length ? ` · from ${n} of ${pubd.length} posts` : ""}</span></div>`; };
    const perf = S.performance;
    return h`<section class="panel" aria-labelledby="res-h"><div class="panel-head"><div><h2 id="res-h">Results</h2><p class="small muted">Real numbers read from YouTube and TikTok for your own posts. A number a platform doesn't report is shown as “—”, never estimated.</p></div>
        <div class="row wrap"><span class="tiny faint">Updated ${perf.lastRefreshed}</span><button class="btn btn-small" type="button" data-action="demo-note" data-note="Refresh asks YouTube and TikTok for the latest numbers (demo: nothing changes).">${icon("refresh")}Refresh numbers</button>
          <button class="btn btn-small btn-quiet" type="button" data-action="demo-note" data-note="In the app this downloads a CSV of each post's scores at publish time next to its real numbers.">${icon("download")}Download data (CSV)</button></div></div>
      ${pubd.length ? h`<div class="totals">${tot("views", "Views")}${tot("likes", "Likes")}${tot("comments", "Comments")}${tot("shares", "Shares")}</div>
        <div class="table-wrap"><table class="data"><caption class="sr-only">Results per post</caption><thead><tr><th scope="col">Post</th><th scope="col">Platform</th><th scope="col" class="num">Views</th><th scope="col" class="num">Likes</th><th scope="col" class="num">Comments</th><th scope="col" class="num">Shares</th><th scope="col" class="num">Avg. % viewed</th><th scope="col" class="num">Viral Potential at posting</th></tr></thead>
          <tbody>${pubd.map((p) => { const s = p.stats || {}; const note = (k) => (s.notes && (s.notes[k] || s.notes.all)) || "Not reported by the platform";
            const cell = (v, k, suf = "") => v === null || v === undefined ? h`<td class="num"><span class="metric-missing" tabindex="0" title="${note(k)}" aria-label="Not available: ${note(k)}">—</span></td>` : h`<td class="num">${num(v)}${suf}</td>`;
            return h`<tr><td><a class="textlink" href="#/post/${p.id}">${clip(p.clipId).title}</a><div class="tiny faint">${p.published}</div></td><td>${platform(p.platform)}</td>${cell(s.views, "views")}${cell(s.likes, "likes")}${cell(s.comments, "comments")}${cell(s.shares, "shares")}${cell(s.avgPct, "avgPct", "%")}<td class="num">${p.score} <span class="tiny faint">(estimate)</span></td></tr>`; })}</tbody></table></div>
        <p class="small muted">Comparing Viral Potential with real views needs at least ${perf.minSamples} posts with view counts (now ${perf.samples}).</p>
        ${pubd.some((p) => p.stats && p.stats.notes && p.stats.notes.all) ? h`<p class="small"><span class="pill neutral">${icon("info")}TikTok</span> ${pubd.find((p) => p.stats.notes.all).stats.notes.all}</p>` : ""}`
      : h`<p class="muted">Nothing published yet.</p>`}</section>`;
  }

  // ------------------------------------------------------------------ one post, focused review
  function pageReview(x) {
    const c = clip(x.clipId); const yt = x.platform === "youtube"; const acc = S.accounts[x.platform];
    const [tone, word, ic] = postStatus(x);
    const f = ui.review[x.id] || (ui.review[x.id] = { title: x.title, text: x.description, tags: (x.tags || []).join(" "), privacy: yt ? x.privacy : "", kids: "", agree: false, mode: x.mode || "direct" });
    const q = x.quality;
    const problems = [
      !accOk(x.platform) && `reconnect ${PNAME[x.platform]}`,
      yt && !f.title.trim() && "enter a title",
      yt && !f.kids && "answer “made for kids”",
      !yt && f.mode === "direct" && !f.privacy && "choose who can see it",
      q.status === "failed" && "fix what the final check found",
      q.status === "pending" && "wait for the final check",
      !f.agree && "confirm that you reviewed it",
    ].filter(Boolean);
    const view = VIEW_OF.review(x) ? "review" : VIEW_OF.scheduled(x) ? "scheduled" : VIEW_OF.problems(x) ? "problems" : "published";
    const viewName = { review: "Needs review", scheduled: "Scheduled", problems: "Problems", published: "Published" }[view];
    return h`<div class="page">${connectionBanner()}
      <nav class="crumbs" aria-label="Breadcrumb"><a href="#/posts/${view}">Posts: ${viewName}</a><span aria-hidden="true">/</span><span aria-current="page" class="clamp-1" style="max-width:50ch">${c.title}</span></nav>
      <div class="page-head"><div><span class="kind-label">${PNAME[x.platform]} post</span><h1 class="break">${x.status === "awaiting_approval" ? `Review for ${yt ? "YouTube" : "TikTok"}` : c.title}</h1>
        <div class="row wrap">${pill(tone, word, ic)}<span class="small muted tnum">Planned for ${at(x.when)} ${S.tzAbbr}</span></div></div></div>
      <div class="review">
        <div class="stack-3"><div class="player-wrap">${playerBox(c, draftFor(c))}<div class="player-controls"><button class="btn btn-small" type="button" data-action="play" aria-pressed="${String(!!(ui.edit && ui.edit.playing))}">${icon(ui.edit && ui.edit.playing ? "pause" : "play")}${ui.edit && ui.edit.playing ? "Pause" : "Play"}</button><span class="tiny faint">The exact file that will be posted: version ${c.version}.</span></div></div>
          <p class="small"><a class="textlink" href="#/clip/${c.id}">${c.title}</a> <span class="faint">· clip from “${project(c.projectId).name}”</span></p>
          <p class="tiny faint">Changing the clip makes a new file. A new file needs a new final check and a new OK before it can be posted.</p></div>
        <div class="stack-4">
          ${statusBlock(x)}
          <section class="panel" aria-labelledby="checks-h"><h2 id="checks-h" style="font-size:var(--fs-h3)">Before it can go out</h2>
            <dl class="kv"><dt>Account</dt><dd>${acc.state === "connected" ? acc.name : h`${pill("bad", acc.state === "expired" ? "Sign-in expired" : "Not connected", "alert")} <button class="btn btn-small" type="button" data-action="reconnect" data-id="${x.platform}">Reconnect <span class="demo-mark">demo</span></button>`}</dd>
              <dt>Permission to use</dt><dd>${pill("good", x.rights.label, "shield")} <span class="small muted">${x.rights.basis}</span></dd>
              <dt>Final check</dt><dd>${q.status === "passed" ? pill(q.warnings.length ? "warn" : "good", q.warnings.length ? `Passed with ${plural(q.warnings.length, "warning")}` : "Passed", q.warnings.length ? "alert" : "check") : q.status === "pending" ? pill("neutral", "Not done yet", "clock") : pill("bad", "Failed", "alert")}
                ${q.warnings.map((w) => h`<div class="small muted">${w}</div>`)}${q.blockers.map((w) => h`<div class="small">${w}</div>`)}</dd></dl>
            ${q.checks.length ? h`<details class="plain"><summary>${icon("chev", "chev sm")}All ${q.checks.length} checks of this exact file</summary><div class="more-body"><ul class="check-list">${q.checks.map((k) => h`<li><span class="${{ pass: "good", warn: "warn", fail: "bad", skipped: "skip" }[k.status]}">${icon(k.status === "pass" ? "check" : k.status === "fail" ? "x" : "alert", "sm")}</span><span>${k.label}: ${{ pass: "passed", warn: "warning", fail: "failed", skipped: "not checked" }[k.status]}${k.detail ? ` (${k.detail})` : ""}</span></li>`)}</ul><p class="tiny faint">Checks marked “estimate” are heuristics. The report is tied to this file's fingerprint (SHA-256).</p></div></details>` : ""}
          </section>
          ${x.status === "awaiting_approval" || x.status === "approved" ? h`<section class="panel" aria-labelledby="text-h"><h2 id="text-h" style="font-size:var(--fs-h3)">Text and visibility</h2>
            ${x.options ? h`<div class="field"><span class="label">Suggestions <span class="hint">written from the clip's own words</span></span><div class="chips">${x.options.map((o) => h`<button class="chip" type="button" data-action="rv-option" data-id="${x.id}" data-value="${o}" aria-pressed="${String(!!(f.title === o))}">${o}</button>`)}</div></div>` : ""}
            ${yt ? h`<div class="field"><label for="rv-title">Title <span class="hint tnum">${f.title.length}/100</span></label><input id="rv-title" type="text" value="${f.title}" data-bind="rv-title" data-id="${x.id}"></div>` : ""}
            <div class="field"><label for="rv-text">${yt ? "Description" : "Caption"} ${!yt ? h`<span class="hint tnum">${f.text.length}/2200</span>` : ""}</label><textarea id="rv-text" rows="4" data-bind="rv-text" data-id="${x.id}">${f.text}</textarea></div>
            ${yt ? h`<div class="field"><label for="rv-tags">Tags</label><input id="rv-tags" type="text" value="${f.tags}" data-bind="rv-tags" data-id="${x.id}"></div>
              <div class="field"><span class="label">Who can see it</span>${seg("rv-priv", [["public", "Public"], ["unlisted", "Unlisted"], ["private", "Private"]], f.privacy, "Who can see it")}</div>
              ${f.privacy === "public" ? h`<p class="tiny faint">It is uploaded early as Private with a publish time; YouTube itself makes it public ${at(x.when)}.</p>` : ""}
              ${acc.restriction && f.privacy !== "private" ? h`<p class="small"><span class="pill warn">${icon("alert")}Note</span> ${acc.restriction}</p>` : ""}
              <fieldset><legend class="label">Made for kids <span class="hint">(YouTube requires an answer)</span></legend>${[["no", "No, it's not made for kids"], ["yes", "Yes, it's made for kids"]].map(([v, l]) => h`<label class="choice"><input type="radio" name="rv-kids" value="${v}" ${f.kids === v ? raw("checked") : ""} data-bind="rv-kids" data-id="${x.id}"><span>${l}</span></label>`)}</fieldset>`
            : h`<p class="small">Posting as <b>${acc.name}</b></p>
              <fieldset><legend class="label">How to post</legend>${[["direct", "Post directly to your profile"], ["inbox", "Send to your TikTok inbox as a draft (you finish it in the TikTok app)"]].map(([v, l]) => h`<label class="choice"><input type="radio" name="rv-mode" value="${v}" ${f.mode === v ? raw("checked") : ""} data-bind="rv-mode" data-id="${x.id}"><span>${l}</span></label>`)}</fieldset>
              ${f.mode === "direct" ? h`<div class="field"><label for="rv-tpriv">Who can see it</label><select id="rv-tpriv" data-bind="rv-tpriv" data-id="${x.id}"><option value="" ${f.privacy ? "" : raw("selected")} disabled>Choose…</option><option disabled>Everyone (needs TikTok's app audit)</option><option disabled>Followers (needs TikTok's app audit)</option><option value="SELF_ONLY" ${f.privacy === "SELF_ONLY" ? raw("selected") : ""}>Only me</option></select></div>
                <p class="small"><span class="pill warn">${icon("alert")}Note</span> ${acc.restriction || "Until TikTok audits your app, Direct Post only works for “Only me”."}</p>
                <fieldset><legend class="label">Allow viewers to</legend><div class="row wrap">${checkbox("rv-c", "Comment", false)}${checkbox("rv-d", "Duet", false)}${checkbox("rv-s", "Stitch", false)}</div></fieldset>
                ${checkbox("rv-disc", "This video promotes a brand, product or service (disclose commercial content)", false)}` : ""}
              <p class="tiny faint">By posting, you agree to TikTok's Music Usage Confirmation. It may take a few minutes for the video to appear on your profile.</p>`}
          </section>` : ""}
          <div class="row wrap">${["awaiting_approval", "approved", "failed", "action_needed"].includes(x.status) ? h`<button class="btn btn-danger" type="button" data-action="cancel-post" data-id="${x.id}">Cancel this post…</button>` : ""}
            ${["awaiting_approval", "approved"].includes(x.status) ? h`<button class="btn btn-quiet" type="button" data-action="demo-note" data-note="In the app this lets you pick another date and time (in ${S.tzAbbr}).">${icon("clock")}Change the time…</button>` : ""}</div>
        </div></div>
      ${x.status === "awaiting_approval" ? h`<section class="savebar approve-bar" aria-labelledby="ok-h">
        <div class="grow"><h2 id="ok-h" class="small strong">Your OK for ${PNAME[x.platform]}</h2>
          <span class="small muted">Approving posts this exact video with this text ${at(x.when)} ${S.tzAbbr} to ${acc.name || PNAME[x.platform]}, without asking again. Nothing is posted now. If the video or the text changes, it needs your OK again, and you can cancel it until it goes out.</span>
          <label class="choice"><input type="checkbox" ${f.agree ? raw("checked") : ""} data-bind="rv-agree" data-id="${x.id}"><span class="small">I watched this video and read its text.</span></label></div>
        <div class="stack approve-side"><button class="btn btn-primary" type="button" data-action="approve" data-id="${x.id}" ${problems.length ? raw('aria-disabled="true"') : ""} aria-describedby="ok-why">${icon("check")}Approve for ${PNAME[x.platform]} <span class="demo-mark">demo</span></button>
          <span class="tiny muted" id="ok-why">${problems.length ? `To approve: ${problems.join(", ")}.` : "Ready to approve."}</span></div>
      </section>` : ""}</div>`;
  }
  function statusBlock(x) {
    const yt = x.platform === "youtube";
    if (x.status === "approved") return h`<section class="panel" aria-labelledby="st-h"><h2 id="st-h" style="font-size:var(--fs-h3)">${x.approvedBy === "automatic" ? "Approved automatically" : "Approved by you"}</h2>
      <p class="small muted">${x.approvedBy === "automatic" ? "Your automatic-publishing permission for YouTube approved it, because every check passed. You did not review it." : "You approved this exact video and text."} It goes out ${at(x.when)} ${S.tzAbbr} by itself.</p>
      <div class="consequence"><b>Publish now instead?</b><span>“Publish now” uploads it right away instead of ${at(x.when)}. The upload can't be taken back from ClipFoundry; you would remove it on ${PNAME[x.platform]}.</span></div>
      <div class="row wrap"><button class="btn" type="button" data-action="publish-now" data-id="${x.id}">${icon("upload")}Publish now… <span class="demo-mark">demo</span></button></div></section>`;
    if (x.status === "reconciling") return h`<section class="banner warn" role="alert" aria-labelledby="st-h">${icon("question")}<div class="grow"><b id="st-h">Upload not confirmed</b><span class="small">${x.statusNote}</span><span class="small">ClipFoundry won't upload it again by itself, so the video can never be posted twice.</span><span class="small"><b>What to do:</b> ${x.fix}</span>
      <div class="actions"><button class="btn btn-small" type="button" data-action="resolve-yes" data-id="${x.id}">${icon("check")}It's on YouTube: add its link… <span class="demo-mark">demo</span></button><button class="btn btn-small" type="button" data-action="resolve-no" data-id="${x.id}">${icon("refresh")}It's not there: upload again… <span class="demo-mark">demo</span></button></div></div></section>`;
    if (x.status === "failed") return h`<section class="banner bad" role="alert" aria-labelledby="st-h">${icon("alert")}<div class="grow"><b id="st-h">It could not be posted</b><span class="small">${x.statusNote}</span><span class="small"><b>What to do:</b> ${x.fix}</span>
      <div class="actions">${!accOk(x.platform) ? h`<button class="btn btn-small" type="button" data-action="reconnect" data-id="${x.platform}">Reconnect ${PNAME[x.platform]} <span class="demo-mark">demo</span></button>` : ""}<button class="btn btn-small" type="button" data-action="retry" data-id="${x.id}" ${accOk(x.platform) ? "" : raw('aria-disabled="true" title="Reconnect first"')}>${icon("refresh")}Try again <span class="demo-mark">demo</span></button></div></div></section>`;
    if (x.status === "blocked") return h`<section class="banner bad" role="alert" aria-labelledby="st-h">${icon("shield")}<div class="grow"><b id="st-h">Blocked: this file did not pass the final check</b><span class="small">${x.statusNote}</span><span class="small"><b>What to do:</b> ${x.fix}</span><div class="actions"><a class="btn btn-small" href="#/clip/${x.clipId}">${icon("edit")}Open the clip</a></div></div></section>`;
    if (x.status === "action_needed") return h`<section class="banner info" aria-labelledby="st-h">${icon("info")}<div class="grow"><b id="st-h">Finish it in the TikTok app</b><span class="small">${x.statusNote}</span>
      <div class="field"><label for="link-in">Link of the post you made</label><input id="link-in" type="url" placeholder="https://www.tiktok.com/@…"></div><div class="actions"><button class="btn btn-small" type="button" data-action="demo-note" data-note="The link would be saved so the post's results can be tracked.">Save link <span class="demo-mark">demo</span></button></div></div></section>`;
    if (x.status === "published" && x.onPlatform) return h`<section class="banner info" aria-labelledby="st-h">${icon("clock")}<div class="grow"><b id="st-h">Uploaded and waiting for its time</b><span class="small">${x.note}</span></div></section>`;
    if (x.status === "published") return h`<section class="panel" aria-labelledby="st-h"><h2 id="st-h" style="font-size:var(--fs-h3)">Published ${x.published}</h2>
      <div class="row wrap"><button class="btn btn-small" type="button" data-action="demo-note" data-note="This opens the post on ${PNAME[x.platform]}.">${icon("external")}Open on ${PNAME[x.platform]}</button>${yt ? h`<button class="btn btn-small btn-quiet" type="button" data-action="demo-note" data-note="This opens YouTube Studio.">YouTube Studio</button>` : ""}</div>
      ${x.stats ? h`<div class="totals">${[["Views", x.stats.views], ["Likes", x.stats.likes], ["Comments", x.stats.comments], ["Shares", x.stats.shares]].map(([l, v]) => h`<div class="total"><b>${v === null ? "—" : num(v)}</b><span>${l}${v === null ? " · not reported" : ""}</span></div>`)}</div><p class="tiny faint">As of ${x.stats.at}. ${Object.values(x.stats.notes || {}).join(" ")}</p>` : ""}</section>`;
    if (x.status === "canceled") return h`<section class="panel"><p class="small muted">${x.statusNote}</p></section>`;
    return "";
  }

  // ================================================================== SETTINGS
  function pageSettings(tab) {
    const tabs = [["accounts", "Accounts"], ["defaults", "Defaults"], ["advanced", "Advanced"]];
    const t = tabs.some(([k]) => k === tab) ? tab : "accounts";
    if (!ui.settings) ui.settings = { ...S.settings, dirty: false };
    const s = ui.settings;
    const gpuBad = S.autopilot.gpu.state === "problem";
    const accBad = ["youtube", "tiktok"].filter((p) => S.accounts[p].state === "expired");
    return h`<div class="page narrow">${connectionBanner()}
      <div class="page-head"><div><h1>Settings</h1><p class="muted">Stored on this computer, in ClipFoundry's data folder.</p></div></div>
      ${accBad.length && t !== "accounts" ? h`<div class="banner bad">${icon("link")}<div class="grow"><span class="small"><b>${accBad.map((p) => PNAME[p]).join(" and ")} ${accBad.length > 1 ? "need" : "needs"} you to sign in again.</b> <a class="textlink" href="#/settings">Open Accounts</a></span></div></div>` : ""}
      ${gpuBad && t !== "advanced" ? h`<div class="banner bad">${icon("cpu")}<div class="grow"><span class="small"><b>GPU transcription is not working.</b> ${S.autopilot.gpu.fix} <a class="textlink" href="#/settings/advanced">Open GPU settings</a></span></div></div>` : ""}
      <nav class="tabs" aria-label="Settings">${tabs.map(([k, l]) => h`<a href="#/settings${k === "accounts" ? "" : "/" + k}" ${k === t ? raw('aria-current="page"') : ""}>${l}</a>`)}</nav>
      ${t === "accounts" ? settingsAccounts() : t === "defaults" ? settingsDefaults(s) : settingsAdvanced(s)}
      ${t !== "accounts" ? h`<div class="savebar" role="region" aria-label="Save settings"><div class="grow"><b class="small">${s.dirty ? "Unsaved changes" : ui.settingsSaved ? "Saved" : "No changes"}</b>${Object.keys(ui.settingsErrors).length ? h`<span class="error-text" role="alert">${icon("alert", "sm")}Fix the field marked below before saving.</span>` : ""}</div>
        <button class="btn btn-quiet" type="button" data-action="settings-discard" ${s.dirty ? "" : raw("disabled")}>Discard</button><button class="btn btn-primary" type="button" data-action="settings-save" ${s.dirty ? "" : raw("disabled")}>Save settings <span class="demo-mark">demo</span></button></div>` : ""}
    </div>`;
  }
  function settingsAccounts() {
    return h`<p class="small muted">Connect the platforms you want to post to. You sign in on Google's or TikTok's own page; ClipFoundry never sees your password. <b>Connecting an account doesn't let ClipFoundry post by itself.</b></p>
      ${["youtube", "tiktok"].map((pf) => { const a = S.accounts[pf]; const yt = pf === "youtube";
        const state = a.state === "connected" ? pill("good", `Connected: ${a.name}`, "check") : a.state === "expired" ? pill("bad", "Sign-in expired: connect again", "alert") : pill("neutral", a.configured ? "Not connected" : "Not set up", "link");
        return h`<section class="panel" aria-labelledby="acc-${pf}"><div class="panel-head"><h2 id="acc-${pf}">${yt ? "YouTube" : "TikTok"}</h2><div class="row wrap">${state}
            ${a.state === "connected" ? h`<button class="btn btn-small" type="button" data-action="disconnect" data-id="${pf}">Disconnect…</button>` : h`<button class="btn btn-small btn-primary" type="button" data-action="reconnect" data-id="${pf}">${a.state === "expired" ? `Reconnect ${PNAME[pf]}` : `Connect ${PNAME[pf]}`} <span class="demo-mark">demo</span></button>`}</div></div>
          ${a.state === "expired" ? h`<p class="small">${PNAME[pf]} stopped accepting ClipFoundry's sign-in. Sign in again to keep posting. Planned posts wait until then.</p>` : ""}
          ${a.restriction && a.state !== "not_set_up" ? h`<p class="small"><span class="pill warn">${icon("alert")}Note</span> ${a.restriction}</p>` : ""}
          ${yt ? h`<div class="stack"><span class="label small strong">Automatic publishing</span>${autoPublishLines()}</div>` : h`<p class="small">Posting: <b>your OK on each post</b>. TikTok's rules require a preview and your consent for every upload. ${a.state === "connected" ? `Permissions: ${a.directPost ? "Direct Post" : "no Direct Post"} · ${a.inbox ? "send to inbox" : "no inbox"} · ${a.stats ? "video statistics" : "no video statistics"}.` : ""}</p>`}
          <details class="plain"><summary>${icon("chev", "chev sm")}Your ${PNAME[pf]} app codes${a.configured ? "" : " (needed once)"}</summary><div class="more-body">
            <p class="small muted">${PNAME[pf]} only lets apps like ClipFoundry post through your own free developer app. Paste its two codes once.</p>
            <div class="field"><label for="${pf}-id">${yt ? "OAuth client ID" : "Client key"}</label><input id="${pf}-id" type="text" value="${a.configured ? (yt ? "sample-id.apps.googleusercontent.com" : "sample-client-key") : ""}" autocomplete="off"></div>
            <div class="field"><label for="${pf}-secret">Client secret <span class="hint">stored encrypted with Windows (DPAPI) and never shown again</span></label>
              ${a.configured && !ui.replaceSecret[pf] ? h`<div class="row"><input id="${pf}-secret" type="text" value="•••••••• (saved)" readonly><button class="btn btn-small" type="button" data-action="replace-secret" data-id="${pf}">Replace…</button></div>` : h`<input id="${pf}-secret" type="password" autocomplete="new-password" placeholder="Paste the new secret">`}</div>
            ${!yt ? h`<div class="field"><span class="label">Redirect address to register in your TikTok app</span><div class="row"><code class="break grow">http://127.0.0.1:8765/api/oauth/tiktok/callback</code><button class="btn btn-small" type="button" data-action="copy" data-note="http://127.0.0.1:8765/api/oauth/tiktok/callback">Copy</button></div></div>
              <fieldset><legend class="label">Permissions to ask TikTok for</legend>${checkbox("tt-direct", "Direct Post (video.publish)", true)}${checkbox("tt-stats", "Video statistics (video.list)", false)}</fieldset>` : ""}
            ${checkbox(`${pf}-audited`, yt ? "My Google Cloud project passed YouTube's API audit (tick only after Google approved it)" : "My TikTok app passed TikTok's Content Posting audit (tick only after TikTok approved it)", a.audited)}
            <details class="plain"><summary>${icon("chev", "chev sm")}How to get these codes (free, about 10 minutes)</summary><div class="more-body small muted">${yt ? "Create a project in Google Cloud, enable YouTube Data API v3, set up the OAuth consent screen with yourself as a test user, create an OAuth client of type Desktop app, then paste its ID and secret here." : "Create an app at developers.tiktok.com with Login Kit (Desktop) and Content Posting API, add the scopes, register the redirect address above, add yourself as a target user, then paste the key and secret here."}</div></details>
          </div></details></section>`; })}`;
  }
  function settingsDefaults(s) {
    return h`<section class="panel" aria-labelledby="def-clips"><h2 id="def-clips">New clips</h2><p class="small muted">Used for every new video. You can change them per video under Add video, More options.</p>
        <div>${settingRow("Clips per video", "At most; weak moments are skipped", seg("set-count", [3, 5, 10].map((n) => [n, String(n)]), s.clip_count))}
        ${settingRow("Clip length", "", seg("set-len", [["short", "15–30 s"], ["standard", "15–60 s"], ["long", "30–90 s"]], s.length))}
        ${settingRow("Caption style", "", captionStyles("set-style", s.caption_style))}
        ${settingRow("Framing", "How the 9:16 crop follows the action", h`<div class="stack"><select aria-label="Framing follows"><option>Auto</option><option>Center</option><option>Face</option><option>Active speaker</option><option>Screen content</option></select>${seg("set-layout", [["fill", "Fill (crop)"], ["fit", "Fit (blurred background)"]], s.layout)}</div>`)}
        ${settingRow("Silence cleanup", "", seg("set-sil", [["off", "Off"], ["light", "Light"], ["aggressive", "Strong"]], s.silence))}
        ${settingRow("Extras", "", h`<div class="stack">${checkbox("set-zoom", "Auto-zoom", s.auto_zoom)}${checkbox("set-fill", "Cut filler words", s.remove_fillers)}${checkbox("set-emph", "Emphasize key words", s.caption_emphasis)}${checkbox("set-hook", "Hook on screen", s.hook_overlay)}${checkbox("set-norm", "Normalize loudness", s.normalize_audio)}</div>`)}</div></section>
      <section class="panel" aria-labelledby="def-ap"><h2 id="def-ap">Autopilot</h2>
        <div>${settingRow("Daily target", "Clips a day to aim for. A target, not a quota: quality and your rights come first", h`<input type="number" min="1" max="100" value="${s.daily_target}" style="max-width:140px" aria-label="Daily target" data-bind="set-target">`)}
        ${settingRow("Posting hours", `Posts only between these hours (${S.timezone})`, h`<div class="inline-fields"><input type="number" min="0" max="23" value="${s.active_start}" aria-label="From hour" data-bind="set-x"><span>to</span><input type="number" min="1" max="24" value="${s.active_end}" aria-label="To hour" data-bind="set-x"></div>`)}
        ${settingRow("Topics to look for online", "Broad on purpose", h`<input type="text" value="${S.topics.join(", ")}" aria-label="Topics" data-bind="set-x">`)}</div>
        <p class="small muted">Everything else has a sensible default. It's under Advanced, but you don't need to change it.</p></section>`;
  }
  function settingsAdvanced(s) {
    const tzErr = ui.settingsErrors.tz;
    const g = S.autopilot.gpu;
    return h`
      <section class="panel" aria-labelledby="adv-gpu" id="gpu"><h2 id="adv-gpu">Transcription and GPU</h2>
        ${g.state === "problem" ? h`<div class="banner bad" role="alert">${icon("cpu")}<div class="grow"><b>GPU transcription is not working</b><span class="small">${g.detail}</span><span class="small"><b>What to do:</b> ${g.fix}</span></div></div>` : ""}
        <dl class="kv"><dt>GPU</dt><dd>${g.state === "none" ? "No NVIDIA GPU found" : g.name}</dd><dt>Transcription now</dt><dd>${gpuFact()[2]}</dd></dl>
        <div>${settingRow("Whisper model", "auto = large-v3-turbo on the GPU, small on the CPU", h`<select aria-label="Whisper model">${["auto", "tiny", "base", "small", "medium", "large-v3", "large-v3-turbo", "distil-large-v3"].map((m) => h`<option>${m}</option>`)}</select>`)}
        ${settingRow("Device", "", seg("adv-dev", [["auto", "Auto"], ["cuda", "GPU (CUDA)"], ["cpu", "CPU"]], s.whisper_device))}
        ${settingRow("Allow CPU transcription in Autopilot", "Off: if the GPU fails, Autopilot pauses and tells you why. Videos you add yourself always fall back to the CPU, and say so", toggle("adv-cpu", s.allow_cpu, "Allow CPU transcription in Autopilot", "set-toggle"))}
        ${settingRow("Free GPU memory needed", "Autopilot waits for this much free VRAM before transcribing (MB)", h`<input type="number" value="1500" style="max-width:140px" aria-label="Free GPU memory needed in MB">`)}</div></section>
      <section class="panel" aria-labelledby="adv-ap"><h2 id="adv-ap">Autopilot details</h2>
        <div>${settingRow("Time zone", "Posting hours and times use this zone", h`<div class="stack"><input id="adv-tz" type="text" value="${s.timezone}" data-bind="set-tz" ${tzErr ? raw('aria-invalid="true" aria-describedby="adv-tz-err"') : ""}>${tzErr ? h`<span class="error-text" id="adv-tz-err">${icon("alert", "sm")}${tzErr}</span>` : ""}</div>`, "adv-tz")}
        ${settingRow("Keep the PC awake", "Windows: the PC doesn't sleep while Autopilot is on (the screen still can)", toggle("adv-awake", s.keep_awake, "Keep the PC awake", "set-toggle"))}
        ${settingRow("Sources per day, clips per source, minimum quality", "", h`<div class="inline-fields"><input type="number" value="3" aria-label="Sources per day"><input type="number" value="5" aria-label="Clips per source"><input type="number" value="60" aria-label="Minimum clip quality"></div>`)}
        ${settingRow("Replace weaker planned posts", "A clearly stronger new clip may take the slot of the weakest future post, at most once every 24 hours per slot", toggle("adv-repl", true, "Replace weaker planned posts", "set-toggle"))}
        ${settingRow("Worker process", "Own process: a crash in a worker can't take the app down", seg("adv-proc", [["separate", "Own process"], ["in_app", "Inside the app"]], "separate"))}</div>
        <p class="small muted">Also here, unchanged: platforms used, automatic scheduling, live monitoring, learning, minimum gap, posts per day per platform, suggested YouTube visibility, upload lead time, allow republishing.</p></section>
      <section class="panel" aria-labelledby="adv-disc"><h2 id="adv-disc">Discovery and rights</h2>
        <div>${settingRow("YouTube Data API key", "Optional", h`<div class="row"><input type="text" value="•••••••• (saved)" readonly aria-label="YouTube Data API key (saved)"><button class="btn btn-small" type="button" data-action="demo-note" data-note="Replace would show an empty password field for a new key.">Replace…</button></div>`)}
        ${settingRow("Monthly cost limit", "US dollars for paid web searches. 0 = never spend money", h`<input type="number" value="0" style="max-width:140px" aria-label="Monthly cost limit in US dollars">`)}
        ${settingRow("Use automatically", "Owned videos are always allowed. Uncovered videos never are: they're skipped and listed in Activity", h`<div class="stack">${checkbox("r-lic", "Licensed", true)}${checkbox("r-allow", "Allowlisted (creator agreements)", true)}${checkbox("r-cc", "Creative Commons (CC BY, with a credit line)", true)}${checkbox("r-pd", "Public domain and CC0", true)}</div>`)}</div>
        <p class="small muted">Also here, unchanged: region and language, check interval, video age, derived-metrics approval, web search key and credits, free-license library, “ask me about strong videos”, “my posts are commercial”, downloads of authorized sources, YouTube quota shares.</p></section>
      <section class="panel" aria-labelledby="adv-render"><h2 id="adv-render">Rendering, AI scoring and system</h2>
        <p class="small muted">Unchanged from today and kept here: encoder (Auto, NVENC, x264), quality (CRF), x264 preset, frame rate, FFmpeg location, minimum Viral Potential, clip length in seconds, AI scoring provider (local heuristic, Ollama, LM Studio, Claude API with its key and cost cap) with “Test connection”, and the system details (version, FFmpeg, Whisper, data folder).</p></section>`;
  }

  // ================================================================== FIRST-TIME SETUP
  function pageSetup(step) {
    const steps = [["videos", "Add your videos"], ["mode", "Choose how to work"], ["posting", "Set up posting"]];
    const idx = Math.max(0, steps.findIndex(([k]) => k === step));
    const nav = h`<ol class="setup-steps" aria-label="Setup steps">${steps.map(([k, l], i) => h`<li class="${i < idx ? "done" : ""}" ${i === idx ? raw('aria-current="step"') : ""}><span class="n">${i < idx ? icon("check", "sm") : i + 1}</span>${l}</li>`)}</ol>`;
    let body;
    if (idx === 0) body = h`<section class="panel" aria-labelledby="st1"><h2 id="st1">Where are your videos?</h2>
        <p class="muted">Use videos you made, or videos you have permission to use. ClipFoundry never uses other people's videos without an agreement or a free license.</p>
        <div class="cols-2"><div class="choice-card" style="display:grid"><b>Choose one video now</b><span class="small muted">Pick a long video and see its clips in a few minutes.</span><a class="btn" href="#/create" style="justify-self:start">${icon("plus")}Choose a video</a></div>
          <div class="choice-card" style="display:grid"><b>Use your videos folder</b><span class="small muted">A folder in Videos\\ClipFoundry. Anything you put there is clipped by Autopilot, once it's on.</span><button class="btn" type="button" data-action="open-folder" style="justify-self:start">${icon("folder")}Open videos folder <span class="demo-mark">demo</span></button></div></div>
        <div class="row wrap"><span class="grow small muted">You can do both, and add more later.</span><a class="btn btn-primary" href="#/setup/mode">Continue</a></div></section>`;
    else if (idx === 1) body = h`<section class="panel" aria-labelledby="st2"><fieldset><legend><h2 id="st2">How do you want to work?</h2></legend>
        <label class="choice-card"><input type="radio" name="how" value="manual" ${ui.setup.how === "manual" ? raw("checked") : ""} data-bind="setup-how"><span class="stack" style="gap:2px"><b>I'll pick videos and make clips myself</b><span class="small muted">You add a video, choose the clips you like, edit and export them. Nothing runs in the background.</span></span></label>
        <label class="choice-card"><input type="radio" name="how" value="autopilot" ${ui.setup.how === "autopilot" ? raw("checked") : ""} data-bind="setup-how"><span class="stack" style="gap:2px"><b>Let Autopilot do it</b><span class="small muted">It clips your videos folder and videos it may use (like public-domain ones), writes titles and plans posting times. It never posts without an OK.</span></span></label></fieldset>
        ${ui.setup.how === "autopilot" ? h`<div class="field"><span class="label" id="topics-l">What should it look for online? <span class="hint">A suggestion is filled in; change it if you like</span></span>
          <div class="chips" role="group" aria-labelledby="topics-l">${["podcasts", "interviews", "comedy", "sports", "gaming", "science", "business", "education", "news", "technology"].map((t) => h`<button class="chip" type="button" aria-pressed="${String(!!(ui.setup.topics.includes(t)))}" data-action="topic" data-id="${t}">${t}</button>`)}</div></div>` : ""}
        <div class="row wrap"><a class="btn btn-quiet" href="#/setup/videos">Back</a><span class="grow small muted">You can switch any time.</span><a class="btn btn-primary" href="#/setup/posting" ${ui.setup.how ? "" : raw('aria-disabled="true" data-action="need-choice"')}>Continue</a></div></section>`;
    else body = h`<section class="panel" aria-labelledby="st3"><h2 id="st3">Post to YouTube and TikTok when you're ready</h2>
        <p class="muted">Optional. Without accounts you can still make clips and export them. Connecting an account does <b>not</b> let ClipFoundry post by itself: every post needs your OK, and YouTube can post automatically only if you turn that on separately. TikTok always asks.</p>
        <div class="rows">${["youtube", "tiktok"].map((pf) => h`<div class="row wrap" style="padding:12px 0">${platform(pf)}<span class="grow small muted">${pf === "youtube" ? "Posts Shorts to your channel and finds videos you may use." : "Posts to your TikTok account, with your OK on each post."}</span>
          ${accOk(pf) ? pill("good", `Connected: ${S.accounts[pf].name}`, "check") : h`<button class="btn" type="button" data-action="reconnect" data-id="${pf}">Connect ${PNAME[pf]} <span class="demo-mark">demo</span></button>`}</div>`)}</div>
        <p class="small muted">The first time, each platform asks for the two codes of your own free developer app (10 minutes, steps included).</p>
        <div class="row wrap"><a class="btn btn-quiet" href="#/setup/mode">Back</a><span class="grow"></span><button class="btn" type="button" data-action="setup-finish" data-id="skip">Skip for now</button>
          <button class="btn btn-primary" type="button" data-action="setup-finish" data-id="done">${ui.setup.how === "autopilot" ? "Start Autopilot" : "Finish"} <span class="demo-mark">demo</span></button></div></section>`;
    return h`<div class="page narrow"><div class="page-head"><div><h1>Set up ClipFoundry</h1><p class="muted">Three short steps. You can skip anything and come back later.</p></div></div>${nav}${body}</div>`;
  }

  // ================================================================== drawer (small windows)
  function renderDrawer() {
    const root = document.getElementById("drawer-root");
    const btn = document.querySelector('[data-action="drawer"]');
    if (btn) btn.setAttribute("aria-expanded", String(ui.drawer));
    if (!ui.drawer) { root.innerHTML = ""; return; }
    root.innerHTML = val(h`<div class="drawer-bg" data-action="drawer-close"></div><div class="drawer" id="drawer" role="dialog" aria-modal="true" aria-label="Menu">
      <div class="drawer-head"><span class="brand-name">Clip<span>Foundry</span></span><button class="btn btn-icon btn-quiet" type="button" data-action="drawer-close" aria-label="Close menu">${icon("x")}</button></div>
      <nav class="nav" aria-label="Main">${navItems()}</nav></div>`);
    trapFocus(root.querySelector(".drawer"), () => { ui.drawer = false; renderDrawer(); btn && btn.focus(); });
  }

  // ================================================================== dialogs, toasts, announcements
  let dialogReturn = null;
  function dialog({ title, body, actions, wide }) {
    dialogReturn = document.activeElement;
    const root = document.getElementById("dialog-root");
    root.innerHTML = val(h`<div class="dialog-bg" data-action="dialog-bg"><div class="dialog ${wide ? "wide" : ""}" role="dialog" aria-modal="true" aria-labelledby="dlg-title">
      <h2 id="dlg-title">${title}</h2>${body}<div class="dialog-actions">${actions.map((a, i) => h`<button class="btn ${a.primary ? "btn-primary" : a.danger ? "btn-danger" : a.quiet ? "btn-quiet" : ""}" type="button" data-dlg="${i}">${a.label}${a.demo ? h` <span class="demo-mark">demo</span>` : ""}</button>`)}</div></div></div>`);
    const box = root.querySelector(".dialog");
    root.querySelectorAll("[data-dlg]").forEach((b) => b.addEventListener("click", () => {
      const a = actions[+b.dataset.dlg];
      const keep = a.run && a.run(box) === false;
      if (!keep) closeDialog();
    }));
    trapFocus(box, closeDialog);
    const first = box.querySelector("input, select, textarea") || box.querySelector("[data-dlg]");
    first && first.focus();
  }
  function closeDialog() {
    document.getElementById("dialog-root").innerHTML = "";
    if (dialogReturn && document.contains(dialogReturn)) dialogReturn.focus();
    dialogReturn = null;
  }
  function trapFocus(box, onEscape) {
    box.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); onEscape(); return; }
      if (e.key !== "Tab") return;
      const f = [...box.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex="0"]')].filter((x) => x.offsetParent !== null);
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    });
    if (!box.contains(document.activeElement)) { const f = box.querySelector("button, a[href]"); f && f.focus(); }
  }
  let toastTimer;
  function toast(msg, bad) {
    document.getElementById("live").textContent = msg;
    document.getElementById("toast-root").innerHTML = val(h`<div class="toast ${bad ? "bad" : ""}" aria-hidden="true">${icon(bad ? "alert" : "check")}<span>${msg}</span></div>`);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { document.getElementById("toast-root").innerHTML = ""; }, 5200);
  }
  function askLeave(target) {
    dialog({ title: "Leave without saving?", body: h`<p class="muted">You changed ${[...ui.edit.dirty].map((k) => EDIT_TABS.find((t) => t[0] === k)[1]).join(", ")}. If you leave now, those changes are lost.</p>`,
      actions: [{ label: "Stay", quiet: true }, { label: "Discard and leave", danger: true, run: () => { ui.edit = null; pendingLeave = target; setTimeout(() => go(target)); } },
        { label: "Save and leave", primary: true, run: () => { saveEdit(false); pendingLeave = target; setTimeout(() => go(target)); } }] });
  }

  // ================================================================== actions
  function saveEdit(announce = true) {
    const e = ui.edit; if (!e) return;
    const renderish = [...e.dirty].some((k) => k !== "post");
    e.saved = { ...e.draft }; e.dirty.clear(); e.savedNotRendered = e.savedNotRendered || renderish; e.justRendered = false;
    if (announce) toast(renderish ? "Saved. The video changes when you render it." : "Post text saved.");
  }
  function markDirty(group) { if (ui.edit) { ui.edit.dirty.add(group); ui.edit.justRendered = false; } }
  const DEMO_ONLY = " Nothing really happened: this is a prototype.";

  const ACTIONS = {
    "demo-panel": () => { ui.demo.panel = !ui.demo.panel; renderDemo(); },
    "demo-note": (el) => toast(`${el.dataset.note || el.dataset.id}${DEMO_ONLY}`),
    skip: (el, e) => { e.preventDefault(); document.getElementById("main").focus(); },
    drawer: () => { ui.drawer = !ui.drawer; renderDrawer(); },
    "drawer-close": () => { ui.drawer = false; renderDrawer(); const b = document.querySelector('[data-action="drawer"]'); b && b.focus(); },
    menu: (el) => { ui.menu = ui.menu === el.dataset.id ? null : el.dataset.id; render(); const m = document.getElementById(ui.menu || ""); if (m) { const f = m.querySelector("button:not([disabled]), a"); f && f.focus(); } },
    "dialog-bg": (el, e) => { if (e.target === el) closeDialog(); },
    "reconnect-app": () => { S.connection = "live"; toast("ClipFoundry answered again (demo)."); render(); },
    reconnect: (el) => { const pf = el.dataset.id; S.accounts[pf] = { ...S.accounts[pf], state: "connected", configured: true, name: S.accounts[pf].name || (pf === "youtube" ? "Sample channel · Morning Mic" : "@sample.morningmic"), restriction: S.accounts[pf].restriction || (pf === "youtube" ? "Until Google audits your API project, YouTube keeps uploads from it Private." : "Until TikTok audits your app, Direct Post only works for private accounts and “Only me”.") };
      toast(`${PNAME[pf]} connected (demo). In the app, ${PNAME[pf]}'s own sign-in page opens in a new tab.`); render(); },
    disconnect: (el) => { const pf = el.dataset.id; dialog({ title: `Disconnect ${PNAME[pf]}?`, body: h`<p class="muted">ClipFoundry gives up its access and deletes the stored sign-in. Planned ${PNAME[pf]} posts wait until you connect again.</p>`,
      actions: [{ label: "Keep connected", quiet: true }, { label: "Disconnect", danger: true, demo: true, run: () => { S.accounts[pf].state = "not_connected"; toast(`${PNAME[pf]} disconnected (demo).`); render(); } }] }); },
    "open-folder": () => toast(`In the app this opens File Explorer at ${S.myVideos.path}.${DEMO_ONLY}`),
    "add-file": () => dialog({ title: "Add the video file", body: h`<p class="muted small">ClipFoundry doesn't download videos from YouTube or other platforms by itself (their terms). Choose the original file on this computer; for your own videos, YouTube Studio, Download gives you one.</p><div class="field"><label for="af">Full path of the video file</label><input id="af" type="text" placeholder="C:\\Users\\you\\Videos\\talk.mp4"></div>`,
      actions: [{ label: "Cancel", quiet: true }, { label: "Add file", primary: true, demo: true, run: () => toast(`The file would be added and clipped.${DEMO_ONLY}`) }] }),
    pause: () => { S.autopilot.enabled = false; toast("Autopilot is paused. Nothing new is found, clipped or posted (demo)."); render(); },
    start: () => { S.autopilot.enabled = true; toast("Autopilot is on (demo)."); render(); },
    "stop-all": () => dialog({ title: "Stop all jobs?", body: h`<p class="muted">This is the emergency stop. Queued work is canceled and running jobs stop at their next safe point. Nothing runs or posts until you press Resume jobs.</p><p class="small">To only stop new work for a while, use <b>Pause Autopilot</b> instead: it keeps what's queued.</p>`,
      actions: [{ label: "Keep running", quiet: true }, { label: "Stop all jobs", danger: true, demo: true, run: () => { S.autopilot.stopped = true; toast("All jobs stopped (demo): 3 queued jobs canceled, 1 stopping."); render(); } }] }),
    resume: () => { S.autopilot.stopped = false; toast("Jobs allowed again (demo)."); render(); },
    "autopub-dialog": () => autoPublishDialog(),
    "autopub-off": () => dialog({ title: "Turn off automatic publishing for YouTube?", body: h`<p class="muted">Upcoming YouTube posts it approved go back to Needs review and wait for your OK.</p>`,
      actions: [{ label: "Keep it on", quiet: true }, { label: "Turn off", danger: true, demo: true, run: () => { S.autopilot.autoPublish.youtube.enabled = false; S.posts.forEach((p) => { if (p.approvedBy === "automatic" && p.status === "approved") { p.status = "awaiting_approval"; p.approvedBy = ""; } }); toast("Automatic publishing is off (demo). Its posts wait for your OK."); render(); } }] }),
    "agreement-dialog": () => agreementDialog(),
    "add-content": () => dialog({ title: "Add a video Autopilot may use", body: h`<p class="small muted">Optional: Autopilot finds videos by itself. Use this for your own videos or links you may use.</p>
      <div class="field"><label for="ac-where">Link, file path or folder</label><input id="ac-where" type="text" placeholder="https://… or C:\\Users\\you\\Videos\\Recordings"></div>
      <fieldset><legend class="label">Can ClipFoundry use it?</legend><label class="choice"><input type="radio" name="ac"><span>Yes, it's my own content</span></label><label class="choice"><input type="radio" name="ac"><span>Yes, I have permission from the creator</span></label><label class="choice"><input type="radio" name="ac"><span>Not sure: don't use it until I decide</span></label></fieldset>`,
      actions: [{ label: "Cancel", quiet: true }, { label: "Add", primary: true, demo: true, run: () => toast(`It would be added and checked.${DEMO_ONLY}`) }] }),
    toggle: (el) => { const on = el.getAttribute("aria-checked") !== "true"; el.setAttribute("aria-checked", String(on)); el.querySelector(".state-word").textContent = on ? "On" : "Off"; toast(`${on ? "Turned on" : "Turned off"} (demo).`); },
    "confirm-remove": (el) => dialog({ title: "Remove this agreement?", body: h`<p class="muted">${el.dataset.note}</p>`, actions: [{ label: "Keep it", quiet: true }, { label: "Remove", danger: true, demo: true, run: () => toast(`The agreement would be removed.${DEMO_ONLY}`) }] }),

    "lib-filter": (el) => { ui.libFilter = el.dataset.id; render(); },
    "lib-clear": () => { ui.libFilter = "all"; ui.libQuery = ""; render(); },
    "cancel-processing": (el) => { const p = project(el.dataset.id); p.status = "error"; p.error = "Canceled by you."; p.fix = "Press Try again to start over."; toast("Processing canceled (demo)."); render(); },
    "delete-project": (el) => { const p = project(el.dataset.id); const n = clipsOf(p.id).length;
      dialog({ title: `Delete “${p.name}”?`, body: h`<p class="muted">This deletes the source video, its transcript and its ${plural(n, "clip")} from ClipFoundry on this computer. It can't be undone. Posts already on YouTube or TikTok stay there.</p>`,
        actions: [{ label: "Keep it", quiet: true }, { label: `Delete video and ${plural(n, "clip")}`, danger: true, demo: true, run: () => { S.projects = S.projects.filter((x) => x.id !== p.id); S.clips = S.clips.filter((c) => c.projectId !== p.id); toast("Deleted (demo)."); if (current.parts[0] === "project") go("library"); else render(); } }] }); },
    regenerate: (el) => { const p = project(el.dataset.id);
      dialog({ title: "Make clips again", body: h`<p class="muted small">The transcript is reused, so this is much faster than the first time. Manual edits on the current clips are discarded.</p>
        <div class="field"><span class="label">Clips</span>${seg("rg-count", [[3, "3"], [5, "5"], [10, "10"]], 5)}</div><div class="row wrap"><div class="field" style="flex:1"><label for="rg-min">Shortest clip (seconds)</label><input id="rg-min" type="number" value="15"></div><div class="field" style="flex:1"><label for="rg-max">Longest clip (seconds)</label><input id="rg-max" type="number" value="60"></div></div>`,
        actions: [{ label: "Cancel", quiet: true }, { label: "Make clips again", primary: true, demo: true, run: () => { Object.assign(p, { status: "processing", stageIndex: 2, progress: 0.1, message: "Finding the best moments", error: "", fix: "" }); S.clips = S.clips.filter((c) => c.projectId !== p.id); render(); simulateProject(p.id); } }] }); },
    "select-all": (el) => { const cs = clipsOf(el.dataset.id); const all = cs.every((c) => ui.selected.has(c.id)); cs.forEach((c) => (all ? ui.selected.delete(c.id) : ui.selected.add(c.id))); render(); },
    zip: (el) => toast(`A ZIP of ${el.dataset.id === "all" ? "all clips" : "the selected clips"} with their titles and captions would download.${DEMO_ONLY}`),
    export: (el) => { const c = clip(el.dataset.id); dialog({ title: "Export clip", body: h`<p class="muted small">“${c.title}”, the version used for posts (Original).</p>
        <fieldset><legend class="sr-only">Format</legend><label class="choice-card"><input type="radio" name="ex" checked><span class="stack" style="gap:2px"><b>MP4 video</b><span class="small muted">1080×1920, ready to upload anywhere.</span></span></label>
        <label class="choice-card"><input type="radio" name="ex"><span class="stack" style="gap:2px"><b>ZIP with the video and its text</b><span class="small muted">The MP4 plus its title, caption and hashtags.</span></span></label></fieldset>`,
      actions: [{ label: "Cancel", quiet: true }, { label: "Download", primary: true, demo: true, run: () => toast(`The file would download.${DEMO_ONLY}`) }] }); },

    "add-sample": () => { ui.add.file = { name: "Sample: Sunday Q&A recording.mp4", size: "1.42 GB", sample: true }; render(); },
    "add-clear": () => { ui.add.file = null; render(); },
    "add-start": () => startUpload(),

    "ed-tab": (el) => { ui.edit.tab = el.dataset.id; render(); document.getElementById(`tab-${el.dataset.id}`).focus(); },
    "ed-word": (el) => { const w = S.words[+el.dataset.id]; const d = ui.edit.draft;
      if (ui.edit.clickMode === "start") { d.start = Math.max(0, +(w.start - 0.12).toFixed(2)); if (d.end - d.start < 1.5) d.end = +(d.start + 1.5).toFixed(2); }
      else { d.end = +(w.end + 0.3).toFixed(2); if (d.end - d.start < 1.5) d.start = +(d.end - 1.5).toFixed(2); }
      markDirty("trim"); render(); },
    "ed-reset-trim": () => { const c = clip(ui.edit.clipId); ui.edit.draft.start = c.start; ui.edit.draft.end = c.end; markDirty("trim"); render(); },
    "ed-toggle": (el) => { const on = el.getAttribute("aria-checked") !== "true"; if (el.dataset.id === "ed-captions") { ui.edit.draft.captions = on; markDirty("text"); } render(); },
    "ed-discard": () => { const e = ui.edit; e.draft = { ...e.saved }; e.dirty.clear(); toast("Changes discarded."); render(); },
    "ed-save": () => { saveEdit(); render(); },
    "ed-render": () => { saveEdit(false); startRender(); },
    play: () => { const c = clip(ui.edit ? ui.edit.clipId : current.parts[1]) || clip(post(current.parts[1]) ? post(current.parts[1]).clipId : ""); if (!ui.edit && c) draftFor(c); const e = ui.edit; e.playing = !e.playing; if (e.playing) playLoop(); render(); },

    "publish-now-manual": (el) => { const pf = el.dataset.id; const a = S.accounts[pf];
      dialog({ title: pf === "youtube" ? "Publish to YouTube now?" : "Post to TikTok now?", body: h`<dl class="kv"><dt>Account</dt><dd>${a.name}</dd><dt>Who can see it</dt><dd>${pf === "youtube" ? "Private" : "Only me"}</dd><dt>When</dt><dd>Right away</dd></dl>
        <div class="consequence"><span>The upload starts as soon as you confirm. ClipFoundry can't take it back afterwards; you would delete it on ${PNAME[pf]}.</span></div>`,
        actions: [{ label: "Cancel", quiet: true }, { label: pf === "youtube" ? "Publish now" : "Post now", primary: true, demo: true, run: () => toast(`Nothing was uploaded: this is a prototype. In the app, the upload would start and its progress would show under “Uploads you started here”.`) }] }); },
    approve: (el) => { const x = post(el.dataset.id); const f = ui.review[x.id];
      if (el.getAttribute("aria-disabled") === "true") { toast(document.getElementById("ok-why").textContent, true); return; }
      x.status = "approved"; x.approvedBy = "you"; x.title = f.title; x.description = f.text; x.needsNewOk = false;
      toast(`Approved for ${PNAME[x.platform]} (demo). It would go out ${at(x.when)}. Nothing was uploaded.`); render(); },
    "rv-option": (el) => { const f = ui.review[el.dataset.id]; f.title = el.dataset.value; render(); },
    "publish-now": (el) => { const x = post(el.dataset.id);
      dialog({ title: `Publish to ${PNAME[x.platform]} now?`, body: h`<p class="muted">It uploads right away instead of ${at(x.when)} ${S.tzAbbr}. ClipFoundry can't take it back afterwards; you would remove it on ${PNAME[x.platform]}.</p>`,
        actions: [{ label: "Wait for its time", quiet: true }, { label: "Publish now", primary: true, demo: true, run: () => { x.status = "publishing"; toast("Uploading (demo). Nothing really leaves this page."); render(); setTimeout(() => { x.status = "published"; x.published = "Today, 4:15 PM"; x.stats = { views: null, likes: null, comments: null, shares: null, notes: { all: "No numbers yet: YouTube reports them after a while." }, at: "Today, 4:15 PM" }; render(); }, 2500); } }] }); },
    "cancel-post": (el) => { const x = post(el.dataset.id);
      dialog({ title: `Cancel this ${PNAME[x.platform]} post?`, body: h`<p class="muted">It won't be posted. The clip stays in your Library, and you can plan it again later.</p>`,
        actions: [{ label: "Keep the post", quiet: true }, { label: "Cancel post", danger: true, demo: true, run: () => { x.status = "canceled"; x.statusNote = "Canceled by you."; toast("Post canceled (demo)."); render(); } }] }); },
    retry: (el) => { const x = post(el.dataset.id); if (!accOk(x.platform)) { toast(`Reconnect ${PNAME[x.platform]} first.`, true); return; } x.status = "approved"; x.approvedBy = "you"; x.statusNote = ""; toast("It will be tried again at its time (demo)."); render(); },
    "resolve-yes": (el) => { const x = post(el.dataset.id);
      dialog({ title: "Where is the video on YouTube?", body: h`<div class="field"><label for="rs-url">Link of the video</label><input id="rs-url" type="url" placeholder="https://youtube.com/shorts/…"></div><p class="small muted">ClipFoundry marks it as published and never uploads it again.</p>`,
        actions: [{ label: "Cancel", quiet: true }, { label: "Mark as published", primary: true, demo: true, run: () => { x.status = "published"; x.published = "Today, 11:40 AM"; x.statusNote = ""; x.stats = { views: null, likes: null, comments: null, shares: null, notes: { all: "Numbers appear after the next refresh." }, at: "—" }; toast("Marked as published (demo)."); render(); } }] }); },
    "resolve-no": (el) => { const x = post(el.dataset.id);
      dialog({ title: "Upload it again?", body: h`<p class="muted">Only do this if you checked YouTube Studio and the video is <b>not</b> there. Otherwise it would be posted twice.</p>`,
        actions: [{ label: "Cancel", quiet: true }, { label: "I checked: upload again", primary: true, demo: true, run: () => { x.status = "awaiting_approval"; x.statusNote = ""; x.when = "Today, 7:05 PM"; toast("It will be uploaded again at a new time after your OK (demo)."); render(); } }] }); },

    "settings-save": () => { const s = ui.settings; if (ui.settingsErrors.tz) { toast("Fix the time zone first.", true); render(); document.getElementById("adv-tz") && document.getElementById("adv-tz").focus(); return; }
      s.dirty = false; ui.settingsSaved = true; toast("Settings saved (demo)."); render(); },
    "settings-discard": () => { ui.settings = null; ui.settingsErrors = {}; render(); },
    "set-toggle": (el) => { const on = el.getAttribute("aria-checked") !== "true"; const k = { "adv-cpu": "allow_cpu", "adv-awake": "keep_awake" }[el.dataset.id]; if (k) ui.settings[k] = on; ui.settings.dirty = true; ui.settingsSaved = false; render(); },
    "replace-secret": (el) => { ui.replaceSecret[el.dataset.id] = true; render(); const f = document.getElementById(`${el.dataset.id}-secret`); f && f.focus(); },
    copy: (el) => { const t = el.dataset.note; try { navigator.clipboard.writeText(t).then(() => toast("Copied."), () => toast("Select the address and copy it with Ctrl+C.")); } catch (e) { toast("Select the address and copy it with Ctrl+C."); } },

    topic: (el) => { const t = el.dataset.id; const l = ui.setup.topics; ui.setup.topics = l.includes(t) ? l.filter((x) => x !== t) : [...l, t]; render(); },
    "need-choice": (el, e) => { e.preventDefault(); toast("Choose one way to work first.", true); },
    "setup-finish": (el) => { S.setupDone = true; S.mode = ui.setup.how || "manual";
      if (S.mode === "autopilot" && el.dataset.id === "done") { S.autopilot.enabled = true; S.autopilot.currently = "Looking for videos it may use"; }
      toast(S.mode === "autopilot" && el.dataset.id === "done" ? "Autopilot is on (demo). Connecting accounts didn't allow any post by itself." : "Setup finished (demo)."); go(""); },
  };

  function autoPublishDialog() {
    dialog({ title: "Let YouTube posts go out without asking", wide: true, body: h`<p class="small">ClipFoundry will publish finished clips to YouTube by itself, without asking you about each one.</p>
      <dl class="kv"><dt>Account</dt><dd>${S.accounts.youtube.name}</dd><dt>What gets posted</dt><dd>Only clips that passed every automatic check (file, sound, captions, framing, text), from videos you own or that an agreement or license covers. A clip with a possible problem waits for you instead.</dd></dl>
      <div class="field"><label for="ap-vis">Who can see them</label><select id="ap-vis"><option value="" selected disabled>Choose…</option><option value="public">Public: anyone</option><option value="unlisted">Unlisted: only people with the link</option><option value="private">Private: only you</option></select></div>
      <fieldset><legend class="label">Made for kids</legend><label class="choice"><input type="radio" name="ap-kids" value="no"><span>No</span></label><label class="choice"><input type="radio" name="ap-kids" value="yes"><span>Yes</span></label></fieldset>
      <div class="inline-fields"><span class="small">At most</span><input type="number" value="3" min="1" max="15" aria-label="Posts a day at most"><span class="small">a day, between</span><input type="number" value="9" aria-label="From hour"><span class="small">and</span><input type="number" value="21" aria-label="To hour"><span class="small">o'clock (${S.tzAbbr})</span></div>
      ${!S.accounts.youtube.audited ? h`<p class="small"><span class="pill warn">${icon("alert")}Note</span> Until Google audits your YouTube API project, YouTube keeps these uploads Private whatever you choose here.</p>` : ""}
      <p class="small muted"><b>TikTok</b> is not included: TikTok requires your OK on each post.</p>
      <label class="choice"><input type="checkbox" id="ap-agree"><span>I understand: ClipFoundry uploads these clips to my channel without asking me each time. I can cancel any upcoming post, and turn this off at any time.</span></label>
      <p class="error-text" id="ap-err" hidden>${icon("alert", "sm")}<span></span></p>`,
      actions: [{ label: "Cancel", quiet: true }, { label: "Turn on automatic publishing", primary: true, demo: true, run: (box) => {
        const vis = box.querySelector("#ap-vis").value; const kids = box.querySelector('input[name="ap-kids"]:checked'); const ok = box.querySelector("#ap-agree").checked;
        const missing = [!vis && "choose who can see them", !kids && "answer “made for kids”", !ok && "tick that you understand"].filter(Boolean);
        if (missing.length) { const err = box.querySelector("#ap-err"); err.hidden = false; err.querySelector("span").textContent = `To turn it on: ${missing.join(", ")}.`; err.setAttribute("role", "alert"); return false; }
        Object.assign(S.autopilot.autoPublish.youtube, { enabled: true, visibility: vis }); toast("Automatic publishing is on for YouTube (demo)."); render(); } }] });
  }
  function agreementDialog() {
    dialog({ title: "Record an agreement with a creator", wide: true, body: h`
      <div class="field"><label for="ag-c">Creator</label><input id="ag-c" type="text" placeholder="Their name or channel name"></div>
      <div class="field"><label for="ag-ch">YouTube channel IDs and TikTok handles <span class="hint">UC… or @name, separated by commas</span></label><input id="ag-ch" type="text"></div>
      <div class="field"><label for="ag-ev">What shows the agreement <span class="hint">required: where and when they agreed, or the program's terms</span></label><textarea id="ag-ev" rows="2"></textarea></div>
      <div class="field"><label for="ag-url">Link to it <span class="hint">optional</span></label><input id="ag-url" type="url"></div>
      <div class="field"><label for="ag-at">Credit line they want <span class="hint">optional, added to every post</span></label><input id="ag-at" type="text"></div>
      <div class="row wrap">${checkbox("ag-com", "Allows commercial use", true)}${checkbox("ag-yt", "YouTube", true)}${checkbox("ag-tt", "TikTok", true)}</div>
      <div class="field"><label for="ag-end">Ends on <span class="hint">optional</span></label><input id="ag-end" type="date"></div>
      <div class="field"><label for="ag-f">Folder with their files on this computer <span class="hint">optional, e.g. a shared Dropbox folder</span></label><input id="ag-f" type="text"></div>
      <div class="field"><label for="ag-p">Address of their file links <span class="hint">optional</span></label><input id="ag-p" type="text"></div>
      ${checkbox("ag-3p", "It also covers other people's music or footage in their videos (only if the agreement says so)", false)}
      <p class="small muted">Without a shared folder or file link, their YouTube videos are still skipped: YouTube doesn't allow downloading its videos without its permission.</p>`,
      actions: [{ label: "Cancel", quiet: true }, { label: "Save agreement", primary: true, demo: true, run: () => toast(`The agreement would be saved.${DEMO_ONLY}`) }] });
  }

  // ------------------------------------------------------------------ input bindings
  function onInput(e) {
    const el = e.target; const b = el.dataset && el.dataset.bind; if (!b) return;
    const v = el.type === "checkbox" ? el.checked : el.value;
    const E = ui.edit; const d = E && E.draft;
    const live = e.type === "input";
    switch (b) {
      case "libQuery": ui.libQuery = v; if (live) render(); return;
      case "addUrl": ui.add.url = v; if (live) { const btn = document.querySelector('[data-action="add-start"]'); if (btn) btn.disabled = !(ui.add.file || /^https?:\/\//.test(v)); } return;
      case "ed-view": E.view = v; E.t = 0; render(); return;
      case "ed-click": E.clickMode = v; render(); return;
      case "ed-start": d.start = Math.min(+v, d.end - 1); markDirty("trim"); if (!live || el.type === "range") render(); return;
      case "ed-end": d.end = Math.max(+v, d.start + 1); markDirty("trim"); if (!live || el.type === "range") render(); return;
      case "ed-style": d.style = v; markDirty("text"); render(); return;
      case "ed-pos": d.position = v; markDirty("text"); render(); return;
      case "ed-size": d.size = +v; markDirty("text"); render(); return;
      case "ed-emph": d.emphasis = v; markDirty("text"); render(); return;
      case "ed-hl": d.highlight = v; markDirty("text"); render(); return;
      case "ed-captext": markDirty("text"); if (!live) render(); else updateSaveBar(); return;
      case "ed-hook": d.hook = v; markDirty("text"); render(); return;
      case "ed-hookon": d.hookOn = v; markDirty("text"); render(); return;
      case "ed-hooksecs": d.hookSecs = +v; markDirty("text"); if (!live) render(); else updateSaveBar(); return;
      case "ed-track": d.tracking = v; markDirty("layout"); render(); return;
      case "ed-layout": d.layout = v; markDirty("layout"); render(); return;
      case "ed-zoom": d.zoom = +v; markDirty("layout"); render(); return;
      case "ed-autozoom": d.autoZoom = v; markDirty("layout"); render(); return;
      case "ed-gain": d.gain = +v; markDirty("audio"); render(); return;
      case "ed-norm": d.normalize = v; markDirty("audio"); render(); return;
      case "ed-sil": d.silence = v; markDirty("audio"); render(); return;
      case "ed-fillers": d.fillers = v; markDirty("audio"); render(); return;
      case "ed-speed": d.speed = +v; markDirty("audio"); render(); return;
      case "ed-title": d.title = v; markDirty("post"); if (!live) render(); else updateSaveBar(); return;
      case "ed-caption": d.caption = v; markDirty("post"); if (!live) render(); else updateSaveBar(); return;
      case "ed-version": toast("In the app this chooses the version used for export and posts."); return;
      case "rv-title": ui.review[el.dataset.id].title = v; if (!live) render(); return;
      case "rv-text": ui.review[el.dataset.id].text = v; if (!live) render(); return;
      case "rv-tags": ui.review[el.dataset.id].tags = v; return;
      case "rv-priv": { const id = current.parts[1]; ui.review[id].privacy = v; render(); return; }
      case "rv-kids": ui.review[el.dataset.id].kids = v; render(); return;
      case "rv-mode": ui.review[el.dataset.id].mode = v; render(); return;
      case "rv-tpriv": ui.review[el.dataset.id].privacy = v; render(); return;
      case "rv-agree": ui.review[el.dataset.id].agree = v; render(); return;
      case "setup-how": ui.setup.how = v; render(); return;
      case "posts-all": go(v ? "posts/history" : "posts/published"); return;
      case "set-tz": ui.settings.timezone = v; ui.settings.dirty = true; ui.settingsSaved = false;
        ui.settingsErrors = /^[A-Za-z]+\/[A-Za-z_]+$/.test(v.trim()) && !/Chicgo/.test(v) ? {} : { tz: "Unknown time zone. Use a name like America/Chicago." };
        if (!live) render(); return;
      default:
        if (b.startsWith("set-") || b.startsWith("adv-")) { if (ui.settings) { ui.settings.dirty = true; ui.settingsSaved = false; if (!live) render(); } }
    }
  }
  function updateSaveBar() {
    const st = document.querySelector('[data-live="ed-status"]'); if (st) st.textContent = editStatus(ui.edit);
    ["ed-discard", "ed-save", "ed-render"].forEach((a) => { const b = document.querySelector(`[data-action="${a}"]`); if (b) b.disabled = !!ui.edit.render || (!ui.edit.dirty.size && !(a === "ed-render" && ui.edit.savedNotRendered)); });
  }

  // ================================================================== simulations (clearly demo; no timers touch real data)
  function stopTimers() { timers.forEach(clearInterval); timers = []; if (ui.edit) ui.edit.playing = false; }
  function every(ms, fn) { const t = setInterval(fn, ms); timers.push(t); return t; }
  function startSimulations() {
    if (ui.scenario === "working") {
      every(1600, () => {
        const w = S.autopilot.working; if (!w || !S.autopilot.enabled || S.autopilot.stopped || lost()) return;
        w.progress = Math.min(0.98, (w.progress || 0) + 0.04);
        setBar("ap-progress", w.progress, `${Math.round(w.progress * 100)}% of this step, as the job reports it. No time estimate is available.`);
      });
    }
  }
  function setBar(key, frac, text) {
    const bar = document.querySelector(`[data-live="${key}"]`);
    if (bar) { bar.firstElementChild.style.width = `${Math.round(frac * 100)}%`; bar.setAttribute("aria-valuenow", String(Math.round(frac * 100))); }
    const t = document.querySelector(`[data-live="${key}-text"]`); if (t && text) t.textContent = text;
  }
  function startUpload() {
    const a = ui.add; if (!a.file && a.url) a.file = { name: a.url, size: "from a link" };
    a.progress = 0; render();
    const t = every(250, () => {
      a.progress = Math.min(1, a.progress + 0.08);
      setBar("upload", a.progress, `Copying into ClipFoundry: ${Math.round(a.progress * 100)}%`);
      if (a.progress >= 1) {
        clearInterval(t);
        const id = `p${Date.now()}`;
        S.projects.unshift({ id, name: a.file.name.replace(/\.(mp4|mov|mkv|webm|m4v)$/i, ""), origin: "Added by you", created: "Just now", duration: "38:12",
          format: "1920×1080 · 30 fps", status: "processing", stage: "Prepare", stageIndex: 0, progress: 0.05, message: "Preparing the video", clipCount: 0, seed: 5,
          transcribed: "", candidates: 8, requested: S.settings.clip_count, minScore: 50 });
        ui.add = { file: null, progress: null, url: "", tab: "file" };
        toast("Video copied. ClipFoundry is making clips (demo).");
        go(`project/${id}`);
        simulateProject(id);
      }
    });
  }
  function simulateProject(id) {
    const msgs = ["Preparing the video", "Transcribing on the GPU", "Finding the best moments", "Scoring and writing hooks", "Rendering 9:16 clips"];
    const t = every(900, () => {
      const p = project(id); if (!p) { clearInterval(t); return; }
      p.progress = Math.min(1, (p.progress || 0) + 0.07);
      const idx = Math.min(4, Math.floor(p.progress * 5));
      if (idx !== p.stageIndex) { p.stageIndex = idx; p.message = msgs[idx]; if (idx >= 2) p.transcribed = "Transcribed on the GPU (RTX 3050, large-v3-turbo, 17× real time)"; if (current.parts[1] === id) render(); }
      else setBar(`p-progress-${id}`, p.progress);
      if (p.progress >= 1) {
        clearInterval(t);
        p.status = "ready";
        const base = S.clips.filter((c) => c.projectId === "p1").slice(0, 3);
        base.forEach((c, i) => S.clips.push({ ...c, id: `${id}-c${i}`, projectId: id, seed: c.seed + 3, selected: false, rendered: "Rendered just now", version: 1 }));
        p.clipCount = 3;
        toast(`3 clips are ready from “${p.name}”.`);
        render();
      }
    });
  }
  function startRender() {
    const e = ui.edit; e.render = { progress: 0 }; e.playing = false; render();
    const t = every(300, () => {
      e.render.progress = Math.min(1, e.render.progress + 0.09);
      const st = document.querySelector('[data-live="ed-status"]'); if (st) st.textContent = editStatus(e);
      if (e.render.progress >= 1) {
        clearInterval(t);
        e.render = null; e.version += 1; e.rendered = "Rendered just now"; e.savedNotRendered = false; e.justRendered = true;
        const c = clip(e.clipId); c.version = e.version; c.rendered = "Rendered just now"; c.start = e.saved.start; c.end = e.saved.end; c.duration = +(e.saved.end - e.saved.start).toFixed(1);
        let reopened = 0;
        postsOf(c.id).forEach((p) => {
          if (["approved", "awaiting_approval"].includes(p.status)) { if (p.status === "approved") reopened++; p.status = "awaiting_approval"; p.needsNewOk = true; p.quality = SAMPLE.quality("pending"); }
        });
        toast(`Rendered version ${e.version}.${reopened ? ` ${plural(reopened, "approved post")} for this clip now ${reopened === 1 ? "needs" : "need"} your OK again.` : ""} The new file gets a new final check.`);
        render();
        setTimeout(() => { postsOf(c.id).forEach((p) => { if (p.quality.status === "pending") p.quality = SAMPLE.quality("warn"); }); if (["post", "posts"].includes(current.parts[0])) render(); }, 4000);
      }
    });
  }
  let playTimer = null;
  function playLoop() {
    clearInterval(playTimer);
    playTimer = setInterval(() => {
      const e = ui.edit; if (!e || !e.playing) { clearInterval(playTimer); return; }
      const c = clip(e.clipId); const len = e.view === "source" ? e.draft.end - e.draft.start : c.duration;
      e.t += 0.25; if (e.t >= len) { e.t = 0; e.playing = false; clearInterval(playTimer); render(); return; }
      const box = document.querySelector(".player"); if (box) box.outerHTML = val(playerBox(c, e));
      const tt = document.querySelector('[data-live="ed-time"]'); if (tt) tt.textContent = `${fmtPrecise(e.t)} / ${fmtPrecise(len)}`;
      const head = document.querySelector('[data-live="ed-head"]');
      if (head) { const d = e.draft; const lo = d.start - 6; const hi = d.end + 6; const at = (e.view === "source" ? d.start : e.saved.start) + e.t; head.style.left = `${(100 * (at - lo)) / (hi - lo)}%`; }
    }, 250);
  }

  // ================================================================== prototype control panel (never a production feature)
  function renderDemo() {
    const root = document.getElementById("demo-root");
    const btn = document.querySelector('[data-action="demo-panel"]');
    if (btn) btn.setAttribute("aria-expanded", String(ui.demo.panel));
    if (!ui.demo.panel) { root.innerHTML = ""; return; }
    const sel = (id, label, opts, value) => h`<div class="field"><label for="${id}">${label}</label><select id="${id}" data-demo="${id}">${opts.map(([v, l]) => h`<option value="${v}" ${v === value ? raw("selected") : ""}>${l}</option>`)}</select></div>`;
    const apv = S.autopilot.stopped ? "stopped" : S.autopilot.enabled ? "on" : "paused";
    root.innerHTML = val(h`<section class="demo-panel" id="demo-panel" aria-labelledby="demo-h">
      <div class="row"><h2 id="demo-h" class="grow">Prototype controls</h2><button class="btn btn-small" type="button" data-action="demo-panel" aria-label="Close prototype controls">${icon("x")}</button></div>
      <p class="tiny muted">Only for trying the design. Not part of the proposed app.</p>
      <fieldset><legend class="label">Scenario</legend>${Object.entries(SAMPLE.scenarios).map(([k, l]) => h`<label class="choice"><input type="radio" name="demo-scn" value="${k}" ${ui.scenario === k ? raw("checked") : ""} data-demo="scenario"><span>${l}</span></label>`)}</fieldset>
      <hr class="divider"><span class="label small strong">Change one thing</span>
      ${sel("demo-ap", "Autopilot", [["on", "On"], ["paused", "Paused"], ["stopped", "Stopped (emergency stop)"]], apv)}
      ${sel("demo-sleep", "This PC's sleep", [["on", "Kept awake (Windows agreed)"], ["pending", "Asking Windows"], ["failed", "Windows said no"], ["off", "Setting turned off"], ["unsupported", "Not supported"]], S.autopilot.keepAwake)}
      ${sel("demo-gpu", "Processing", [["ok", "GPU works"], ["problem", "GPU transcription not working"], ["cpu", "Last video fell back to CPU"], ["none", "No NVIDIA GPU"]], S.autopilot.gpu.state)}
      ${sel("demo-yt", "YouTube account", [["connected", "Connected"], ["expired", "Sign-in expired"], ["not_connected", "Not connected"]], S.accounts.youtube.state)}
      ${sel("demo-conn", "Connection to ClipFoundry", [["live", "Answering"], ["lost", "Not answering (window closed)"]], S.connection)}
      <label class="choice"><input type="checkbox" data-demo="long" ${ui.demo.longNames ? raw("checked") : ""}><span>Very long names</span></label>
      <label class="choice"><input type="checkbox" data-demo="nothumb" ${ui.demo.noThumbs ? raw("checked") : ""}><span>Missing thumbnails</span></label>
      <div class="row wrap"><button class="btn btn-small" type="button" data-action="demo-loading">Show loading state</button><button class="btn btn-small" type="button" data-action="demo-reset">Reset</button></div>
    </section>`);
  }
  ACTIONS["demo-loading"] = () => { ui.demo.loading = true; render(); setTimeout(() => { ui.demo.loading = false; render(); }, 1800); };
  ACTIONS["demo-reset"] = () => { ui.demo.longNames = false; ui.demo.noThumbs = false; load("ready"); render(); renderDemo(); toast("Prototype reset."); };
  function onDemo(e) {
    const el = e.target; const k = el.dataset.demo; if (!k) return;
    if (k === "scenario") { load(el.value); if (el.value === "first" && current.parts[0] !== "setup") go(""); }
    if (k === "demo-ap") { S.autopilot.stopped = el.value === "stopped"; S.autopilot.enabled = el.value !== "paused"; if (!S.setupDone) S.setupDone = true; }
    if (k === "demo-sleep") S.autopilot.keepAwake = el.value;
    if (k === "demo-gpu") { const g = S.autopilot.gpu; g.state = el.value; if (el.value === "problem") { g.detail = "CUDA could not load cuBLAS (cublas64_12.dll was not found). Autopilot paused transcription for 30 minutes instead of using the slower CPU."; g.fix = "Run gpu-check.bat from the ClipFoundry folder and follow what it says, then restart ClipFoundry."; } else { g.detail = ""; g.fix = el.value === "cpu" ? "Run gpu-check.bat from the ClipFoundry folder to see why CUDA could not start." : ""; } }
    if (k === "demo-yt") S.accounts.youtube.state = el.value;
    if (k === "demo-conn") S.connection = el.value;
    if (k === "long") { ui.demo.longNames = el.checked; const keep = ui.scenario; load(keep); }
    if (k === "nothumb") ui.demo.noThumbs = el.checked;
    render(); renderDemo();
    const again = document.querySelector(`[data-demo="${k}"]${k === "scenario" ? `[value="${el.value}"]` : ""}`); again && again.focus();
  }

  // ================================================================== wiring
  function afterRender() {
    const drop = document.querySelector("[data-drop]");
    if (drop) {
      drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
      drop.addEventListener("dragleave", () => drop.classList.remove("over"));
      drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); const f = e.dataTransfer.files && e.dataTransfer.files[0]; if (f) pickFile(f); });
    }
  }
  function pickFile(f) {
    const ok = /\.(mp4|mov|mkv|webm|m4v)$/i.test(f.name);
    if (!ok) { toast(`“${f.name}” isn't a video ClipFoundry can use. Use MP4, MOV, MKV, WEBM or M4V.`, true); return; }
    ui.add.file = { name: f.name, size: f.size > 1e9 ? `${(f.size / 1e9).toFixed(2)} GB` : `${(f.size / 1e6).toFixed(1)} MB` };
    render();
  }
  document.addEventListener("click", (e) => {
    const link = e.target.closest('a[href^="#/"]');
    if (link && current.parts[0] === "clip" && ui.edit && ui.edit.dirty.size && !link.closest(".dialog")) {
      e.preventDefault(); askLeave(link.getAttribute("href").replace(/^#\//, "")); return;
    }
    const el = e.target.closest("[data-action]");
    if (ui.menu && !e.target.closest(".menu-wrap")) { ui.menu = null; if (!el) { render(); return; } }
    if (!el) return;
    const fn = ACTIONS[el.dataset.action];
    if (fn && el.tagName !== "INPUT") { if (el.getAttribute("aria-disabled") === "true" && el.dataset.action !== "approve" && el.dataset.action !== "need-choice") { e.preventDefault(); return; } fn(el, e); }
  });
  document.addEventListener("change", (e) => {
    const el = e.target;
    if (el.dataset && el.dataset.demo) { onDemo(e); return; }
    if (el.dataset && el.dataset.action === "select") { const id = el.dataset.id; el.checked ? ui.selected.add(id) : ui.selected.delete(id); render(); return; }
    if (el.dataset && el.dataset.action === "file-pick") { const f = el.files && el.files[0]; if (f) pickFile(f); return; }
    onInput(e);
  });
  document.addEventListener("input", (e) => { if (e.target.dataset && e.target.dataset.bind) onInput(e); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && ui.menu) { const id = ui.menu; ui.menu = null; render(); const b = document.querySelector(`[data-action="menu"][data-id="${id}"]`); b && b.focus(); }
    if (e.key === "Escape" && ui.demo.panel && e.target.closest && e.target.closest(".demo-panel")) { ui.demo.panel = false; renderDemo(); const b = document.querySelector('[data-action="demo-panel"]'); b && b.focus(); }
    const tab = e.target.closest && e.target.closest('[role="tab"]');
    if (tab && ["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)) {
      const tabs = [...tab.parentElement.querySelectorAll('[role="tab"]')]; let i = tabs.indexOf(tab);
      i = e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : (i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      e.preventDefault(); ACTIONS["ed-tab"](tabs[i]);
    }
  });
  window.addEventListener("beforeunload", (e) => { if (ui.edit && ui.edit.dirty.size) { e.preventDefault(); e.returnValue = ""; } });
  window.addEventListener("hashchange", onRoute);

  shell();
  load("ready");
  if (!location.hash) history.replaceState(null, "", "#/");
  onRoute();
})();
