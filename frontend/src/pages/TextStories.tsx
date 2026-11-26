import { CSSProperties, Fragment, ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";
import { errorText } from "../api";
import { Banner, EmptyState, Icon, PageHead, Segmented, Skel, toast } from "../components/ui";
import { navigate } from "../router";
import { cancelUpload, MediaResult, studio, uploadFile } from "../studio";
import {
  Background, BackgroundChoice, ChatPatch, clock, PersonVoice, Story, StoryChat, StoryKind, StoryListItem,
  StoryOptions, StoryPatch, StoryVoice, textStories,
} from "../textStories";
import "./stories.css";

/**
 * Text Stories (+ Make → Make a text story): a text-message story (a phone chat that appears a bubble at a time, each
 * message read aloud in its sender's voice, the way they look on TikTok) or a narrated story (read aloud with big
 * captions). Write or paste it, or let ClipForge AI write and revise it (up to ten minutes); choose the voices; put
 * your own clips behind it (trimmed, looped, moved in the frame) or let ClipForge pick; preview it small and fast,
 * then export the full video. The work runs in ClipForge's job line, so Stop always works and a restart carries on.
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
  const start = async (kind: StoryKind) => {
    setBusy(true);
    try {
      const s = await textStories.create({ kind });
      navigate(`stories/${s.id}`);
    } catch (e) {
      toast(errorText(e), true);
      setBusy(false);
    }
  };
  const newButton = (
    <div className="row wrap">
      <button type="button" className="btn btn-primary btn-large" disabled={busy} onClick={() => void start("chat")}>
        <Icon name="chat" />New text-message story
      </button>
      <button type="button" className="btn btn-large" disabled={busy} onClick={() => void start("narrated")}>
        <Icon name="story" />New narrated story
      </button>
    </div>
  );
  return (
    <div className="page narrow stories">
      <PageHead kind="Make" title="Text Stories" actions={newButton}
        sub={"A text-message chat that pops up a bubble at a time, each message read aloud, or a story read aloud "
          + "with big captions; over satisfying footage, gameplay or any background. Up to ten minutes."} />
      {problem && <Banner tone="bad" title="Your stories could not be loaded">{problem}</Banner>}
      {!list && !problem && (
        <div className="stack-3" aria-hidden="true"><Skel className="skel-block" /><Skel className="skel-block" /></div>
      )}
      {list && list.length === 0 && (
        <EmptyState icon="story" title="No text stories yet">
          Start a text-message story: paste the chat (Sienna: Be honest. / Me: …) or let ClipForge AI write one.
          Cooking, cutting, gameplay or other satisfying clips go behind it, or ClipForge picks.
        </EmptyState>
      )}
      {list && list.length > 0 && (
        <ul className="story-list">
          {list.map((s) => (
            <li key={s.id}>
              <a href={`#/stories/${s.id}`} className="story-row">
                <Icon name={s.kind === "chat" ? "chat" : "story"} />
                <span className="grow"><b>{s.name}</b>
                  <span className="small muted">
                    {s.kind === "chat" ? `Text messages · ${s.messages} messages` : `Narrated · ${s.words} words`}
                    {" · "}{STATUS[s.status] || s.status}{s.exported ? " · exported" : ""}
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
  const chat = story.kind === "chat" ? story.chat : null;
  const words = chat ? story.words
    : script.split(/\s+/).filter(Boolean).length + title.split(/\s+/).filter(Boolean).length;
  const locked = story.working;
  const progress = story.job ? Math.round(story.job.progress * 100) : 0;
  const changeChat = (patch: ChatPatch) => change({ chat: patch });
  const sub = chat ? `Text-message story · ${chat.messages.length} messages · about ${clock(story.seconds)}`
    : `${words} words · about ${clock(story.seconds)} read aloud`;

  return (
    <div className="page narrow stories">
      <PageHead kind="Text story" title={story.name}
        crumbs={[{ label: "Text Stories", href: "#/stories" }, { label: story.name }]}
        sub={`${sub}${saving ? " · saving…" : ""}`} />

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

      {chat ? <>
        <Step n={1} id={`${ids}-chat`} title="Chat" done={story.steps.script}>
          <div className="chat-write">
            <div className="stack-3 grow">
              <label className="field"><span>Messages <span className="muted">(one a line: name, colon,
                message)</span></span>
                <textarea className="story-script chat-script" rows={16} value={script} disabled={locked} spellCheck
                  placeholder={CHAT_EXAMPLE} onChange={(e) => typing({ script: e.target.value })} onBlur={flush} />
              </label>
              <p className="small muted">{chat.messages.length} of {opts.chat.limits.max_messages} messages
                · {words} words · about {clock(story.seconds)} (up to {clock(opts.chat.limits.max_seconds)}).</p>
              <p className="small muted">Me (or I) is whose phone it is: blue bubbles on the right. Everyone else is
                grey on the left; with three or more people it is a group chat with names. A line without a name
                adds a message from the last person.</p>
            </div>
            <ChatPreview chat={chat} opts={opts} />
          </div>
          <Writer story={story} opts={opts} locked={locked} onStory={(s) => { typed.current = false; take(s); }} />
          <label className="field story-name"><span>Name (optional)</span>
            <input type="text" value={name} maxLength={120} disabled={locked} placeholder="Named from the chat"
              onChange={(e) => typing({ name: e.target.value })} onBlur={flush} /></label>
        </Step>

        <Step n={2} id={`${ids}-people`} title="People and voices" done={story.steps.voice}>
          <ChatPeople story={story} chat={chat} opts={opts} locked={locked} audio={audio} onChat={changeChat}
            onRules={(pronunciations) => change({ pronunciations })} />
        </Step>

        <Step n={3} id={`${ids}-bg`} title="Background" done={story.steps.background}>
          <Backgrounds story={story} opts={opts} locked={locked} onChange={(backgrounds) => change({ backgrounds })}
            onStory={take} />
        </Step>

        <Step n={4} id={`${ids}-look`} title="Look and sound" done={story.steps.script}>
          <ChatLook chat={chat} opts={opts} locked={locked} onChat={changeChat} />
        </Step>
      </> : <>
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
      </>}

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
            <p className="small muted">A small, quick version to check the {chat ? "voices" : "voice"}, the timing
              and the background.</p>
            {chat && opts.chat.emoji_note && <p className="small muted">{opts.chat.emoji_note}</p>}
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
  const chat = story.kind === "chat";
  const tones = chat ? opts.chat.tones : opts.tones;
  const lengths = chat ? opts.chat.lengths : opts.lengths;
  const noun = chat ? "chat" : "story";
  const [topic, setTopic] = useState("");
  const [tone, setTone] = useState(tones[0]?.id || "drama");
  const [length, setLength] = useState("standard");
  const [ask, setAsk] = useState("");
  const [busy, setBusy] = useState(false);
  const has = story.script.trim().length > 0;
  if (!opts.writer.configured) {
    return (
      <Banner tone="neutral" title={`ClipForge AI can write and revise ${chat ? "chats" : "stories"}`}
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
              placeholder={chat ? "Make her replies meaner and add a twist at the end" : "Make the ending scarier"}
              onChange={(e) => setAsk(e.target.value)} /></label>
          <button type="button" className="btn" disabled={locked || busy || !ask.trim()}
            onClick={() => void go({ change: ask.trim() })}><Icon name="edit" />Revise</button>
        </div>
      ) : null}
      <details open={!has}>
        <summary className="small">{has ? `Or write a new ${noun} from a topic` : "Write it for me"}</summary>
        <div className="stack-3 story-writer-new">
          <label className="field"><span>Topic</span>
            <input type="text" value={topic} maxLength={300} disabled={locked || busy}
              placeholder={chat ? "My best friend texts me by mistake about my surprise party"
                : "A neighbour who keeps stealing packages"}
              onChange={(e) => setTopic(e.target.value)} /></label>
          <div className="row wrap">
            <label className="field"><span>Kind of {noun}</span>
              <select value={tone} disabled={locked || busy} onChange={(e) => setTone(e.target.value)}>
                {tones.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
              </select></label>
            <div className="field"><span id={`${ids}-len`}>Length</span>
              <Segmented labelledBy={`${ids}-len`} value={length} onChange={setLength} disabled={locked || busy}
                options={lengths.map((l) => ({ value: l.id, label: l.label }))} /></div>
          </div>
          <button type="button" className="btn" disabled={locked || busy || !topic.trim()}
            onClick={() => void go({ topic: topic.trim(), tone, length })}>
            <Icon name="spark" />{has ? `Write a new ${noun} (replaces this one)` : "Write it for me"}</button>
          {length === lengths[lengths.length - 1]?.id && <span className="small muted">A long {noun} is written a
            part at a time, so it takes a few minutes; Stop keeps what was there before.</span>}
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
      <Pronunciations story={story} locked={locked} onRules={onRules} />
    </div>
  );
}

/** Words the voice should say another way (GIF → jif); the captions and bubbles still show them as written. */
function Pronunciations({ story, locked, onRules }: { story: Story; locked: boolean;
  onRules: (r: Story["pronunciations"]) => Promise<boolean> }) {
  const [rules, setRules] = useState(story.pronunciations);
  useEffect(() => setRules(story.pronunciations), [story.pronunciations]);
  return (
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
            For example GIF → jif. {story.kind === "chat" ? "The bubbles" : "The captions"} still show the word as
            you wrote it.
          </span>
        </div>
      </details>
  );
}

const CHAT_EXAMPLE = "Sienna: Be honest. Did you eat my leftovers?\nMe: Which leftovers\n"
  + "Sienna: The pasta. With my NAME on it 😤\nMe: There was a name on it?";
const PREVIEW_MESSAGES = 80;   // the page's chat shows this many; the video shows them all

/** The chat as the video shows it (the colours of the look chosen): the header with the name and the unread number,
 * then the bubbles, theirs grey on the left and whose phone it is on the right. */
function ChatPreview({ chat, opts }: { chat: StoryChat; opts: StoryOptions }) {
  const t = opts.chat.themes.find((x) => x.id === chat.theme) || opts.chat.themes[0];
  const look = t ? {
    "--c-card": t.card, "--c-head": t.head, "--c-rule": t.rule, "--c-them": t.them, "--c-them-text": t.them_text,
    "--c-me": t.me, "--c-me-text": t.me_text, "--c-name": t.name, "--c-accent": t.accent, "--c-muted": t.muted,
  } as CSSProperties : undefined;
  const shown = chat.messages.slice(0, PREVIEW_MESSAGES);
  const name = chat.shown_contact || "Unknown";
  return (
    <figure className="chat-phone" style={look} aria-label="How the chat looks in the video">
      <div className="chat-head" aria-hidden="true">
        <span className="chat-back"><Icon name="back" />{chat.badge > 0 && <b>{chat.badge}</b>}</span>
        <Icon name="video" className="chat-cam" />
        <span className="chat-avatar">{Array.from(name)[0]?.toUpperCase()}</span>
        <span className="chat-name">{name}<Icon name="chev" /></span>
      </div>
      <div className="chat-body">
        {shown.length === 0 && <p className="chat-empty">The messages show up here as you write them.</p>}
        {shown.map((m, i) => {
          const first = i === 0 || shown[i - 1].who !== m.who;
          const last = i === shown.length - 1 || shown[i + 1].who !== m.who;
          return (
            <Fragment key={i}>
              {m.label && m.side === "them" && <span className="chat-sender">{m.label}</span>}
              <p className={`chat-bubble ${m.side}${last ? " tail" : ""}${first && i > 0 ? " turn" : ""}`}>{m.text}</p>
            </Fragment>
          );
        })}
        {chat.messages.length > shown.length && (
          <p className="chat-empty">and {chat.messages.length - shown.length} more messages</p>)}
      </div>
    </figure>
  );
}

/** Whose phone it is, the name at the top, and a voice for everyone in the chat. */
function ChatPeople({ story, chat, opts, locked, audio, onChat, onRules }: { story: Story; chat: StoryChat;
  opts: StoryOptions; locked: boolean; audio: Audio; onChat: (c: ChatPatch) => Promise<boolean>;
  onRules: (r: Story["pronunciations"]) => Promise<boolean> }) {
  const [contact, setContact] = useState(chat.contact);
  useEffect(() => setContact(chat.contact), [chat.contact]);
  // a slider's value while it moves: saved a moment after it stops (and when the page closes)
  const [moving, setMoving] = useState<Record<string, PersonVoice>>({});
  const pending = useRef<Record<string, PersonVoice>>({});
  const timer = useRef<number | undefined>(undefined);
  const save = useRef(onChat);
  save.current = onChat;
  const send = useCallback(() => {
    window.clearTimeout(timer.current);
    const people = pending.current;
    pending.current = {};
    if (Object.keys(people).length === 0) return;
    void save.current({ people }).finally(() => setMoving({ ...pending.current }));
  }, []);
  useEffect(() => send, [send]);
  const slide = (who: string, patch: PersonVoice) => {
    pending.current = { ...pending.current, [who]: { ...pending.current[who], ...patch } };
    setMoving({ ...pending.current });
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(send, 450);
  };
  const theme = opts.chat.themes.find((x) => x.id === chat.theme) || opts.chat.themes[0];
  if (chat.names.length === 0) {
    return <p className="small muted">Write the chat first: everyone in it shows up here with a voice of their own.</p>;
  }
  const said = (who: string) => chat.messages.filter((m) => m.who === who).slice(0, 2).map((m) => m.text).join(" ")
    || `Hi, it's ${who}.`;
  return (
    <div className="stack-4">
      <div className="story-rows">
        {chat.names.length > 1 && (
          <label className="story-row-pick"><span className="label">Whose phone it is</span>
            <select value={chat.names.includes(chat.me) ? chat.me : ""} disabled={locked}
              onChange={(e) => void onChat({ me: e.target.value })}>
              <option value="">Automatic: {chat.whose_phone || "nobody"}</option>
              {chat.names.map((n) => <option key={n} value={n}>{n}</option>)}
            </select></label>
        )}
        <label className="story-row-pick"><span className="label">Name at the top</span>
          <input type="text" value={contact} maxLength={40} disabled={locked}
            placeholder={chat.shown_contact || "Unknown"} onChange={(e) => setContact(e.target.value)}
            onBlur={() => { if (contact !== chat.contact) void onChat({ contact }); }} /></label>
      </div>
      <ul className="chat-people" aria-label="Voices">
        {chat.names.map((n) => {
          const v = { voice: opts.default_voice, speed: 1, tone: 0, ...chat.people[n], ...moving[n] };
          const mine = n === chat.whose_phone;
          return (
            <li key={n} className="chat-person">
              <span className="chat-dot" style={{ background: mine ? theme?.me : theme?.them }} aria-hidden="true" />
              <span className="chat-who"><b>{n}</b><span className="small muted">
                {mine ? "whose phone it is (right)" : chat.group ? "in the group (left)" : "the contact (left)"}
              </span></span>
              <select aria-label={`${n}'s voice`} value={v.voice} disabled={locked}
                onChange={(e) => void onChat({ people: { [n]: { voice: e.target.value } } })}>
                {opts.voices.map((x) => (
                  <option key={x.id} value={x.id}>{x.about ? `${x.name} · ${x.about}` : x.name}</option>
                ))}
              </select>
              <label className="small chat-slide">Speed <span className="muted tnum">{v.speed.toFixed(2)}×</span>
                <input type="range" min={opts.speed_range[0]} max={opts.speed_range[1]} step={0.02} value={v.speed}
                  disabled={locked} onChange={(e) => slide(n, { speed: Number(e.target.value) })} /></label>
              <label className="small chat-slide">Tone <span className="muted tnum">{v.tone > 0 ? `+${v.tone}` : v.tone}
              </span>
                <input type="range" min={opts.tone_range[0]} max={opts.tone_range[1]} step={0.5} value={v.tone}
                  disabled={locked} onChange={(e) => slide(n, { tone: Number(e.target.value) })} /></label>
              <button type="button" className="btn btn-small hear-btn" aria-label={`Hear ${n}`}
                onClick={() => void audio.play(`person:${n}`,
                  { voice: v.voice, speed: v.speed, tone: v.tone, text: said(n) })}>
                {audio.playing === `person:${n}` ? <><Icon name="stop" />Stop</> : <><Icon name="play" />Hear</>}
              </button>
            </li>
          );
        })}
      </ul>
      <label className="choice"><input type="checkbox" checked={chat.read_aloud} disabled={locked}
        onChange={(e) => void onChat({ read_aloud: e.target.checked })} />
        <span>Read every message aloud in its sender's voice</span></label>
      <p className="small muted">{chat.read_aloud ? "Each person gets a different voice to start with. Tone moves a "
        + "voice higher or lower, so two people can share one." : "Without voices each message stays on screen long "
        + "enough to read it (with the pop and whoosh sounds when they are on)."}</p>
      <Pronunciations story={story} locked={locked} onRules={onRules} />
    </div>
  );
}

/** The chat's look (dark, light, green bubbles), its pace and sounds, and the unread number by the back arrow. */
function ChatLook({ chat, opts, locked, onChat }: { chat: StoryChat; opts: StoryOptions; locked: boolean;
  onChat: (c: ChatPatch) => Promise<boolean> }) {
  const ids = useId();
  const [badge, setBadge] = useState(String(chat.badge));
  useEffect(() => setBadge(String(chat.badge)), [chat.badge]);
  const saveBadge = () => {
    const n = Math.max(0, Math.min(999, Math.round(Number(badge) || 0)));
    if (n !== chat.badge) void onChat({ badge: n });
    else setBadge(String(chat.badge));
  };
  return (
    <div className="stack-4">
      <div className="chat-themes" role="radiogroup" aria-label="Look">
        {opts.chat.themes.map((t) => (
          <label key={t.id} className={`chat-theme${chat.theme === t.id ? " on" : ""}`}>
            <input type="radio" name={`${ids}-theme`} checked={chat.theme === t.id} disabled={locked}
              onChange={() => void onChat({ theme: t.id })} />
            <span className="chat-theme-sample" style={{ background: t.card, borderColor: t.rule }} aria-hidden="true">
              <i style={{ background: t.them }} /><i style={{ background: t.me }} />
            </span>
            <span className="small">{t.label}</span>
          </label>
        ))}
      </div>
      <div className="story-rows">
        <div className="story-row-pick"><span className="label" id={`${ids}-pace`}>Pace</span>
          <Segmented labelledBy={`${ids}-pace`} value={chat.pace} disabled={locked}
            onChange={(pace) => void onChat({ pace })}
            options={opts.chat.paces.map((x) => ({ value: x.id, label: x.label }))} /></div>
        <label className="story-row-pick"><span className="label">Unread number</span>
          <input type="number" className="chat-badge-input" min={0} max={999} value={badge} disabled={locked}
            onChange={(e) => setBadge(e.target.value)} onBlur={saveBadge}
            onKeyDown={(e) => { if (e.key === "Enter") saveBadge(); }} /></label>
      </div>
      <label className="choice"><input type="checkbox" checked={chat.sounds} disabled={locked}
        onChange={(e) => void onChat({ sounds: e.target.checked })} />
        <span>A pop when a message comes in and a whoosh when one is sent</span></label>
      <p className="small muted">Pace sets the pauses between messages. The unread number sits by the back arrow (0
        hides it). The chat sits in the middle of the video, clear of the app buttons at the top and the caption at
        the bottom, and a new page of the chat starts when it fills up.</p>
    </div>
  );
}

const MAX_SHOWN = 6;

/** The list with item i moved one place up. */
function swapUp<T>(all: T[], i: number): T[] {
  return all.map((x, k) => (k === i - 1 ? all[i] : k === i ? all[i - 1] : x));
}

const FOOTAGE_IDEAS = ["satisfying", "cooking", "cutting food", "soap cutting", "kinetic sand", "parkour",
  "minecraft parkour", "slime", "subway train", "ocean waves"];

/** Search the free footage sources (Settings → Media sources) for a background, and use one: it is copied into
 * your videos with where it came from and its license, and goes behind the story. Only footage whose license lets
 * it be trimmed and used in a video for any purpose is offered. */
function FreeFootage({ onUse, close }: { onUse: (b: Partial<Background>) => void; close: () => void }) {
  const [query, setQuery] = useState(FOOTAGE_IDEAS[0]);
  const [found, setFound] = useState<MediaResult[] | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState("");   // the result being copied in
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);
  // the footage goes in with the backgrounds as they are when the copy finishes, not as they were at the click
  const latestUse = useRef(onUse);
  latestUse.current = onUse;

  const search = async (words = query) => {
    if (words.trim().length < 2) return;
    setQuery(words);
    setNote("Searching…");
    try {
      const got = await studio.searchMedia({ kind: "footage", query: words.trim(), filters: { license: "fits" } });
      const fits = got.results.filter((r) => r.fits.eligible && (r.duration_s ?? 0) >= 5);
      setFound(fits);
      const down = got.providers.filter((p) => p.state !== "ready" && p.message).map((p) => p.message);
      setNote(fits.length ? "" : `Nothing usable came back for “${words.trim()}”.${down.length ? ` ${down[0]}` : ""}`
        + " Try other words, or turn on more sources in Settings → Media sources.");
    } catch (e) {
      setNote(errorText(e));
    }
  };
  const use = async (r: MediaResult) => {
    setBusy(r.id);
    try {
      let job = await studio.importMedia({ result_id: r.id });
      for (let i = 0; i < 400 && alive.current && (job.status === "queued" || job.status === "importing"); i++) {
        await new Promise((ok) => window.setTimeout(ok, 1500));
        job = await studio.mediaImport(job.id);
      }
      if (!alive.current) return;
      if (job.status !== "ready" || !job.asset_id) throw new Error(job.error || "The footage could not be copied in.");
      const credit = r.fits.credit_required && r.credit ? ` Credit: ${r.credit}` : "";
      latestUse.current({ asset_id: job.asset_id, in_s: 0, out_s: r.duration_s || 10, focus_x: 0.5, focus_y: 0.5,
        why: `Free footage from ${r.provider_name} (${r.license_name}).${credit}`.slice(0, 200) });
      toast(r.fits.credit_required ? "Added. Its license asks for a credit: put the credit line in your post."
        : "Added behind the story.");
    } catch (e) {
      if (alive.current) toast(errorText(e), true);
    } finally {
      if (alive.current) setBusy("");
    }
  };
  return (
    <section className="stack-2" aria-label="Find free footage">
      <form className="row wrap" onSubmit={(e) => { e.preventDefault(); void search(); }}>
        <input type="search" value={query} maxLength={80} aria-label="What the footage shows"
          onChange={(e) => setQuery(e.target.value)} />
        <button type="submit" className="btn btn-small"><Icon name="search" />Search</button>
        <button type="button" className="btn btn-small btn-quiet" onClick={close}>Close</button>
      </form>
      <div className="row wrap" role="group" aria-label="Ideas">
        {/* the kinds of footage stories are told over; a story's own words make poor searches ("I worked one") */}
        {FOOTAGE_IDEAS.slice(1).map((idea) => <button key={idea} type="button" className="btn btn-small btn-quiet"
          onClick={() => void search(idea)}>{idea}</button>)}
      </div>
      {note && <p className="small muted" role="status">{note}</p>}
      {found && found.length > 0 && (
        <div className="bg-choices" role="group" aria-label="Free footage">
          {found.slice(0, MAX_SHOWN * 2).map((r) => (
            <button key={r.id} type="button" className="bg-choice" disabled={!!busy} onClick={() => void use(r)}>
              {r.preview.image ? <img src={r.preview.image} alt="" loading="lazy" />
                : <span className="bg-swatch" aria-hidden="true" />}
              <b className="small">{busy === r.id ? "Copying it in…" : r.title || "Untitled"}</b>
              <span className="small muted">{clock(r.duration_s || 0)} · {r.provider_name} · {r.license_name}
                {r.fits.credit_required ? " · credit required" : ""}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
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
  const [finding, setFinding] = useState(false);
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
      {list.length === 0 && <p className="small muted">Satisfying clips (cooking, cutting, soap, sand), gameplay,
        parkour or anything with steady motion works best. The background's own sound is left out, so the voice stays
        clear.</p>}
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
        <button type="button" className="btn" disabled={locked} aria-expanded={finding}
          onClick={() => setFinding(!finding)}><Icon name="search" />Find free footage</button>
        <input ref={file} type="file" accept="video/*" hidden onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) void sendFile(f);
        }} />
      </div>
      {finding && !locked && <FreeFootage onUse={(b) => { add(b); setFinding(false); }}
        close={() => setFinding(false)} />}
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
