import { ReactNode, useEffect, useId, useMemo, useState } from "react";
import { errorText } from "../api";
import { HearButton } from "../components/ShortScenes";
import { Banner, Icon, PageHead, Segmented, Skel } from "../components/ui";
import { navigate } from "../router";
import {
  aboutLength, ShortLength, ShortLook, ShortMode, ShortMotion, ShortOptions, shorts, speakingSeconds, spokenWords,
} from "../shorts";
import "./shorts.css";

/** The choices remembered in this browser for the next short (a convenience: the page works without them). */
const KEPT = "clipforge.short-choices";
type Choices = { look: string; voice: string; speed: number; music: string; captions: string; motion: ShortMotion };

function kept(): Partial<Choices> {
  try {
    const v = JSON.parse(localStorage.getItem(KEPT) || "{}");
    return v && typeof v === "object" ? (v as Partial<Choices>) : {};
  } catch {
    return {};
  }
}

function keep(c: Choices) {
  try {
    localStorage.setItem(KEPT, JSON.stringify(c));
  } catch {
    /* private window or blocked storage: nothing is remembered */
  }
}

/** The remembered choices that still exist, else ClipForge's defaults. */
function startingChoices(o: ShortOptions): Choices {
  const k = kept();
  const one = <T,>(want: unknown, ok: T[], fallback: T): T => (ok.includes(want as T) ? (want as T) : fallback);
  const music: string[] = o.music.map((m) => m.id);
  const captions: string[] = o.captions.map((c) => c.id);
  const speeds = o.speeds.map((x) => x.value);
  return {
    look: one(k.look, o.looks.map((l) => l.id), o.looks[0]?.id ?? ""),
    voice: one(k.voice, o.voices.map((x) => x.id), o.default_voice || o.voices[0]?.id || "auto"),
    speed: one(k.speed, speeds, speeds.includes(1) ? 1 : speeds[Math.floor(speeds.length / 2)] ?? 1),
    music: one(k.music, music, music.includes("balanced") ? "balanced" : music[0] ?? "none"),
    captions: one(k.captions, captions, captions.includes("") ? "" : captions[0] ?? ""),  // "": the look's own style
    motion: k.motion === "animate" && o.engines.video.ready ? "animate" : "camera",
  };
}

const HEX = /^#[0-9a-f]{3,8}$/i;

/** A look's colours: its gradient, a caption bar and its accent dot. */
function LookSwatch({ look }: { look: ShortLook }) {
  const top = HEX.test(look.top) ? look.top : "#2A3142";
  const bottom = HEX.test(look.bottom) ? look.bottom : "#11151E";
  return (
    <span className="look-swatch" aria-hidden="true" style={{ background: `linear-gradient(180deg, ${top}, ${bottom})` }}>
      <i style={{ background: HEX.test(look.accent) ? look.accent : "#FFFFFF" }} />
    </span>
  );
}

/** One labeled row of choices: the label (and its hint) on the left, the control on the right. */
function Row({ label, hint, htmlFor, labelId, children }: { label: string; hint?: ReactNode; htmlFor?: string;
  labelId?: string; children: ReactNode }) {
  return (
    <div className="setting">
      <div className="stack-1">
        {htmlFor ? <label className="label" htmlFor={htmlFor}>{label}</label> : <span className="label" id={labelId}>{label}</span>}
        {hint && <span className="hint">{hint}</span>}
      </div>
      <div className="short-control">{children}</div>
    </div>
  );
}

/**
 * Make an animated short (docs/clipforge/ANIMATED_SHORTS.md): a script pasted or written by ClipForge AI from a topic,
 * a look, a voice, music, captions and motion. Make the short opens the short's editor page, where each scene is made.
 */
export default function MakeShort() {
  const ids = useId();
  const [opts, setOpts] = useState<ShortOptions | null>(null);
  const [loadProblem, setLoadProblem] = useState("");
  const [tries, setTries] = useState(0);
  const [mode, setMode] = useState<ShortMode>("paste");
  const [script, setScript] = useState("");
  const [topic, setTopic] = useState("");
  const [tone, setTone] = useState("");
  const [length, setLength] = useState<ShortLength>("standard");
  const [audience, setAudience] = useState("");
  const [review, setReview] = useState(false);
  const [c, setC] = useState<Choices | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  useEffect(() => {
    let alive = true;
    setLoadProblem("");
    // asked again on every visit: a picture maker or ClipForge AI may have been set up since
    shorts.options(true).then((o) => {
      if (!alive) return;
      setOpts(o);
      setC((now) => now || startingChoices(o));
      setTone((t) => (o.tones.some((x) => x.id === t) ? t : o.tones[0]?.id ?? ""));
      setLength((l) => (o.lengths.some((x) => x.id === l) ? l : o.lengths[0]?.id ?? "standard"));
    }).catch((e) => alive && setLoadProblem(errorText(e)));
    return () => {
      alive = false;
    };
  }, [tries]);
  useEffect(() => {
    if (c) keep(c);
  }, [c]);
  const set = <K extends keyof Choices>(k: K, value: Choices[K]) => setC((now) => (now ? { ...now, [k]: value } : now));

  const words = useMemo(() => spokenWords(script), [script]);
  const maxWords = opts?.limits.max_words || 600;
  const seconds = speakingSeconds(words, opts?.limits.wpm || 175, c?.speed ?? 1);
  const tooLong = words > maxWords;
  const writer = opts?.writer;
  const canWrite = !!writer?.configured;
  const engines = opts?.engines;
  const why = !opts || !c ? "" : mode === "paste"
    ? (!words ? "Paste your script first." : tooLong ? `Shorten the script to ${maxWords} words or fewer.` : "")
    : (!canWrite ? "Writing needs ClipForge AI. Set it up, or paste your own script." : !topic.trim() ? "Type a topic first." : "");
  const ready = !!opts && !!c && !why;
  const voiceByEngine = !!engines?.voice.ready && !!c && (c.voice === "auto" || c.voice.startsWith("engine:"));

  const submit = async () => {
    if (!ready || !c || busy) return;
    setBusy(true);
    setProblem("");
    try {
      const v = await shorts.create({
        name: name.trim(), mode, ...c, review: mode === "write" && review,
        ...(mode === "paste" ? { script: script.trim() } : { topic: topic.trim(), tone, length, audience: audience.trim() }),
      });
      navigate(`video/${v.id}`);
    } catch (e) {
      setProblem(errorText(e));
      setBusy(false);
    }
  };

  return (
    <div className="page narrow make-short">
      <PageHead kind="Make" title="Make an animated short" crumbs={[{ label: "Projects", href: "#/projects" }, { label: "Animated short" }]}
        sub="A vertical short of moving pictures with a voice-over, big captions and music. Paste your script, or let ClipForge AI write one from a topic." />

      {loadProblem && (
        <Banner tone="bad" title="The choices could not be loaded"
          actions={<button type="button" className="btn btn-small" onClick={() => setTries((n) => n + 1)}><Icon name="refresh" />Try again</button>}>
          {loadProblem}
        </Banner>
      )}

      <section className="panel" aria-labelledby={`${ids}-script`}>
        <h2 id={`${ids}-script`}>The script</h2>
        <Segmented label="Where the script comes from" value={mode} onChange={setMode}
          options={[{ value: "paste", label: "Paste my script" }, { value: "write", label: "Write it for me" }]} />
        {mode === "paste" ? (
          <div className="field">
            <label htmlFor={`${ids}-text`}>Your script</label>
            <textarea id={`${ids}-text`} className="short-script" rows={10} value={script} spellCheck
              aria-describedby={`${ids}-hint ${ids}-count`} aria-invalid={tooLong || undefined}
              placeholder={"[Visual: a fox in the snow]\nEvery winter, the red fox does something strange."}
              onChange={(e) => setScript(e.target.value)} />
            <span className="hint" id={`${ids}-hint`}>One picture per sentence or two. A line like [Visual: a fox in the snow] says what the next picture shows.</span>
            <p className="short-count small" id={`${ids}-count`}>
              <span className="tnum">{words} {words === 1 ? "word" : "words"}</span>
              {words > 0 && <span className="tnum">{aboutLength(seconds)}</span>}
            </p>
            <div aria-live="polite">
              {tooLong && <p className="short-warn small"><Icon name="alert" className="sm" />
                <span>This script has {words} words; a short can have up to {maxWords}. Take some out to make it.</span></p>}
            </div>
          </div>
        ) : (
          <div className="stack-4">
            {opts && !canWrite && (
              <Banner tone="info" title="Writing needs ClipForge AI"
                actions={<a className="btn btn-small" href={opts.links.ai}><Icon name="settings" />Set up ClipForge AI</a>}>
                ClipForge AI writes the script from your topic. Set it up once in Settings (a free model on this computer works),
                or paste your own script instead.
              </Banner>
            )}
            <label className="field"><span>Topic</span>
              <input type="text" value={topic} maxLength={300} aria-required="true" placeholder="For example: why octopuses have three hearts"
                onChange={(e) => setTopic(e.target.value)} /></label>
            <div className="grid-2">
              <label className="field"><span>Tone</span>
                {opts ? (
                  <select value={tone} onChange={(e) => setTone(e.target.value)}>
                    {opts.tones.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
                  </select>
                ) : <Skel className="skel-line short-skel-control" />}
              </label>
              <div className="field">
                <span id={`${ids}-length`}>Length</span>
                {opts ? (
                  <Segmented labelledBy={`${ids}-length`} value={length} onChange={setLength}
                    options={opts.lengths.map((l) => ({ value: l.id, label: l.label }))} />
                ) : <Skel className="skel-line short-skel-control" />}
              </div>
            </div>
            <label className="field"><span>Who it is for (optional)</span>
              <input type="text" value={audience} maxLength={120} placeholder="For example: curious kids"
                onChange={(e) => setAudience(e.target.value)} /></label>
            <label className="choice">
              <input type="checkbox" checked={review} onChange={(e) => setReview(e.target.checked)} />
              <span>Let me check the script before the pictures are made</span>
            </label>
            {opts && writer && canWrite && (
              <p className="small muted short-writer"><Icon name="info" className="sm" />
                <span>Written by {writer.label} {writer.local ? "on this computer" : `online (the topic is sent to ${writer.label})`}.</span></p>
            )}
          </div>
        )}
      </section>

      <section className="panel" aria-labelledby={`${ids}-look`}>
        <h2 id={`${ids}-look`}>Look</h2>
        <p className="small muted">{engines && !engines.image.ready
          ? "How the pictures look. No picture maker is set up yet, so each scene is a designed card in these colours."
          : "How every picture is drawn, so all the scenes look like one story."}</p>
        {opts && c ? (
          <div className="look-grid" role="radiogroup" aria-labelledby={`${ids}-look`}>
            {opts.looks.map((l) => (
              <label key={l.id} className="look-card">
                <input type="radio" name={`${ids}-look-choice`} value={l.id} checked={c.look === l.id} onChange={() => set("look", l.id)} />
                <LookSwatch look={l} />
                <span className="look-check" aria-hidden="true"><Icon name="check" /></span>
                <b>{l.name}</b>
                <span className="small muted">{l.about}</span>
              </label>
            ))}
          </div>
        ) : (
          <div className="look-grid" aria-hidden="true">{[0, 1, 2, 3].map((i) => <Skel key={i} className="look-skel" />)}</div>
        )}
      </section>

      <section className="panel" aria-labelledby={`${ids}-sound`}>
        <h2 id={`${ids}-sound`}>Voice and sound</h2>
        {opts && c ? (
          <div className="short-rows">
            <Row label="Voice" htmlFor={`${ids}-voice`} hint="Hear it plays a few seconds of the voice at this speed.">
              <div className="short-voice-row">
                <select id={`${ids}-voice`} value={c.voice} onChange={(e) => set("voice", e.target.value)}>
                  {opts.voices.map((x) => <option key={x.id} value={x.id}>{x.about ? `${x.name} · ${x.about}` : x.name}</option>)}
                </select>
                <HearButton voice={c.voice} speed={c.speed} />
              </div>
            </Row>
            <Row label="Speed" labelId={`${ids}-speed`}>
              <Segmented labelledBy={`${ids}-speed`} value={c.speed} onChange={(x) => set("speed", x)}
                options={opts.speeds.map((x) => ({ value: x.value, label: x.label }))} />
            </Row>
            <Row label="Music" labelId={`${ids}-music`} hint="It dips under the voice.">
              <Segmented labelledBy={`${ids}-music`} value={c.music} onChange={(x) => set("music", x)}
                options={opts.music.map((m) => ({ value: m.id as string, label: m.label }))} />
            </Row>
            <Row label="Captions" labelId={`${ids}-captions`} hint="Big words in the middle; the word being said lights up.">
              <Segmented labelledBy={`${ids}-captions`} value={c.captions} onChange={(x) => set("captions", x)}
                options={opts.captions.map((x) => ({ value: x.id as string, label: x.label }))} />
            </Row>
          </div>
        ) : <div className="stack-3" aria-hidden="true"><Skel className="skel-line" /><Skel className="skel-line" /><Skel className="skel-line" /></div>}
      </section>

      <section className="panel" aria-labelledby={`${ids}-motion`}>
        <h2 id={`${ids}-motion`}>Motion</h2>
        {opts && c && engines ? (
          <div className="mode-pick" role="radiogroup" aria-labelledby={`${ids}-motion`}>
            <label>
              <input type="radio" name={`${ids}-motion-choice`} checked={c.motion === "camera"} onChange={() => set("motion", "camera")} />
              <b>Gentle camera moves</b><span>Quick, works on every computer</span>
            </label>
            <label className={engines.video.ready ? "" : "off"}>
              <input type="radio" name={`${ids}-motion-choice`} checked={c.motion === "animate"} disabled={!engines.video.ready}
                aria-describedby={engines.video.ready ? undefined : `${ids}-video-why`} onChange={() => set("motion", "animate")} />
              <b>Animate the pictures with the video maker</b>
              <span>Slow{engines.video.ready && engines.video.engine ? `. Uses ${engines.video.engine} on this computer` : ""}</span>
              {!engines.video.ready && <span className="hint" id={`${ids}-video-why`}>{engines.video.why || "No video maker is set up."}</span>}
            </label>
          </div>
        ) : <Skel className="skel-block short-skel-motion" />}
      </section>

      <section className="panel tight" aria-labelledby={`${ids}-made`}>
        <h2 id={`${ids}-made`}>What makes it</h2>
        {opts && engines ? (
          <dl className="kv short-facts">
            <dt>Pictures</dt>
            <dd>{engines.image.ready ? `${engines.image.engine || "The picture maker"} on this computer`
              : <>Designed cards with the key words (no picture maker is set up)
                {engines.available && <>. <a className="textlink" href={opts.links.makers}>Set up a picture maker</a></>}</>}</dd>
            <dt>Voice</dt>
            <dd>{voiceByEngine ? engines.voice.engine || "The voice maker on this computer" : "This computer's own voice"}</dd>
            <dt>Word timing</dt>
            <dd>{opts.timing === "listened" ? "Exact" : "Estimated from the sound"}</dd>
          </dl>
        ) : <div className="stack-2" aria-hidden="true"><Skel className="skel-line" /><Skel className="skel-line" /></div>}
      </section>

      <label className="field short-name"><span>Name (optional)</span>
        <input type="text" value={name} maxLength={120} placeholder="Named from the script" onChange={(e) => setName(e.target.value)} /></label>

      {problem && <Banner tone="bad" title="Not started">{problem}</Banner>}

      <div className="short-make">
        <span className="small muted short-next">{why || (mode === "write" && review
          ? "Next: ClipForge AI writes the script and waits on the short's page for you to check it."
          : "Next: the short's page opens and ClipForge makes each scene there. Keep ClipForge running until it is ready.")}</span>
        <button type="button" className="btn btn-primary btn-large" disabled={!ready || busy} onClick={() => void submit()}>
          {busy ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="spark" />}
          {busy ? "Starting…" : "Make the short"}
        </button>
      </div>
    </div>
  );
}
