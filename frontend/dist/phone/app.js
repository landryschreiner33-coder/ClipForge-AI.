"use strict";
(() => {
  const el = (id) => document.getElementById(id);
  const text = (id, value) => { el(id).textContent = String(value ?? ""); };
  const show = (id, visible) => { el(id).hidden = !visible; };
  const KEY = "clipfoundry.phone.v1";
  const POLL = 10_000;
  let token = "";
  let expiry = 0;
  let timer;
  let controller;
  let generation = 0;
  let failures = 0;
  let lastUpdate = 0;
  let timezone;

  function clearStorage() {
    for (const name of ["localStorage", "sessionStorage"]) {
      try { window[name].removeItem(KEY); } catch { /* Storage may be unavailable in private browsing. */ }
    }
  }
  function storedGrant() {
    for (const name of ["localStorage", "sessionStorage"]) {
      try {
        const grant = JSON.parse(window[name].getItem(KEY) || "null");
        if (grant && /^[A-Za-z0-9_-]{43}$/.test(grant.token) && grant.expires_at > Date.now() / 1000) return grant;
        window[name].removeItem(KEY);
      } catch { /* A malformed/blocked browser store never prevents fresh pairing. */ }
    }
    return null;
  }
  function saveGrant(grant, remember) {
    clearStorage();
    try { window[remember ? "localStorage" : "sessionStorage"].setItem(KEY, JSON.stringify(grant)); }
    catch { /* Keep the grant in memory for this open page if the browser blocks storage. */ }
  }
  function stopRequests() {
    generation++;
    clearTimeout(timer);
    if (controller) controller.abort();
    controller = null;
  }
  function badge(id, label, tone = "") {
    text(id, label);
    el(id).className = `badge ${tone}`;
  }
  function time(value, date = false) {
    if (!Number.isFinite(value) || value <= 0) return "Not reported";
    try {
      return new Intl.DateTimeFormat(undefined, {
        ...(date ? { month: "short", day: "numeric" } : {}),
        hour: "numeric", minute: "2-digit", ...(timezone ? { timeZone: timezone } : {}),
      }).format(new Date(value * 1000));
    } catch { return new Date(value * 1000).toLocaleTimeString(); }
  }
  function pairScreen(message = "") {
    stopRequests(); token = ""; expiry = 0; failures = 0; lastUpdate = 0;
    clearStorage(); show("dashboard", false); show("pair-screen", true);
    // Clear private status from the DOM when access is lost, not just from the screen.
    for (const id of ["work-title", "working-title", "step", "percent", "workers", "updated", "next-name",
      "next-time", "version", "published", "scheduled", "processed", "daily", "published-posts", "scheduled-posts",
      "ready", "review", "fix", "queued", "zone", "run", "health", "health-time", "attention-count", "platform"]) {
      text(id, "");
    }
    el("progress").removeAttribute("value");
    el("attention").replaceChildren(); el("health-checks").replaceChildren();
    badge("connection", "Not connected");
    text("pair-error", message); show("pair-error", !!message);
    el("code").value = "";
  }
  function stale(message) {
    badge("connection", "Not live", "warn");
    const since = lastUpdate ? ` Last received ${time(lastUpdate)}. The values below may have changed.` : "";
    text("stale", message + since); show("stale", true);
  }
  function count(value) { return Number.isFinite(value) && value >= 0 ? Math.floor(value).toLocaleString() : "—"; }
  function items(id, rows, checked = false) {
    const list = el(id);
    list.replaceChildren();
    for (const row of rows) {
      const li = document.createElement("li");
      const title = document.createElement("span");
      title.textContent = row.title || row.label;
      li.append(title);
      if (checked) {
        const status = document.createElement("span");
        status.className = "check-status";
        status.textContent = { healthy: "Healthy", degraded: "Degraded", error: "Error", unknown: "Unknown" }
          [row.status] || "Unknown";
        li.append(status);
      }
      list.append(li);
    }
  }
  function render(data) {
    timezone = typeof data.timezone === "string" ? data.timezone : undefined;
    lastUpdate = data.server_time;
    show("pair-screen", false); show("dashboard", true); show("stale", false);
    badge("connection", "Live", "good");
    badge("run", data.run.label, data.run.state === "running" ? "good" : "warn");
    text("work-title", data.currently);
    const work = data.working;
    show("working-title", !!work?.title); text("working-title", work?.title);
    show("work-progress", !!work);
    text("step", work?.step);
    if (work && Number.isFinite(work.progress)) {
      const value = Math.min(100, Math.max(0, Math.round(work.progress * 100)));
      el("progress").value = value; text("percent", `${value}%`); show("progress", true);
    } else {
      show("progress", false); text("percent", work ? "Progress not reported" : "");
    }
    show("publish-paused", data.run.publishing_paused);
    text("workers", data.workers.alive ? "Background workers online" : "Background workers not reporting");
    text("updated", `Updated ${time(data.server_time)}`);
    text("zone", timezone || "PC time zone");
    for (const key of ["published", "scheduled", "processed", "daily"]) text(key, count(data.today[key]));
    text("published-posts", `${count(data.today.published_posts)} platform posts`);
    text("scheduled-posts", `${count(data.today.scheduled_posts)} platform posts`);
    const next = data.next_post;
    show("platform", !!next);
    if (next) {
      badge("platform", { youtube: "YouTube", tiktok: "TikTok" }[next.platform] || "Post");
      text("next-name", next.title || "Untitled clip");
      const status = { approved: "Scheduled", awaiting_approval: "Awaiting approval", publishing: "Publishing",
        reconciling: "Upload not confirmed", action_needed: "Needs attention" }[next.status] || "Planned";
      text("next-time", `${status} · ${time(next.planned_at, true)}`);
    } else { text("next-name", "No post planned yet"); text("next-time", ""); }
    const needs = Array.isArray(data.needs_you) ? data.needs_you.slice(0, 8) : [];
    badge("attention-count", needs.length ? String(needs.length) : "Clear", needs.length ? "warn" : "good");
    items("attention", needs.length ? needs : [{ title: "Nothing needs your attention right now." }]);
    for (const [id, key] of [["ready", "ready"], ["review", "review"], ["fix", "fix"], ["queued", "scheduled"]]) {
      text(id, count(data.posts[key]));
    }
    const health = data.health;
    badge("health", health.label, health.status === "healthy" ? "good" : health.status === "error" ? "bad" : "warn");
    text("health-time", `Checked ${time(health.checked_at)}`);
    items("health-checks", Array.isArray(data.health_checks) ? data.health_checks : [], true);
    text("desktop-note", data.desktop_note); text("version", `ClipFoundry ${data.version}`);
  }
  async function jsonRequest(path, options) {
    controller = new AbortController();
    const active = controller;
    const timeout = setTimeout(() => active.abort(), 8000);
    try {
      const response = await fetch(path, { ...options, cache: "no-store", credentials: "omit", signal: active.signal });
      let body;
      try { body = await response.json(); } catch { body = null; }
      return { response, body };
    } finally { clearTimeout(timeout); if (controller === active) controller = null; }
  }
  async function refresh() {
    if (!token || document.hidden || controller) return;
    clearTimeout(timer);
    if (expiry <= Date.now() / 1000) {
      pairScreen("Phone access expired. Get a new pairing code on your PC."); return;
    }
    const expected = generation;
    try {
      const { response, body } = await jsonRequest("/api/status", { headers: { Authorization: `Bearer ${token}` } });
      if (expected !== generation) return;
      if (response.status === 401 || response.status === 403) {
        pairScreen("Phone access expired or was unpaired. Get a new pairing code on your PC."); return;
      }
      if (!response.ok || !body || typeof body.currently !== "string" || !Number.isFinite(body.server_time)
        || !body.run || !body.workers || !body.today || !body.posts || !body.health) throw new Error("Unavailable");
      render(body); failures = 0;
    } catch {
      if (expected !== generation) return;
      failures++;
      stale("Your PC is not answering. Check that ClipFoundry is open and your private connection is active.");
    } finally {
      if (expected === generation && token && !document.hidden) {
        timer = setTimeout(refresh, Math.min(60_000, POLL * Math.max(1, 2 ** Math.min(failures, 3))));
      }
    }
  }
  el("pair-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const code = el("code").value.trim();
    if (!/^[0-9]{8}$/.test(code) || controller) return;
    const remember = el("remember").checked;
    const expected = generation;
    el("connect").disabled = true; show("pair-error", false);
    try {
      const { response, body } = await jsonRequest("/api/pair", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }),
      });
      if (expected !== generation) return;
      if (!response.ok) {
        const message = response.status === 429 ? "Too many attempts. Wait a minute, then get a new code on your PC."
          : response.status === 409 ? "Phone pairing is unavailable. Check phone settings on your PC."
            : "Code incorrect, expired or already used. Get a new pairing code on your PC.";
        text("pair-error", message); show("pair-error", true); return;
      }
      if (!body || !/^[A-Za-z0-9_-]{43}$/.test(body.token) || !Number.isFinite(body.expires_at)) {
        throw new Error("Invalid pairing response");
      }
      token = body.token; expiry = body.expires_at; saveGrant(body, remember); el("code").value = "";
      show("pair-screen", false); show("dashboard", true); badge("connection", "Connecting…");
      stale("Connecting to your PC…");
      await refresh();
    } catch {
      if (expected !== generation) return;
      text("pair-error", "Could not reach your PC. Keep ClipFoundry open and check your connection.");
      show("pair-error", true);
    } finally { el("connect").disabled = false; }
  });
  el("refresh").addEventListener("click", refresh);
  el("disconnect").addEventListener("click", () => pairScreen());
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopRequests();
      if (token) stale("Updates paused while this page is in the background.");
    } else if (token) refresh();
  });
  const grant = storedGrant();
  if (grant) {
    token = grant.token; expiry = grant.expires_at;
    show("pair-screen", false); show("dashboard", true);
    stale("Connecting to your PC…"); refresh();
  }
})();
