/*
 * SAMPLE DATA for the ClipFoundry redesign prototype.
 * Everything here is invented for the demo: no real channels, people, accounts, files or credentials.
 * Field names follow the app's real API types (frontend/src/api.ts, frontend/src/autopilot.ts) where they exist, so
 * the spec can map each screen to an existing endpoint. Nothing in the prototype reads or writes app data.
 */
window.CF_SAMPLE = (function () {
  "use strict";

  const SPEECH =
    "Here is the thing nobody tells you about starting a podcast. You do not need expensive gear. You need one good " +
    "question. Ask your guest what they got wrong last year. That answer is always the best part of the episode. People " +
    "love honest stories about mistakes. Keep the recording short and cut the slow parts. Your first ten episodes are " +
    "practice, so publish them anyway.";

  /** Timed words like /api/clips/{id}/words returns them (start/end in seconds of the source video). */
  function timedWords(text, offset) {
    const out = [];
    let t = offset;
    for (const w of text.split(/\s+/)) {
      const len = 0.18 + Math.min(0.32, w.length * 0.035);
      out.push({ w, start: +t.toFixed(2), end: +(t + len).toFixed(2) });
      t += len + (/[.,]$/.test(w) ? 0.42 : 0.08);
    }
    return out;
  }

  const SOURCE_WORDS = timedWords(SPEECH + " " + SPEECH.replace("Here is the thing", "So here is the thing"), 1612.4);

  const QUALITY_PASS = [
    ["Video file", "pass", ""], ["Same file as rendered", "pass", ""], ["H.264 video and AAC audio", "pass", ""],
    ["Audio track", "pass", ""], ["1080x1920 vertical", "pass", ""], ["Duration", "pass", "28.4 s"],
    ["Decodes completely", "pass", "852 frames"], ["Black frames", "pass", ""], ["Moving picture", "pass", ""],
    ["Sound", "pass", "No long silence"], ["Caption timing", "pass", ""], ["Cuts between words", "pass", ""],
    ["Hook, context and payoff", "warn", "The payoff comes in the last 2 seconds (estimate)"],
    ["Framing", "pass", "Follows 1 face (estimate)"],
  ];

  function quality(kind) {
    if (kind === "pending") return { status: "pending", warnings: [], blockers: [], checks: [] };
    const checks = QUALITY_PASS.map(([label, status, detail]) => ({ label, status, detail }));
    if (kind === "failed") {
      checks[7] = { label: "Black frames", status: "fail", detail: "Black for 2.1 of 31.0 s (at 0:12)" };
      return { status: "failed", warnings: [], blockers: ["Black for 2.1 of 31.0 s (at 0:12)"], checks };
    }
    if (kind === "clean") {
      checks[12] = { label: "Hook, context and payoff", status: "pass", detail: "" };
      return { status: "passed", warnings: [], blockers: [], checks };
    }
    return { status: "passed", warnings: ["The payoff comes in the last 2 seconds (estimate)"], blockers: [], checks };
  }

  function base() {
    return {
      now: "Wed, Sep 30 · 4:12 PM",
      timezone: "America/Chicago",
      tzAbbr: "CDT",
      setupDone: true,
      mode: "autopilot",
      topics: ["podcasts", "interviews", "comedy"],
      connection: "live",
      lastUpdate: "4:12 PM",

      accounts: {
        youtube: {
          state: "connected", name: "Sample channel · Morning Mic", configured: true, audited: false,
          restriction: "Until Google audits your API project, YouTube keeps uploads from it Private.",
        },
        tiktok: {
          state: "connected", name: "@sample.morningmic", configured: true, audited: false, directPost: true, inbox: true, stats: false,
          restriction: "Until TikTok audits your app, Direct Post only works for private accounts and “Only me”.",
        },
      },

      autopilot: {
        enabled: true,
        stopped: false,
        currently: "Finding the best moments",
        working: {
          title: "Sample: Saturday livestream Q&A (part 2)", seed: 3, stage: "Finding the best moments",
          stages: ["Getting the video", "Transcribing", "Finding the best moments", "Rendering clips", "Checking the files", "Writing titles and captions", "Planning posting times"],
          stageIndex: 2, progress: 0.46, projectId: "p3",
        },
        nextLook: "7:22 PM",
        folderEvery: "every 3 minutes",
        keepAwake: "on",
        gpu: { state: "ok", name: "NVIDIA GeForce RTX 3050", mode: "GPU", model: "large-v3-turbo", compute: "int8_float16" },
        workersAlive: true,
        skipped24h: 7,
        dailyTarget: 15,
        autoPublish: {
          youtube: { enabled: false, visibility: "", dailyLimit: 3, start: 9, end: 21 },
          tiktok: { note: "TikTok's rules require your OK and a preview for each post." },
        },
      },

      myVideos: { path: "C:\\Users\\you\\Videos\\ClipFoundry", videos: 3, watching: true },

      projects: [
        {
          id: "p1", name: "Sample: Morning Mic podcast, episode 12", origin: "Your videos folder", created: "Today, 2:10 PM",
          duration: "1:04:12", format: "1920×1080 · 30 fps", status: "ready", clipCount: 5, seed: 1,
          transcribed: "Transcribed on the GPU (RTX 3050, large-v3-turbo, 18× real time)", candidates: 11, requested: 5, minScore: 50,
        },
        {
          id: "p2", name: "Sample: Kitchen table interview with a first-time founder", origin: "Added by you", created: "Yesterday, 7:45 PM",
          duration: "48:30", format: "1920×1080 · 25 fps", status: "ready", clipCount: 3, seed: 2,
          transcribed: "Transcribed on the GPU (RTX 3050, large-v3-turbo, 16× real time)", candidates: 7, requested: 5, minScore: 50,
        },
        {
          id: "p3", name: "Sample: Saturday livestream Q&A (part 2)", origin: "Your videos folder", created: "Today, 3:58 PM",
          duration: "1:31:05", format: "1920×1080 · 60 fps", status: "processing", stage: "Find moments", stageIndex: 2,
          progress: 0.46, message: "Finding the best moments", clipCount: 0, seed: 3, transcribed: "Transcribed on the GPU (RTX 3050, large-v3-turbo, 17× real time)",
        },
        {
          id: "p4", name: "Sample: Trail running vlog, week 3", origin: "Added by you", created: "Mon, 11:20 AM", duration: "22:47",
          format: "3840×2160 · 30 fps", status: "error", clipCount: 0, seed: 4,
          error: "The video has no sound, so there is nothing to transcribe.",
          fix: "Choose the original recording with its sound, or attach a transcript (.srt or .vtt) under More options.",
        },
      ],

      clips: [
        { id: "c1", projectId: "p1", title: "You don't need expensive gear to start a podcast", hook: "Here is the thing nobody tells you about starting a podcast.",
          hooksAlt: ["You do not need expensive gear.", "You need one good question."], category: "Advice", score: 86,
          sub: { hook: 88, retention: 81, context: 79, engagement: 74 }, structure: [true, true, true], duration: 28.4,
          start: 1612.4, end: 1640.8, status: "ready", version: 2, rendered: "Rendered today, 2:41 PM", seed: 1, selected: true,
          hashtags: ["#podcast", "#podcasting", "#creator"] },
        { id: "c2", projectId: "p1", title: "Ask your guest what they got wrong last year", hook: "Ask your guest what they got wrong last year.",
          hooksAlt: ["That answer is always the best part of the episode."], category: "Interview tip", score: 81,
          sub: { hook: 83, retention: 78, context: 80, engagement: 72 }, structure: [true, true, true], duration: 33.9,
          start: 1618.9, end: 1652.8, status: "ready", version: 1, rendered: "Rendered today, 2:43 PM", seed: 5, selected: true,
          hashtags: ["#podcast", "#interview"] },
        { id: "c3", projectId: "p1", title: "Your first ten episodes are practice", hook: "Your first ten episodes are practice.",
          hooksAlt: [], category: "Motivation", score: 74, sub: { hook: 76, retention: 72, context: 70, engagement: 69 },
          structure: [true, true, false], duration: 21.6, start: 1633.0, end: 1654.6, status: "ready", version: 1,
          rendered: "Rendered today, 2:44 PM", seed: 6, selected: false, hashtags: ["#podcast"] },
        { id: "c4", projectId: "p1", title: "Cut the slow parts, keep the honest ones", hook: "People love honest stories about mistakes.",
          hooksAlt: [], category: "Editing", score: 69, sub: { hook: 66, retention: 71, context: 68, engagement: 64 },
          structure: [true, false, true], duration: 40.8, start: 1627.1, end: 1667.9, status: "ready", version: 1,
          rendered: "Rendered today, 2:45 PM", seed: 7, selected: false, hashtags: ["#editing"] },
        { id: "c5", projectId: "p1", title: "Why people love stories about mistakes", hook: "People love honest stories about mistakes.",
          hooksAlt: [], category: "Storytelling", score: 63, sub: { hook: 61, retention: 64, context: 66, engagement: 58 },
          structure: [false, true, true], duration: 30.7, start: 1628.0, end: 1658.7, status: "ready", version: 1,
          rendered: "Rendered today, 2:46 PM", seed: 8, selected: false, hashtags: ["#storytelling"] },
        { id: "c6", projectId: "p2", title: "The week I almost quit", hook: "I had the resignation email written.",
          hooksAlt: [], category: "Story", score: 84, sub: { hook: 86, retention: 82, context: 77, engagement: 80 },
          structure: [true, true, true], duration: 37.2, start: 402.0, end: 439.2, status: "ready", version: 1,
          rendered: "Rendered yesterday, 8:31 PM", seed: 2, selected: false, hashtags: ["#founder", "#startup"] },
        { id: "c7", projectId: "p2", title: "What the first customer actually said", hook: "She asked one question I could not answer.",
          hooksAlt: [], category: "Story", score: 77, sub: { hook: 79, retention: 75, context: 74, engagement: 70 },
          structure: [true, true, true], duration: 44.1, start: 1210.5, end: 1254.6, status: "ready", version: 1,
          rendered: "Rendered yesterday, 8:33 PM", seed: 9, selected: false, hashtags: ["#founder"] },
        { id: "c8", projectId: "p2", title: "Pricing was the hardest part", hook: "Nobody tells you how to charge.",
          hooksAlt: [], category: "Business", score: 71, sub: { hook: 70, retention: 72, context: 69, engagement: 66 },
          structure: [true, true, false], duration: 26.3, start: 2230.0, end: 2256.3, status: "ready", version: 1,
          rendered: "Rendered yesterday, 8:35 PM", seed: 10, selected: false, hashtags: ["#pricing"] },
      ],

      words: SOURCE_WORDS,

      versions: {
        c1: [
          { id: "", label: "Original", description: "The clip as edited.", status: "ready", duration: 28.4 },
          { id: "v-fast", label: "Faster pacing", description: "Tighter pauses, no filler words, 8% faster.", status: "ready", duration: 25.9 },
        ],
      },

      posts: [
        { id: "s1", clipId: "c1", platform: "youtube", title: "You don't need expensive gear to start a podcast",
          description: "Here is the thing nobody tells you about starting a podcast. You do not need expensive gear.",
          tags: ["podcast", "podcasting", "creator"], privacy: "public", status: "awaiting_approval", when: "Today, 5:25 PM",
          rights: { label: "Owned", basis: "From your videos folder" }, quality: quality("warn"), madeForKids: null,
          options: [
            "You don't need expensive gear to start a podcast",
            "The thing nobody tells you about starting a podcast",
            "You need one good question",
          ],
          score: 78 },
        { id: "s2", clipId: "c1", platform: "tiktok", title: "You don't need expensive gear to start a podcast",
          description: "Here is the thing nobody tells you about starting a podcast. #podcast #podcasting #creator",
          tags: ["#podcast", "#podcasting", "#creator"], privacy: "", status: "awaiting_approval", when: "Today, 6:10 PM",
          rights: { label: "Owned", basis: "From your videos folder" }, quality: quality("warn"), score: 78 },
        { id: "s3", clipId: "c2", platform: "youtube", title: "Ask your guest what they got wrong last year",
          description: "Ask your guest what they got wrong last year. That answer is always the best part of the episode.",
          tags: ["podcast", "interview"], privacy: "public", status: "approved", approvedBy: "automatic", when: "Tomorrow, 9:40 AM",
          rights: { label: "Owned", basis: "From your videos folder" }, quality: quality("clean"), score: 74 },
        { id: "s4", clipId: "c6", platform: "youtube", title: "The week I almost quit", description: "I had the resignation email written.",
          tags: ["founder"], privacy: "public", status: "published", onPlatform: true, when: "Today, 8:15 PM",
          rights: { label: "Owned", basis: "Added by you" }, quality: quality("clean"), score: 80,
          note: "Uploaded early as Private with a publish time. YouTube makes it public at 8:15 PM, even if this PC is off." },
        { id: "s5", clipId: "c7", platform: "tiktok", title: "What the first customer actually said",
          description: "She asked one question I could not answer. #founder", tags: ["#founder"], privacy: "SELF_ONLY",
          status: "approved", approvedBy: "you", when: "Tomorrow, 12:15 PM", rights: { label: "Owned", basis: "Added by you" },
          quality: quality("clean"), score: 72 },
        { id: "s6", clipId: "c3", platform: "youtube", title: "Your first ten episodes are practice", description: "Your first ten episodes are practice, so publish them anyway.",
          tags: ["podcast"], privacy: "public", status: "published", when: "Mon, 10:05 AM", published: "Mon, 10:05 AM",
          rights: { label: "Owned", basis: "From your videos folder" }, quality: quality("clean"), score: 69, url: "#",
          stats: { views: 1284, likes: 96, comments: 12, shares: null, watch: 212, avgView: 17.4, avgPct: 81,
            notes: { shares: "YouTube's API does not report shares." }, at: "Today, 3:30 PM" } },
        { id: "s7", clipId: "c8", platform: "tiktok", title: "Pricing was the hardest part", description: "Nobody tells you how to charge. #pricing",
          tags: ["#pricing"], privacy: "SELF_ONLY", status: "published", when: "Sun, 1:30 PM", published: "Sun, 1:30 PM",
          rights: { label: "Owned", basis: "Added by you" }, quality: quality("clean"), score: 66, url: "#",
          stats: { views: null, likes: null, comments: null, shares: null, watch: null, avgView: null, avgPct: null,
            notes: { all: "TikTok statistics need the “Video statistics” permission, which this app does not have." }, at: "Today, 3:30 PM" } },
        { id: "s8", clipId: "c4", platform: "youtube", title: "Cut the slow parts, keep the honest ones", description: "Keep the recording short and cut the slow parts.",
          tags: ["editing"], privacy: "public", status: "reconciling", when: "Today, 11:40 AM", rights: { label: "Owned", basis: "From your videos folder" },
          quality: quality("clean"), score: 64,
          statusNote: "YouTube received the whole file, but its answer never arrived, so ClipFoundry cannot tell whether the video was created.",
          fix: "Look in YouTube Studio. If the video is there, paste its link. If it is not, upload it again." },
        { id: "s9", clipId: "c5", platform: "tiktok", title: "Why people love stories about mistakes", description: "People love honest stories about mistakes. #storytelling",
          tags: ["#storytelling"], privacy: "SELF_ONLY", status: "failed", when: "Today, 1:20 PM", rights: { label: "Owned", basis: "From your videos folder" },
          quality: quality("clean"), score: 61, statusNote: "TikTok said ClipFoundry's sign-in has expired.",
          fix: "Reconnect TikTok in Settings, Accounts, then press Try again." },
        { id: "s10", clipId: "c7", platform: "tiktok", title: "What the first customer actually said (draft)", description: "She asked one question I could not answer.",
          tags: [], privacy: "", status: "action_needed", when: "Yesterday, 6:00 PM", rights: { label: "Owned", basis: "Added by you" },
          quality: quality("clean"), score: 70, mode: "inbox",
          statusNote: "Sent to your TikTok inbox as a draft. Finish and post it in the TikTok app, then paste the link here to track it." },
        { id: "s11", clipId: "c5", platform: "youtube", title: "Why people love stories about mistakes", description: "People love honest stories about mistakes.",
          tags: ["storytelling"], privacy: "public", status: "blocked", when: "Tomorrow, 3:05 PM", rights: { label: "Owned", basis: "From your videos folder" },
          quality: quality("failed"), score: 58, statusNote: "The final check failed on this exact file: black for 2.1 of 31.0 s (at 0:12).",
          fix: "Open the clip, move the start past the black part, and render it again. The new file is checked again." },
        { id: "s12", clipId: "c8", platform: "youtube", title: "Pricing was the hardest part", description: "", tags: [], privacy: "public",
          status: "canceled", when: "Sat, 10:00 AM", rights: { label: "Owned", basis: "Added by you" }, quality: quality("clean"), score: 60,
          statusNote: "Canceled by you." },
      ],

      publications: {
        c1: [],
        c6: [{ platform: "youtube", status: "done", privacy: "private", when: "Today, 1:02 PM", message: "Uploaded to Sample channel · Morning Mic as Private." }],
      },

      opportunities: [
        { title: "Sample: Saturday livestream Q&A (part 2)", channel: "Your videos folder", score: 72, stage: "Finding the best moments" },
        { title: "Sample: Morning Mic podcast, episode 12", channel: "Your videos folder", score: 64, stage: "5 clips made" },
        { title: "Sample: Public-domain lecture on radio history", channel: "Free-license library (public domain)", score: 58, stage: "Next in line" },
      ],

      activity: [
        { title: "Sample: The podcast moment everyone is talking about", channel: "Another creator's channel", used: false, stage: "Skipped",
          why: "Not covered: no agreement, license or ownership", rights: "Not covered", at: "18 min ago" },
        { title: "Sample: Podcast interview, the founder who almost quit", channel: "Another creator's channel", used: false, stage: "Skipped",
          why: "Not covered: no agreement, license or ownership", rights: "Not covered", at: "18 min ago" },
        { title: "Sample: Morning Mic podcast, episode 12", channel: "Your videos folder", used: true, stage: "5 clips made", why: "",
          rights: "Owned", at: "1 h ago" },
        { title: "Sample: Creative Commons talk (share-alike)", channel: "Free-license library", used: false, stage: "Skipped",
          why: "Share-alike licenses are never used automatically", rights: "Not covered", at: "2 h ago" },
        { title: "Sample: Guest episode from a partner channel", channel: "Partner channel (agreement)", used: false, stage: "Skipped",
          why: "No allowed way to get the file: YouTube does not allow downloading it", rights: "Allowlisted", at: "3 h ago", canAddFile: true },
      ],

      agreements: [
        { creator: "Sample partner podcast", channels: ["UCsample000000000000000001"], commercial: true, platforms: ["YouTube", "TikTok"],
          attribution: "Clip from Sample partner podcast", evidence: "Email from them on 2026-09-01: “You may clip and post our episodes.”", ends: "" },
      ],
      rules: [
        { status: "Owned", label: "Your videos folder", scope: "folder", basis: "Your own recordings (created on START)" },
        { status: "Allowlisted", label: "Sample partner podcast", scope: "channel", basis: "Agreement recorded 2026-09-01" },
      ],
      feeds: [
        { name: "Your videos folder", kind: "watch folder", where: "C:\\Users\\you\\Videos\\ClipFoundry", enabled: true, error: "" },
        { name: "Sample partner podcast uploads", kind: "YouTube channel", where: "UCsample000000000000000001", enabled: true, error: "" },
      ],
      sources: [
        { title: "Sample: Saturday livestream Q&A (part 2)", rights: "Owned", status: "analyzing", score: 72, expected: 4, basis: "Your videos folder" },
        { title: "Sample: Morning Mic podcast, episode 12", rights: "Owned", status: "analyzed", score: 64, expected: 5, made: 5, basis: "Your videos folder" },
        { title: "Sample: The podcast moment everyone is talking about", rights: "Not covered", status: "needs rights", score: 81, expected: 3, basis: "No agreement, license or ownership" },
        { title: "Sample: Guest episode from a partner channel", rights: "Allowlisted", status: "needs file", score: 69, expected: 3, basis: "Agreement recorded 2026-09-01" },
      ],
      workers: [
        ["Trend Scout", "Idle", "Next online search at 7:22 PM"], ["Source Scout", "Working", "Checking your folders"],
        ["Clip Hunter", "Idle", ""], ["Analyzer", "Working", "Finding the best moments · Saturday livestream Q&A"],
        ["Renderer", "Waiting", "Waiting for the GPU"], ["Quality Gate", "Idle", ""], ["Packager", "Idle", ""],
        ["Scheduler", "Idle", "Next check in 1 min"], ["Publisher", "Idle", ""], ["Live Watcher", "Idle", "No live sources"],
        ["Learner", "Idle", "Needs 20 posts with real numbers (has 2)"], ["Maintenance", "Idle", ""],
      ],
      jobs: [
        { kind: "analyze source", worker: "Analyzer", status: "running", attempt: "1/3", message: "Finding the best moments", progress: 0.46 },
        { kind: "render clip", worker: "Renderer", status: "waiting", attempt: "1/3", message: "Waiting for the GPU (transcription holds it)" },
        { kind: "feed scan", worker: "Source Scout", status: "running", attempt: "1/3", message: "Checking your folders" },
        { kind: "publish", worker: "Publisher", status: "failed", attempt: "3/3", message: "TikTok said the sign-in has expired",
          fix: "Reconnect TikTok in Settings, Accounts." },
      ],
      events: [
        ["2 min ago", "Started finding moments in “Sample: Saturday livestream Q&A (part 2)”"],
        ["18 min ago", "Skipped 2 videos from other creators (not covered)"],
        ["1 h ago", "Made 5 clips from “Sample: Morning Mic podcast, episode 12”"],
        ["1 h ago", "2 posts wait for your OK"],
      ],
      quota: [
        ["Units", 1850, 10000, false], ["Uploads", 2, 6, false], ["Searches", 14, 100, false],
      ],

      performance: { lastRefreshed: "Today, 3:30 PM", published: 2, withStats: 1, spearman: null, samples: 1, minSamples: 8 },

      settings: {
        clip_count: 5, length: "standard", caption_style: "bold", tracking: "auto", layout: "fill", silence: "light",
        auto_zoom: true, hook_overlay: true, remove_fillers: true, caption_emphasis: false, normalize_audio: true,
        daily_target: 15, whisper_model: "auto", whisper_device: "auto", compute: "auto", language: "",
        encoder: "auto", crf: 20, preset: "veryfast", fps: 30, min_score: 50, ai_provider: "heuristic",
        timezone: "America/Chicago", active_start: 9, active_end: 21, keep_awake: true, allow_cpu: false,
      },
    };
  }

  /** The demo scenarios. Each returns a complete state; the prototype's controls can then change single parts. */
  const SCENARIOS = {
    first: {
      label: "First use",
      build(s) {
        s.setupDone = false;
        s.mode = "";
        s.accounts.youtube = { state: "not_set_up", name: "", configured: false, audited: false, restriction: "" };
        s.accounts.tiktok = { state: "not_set_up", name: "", configured: false, audited: false, restriction: "" };
        s.autopilot.enabled = false;
        s.autopilot.working = null;
        s.autopilot.currently = "Off";
        s.autopilot.skipped24h = 0;
        s.myVideos.videos = 0;
        s.projects = []; s.clips = []; s.posts = []; s.publications = {};
        s.opportunities = []; s.activity = []; s.agreements = []; s.sources = []; s.jobs = []; s.events = [];
        s.rules = []; s.feeds = [];
        return s;
      },
    },
    empty: {
      label: "Autopilot on, no usable videos",
      build(s) {
        s.autopilot.working = null;
        s.autopilot.currently = "Looking for videos it may use";
        s.myVideos.videos = 0;
        s.projects = []; s.clips = []; s.posts = []; s.publications = {};
        s.opportunities = [];
        s.activity = s.activity.filter((a) => !a.used);
        s.sources = s.sources.filter((x) => x.rights === "Not covered");
        s.jobs = [];
        s.events = [["18 min ago", "Skipped 7 videos from other creators (not covered)"]];
        return s;
      },
    },
    working: {
      label: "Working",
      build(s) {
        s.posts = s.posts.filter((p) => !["awaiting_approval", "reconciling", "failed", "action_needed", "blocked"].includes(p.status));
        return s;
      },
    },
    ready: {
      label: "Clips ready, posts to review",
      build(s) {
        s.autopilot.working = null;
        s.autopilot.currently = "Looking for videos it may use";
        const p3 = s.projects.find((p) => p.id === "p3");
        Object.assign(p3, { status: "ready", clipCount: 0, noClips: true, candidates: 6, requested: 5, minScore: 50 });
        s.posts = s.posts.filter((p) => !["reconciling", "failed", "action_needed", "blocked"].includes(p.status));
        s.projects = s.projects.filter((p) => p.status !== "error");
        return s;
      },
    },
    problems: {
      label: "Problems",
      build(s) {
        s.autopilot.keepAwake = "failed";
        s.accounts.youtube.state = "expired";
        s.accounts.tiktok.state = "expired";
        s.autopilot.gpu = {
          state: "problem", name: "NVIDIA GeForce RTX 3050", mode: "GPU",
          detail: "CUDA could not load cuBLAS (cublas64_12.dll was not found). Autopilot paused transcription for 30 minutes instead of using the slower CPU.",
          fix: "Run gpu-check.bat from the ClipFoundry folder and follow what it says, then restart ClipFoundry.",
        };
        s.autopilot.currently = "Waiting for the GPU";
        s.autopilot.working.stage = "Transcribing";
        s.autopilot.working.stageIndex = 1;
        s.autopilot.working.progress = null;
        s.autopilot.working.waiting = "Paused until 4:42 PM: GPU transcription is not working";
        const p3 = s.projects.find((p) => p.id === "p3");
        Object.assign(p3, { stage: "Transcribe", stageIndex: 1, progress: null, message: "Waiting: GPU transcription is not working" });
        return s;
      },
    },
  };

  function build(name) {
    const s = base();
    return (SCENARIOS[name] || SCENARIOS.ready).build(s);
  }

  return { build, scenarios: Object.fromEntries(Object.entries(SCENARIOS).map(([k, v]) => [k, v.label])), quality, timedWords, SPEECH };
})();
