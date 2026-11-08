import { FormEvent, useCallback, useEffect, useId, useRef, useState } from "react";
import { errorText } from "../api";
import { Agent, agentsApi, AgentsView, AgentTemplate, AgentTool } from "../brain";
import { at, plural } from "../format";
import { Banner, ConfirmDialog, Dialog, EmptyState, Icon, Pill, Skel, Toggle, toast } from "./ui";

// The same limits the app keeps (clipfoundry/brain/agents.py), so a form never sends what it would cut.
const NAME_CHARS = 40;
const ROLE_CHARS = 200;
const INSTRUCTIONS_CHARS = 2000;

/** The icons' names, for screen readers. */
const ICON_WORDS: Record<string, string> = {
  "🔎": "magnifying glass", "✍️": "writing hand", "🪝": "hook", "✂️": "scissors", "🧐": "face with a monocle",
  "🎵": "music note", "🖼️": "picture", "📈": "rising chart", "🎬": "clapper board", "💡": "light bulb", "🗂️": "folders",
  "🤖": "robot", "🎙️": "microphone", "🌍": "globe", "😂": "laughing face", "📣": "megaphone",
};
/** What each tool lets a helper do, in plain words (the app's own label is used for any other tool). */
const TOOL_WORDS: Record<string, string> = {
  find_projects: "See your list of projects", open_project: "Look inside a project or video",
  recall: "Search what you told ClipForge AI", knowhow: "Read ClipForge's editing know-how",
  app_status: "Check what ClipForge is doing", go_to: "Show buttons that open a page or a project",
  remember: "Remember what you tell it", propose_change: "Propose changes to a video's cut (you apply or discard them)",
};
const toolWords = (t: AgentTool) => TOOL_WORDS[t.name] || t.label;

type Draft = { name: string; icon: string; role: string; instructions: string; tools: string[]; helps_plans: boolean };
const BLANK: Draft = { name: "", icon: "🤖", role: "", instructions: "", tools: ["recall", "knowhow"], helps_plans: false };
const ready = (a: Agent) => `${a.name} is ready. Talk to it with “@${a.name} …” in any chat.`;

/**
 * Brain → Agents: the helpers that work alongside ClipForge AI. ClipForge AI hands them jobs, you talk to one with
 * "@Name …", and the ones set to help with plans add a short note when a new video is planned. Ready-made helpers
 * are added with one press; you can also make your own. A helper only looks things up and writes: it never changes
 * or deletes anything.
 */
export function AgentsTab() {
  const [view, setView] = useState<AgentsView | null>(null);
  const [problem, setProblem] = useState("");
  const [editing, setEditing] = useState<Agent | "new" | null>(null);
  const [removing, setRemoving] = useState<Agent | null>(null);
  const [adding, setAdding] = useState("");

  const load = useCallback(async () => {
    try {
      setView(await agentsApi.list());
      setProblem("");
    } catch (e) {
      setProblem(errorText(e));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const put = (a: Agent) => setView((v) => v && { ...v, agents: v.agents.map((x) => (x.id === a.id ? a : x)) });
  const flip = async (a: Agent, patch: Partial<Pick<Agent, "enabled" | "helps_plans">>) => {
    put({ ...a, ...patch });
    try {
      put(await agentsApi.edit(a.id, patch));
    } catch (e) {
      put(a);
      toast(errorText(e), true);
    }
  };
  const addReady = async (t: AgentTemplate) => {
    setAdding(t.template);
    try {
      const a = await agentsApi.add({ template: t.template });
      await load();
      toast(ready(a));
    } catch (e) {
      toast(errorText(e), true);
    }
    setAdding("");
  };
  const save = async (d: Draft) => {
    if (editing && editing !== "new") {
      const a = await agentsApi.edit(editing.id, d);
      toast(`${a.name} is saved.`);
    } else {
      toast(ready(await agentsApi.add({ ...d, enabled: true })));
    }
    setEditing(null);
    await load();
  };
  const remove = async (a: Agent) => {
    await agentsApi.remove(a.id);
    await load();
    toast(`${a.name} is removed. What it wrote in your chats stays.`);
  };

  if (!view) {
    return problem
      ? <Banner tone="bad" title="Your helpers could not be loaded" actions={<button type="button" className="btn btn-small" onClick={() => void load()}>
        <Icon name="refresh" />Try again</button>}>{problem}</Banner>
      : <div className="stack-4" aria-busy="true"><span className="sr-only" role="status">Loading your helpers…</span>
        <Skel className="skel-block" /><Skel className="skel-block" /></div>;
  }
  const full = view.agents.length >= view.limit;
  return (
    <div className="agents-tab stack-5">
      <section className="panel agents-intro" aria-labelledby="agents-about">
        <span className="empty-icon" aria-hidden="true"><Icon name="user" /></span>
        <div className="stack-2">
          <h2 id="agents-about">Helpers</h2>
          <p>Helpers are specialists that work with ClipForge AI. It hands them jobs, and you can talk to one directly by starting a
            message with @ and its name.</p>
          <p className="small muted">They think with the same model as ClipForge AI, on this computer when that model is. A helper
            looks things up and writes for you; it never changes or deletes anything.
            {" "}<a className="textlink" href="#/brain/talk">Talk to ClipForge AI</a></p>
        </div>
      </section>

      <section className="stack-3" aria-labelledby="agents-mine">
        <div className="section-title">
          <h2 id="agents-mine">Your helpers</h2>
          <span className="small muted">{view.agents.length} of {view.limit}</span>
        </div>
        {problem && <p className="error-text" role="alert"><Icon name="alert" className="sm" />{problem}</p>}
        {view.agents.length === 0 ? (
          <EmptyState icon="user" title="No helpers yet" level={3}>Add a ready-made one below with one press, or make your own.</EmptyState>
        ) : (
          <ul className="agent-grid">
            {view.agents.map((a) => (
              <li key={a.id} className={`agent-card${a.enabled ? "" : " off"}`}>
                <div className="agent-card-head">
                  <span className="agent-icon" aria-hidden="true">{a.icon || "🤖"}</span>
                  <div className="grow">
                    <h3 className="break">{a.name}</h3>
                    <p className="small muted break">{a.role}</p>
                  </div>
                </div>
                <div className="agent-switches">
                  <Toggle on={a.enabled} showState ariaLabel={`Use ${a.name}`} onChange={(on) => void flip(a, { enabled: on })} />
                  <Toggle on={a.helps_plans} label="Helps plan new videos" ariaLabel={`${a.name} helps plan new videos`}
                    onChange={(on) => void flip(a, { helps_plans: on })} />
                </div>
                <p className="tiny muted">{a.runs
                  ? `Worked ${plural(a.runs, "time")}${a.last_run_at ? `, last ${at(a.last_run_at)}` : ""}.`
                  : a.enabled ? "Has not worked yet." : "Switched off: ClipForge AI does not hand it jobs."}</p>
                <div className="row wrap agent-actions">
                  <button type="button" className="btn btn-small" aria-label={`Edit ${a.name}`} onClick={() => setEditing(a)}>
                    <Icon name="edit" />Edit</button>
                  <button type="button" className="btn btn-small btn-quiet" aria-label={`Remove ${a.name}`} onClick={() => setRemoving(a)}>
                    <Icon name="trash" />Remove</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="stack-3" aria-labelledby="agents-add">
        <div className="section-title">
          <h2 id="agents-add">Add a helper</h2>
          <span className="small muted">Ready-made helpers: add one with one press and change it any time.</span>
        </div>
        {full && <Banner tone="warn" title={`You have ${view.limit} helpers, the most you can have`}>Remove one to add another.</Banner>}
        <ul className="agent-grid">
          {[...view.templates].sort((x, y) => Number(x.added) - Number(y.added)).map((t) => (
            <li key={t.template} className="agent-card ready">
              <div className="agent-card-head">
                <span className="agent-icon" aria-hidden="true">{t.icon}</span>
                <div className="grow">
                  <h3>{t.name}</h3>
                  <p className="small muted">{t.role}</p>
                </div>
              </div>
              {t.helps_plans && <span className="tag agent-tag"><Icon name="spark" className="xs" />Helps plan new videos</span>}
              <div className="agent-actions">
                {t.added ? <Pill tone="good" icon="check">Added</Pill> : (
                  <button type="button" className="btn btn-small btn-primary" disabled={full || adding !== ""}
                    aria-label={`Add ${t.name}`} onClick={() => void addReady(t)}>
                    {adding === t.template ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="plus" />}Add</button>
                )}
              </div>
            </li>
          ))}
          <li className="agent-card own">
            <div className="agent-card-head">
              <span className="agent-icon" aria-hidden="true"><Icon name="plus" /></span>
              <div className="grow">
                <h3>Make your own</h3>
                <p className="small muted">Give it a name, a job and the way you want it done, in your own words.</p>
              </div>
            </div>
            <div className="agent-actions">
              <button type="button" className="btn btn-small" disabled={full} onClick={() => setEditing("new")}>
                <Icon name="edit" />Make your own</button>
            </div>
          </li>
        </ul>
      </section>

      {editing && <AgentEditor agent={editing === "new" ? null : editing} view={view} onSave={save} onClose={() => setEditing(null)} />}
      {removing && <ConfirmDialog title={`Remove ${removing.name}?`} confirmLabel="Remove" danger
        onConfirm={() => remove(removing)} onClose={() => setRemoving(null)}>
        <p>ClipForge AI stops handing it jobs and “@{removing.name}” no longer reaches it. What it already wrote in your chats
          stays.{removing.template ? " You can add it again from the ready-made helpers." : ""}</p>
      </ConfirmDialog>}
    </div>
  );
}

/** Make a helper, or change one: its name, icon, job, how it works, what it may use, and whether it helps with plans.
 * The app checks what you wrote; what it says is shown next to the buttons. */
function AgentEditor({ agent, view, onSave, onClose }: {
  agent: Agent | null; view: AgentsView; onSave: (d: Draft) => Promise<void>; onClose: () => void;
}) {
  const id = useId();
  const [d, setD] = useState<Draft>(() => agent ? { name: agent.name, icon: agent.icon || "🤖", role: agent.role,
    instructions: agent.instructions, tools: agent.tools, helps_plans: agent.helps_plans } : BLANK);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const roleRef = useRef<HTMLInputElement>(null);
  const icons = view.icons.includes(d.icon) || !d.icon ? view.icons : [d.icon, ...view.icons];
  const bad = !error ? "" : /name|called/i.test(error) ? "name" : /what the agent is for|is for\b/i.test(error) ? "role" : "";
  const set = <K extends keyof Draft>(k: K, value: Draft[K]) => {
    setD((x) => ({ ...x, [k]: value }));
    if (k === bad) setError("");  // the field the app pointed at is being fixed: its message goes
  };
  const toggleTool = (name: string, on: boolean) => set("tools", on ? [...d.tools, name] : d.tools.filter((t) => t !== name));
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    // the two fields everyone fills in, checked here; everything else the app checks and its words are shown
    const missing = !d.name.trim() ? "Give the helper a name." : !d.role.trim() ? "Say in a few words what the helper is for." : "";
    if (missing) {
      setError(missing);
      (d.name.trim() ? roleRef : nameRef).current?.focus();
      return;
    }
    setSaving(true);
    setError("");
    try {
      await onSave({ ...d, name: d.name.trim(), role: d.role.trim(), instructions: d.instructions.trim() });
    } catch (err) {
      const why = errorText(err);
      setError(why);
      setSaving(false);
      (/name|called/i.test(why) ? nameRef : /is for\b/i.test(why) ? roleRef : null)?.current?.focus();
    }
  };
  return (
    <Dialog title={agent ? `Edit ${agent.name}` : "Make your own helper"} wide onClose={onClose} actions={<>
      <button type="button" className="btn" onClick={onClose}>Cancel</button>
      <button type="submit" form={`${id}-form`} className="btn btn-primary" disabled={saving}>
        {saving ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="check" />}{agent ? "Save" : "Add this helper"}</button>
    </>}>
      <form id={`${id}-form`} className="agent-editor" onSubmit={submit} noValidate>
        <label className="field"><span>Name</span>
          <input ref={nameRef} type="text" value={d.name} maxLength={NAME_CHARS} data-autofocus autoComplete="off"
            placeholder="For example: Thumbnail buddy" aria-invalid={bad === "name" || undefined}
            aria-describedby={`${id}-name-hint${bad === "name" ? ` ${id}-error` : ""}`}
            onChange={(e) => set("name", e.target.value)} />
          <span id={`${id}-name-hint`} className="hint">Short, so it is easy to write after @ in a chat.</span></label>
        <fieldset className="field">
          <legend className="label">Icon</legend>
          <div className="agent-icons" role="radiogroup" aria-label="Icon">
            {icons.map((icon) => (
              <label key={icon} title={ICON_WORDS[icon] || icon}>
                <input type="radio" name={`${id}-icon`} checked={d.icon === icon} onChange={() => set("icon", icon)} />
                <span aria-hidden="true">{icon}</span><span className="sr-only">{ICON_WORDS[icon] || icon}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <label className="field"><span>What it is for</span>
          <input ref={roleRef} type="text" value={d.role} maxLength={ROLE_CHARS} autoComplete="off"
            placeholder="For example: plans thumbnails that get the click" aria-invalid={bad === "role" || undefined}
            aria-describedby={`${id}-role-hint${bad === "role" ? ` ${id}-error` : ""}`}
            onChange={(e) => set("role", e.target.value)} />
          <span id={`${id}-role-hint`} className="hint">One line. ClipForge AI reads it to know when to hand this helper a job.</span></label>
        <label className="field"><span>How it works</span>
          <textarea value={d.instructions} maxLength={INSTRUCTIONS_CHARS} rows={5} aria-describedby={`${id}-how-hint`}
            placeholder="Tell it how you want the job done, in your own words. For example: give 3 ideas, each with the words on the picture and the colours."
            onChange={(e) => set("instructions", e.target.value)} />
          <span id={`${id}-how-hint`} className="hint">Optional. {d.instructions.length.toLocaleString("en-US")} of {INSTRUCTIONS_CHARS.toLocaleString("en-US")} characters.</span></label>
        <fieldset className="field">
          <legend className="label">What it may use</legend>
          <span className="hint">A helper only looks things up and writes. It never changes or deletes anything, and it does not hand
            work on to another helper.</span>
          <div className="agent-tools">
            {view.tools.map((t) => (
              <label key={t.name} className="check-inline">
                <input type="checkbox" checked={d.tools.includes(t.name)} onChange={(e) => toggleTool(t.name, e.target.checked)} />
                <span>{toolWords(t)}{t.video_only && <span className="tag agent-tag">Only in a video's chat</span>}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="stack-1">
          <Toggle on={d.helps_plans} label="Helps plan new videos" describedBy={`${id}-plans-hint`} onChange={(on) => set("helps_plans", on)} />
          <span id={`${id}-plans-hint`} className="hint">When ClipForge AI plans a new video with you, this helper adds a short note
            from its speciality.</span>
        </div>
        {error && <p id={`${id}-error`} className="error-text" role="alert"><Icon name="alert" className="sm" />{error}</p>}
      </form>
    </Dialog>
  );
}
