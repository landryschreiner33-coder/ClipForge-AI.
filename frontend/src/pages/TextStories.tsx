import { ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";
import { errorText } from "../api";
import { Banner, EmptyState, Icon, PageHead, Segmented, Skel, toast } from "../components/ui";
import { navigate } from "../router";
import { cancelUpload, uploadFile } from "../studio";
import {
  Background, BackgroundChoice, clock, Story, StoryListItem, StoryOptions, StoryPatch, StoryVoice, textStories,
} from "../textStories";
import "./stories.css";

/**
 * Text Stories (main navigation): write or paste a story, or let ClipForge AI write and revise it; choose a voice
 * style and hear it; put your own clips behind it (trimmed, looped, moved in the frame) or let ClipForge pick; preview
 * it small and fast, then export the full video. The work runs in ClipForge's job line, so Stop always works and a
 * restart carries on.
 */
export default function TextStories({ id }: { id: string }) {
  return id ? <StoryEditor id={id} key={id} /> : <StoryList />;
}

const STATUS: Record<string, string> = { draft: "Draft", writing: "Writing", voicing: "Recording the voice",
  rendering: "Making the video", ready: "Ready", failed: "Needs you" };

function StoryList() {
  const [list, setList] = useState<StoryListItem[] | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    textStories.list().then((r) => setList(r.stories)).catch((e) => setProblem(errorText(e)));
  }, []);
  const start = async () => {
    setBusy(true);
    try {
      const s = await textStories.create();
      navigate(`stories/${s.id}`);
    } catch (e) {
      toast(errorText(e), true);
      setBusy(false);
    }
  };
  const newButton = (
    <button type="button" className="btn btn-primary btn-large" disabled={busy} onClick={() => void start()}>
      <Icon name="plus" />New text story
    </button>
  );
  return (
    <div className="page narrow stories">
      <PageHead kind="Make" title="Text Stories" actions={newButton}
        sub={"A story read aloud over background video, with big captions: write it, pick a voice and a background, "
          + "preview, export."} />
      {problem && <Banner tone="bad" title="Your stories could not be loaded">{problem}</Banner>}
      {!list && !problem && (
        <div className="stack-3" aria-hidden="true"><Skel className="skel-block" /><Skel className="skel-block" /></div>
      )}
      {list && list.length === 0 && (
        <EmptyState icon="story" title="No text stories yet">
          Paste a story or let ClipForge AI write one. Your own gameplay or satisfying clips go behind it, or
          ClipForge picks.
        </EmptyState>
      )}
      {list && list.length > 0 && (
        <ul className="story-list">
          {list.map((s) => (
            <li key={s.id}>
              <a href={`#/stories/${s.id}`} className="story-row">
                <Icon name="story" />
                <span className="grow"><b>{s.name}</b>
                  <span className="small muted">
                    {s.words} words · {STATUS[s.status] || s.status}{s.exported ? " · exported" : ""}
                  </span>
                </span>
                <Icon name="chev" className="sm" />
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** One numbered step of the story. */
function Step({ n, title, done, children, id }: { n: number; title: string; done: boolean; children: ReactNode;
  id: string }) {
  return (
    <section className="panel story-step" aria-labelledby={id}>
      <h2 id={id}>
        <span className={`step-n${done ? " done" : ""}`} aria-hidden="true">{done ? <Icon name="check" /> : n}</span>
        {title}</h2>
      {children}
    </section>
  );
}

function useAudio() {
  const audio = useRef<HTMLAudioElement | null>(null);
  const url = useRef("");
  const [playing, setPlaying] = useState("");
  const stop = useCallback(() => {
    audio.current?.pause();
    audio.current = null;
    if (url.current) URL.revokeObjectURL(url.current);
    url.current = "";
    setPlaying("");
  }, []);
  useEffect(() => stop, [stop]);
  const play = async (key: string, v: { voice: string; speed: number; tone: number; text?: string }) => {
    if (playing === key) {
      stop();
      return;
    }
    stop();
    setPlaying(key);
    try {
      const { blob, note } = await textStories.hear(v);
      if (note) toast(note);
      url.current = URL.createObjectURL(blob);
      const a = new Audio(url.current);
      audio.current = a;
      a.onended = () => audio.current === a && stop();
      await a.play();
    } catch (e) {
      stop();
      if ((e as Error).name !== "NotAllowedError") toast(errorText(e), true);
    }
  };
  return { playing, play, stop };
}

function StoryEditor({ id }: { id: string }) {
  const ids = useId();
  const [story, setStory] = useState<Story | null>(null);
  const [opts, setOpts] = useState<StoryOptions | null>(null);
  const [problem, setProblem] = useState("");
  const [title, setTitle] = useState("");
  const [script, setScript] = useState("");
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const typed = useRef(false);
  const audio = useAudio();

  const take = useCallback((s: Story) => {
    setStory(s);
    if (!typed.current) {
      setTitle(s.title);
      setScript(s.script);
      setName(s.own_name);
    }
  }, []);
  useEffect(() => {
    textStories.get(id).then(take).catch((e) => setProblem(errorText(e)));
    textStories.options().then(setOpts).catch((e) => setProblem(errorText(e)));
  }, [id, take]);
  // while ClipForge works on it, follow the work
  const working = !!story?.working;
  useEffect(() => {
    if (!working) return;
    const t = window.setInterval(() => {
      textStories.get(id).then((s) => {
        if (!s.working) typed.current = false;  // what was written comes in
        take(s);
      }).catch(() => {});
    }, 1200);
    return () => window.clearInterval(t);
  }, [working, id, take]);

  const change = async (patch: StoryPatch) => {
    setSaving(true);
    try {
      take(await textStories.change(id, patch));
      return true;
    } catch (e) {
      toast(errorText(e), true);
      return false;
    } finally {
      setSaving(false);
    }
  };
  // the text fields are saved a moment after typing stops, and when leaving the field
  const textTimer = useRef<number | undefined>(undefined);
  const saveText = useCallback(async (now: { title: string; script: string; name: string }) => {
    window.clearTimeout(textTimer.current);
    setSaving(true);
    try {
      const s = await textStories.change(id, now);
      typed.current = false;
      take(s);
    } catch (e) {
      toast(errorText(e), true);
    } finally {
      setSaving(false);
    }
  }, [id, take]);
  const typing = (next: Partial<{ title: string; script: string; name: string }>) => {
    typed.current = true;
    const now = { title, script, name, ...next };
    if (next.title !== undefined) setTitle(next.title);
    if (next.script !== undefined) setScript(next.script);
    if (next.name !== undefined) setName(next.name);
    window.clearTimeout(textTimer.current);
    textTimer.current = window.setTimeout(() => void saveText(now), 900);
  };
  const flush = () => {
    if (typed.current) void saveText({ title, script, name });
  };

  const act = async (what: "preview" | "export" | "stop") => {
    if (typed.current) await saveText({ title, script, name });
    try {
      take(await textStories[what](id));
    } catch (e) {
      toast(errorText(e), true);
    }
  };

  if (problem && !story) {
    return (
      <div className="page narrow stories">
        <PageHead kind="Make" title="Text story"
          crumbs={[{ label: "Text Stories", href: "#/stories" }, { label: "Story" }]} />
        <Banner tone="bad" title="This story could not be opened">{problem}</Banner>
      </div>
    );
  }
  if (!story || !opts) {
    return (
      <div className="page narrow stories" aria-busy="true">
        <Skel className="skel-block" /><Skel className="skel-block" />
      </div>
    );
  }
  const words = script.split(/\s+/).filter(Boolean).length + title.split(/\s+/).filter(Boolean).length;
  const locked = story.working;
  const progress = story.job ? Math.round(story.job.progress * 100) : 0;

  return (
    <div className="page narrow stories">
      <PageHead kind="Text story" title={story.name}
        crumbs={[{ label: "Text Stories", href: "#/stories" }, { label: story.name }]}
        sub={`${words} words · about ${clock(story.seconds)} read aloud${saving ? " · saving…" : ""}`} />

      {story.working && (
        <div className="story-work" role="status" aria-live="polite">
          <span className="inline-spinner" aria-hidden="true" />
          <span className="grow"><b>{story.job?.message || story.message}</b>
            <span className="story-bar" aria-hidden="true"><i style={{ width: `${Math.max(4, progress)}%` }} /></span>
          </span>
          <button type="button" className="btn btn-small" onClick={() => void act("stop")}>
            <Icon name="stop" />Stop
          </button>
        </div>
      )}
      {!story.working && story.error && <Banner tone="bad" title="That did not work">{story.error}</Banner>}
      {!story.working && !story.error && story.message && <Banner tone="info">{story.message}</Banner>}

      <Step n={1} id={`${ids}-script`} title="Script" done={story.steps.script}>
        <label className="field"><span>Title <span className="muted">(read first, shown on a card)</span></span>
          <input type="text" value={title} maxLength={opts.limits.max_title} disabled={locked}
            placeholder="My neighbour kept stealing my packages" onChange={(e) => typing({ title: e.target.value })}
            onBlur={flush} /></label>
        <label className="field"><span>Story</span>
          <textarea className="story-script" rows={10} value={script} disabled={locked} spellCheck
            placeholder={"Every Friday a package went missing from my porch.\n\nSo I mailed myself a box of glitter…"}
            onChange={(e) => typing({ script: e.target.value })} onBlur={flush} /></label>
        <p className="small muted">{words} words of {opts.limits.max_words} · about {clock(story.seconds)}. A blank
          line
          starts a new paragraph; the narrator pauses at full stops and commas.</p>
        <Writer story={story} opts={opts} locked={locked} onStory={(s) => { typed.current = false; take(s); }} />
        <label className="field story-name"><span>Name (optional)</span>
          <input type="text" value={name} maxLength={120} disabled={locked} placeholder="Named from the title"
            onChange={(e) => typing({ name: e.target.value })} onBlur={flush} /></label>
      </Step>

      <Step n={2} id={`${ids}-voice`} title="Voice" done={story.narration.ready}>
        <VoicePicker story={story} opts={opts} locked={locked} audio={audio} sample={title || script}
          onChange={(voice) => void change({ voice })} onOpts={setOpts}
          onRules={(pronunciations) => change({ pronunciations })} />
      </Step>

      <Step n={3} id={`${ids}-bg`} title="Background" done={story.steps.background}>
        <Backgrounds story={story} opts={opts} locked={locked} onChange={(backgrounds) => change({ backgrounds })}
          onStory={take} />
      </Step>

      <Step n={4} id={`${ids}-cap`} title="On-screen text" done={story.steps.script}>
        <div className="story-rows">
          <div className="story-row-pick"><span className="label" id={`${ids}-cs`}>Caption style</span>
            <Segmented labelledBy={`${ids}-cs`} value={story.captions.style} disabled={locked}
              onChange={(style) => void change({ captions: { style } })}
              options={opts.captions.styles.map((c) => ({ value: c.id, label: c.label }))} /></div>
          <div className="story-row-pick"><span className="label" id={`${ids}-cp`}>Where</span>
            <Segmented labelledBy={`${ids}-cp`} value={story.captions.position} disabled={locked}
              onChange={(position) => void change({ captions: { position } })}
              options={opts.captions.positions.map((c) => ({ value: c.id, label: c.label }))} /></div>
          <div className="story-row-pick"><span className="label" id={`${ids}-cz`}>Size</span>
            <Segmented labelledBy={`${ids}-cz`} value={story.captions.size} disabled={locked}
              onChange={(size) => void change({ captions: { size } })}
              options={opts.captions.sizes.map((c) => ({ value: c.id, label: c.label }))} /></div>
        </div>
        <p className="small muted">The word being said lights up. The title shows on a white card while it is read.</p>
      </Step>

      <Step n={5} id={`${ids}-pre`} title="Preview" done={story.made.preview.current}>
        <div className="story-out">
          {story.made.preview.ready ? (
            <video className="story-video" src={story.made.preview.url} controls playsInline preload="metadata"
              aria-label="Preview of the story" />
          ) : (
            <div className="story-video empty-video">
              <Icon name="video" /><span className="small muted">No preview yet</span>
            </div>
          )}
          <div className="stack-3">
            <p className="small muted">A small, quick version to check the voice, the timing and the background.</p>
            {story.made.preview.ready && !story.made.preview.current && (
              <p className="small story-stale"><Icon name="alert" className="sm" />Made before your last changes.</p>)}
            {story.narration.fallback && <p className="small muted">{story.narration.fallback}</p>}
            <button type="button" className={`btn${story.made.preview.current ? "" : " btn-primary"}`}
              disabled={locked || !story.steps.script || !story.steps.background}
              onClick={() => void act("preview")}><Icon name="play" />
              {story.made.preview.current ? "Preview is up to date" : "Make the preview"}</button>
            {!story.steps.background && <span className="small muted">Choose a background first.</span>}
          </div>
        </div>
      </Step>

      <Step n={6} id={`${ids}-exp`} title="Export" done={story.made.export.current}>
        <div className="stack-3">
          <p className="small muted">
            1080 × 1920, 30 frames a second, MP4: ready for TikTok, YouTube Shorts and Reels.
          </p>
          <div className="row wrap">
            <button type="button" className={`btn btn-large${story.made.export.current ? "" : " btn-primary"}`}
              disabled={locked || !story.steps.script || !story.steps.background} onClick={() => void act("export")}>
              <Icon name="spark" />{story.made.export.current ? "Exported" : "Export the video"}
            </button>
            {story.made.export.ready && (
              <a className={`btn${story.made.export.current ? "" : " btn-quiet"}`}
                href={`${story.made.export.url}&download=true`} download>
                <Icon name="download" />Download{story.made.export.current ? "" : " (made before your last changes)"}
              </a>
            )}
            {story.made.export.current && (
              <OpenInEditor id={story.id} projectId={story.project_id} />
            )}
          </div>
          {story.narration.rule && <p className="small muted">The voice's licence: {story.narration.rule}</p>}
        </div>
      </Step>

      <DeleteStory id={story.id} />
    </div>
  );
}

function Writer({ story, opts, locked, onStory }: { story: Story; opts: StoryOptions; locked: boolean;
  onStory: (s: Story) => void }) {
  const ids = useId();
  const [topic, setTopic] = useState("");
  const [tone, setTone] = useState(opts.tones[0]?.id || "drama");
  const [length, setLength] = useState("standard");
  const [ask, setAsk] = useState("");
  const [busy, setBusy] = useState(false);
  const has = story.script.trim().length > 0;
  if (!opts.writer.configured) {
    return (
      <Banner tone="neutral" title="ClipForge AI can write and revise stories"
        actions={<a className="btn btn-small" href={opts.links.ai}><Icon name="settings" />Set up ClipForge AI</a>}>
        Set it up once in Settings (a free model on this computer works), or keep writing your own.
      </Banner>
    );
  }
  const go = async (body: { topic?: string; tone?: string; length?: string; change?: string }) => {
    setBusy(true);
    try {
      onStory(await textStories.write(story.id, body));
      setAsk("");
    } catch (e) {
      toast(errorText(e), true);
    } finally {
      setBusy(false);
    }
  };
  const where = opts.writer.local ? "on this computer" : `online (what you type here is sent to ${opts.writer.label})`;
  return (
    <div className="story-writer">
      <b className="small"><Icon name="spark" className="sm" />ClipForge AI</b>
      {has ? (
        <div className="row wrap">
          <label className="field grow"><span className="sr-only">What to change</span>
            <input type="text" value={ask} maxLength={400} disabled={locked || busy}
              placeholder="Make the ending scarier"
              onChange={(e) => setAsk(e.target.value)} /></label>
          <button type="button" className="btn" disabled={locked || busy || !ask.trim()}
            onClick={() => void go({ change: ask.trim() })}><Icon name="edit" />Revise</button>
        </div>
      ) : null}
      <details open={!has}>
        <summary className="small">{has ? "Or write a new story from a topic" : "Write it for me"}</summary>
        <div className="stack-3 story-writer-new">
          <label className="field"><span>Topic</span>
            <input type="text" value={topic} maxLength={300} disabled={locked || busy}
              placeholder="A neighbour who keeps stealing packages"
              onChange={(e) => setTopic(e.target.value)} /></label>
          <div className="row wrap">
            <label className="field"><span>Kind of story</span>
              <select value={tone} disabled={locked || busy} onChange={(e) => setTone(e.target.value)}>
                {opts.tones.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
              </select></label>
            <div className="field"><span id={`${ids}-len`}>Length</span>
              <Segmented labelledBy={`${ids}-len`} value={length} onChange={setLength} disabled={locked || busy}
                options={opts.lengths.map((l) => ({ value: l.id, label: l.label }))} /></div>
          </div>
          <button type="button" className="btn" disabled={locked || busy || !topic.trim()}
            onClick={() => void go({ topic: topic.trim(), tone, length })}>
            <Icon name="spark" />{has ? "Write a new story (replaces this one)" : "Write it for me"}</button>
        </div>
      </details>
      <span className="small muted">Written by {opts.writer.label} {where}.
        {story.writer.notes && story.writer.notes.length > 0 ? ` ${story.writer.notes.join(" ")}` : ""}</span>
    </div>
  );
}

type Audio = ReturnType<typeof useAudio>;

function VoicePicker({ story, opts, locked, audio, sample, onChange, onRules, onOpts }: { story: Story;
  opts: StoryOptions; locked: boolean; audio: Audio; sample: string; onChange: (v: Partial<StoryVoice>) => void;
  onRules: (r: Story["pronunciations"]) => Promise<boolean>; onOpts: (o: StoryOptions) => void }) {
  const ids = useId();
  const v = story.voice;
  const [rules, setRules] = useState(story.pronunciations);
  useEffect(() => setRules(story.pronunciations), [story.pronunciations]);
  const words = sample.split(/\s+/).slice(0, 24).join(" ");
  const favourite = async (scope: string, on: boolean, voiceId = v.voice, quiet = false) => {
    try {
      const keep = { voice: voiceId, speed: v.speed, tone: v.tone, style: v.style };
      const r = await textStories.setFavourite(scope, on ? keep : null);
      onOpts({ ...opts, favourites: r.favourites });
      if (!quiet) toast(on ? "Saved as a favourite." : "Favourite removed.");
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  const styleFav = opts.favourites[`style:${v.style}`];
  const storyFav = opts.favourites[`project:${story.id}`];
  const styleName = opts.styles.find((s) => s.id === v.style)?.name || "this style";
  // the style alone: ClipForge keeps this story's voice when "Keep this voice for this story" is on, else brings the
  // style's favourite voice (voice_styles.for_style)
  const pickStyle = (style: string) => onChange({ style });
  const pickVoice = (voiceId: string) => {
    onChange({ voice: voiceId });
    if (storyFav) void favourite(`project:${story.id}`, true, voiceId, true); // the kept voice follows your choice
  };
  return (
    <div className="stack-4">
      <div className="style-grid" role="radiogroup" aria-labelledby={`${ids}-styles`}>
        <span className="sr-only" id={`${ids}-styles`}>Voice style</span>
        {opts.styles.map((s) => (
          <div key={s.id} className={`style-card${v.style === s.id ? " on" : ""}`}>
            <label>
              <input type="radio" name={`${ids}-style`} checked={v.style === s.id} disabled={locked}
                onChange={() => pickStyle(s.id)} />
              <b>{s.name}</b><span className="small muted">{s.about}</span>
            </label>
            <button type="button" className="btn btn-small hear-btn" aria-label={`Hear ${s.name}`}
              onClick={() => void audio.play(`style:${s.id}`,
                { voice: v.voice, speed: s.speed, tone: s.tone, text: words })}>
              {audio.playing === `style:${s.id}` ? <><Icon name="stop" />Stop</> : <><Icon name="play" />Hear</>}
            </button>
          </div>
        ))}
      </div>
      <div className="story-rows">
        <label className="story-row-pick"><span className="label">Voice</span>
          <select value={v.voice} disabled={locked} onChange={(e) => pickVoice(e.target.value)}>
            {opts.voices.map((x) => (
              <option key={x.id} value={x.id}>{x.about ? `${x.name} · ${x.about}` : x.name}</option>
            ))}
          </select></label>
        <label className="story-row-pick">
          <span className="label">Speed <span className="muted tnum">{v.speed.toFixed(2)}×</span></span>
          <input type="range" min={opts.speed_range[0]} max={opts.speed_range[1]} step={0.02} value={v.speed}
            disabled={locked} onChange={(e) => onChange({ speed: Number(e.target.value) })} /></label>
        <label className="story-row-pick"><span className="label">Tone <span className="muted tnum">
          {v.tone > 0 ? `+${v.tone}` : v.tone} semitones</span></span>
          <input type="range" min={opts.tone_range[0]} max={opts.tone_range[1]} step={0.5} value={v.tone}
            disabled={locked} onChange={(e) => onChange({ tone: Number(e.target.value) })} /></label>
      </div>
      <div className="row wrap">
        <button type="button" className="btn" onClick={() => void audio.play("mine", { ...v, text: words })}>
          {audio.playing === "mine" ? <><Icon name="stop" />Stop</> : <><Icon name="play" />Hear your story's start</>}
        </button>
        <label className="choice"><input type="checkbox" checked={!!styleFav && styleFav.voice === v.voice}
          onChange={(e) => void favourite(`style:${v.style}`, e.target.checked)} />
          <span><Icon name="star" className="sm" />Favourite for {styleName}</span></label>
        <label className="choice"><input type="checkbox" checked={!!storyFav}
          onChange={(e) => void favourite(`project:${story.id}`, e.target.checked)} />
          <span>Keep this voice for this story</span></label>
      </div>
      <p className="small muted">{storyFav ? "This story keeps its voice when you pick another style; the style still "
        + "sets the speed and tone." : "Picking a style brings its favourite voice when it has one."}</p>
      <p className="small muted">Tone moves the voice higher or lower and works with every voice. Only voices ClipForge
        may use are listed: the voices of this computer and the voice engine you set up.</p>
      <details>
        <summary className="small">Pronunciations{rules.length ? ` (${rules.length})` : ""}</summary>
        <div className="stack-2 story-rules">
          {rules.map((r, i) => (
            <div key={i} className="row">
              <input type="text" aria-label="Written word" value={r.word} maxLength={60} disabled={locked}
                onChange={(e) => setRules(rules.map((x, k) => (k === i ? { ...x, word: e.target.value } : x)))} />
              <span aria-hidden="true">→</span>
              <input type="text" aria-label="Say it as" value={r.say} maxLength={60} disabled={locked}
                onChange={(e) => setRules(rules.map((x, k) => (k === i ? { ...x, say: e.target.value } : x)))} />
              <button type="button" className="btn btn-small btn-icon" aria-label={`Remove ${r.word || "this rule"}`}
                disabled={locked} onClick={() => setRules(rules.filter((_, k) => k !== i))}><Icon name="x" /></button>
            </div>
          ))}
          <div className="row wrap">
            <button type="button" className="btn btn-small" disabled={locked}
              onClick={() => setRules([...rules, { word: "", say: "" }])}><Icon name="plus" />Add a word</button>
            <button type="button" className="btn btn-small" disabled={locked}
              onClick={() => void onRules(rules.filter((r) => r.word.trim() && r.say.trim()))}>
              <Icon name="check" />Save
            </button>
          </div>
          <span className="small muted">
            For example GIF → jif. The captions still show the word as you wrote it.
          </span>
        </div>
      </details>
    </div>
  );
}

const MAX_SHOWN = 6;

/** The list with item i moved one place up. */
function swapUp<T>(all: T[], i: number): T[] {
  return all.map((x, k) => (k === i - 1 ? all[i] : k === i ? all[i - 1] : x));
}

/** One of ClipForge's own backgrounds as a CSS gradient (its colours). */
function swatch(opts: StoryOptions, builtin?: string): string | undefined {
  const colours = opts.builtins.find((x) => x.id === builtin)?.colors;
  return colours ? `linear-gradient(160deg, ${colours.join(", ")})` : undefined;
}

function Backgrounds({ story, opts, locked, onChange, onStory }: { story: Story; opts: StoryOptions; locked: boolean;
  onChange: (b: Partial<Background>[]) => Promise<boolean>; onStory: (s: Story) => void }) {
  const [choices, setChoices] = useState<BackgroundChoice[] | null>(null);
  const [replacing, setReplacing] = useState<number | null>(null);
  const [upload, setUpload] = useState("");
  const file = useRef<HTMLInputElement>(null);
  // the clip being sent, for Cancel upload: stop sending, then the server deletes what it received
  const sending = useRef<{ ctl: AbortController; id: string; file: File; canceled: boolean } | null>(null);
  const list = story.backgrounds;
  const plain = (b: Background): Partial<Background> => ({ id: b.id, asset_id: b.asset_id, builtin: b.builtin,
    in_s: b.in_s, out_s: b.out_s, loop: b.loop, focus_x: b.focus_x, focus_y: b.focus_y, why: b.why });
  const put = (next: Partial<Background>[]) => void onChange(next);
  const edit = (i: number, patch: Partial<Background>) =>
    put(list.map((b, k) => (k === i ? { ...plain(b), ...patch } : plain(b))));
  const add = (b: Partial<Background>) => {
    if (replacing !== null) {
      put(list.map((x, k) => (k === replacing ? { ...b, loop: x.loop, focus_x: 0.5, focus_y: 0.5 } : plain(x))));
      setReplacing(null);
    } else {
      // the new clip goes last and loops to the end
      put([...list.map((x) => ({ ...plain(x), loop: false })), { ...b, loop: true }]);
    }
    setChoices(null);
  };
  const browse = async (i: number | null) => {
    setReplacing(i);
    try {
      setChoices((await textStories.backgroundChoices(story.id)).videos);
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  const auto = async () => {
    try {
      onStory(await textStories.pickBackgrounds(story.id));
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  const sendFile = async (f: File) => {
    setUpload(`Uploading ${f.name}…`);
    const now = { ctl: new AbortController(), id: "", file: f, canceled: false };
    sending.current = now;
    try {
      const asset = await uploadFile(f, (p) => {
        if (p.id) now.id = p.id;
        setUpload(p.size ? `Uploading ${f.name}: ${Math.round((p.received / p.size) * 100)}%` : "");
      }, now.ctl.signal);
      if (now.canceled) return;   // it finished while Cancel was pressed: the server's answer decides (below)
      if (asset.kind !== "video") throw new Error("Choose a video file.");
      add({ asset_id: asset.id, in_s: 0, out_s: asset.duration || 10, focus_x: 0.5, focus_y: 0.5,
        why: "You uploaded it." });
    } catch (e) {
      if (!now.canceled) toast(errorText(e), true);
    } finally {
      if (sending.current === now) sending.current = null;
      if (!now.canceled) setUpload("");
    }
  };
  const cancelSend = async () => {
    const now = sending.current;
    if (!now) return;
    now.canceled = true;
    now.ctl.abort();
    setUpload("Canceling the upload…");
    try {
      const out = now.id ? await cancelUpload(now.id, now.file) : { canceled: true, status: "", message: "" };
      toast(out.canceled ? "Upload canceled. Nothing was kept; your file is still on this computer."
        : out.message || "It had already finished uploading, so it was kept in your videos.");
    } catch (e) {
      toast(`Could not cancel: ${errorText(e)}`, true);
    } finally {
      setUpload("");
    }
  };
  return (
    <div className="stack-4">
      {list.length === 0 && <p className="small muted">Gameplay, parkour, satisfying clips or anything with steady
        motion works best. The background's own sound is left out, so the voice stays clear.</p>}
      {list.map((b, i) => {
        const length = b.duration || 0;
        return (
          <div key={b.id} className="bg-row">
            {b.asset_id && b.has_thumbnail ? (
              <img className="bg-thumb" src={`/api/assets/${encodeURIComponent(b.asset_id)}/thumbnail`} alt=""
              style={{ objectPosition: `${b.focus_x * 100}% ${b.focus_y * 100}%` }} />
            ) : <span className="bg-thumb" style={{ background: swatch(opts, b.builtin) }} />}
            <div className="stack-2 grow">
              <b className="small">{b.filename || b.name}{b.missing ? " (deleted)" : ""}</b>
              {b.why && <span className="small muted">{b.why}</span>}
              {b.asset_id ? (
                <div className="row wrap bg-trim">
                  <label className="small">From <input type="number" min={0} max={Math.max(0, length - 1)} step={0.5}
                    value={b.in_s} disabled={locked}
                    onChange={(e) => edit(i, { in_s: Number(e.target.value) })} /> s</label>
                  <label className="small">to <input type="number" min={b.in_s + 1} max={length || undefined} step={0.5}
                    value={b.out_s} disabled={locked}
                    onChange={(e) => edit(i, { out_s: Number(e.target.value) })} /> s</label>
                  <span className="small muted">of {clock(length)}</span>
                </div>
              ) : null}
              <div className="row wrap">
                <label className="small bg-pos">Position
                  <input type="range" min={0} max={1} step={0.05} value={b.focus_x}
                  disabled={locked} aria-label="Which part of the picture shows, left to right"
                  onChange={(e) => edit(i, { focus_x: Number(e.target.value) })} /></label>
                <label className="choice small"><input type="checkbox" checked={b.loop} disabled={locked}
                  onChange={(e) => edit(i, { loop: e.target.checked })} /><span>Loop to the end</span></label>
              </div>
            </div>
            <div className="bg-actions">
              <button type="button" className="btn btn-small btn-icon" aria-label="Move up" disabled={locked || i === 0}
                onClick={() => put(swapUp(list.map(plain), i))}>
                <Icon name="chev" className="up" /></button>
              <button type="button" className="btn btn-small" disabled={locked} onClick={() => void browse(i)}>
                Replace
              </button>
              <button type="button" className="btn btn-small btn-icon" aria-label="Remove" disabled={locked}
                onClick={() => put(list.filter((_, k) => k !== i).map(plain))}><Icon name="trash" /></button>
            </div>
          </div>
        );
      })}
      {list.some((b, i) => b.loop && i < list.length - 1) && (
        <p className="small muted">A looping clip plays until the story ends, so the clips after it are not shown.</p>)}
      <div className="row wrap">
        <button type="button" className="btn" disabled={locked} onClick={() => void auto()}>
          <Icon name="spark" />Let ClipForge pick
        </button>
        <button type="button" className="btn" disabled={locked || !!upload} onClick={() => file.current?.click()}>
          <Icon name="upload" />Upload a clip</button>
        <button type="button" className="btn" disabled={locked} onClick={() => void browse(null)}>
          <Icon name="folder" />From my videos
        </button>
        <input ref={file} type="file" accept="video/*" hidden onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) void sendFile(f);
        }} />
      </div>
      {upload && <p className="small row wrap" role="status">{upload}
        {sending.current && !sending.current.canceled && <button type="button" className="btn btn-small"
          onClick={() => void cancelSend()}><Icon name="x" />Cancel upload</button>}</p>}
      {choices && (
        <div className="bg-choices" role="group" aria-label={replacing !== null ? "Replace with" : "Add a background"}>
          {choices.length === 0 && <span className="small muted">No videos of yours can be used yet (they need to run 5
            seconds or more). Upload a clip, or use one of ClipForge's.</span>}
          {choices.slice(0, MAX_SHOWN * 2).map((c) => (
            <button key={c.asset_id} type="button" className="bg-choice"
              onClick={() => add({ asset_id: c.asset_id, in_s: 0, out_s: c.duration, focus_x: 0.5, focus_y: 0.5,
                why: c.why })}>
              <img src={`/api/assets/${encodeURIComponent(c.asset_id)}/thumbnail`} alt="" loading="lazy" />
              <b className="small">{c.filename}</b><span className="small muted">{clock(c.duration)} · {c.why}</span>
            </button>
          ))}
          {opts.builtins.map((b) => (
            <button key={b.id} type="button" className="bg-choice"
              onClick={() => add({ builtin: b.id, in_s: 0, out_s: 20, focus_x: 0.5, focus_y: 0.5,
                why: "A moving colour background ClipForge draws." })}>
              <span className="bg-swatch" style={{ background: `linear-gradient(160deg, ${b.colors.join(", ")})` }} />
              <b className="small">{b.name}</b><span className="small muted">Made by ClipForge</span>
            </button>
          ))}
          <button type="button" className="btn btn-small" onClick={() => { setChoices(null); setReplacing(null); }}>
            Close
          </button>
        </div>
      )}
    </div>
  );
}

function OpenInEditor({ id, projectId }: { id: string; projectId: string }) {
  const [busy, setBusy] = useState(false);
  if (projectId) return <a className="btn" href={`#/video/${projectId}`}><Icon name="edit" />Open in the editor</a>;
  return (
    <button type="button" className="btn" disabled={busy} onClick={async () => {
      setBusy(true);
      try {
        const r = await textStories.openInEditor(id);
        navigate(`video/${r.video_id}`);
      } catch (e) {
        toast(errorText(e), true);
        setBusy(false);
      }
    }}><Icon name="edit" />Open in the editor</button>
  );
}

function DeleteStory({ id }: { id: string }) {
  const [sure, setSure] = useState(false);
  return (
    <div className="row wrap story-delete">
      {!sure ? (
        <button type="button" className="btn btn-quiet btn-small" onClick={() => setSure(true)}>
          <Icon name="trash" />Delete this story
        </button>
      )
        : <>
          <span className="small">Delete the story, its voice and its videos? Your background clips stay.</span>
          <button type="button" className="btn btn-small btn-danger" onClick={async () => {
            try {
              await textStories.remove(id);
              navigate("stories");
            } catch (e) {
              toast(errorText(e), true);
            }
          }}>Delete</button>
          <button type="button" className="btn btn-small" onClick={() => setSure(false)}>Keep it</button>
        </>}
    </div>
  );
}
