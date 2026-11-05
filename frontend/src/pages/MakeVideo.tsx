import { useEffect, useMemo, useState } from "react";
import { api, errorText } from "../api";
import { ExampleSelect, FileDrop, Picked, StyleSelect, UploadRow, UsedFromBrain } from "../components/studioParts";
import { Banner, Disclosure, Icon, PageHead } from "../components/ui";
import { useAppearance } from "../prefs";
import { navigate } from "../router";
import { SmartLevel, Snapshot, studio } from "../studio";

/** Answers left empty come from the chosen example, style, skills and Brain (shown in "Used from your Brain"). */
type Brief = { video_type: string; audience: string; goal: string; target_min: string; aspect_ratio: string; feel: string;
  captions: "" | "on" | "off"; music: string; must_keep: string; avoid: string; frame_rate: number; caption_size: string;
  caption_position: string; duck_music: "" | "on" | "off"; smart_edit: SmartLevel; broll_images: boolean;
  sound_effects: boolean; punch_in: "" | "on" | "off"; ai_edit: boolean };
const LEVELS: [SmartLevel, string, string][] = [
  ["smart", "Edit it for me", "Cuts long pauses, repeated takes and weak parts, fits your length, adds your pictures, music and soft sound effects"],
  ["tight", "Fast-paced", "The same with shorter pauses and a small zoom on every other cut"],
  ["off", "Keep my clips as they are", "Only trims silence at the start and end of each clip"]];
const DEFAULTS: Record<string, unknown> = { aspect_ratio: "16:9", feel: "balanced", captions: true, frame_rate: 30,
  caption_size: "medium", caption_position: "bottom", duck_music: true };
const WORDS: Record<string, string> = { "16:9": "16:9 widescreen", "9:16": "9:16 vertical", "1:1": "1:1 square",
  "4:5": "4:5 portrait", calm: "calm", balanced: "balanced", energetic: "energetic", bottom: "lower third", middle: "centre",
  top: "top", small: "small", medium: "medium", large: "large", true: "on", false: "off" };

/** Make a YouTube video: a media bin and four questions. The timeline comes after, on the review page. */
export default function MakeVideo() {
  const { appearance } = useAppearance();
  const [files, setFiles] = useState<Picked[]>([]);
  const [order, setOrder] = useState<string[]>([]);
  const [music, setMusic] = useState<Picked | null>(null);
  const [findMedia, setFindMedia] = useState("off");
  const [voices, setVoices] = useState<Picked[]>([]);
  const [name, setName] = useState("");
  const [style, setStyle] = useState("saved");
  const [example, setExample] = useState("");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [brief, setBrief] = useState<Brief>({ video_type: "General YouTube video", audience: "", goal: "", target_min: "",
    aspect_ratio: "", feel: "", captions: "", music: "auto", must_keep: "", avoid: "",
    frame_rate: 0, caption_size: "", caption_position: "", duck_music: "", smart_edit: "smart", broll_images: true,
    sound_effects: true, punch_in: "", ai_edit: true });
  const [ai, setAi] = useState<{ provider: string; label: string } | null>(null);
  const [remember, setRemember] = useState(appearance.remember_style);
  const [styleName, setStyleName] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [dragging, setDragging] = useState<string | null>(null);

  const byKey = Object.fromEntries(files.map((f) => [f.key, f]));
  const ordered = order.map((k) => byKey[k]).filter(Boolean);
  const ready = ordered.length > 0 && ordered.every((f) => f.asset) && ordered.some((f) => f.asset?.kind === "video")
    && (brief.music !== "supplied" || !!music?.asset) && voices.every((f) => f.asset);
  const move = (key: string, by: number) => setOrder((o) => {
    const i = o.indexOf(key);
    const j = Math.max(0, Math.min(o.length - 1, i + by));
    const next = [...o];
    next.splice(i, 1);
    next.splice(j, 0, key);
    return next;
  });
  const set = (k: string, v: unknown) => setBrief((b) => ({ ...b, [k]: v }));
  // Only what you set here is this project's own choice; everything else comes from the example, style and Brain.
  const choices = useMemo(() => {
    const out: Record<string, unknown> = {};
    if (brief.aspect_ratio) out.aspect_ratio = brief.aspect_ratio;
    if (brief.feel) out.feel = brief.feel;
    if (brief.captions) out.captions = brief.captions === "on";
    if (brief.frame_rate) out.frame_rate = brief.frame_rate;
    if (brief.caption_size) out.caption_size = brief.caption_size;
    if (brief.caption_position) out.caption_position = brief.caption_position;
    if (brief.music === "supplied" && brief.duck_music) out.duck_music = brief.duck_music === "on";
    out.smart_edit = brief.smart_edit;
    if (brief.smart_edit !== "off") {
      out.broll_images = brief.broll_images;
      out.sound_effects = brief.sound_effects;
      if (brief.punch_in) out.punch_in = brief.punch_in === "on";
    }
    return out;
  }, [brief]);
  useEffect(() => {
    let alive = true;
    const t = window.setTimeout(() => {
      studio.preview({ mode: "full_video", style_id: style, choices, reference_id: example, title: name })
        .then((s) => alive && setSnapshot(s)).catch(() => alive && setSnapshot(null));
    }, 200);
    return () => {
      alive = false;
      window.clearTimeout(t);
    };
  }, [style, example, choices, name]);
  useEffect(() => {
    let alive = true;
    api.aiSetup().then((s) => alive && setAi({ provider: s.provider, label: s.label })).catch(() => alive && setAi(null));
    return () => { alive = false; };
  }, []);
  const aiOn = !!ai && ai.provider !== "heuristic";
  const smart = brief.smart_edit !== "off";
  const eff = (k: string) => {
    const v = snapshot?.values?.[k] ?? DEFAULTS[k];
    return WORDS[String(v)] || String(v);
  };

  const submit = async () => {
    setBusy(true);
    setProblem("");
    try {
      const minutes = parseFloat(brief.target_min);
      const v = await studio.makeVideo({
        name: name.trim() || ordered[0]?.file.name.replace(/\.[^.]+$/, "") || "My video",
        asset_ids: ordered.map((f) => f.asset!.id), style_id: style, reference_id: example,
        brief: { video_type: brief.video_type, audience: brief.audience, goal: brief.goal,
          ...(Number.isFinite(minutes) && minutes > 0 ? { target_duration_s: minutes * 60 } : {}),
          ...choices, music: brief.music, ...(smart ? { ai_edit: brief.ai_edit } : {}),
          ...(brief.music === "supplied" && music?.asset ? { music_asset_id: music.asset.id } : {}),
          ...(voices.length ? { voiceover_asset_ids: voices.map((f) => f.asset!.id) } : {}),
          must_keep: brief.must_keep, avoid: brief.avoid,
          find_media: brief.music === "find" && findMedia === "off" ? "suggest" : findMedia },
        remember: { enabled: remember, name: styleName.trim() },
      });
      navigate(`video/${v.id}`);
    } catch (e) {
      setProblem(errorText(e));
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <PageHead kind="Make" title="Make a YouTube video" crumbs={[{ label: "Home", href: "#/" }, { label: "Make a YouTube video" }]}
        sub="Add your clips, images and sounds and answer four questions. ClipForge edits a first version for you to preview and change. Add more files any time, also later." />
      <div className="studio-grid">
        <div className="stack-5">
          <section className="panel" aria-labelledby="mv-bin">
            <h2 id="mv-bin">Your media</h2>
            <FileDrop accept="video/*,image/png,image/jpeg,image/webp,audio/*,.mkv,.m4v,.flac,.opus,.ogg" multiple label="Drop videos, images and sounds here (as many as you like)"
              onAssets={(rows) => { setFiles(rows); setOrder((o) => [...o.filter((k) => rows.some((r) => r.key === k)),
                ...rows.map((r) => r.key).filter((k) => !o.includes(k))]); }} />
            {ordered.length > 1 && <p className="small muted">Videos and images start in this order; you can change it any time. Sounds wait in your media until you place them on a track.</p>}
            <ol className="file-list" aria-label="Order of your clips">
              {ordered.map((f, i) => (
                <li key={f.key} draggable onDragStart={() => setDragging(f.key)} onDragEnd={() => setDragging(null)}
                  onDragOver={(e) => e.preventDefault()} onDrop={() => dragging && dragging !== f.key && move(dragging, order.indexOf(f.key) - order.indexOf(dragging))}
                  className={dragging === f.key ? "dragging" : ""}>
                  <UploadRow row={f} extra={<>
                    <button type="button" className="btn btn-small btn-icon" aria-label={`Move ${f.file.name} up`} disabled={i === 0} onClick={() => move(f.key, -1)}><Icon name="chev" className="rot-up" /></button>
                    <button type="button" className="btn btn-small btn-icon" aria-label={`Move ${f.file.name} down`} disabled={i === ordered.length - 1} onClick={() => move(f.key, 1)}><Icon name="chev" /></button>
                    <button type="button" className="btn btn-small btn-icon" aria-label={`Remove ${f.file.name}`} onClick={() => setOrder((o) => o.filter((k) => k !== f.key))}><Icon name="x" /></button>
                  </>} />
                </li>
              ))}
            </ol>
          </section>
          <section className="panel" aria-labelledby="mv-edit">
            <h2 id="mv-edit">How much should ClipForge edit?</h2>
            <div className="mode-pick">
              {LEVELS.map(([v, t, d]) => (
                <label key={v}><input type="radio" name="smart_edit" checked={brief.smart_edit === v} onChange={() => set("smart_edit", v)} /><b>{t}</b><span>{d}</span></label>
              ))}
            </div>
            {smart && <div className="stack-2">
              <label><input type="checkbox" checked={brief.broll_images} onChange={(e) => set("broll_images", e.target.checked)} /> Show my images over the video while people talk (an image whose file name is said appears right then)</label>
              <label><input type="checkbox" checked={brief.sound_effects} onChange={(e) => set("sound_effects", e.target.checked)} /> Soft sound effects at scene changes and as pictures appear</label>
              <label><input type="checkbox" checked={brief.punch_in ? brief.punch_in === "on" : brief.smart_edit === "tight"} onChange={(e) => set("punch_in", e.target.checked ? "on" : "off")} /> Zoom in a little on every other cut</label>
              <label><input type="checkbox" checked={brief.ai_edit && aiOn} disabled={!aiOn} onChange={(e) => set("ai_edit", e.target.checked)} /> Let the AI helper read what is said to choose better cuts, pictures and chapters</label>
              <p className="small muted">{aiOn
                ? <>AI helper: {ai!.label}. Only the words said, as text, are sent to it. <a href="#/settings/ai">Change</a></>
                : <>No AI helper is set up, so ClipForge's built-in editor decides alone (it works well without one). <a href="#/settings/ai">Set up a free AI helper</a> (a model on your computer, or a free key).</>}</p>
              <p className="small muted">Everything it cuts stays in the sequence, switched off, so you can put any part back. Each choice is a version you can undo.</p>
            </div>}
          </section>
          <section className="panel" aria-labelledby="mv-brief">
            <h2 id="mv-brief">Four questions</h2>
            <fieldset className="stack-3"><legend className="label">1. What are we making, and who is it for?</legend>
              <div className="grid-2">
                <label className="field"><span>Video type</span><input value={brief.video_type} maxLength={80} onChange={(e) => set("video_type", e.target.value)} /></label>
                <label className="field"><span>Who is it for</span><input value={brief.audience} maxLength={120} placeholder="For example: friends and family" onChange={(e) => set("audience", e.target.value)} /></label>
              </div>
              <label className="field"><span>Goal (optional)</span><input value={brief.goal} maxLength={200} onChange={(e) => set("goal", e.target.value)} /></label>
            </fieldset>
            <fieldset className="stack-3"><legend className="label">2. How long, and what shape?</legend>
              <div className="grid-2">
                <label className="field"><span>Length in minutes</span><input inputMode="decimal" value={brief.target_min} placeholder="Use your judgment" onChange={(e) => set("target_min", e.target.value)} /></label>
                <label className="field"><span>Shape</span><select value={brief.aspect_ratio} onChange={(e) => set("aspect_ratio", e.target.value)}>
                  <option value="">From your style ({eff("aspect_ratio")})</option>
                  <option value="16:9">16:9 widescreen</option><option value="9:16">9:16 vertical</option><option value="1:1">1:1 square</option><option value="4:5">4:5 portrait</option>
                </select></label>
              </div>
            </fieldset>
            <fieldset className="stack-3"><legend className="label">3. What should it feel like?</legend>
              <div className="mode-pick">
                {[["", "From your style", `Now: ${eff("feel")}`], ["calm", "Calm / storytelling", "Slow dissolves"], ["balanced", "Balanced", "Short dissolves"], ["energetic", "Energetic", "Straight cuts"]].map(([v, t, d]) => (
                  <label key={v || "style"}><input type="radio" name="feel" checked={brief.feel === v} onChange={() => set("feel", v)} /><b>{t}</b><span>{d}</span></label>
                ))}
              </div>
              <label className="field"><span>Burn in captions</span><select value={brief.captions} onChange={(e) => set("captions", e.target.value)}>
                <option value="">From your style ({eff("captions")})</option><option value="on">On</option><option value="off">Off</option></select></label>
              <label className="field"><span>Music</span><select value={brief.music} onChange={(e) => set("music", e.target.value)}>
                <option value="auto">Pick for me (a long music file in your media, or free music made by ClipForge)</option>
                <option value="library">Free music made by ClipForge, in the video's mood</option>
                <option value="supplied">My own music file (it dips while people speak)</option>
                <option value="find">Find music for me in Media sources</option>
                <option value="none">No added music</option></select></label>
              <label className="field"><span>Supporting media</span><select value={findMedia} onChange={(e) => setFindMedia(e.target.value)}>
                <option value="off">Don't look for images or music</option>
                <option value="suggest">After the rough cut, suggest images (and music) for my review</option>
                <option value="auto">After the rough cut, add eligible ones as a version I can undo</option></select></label>
              {(findMedia !== "off" || brief.music === "find") && <p className="small muted">Searches only for this project, using a few words you say most often, under its license rules (commercial use, no share-alike) that you can change in the editor. <a href="#/settings/media">Media sources</a></p>}
              {brief.music === "supplied" && <FileDrop accept="audio/*,.flac,.opus,.ogg" label="Drop the music file" onAssets={(rows) => setMusic(rows[0] || null)} />}
              <Disclosure summary={voices.length ? `Voiceover (${voices.length} file${voices.length > 1 ? "s" : ""})` : "Add a voiceover"}>
                <p className="small muted">Voiceover files play one after another from the start, on their own track. Music dips under them like under speech.</p>
                <FileDrop accept="audio/*,.flac,.opus,.ogg" multiple label="Drop voiceover recordings" onAssets={setVoices} />
              </Disclosure>
            </fieldset>
            <Disclosure summary="Customize">
              <div className="grid-2">
                <label className="field"><span>Frame rate</span><select value={brief.frame_rate} onChange={(e) => set("frame_rate", Number(e.target.value))}>
                  <option value={0}>From your style ({eff("frame_rate")} fps)</option>
                  {[24, 25, 30, 50, 60].map((f) => <option key={f} value={f}>{f} frames per second</option>)}</select></label>
                <label className="field"><span>Caption size</span><select value={brief.caption_size} onChange={(e) => set("caption_size", e.target.value)}>
                  <option value="">From your style ({eff("caption_size")})</option>
                  <option value="small">Small</option><option value="medium">Medium</option><option value="large">Large</option></select></label>
                <label className="field"><span>Caption position</span><select value={brief.caption_position} onChange={(e) => set("caption_position", e.target.value)}>
                  <option value="">From your style ({eff("caption_position")})</option>
                  <option value="bottom">Lower third</option><option value="middle">Centre</option><option value="top">Top</option></select></label>
                {brief.music === "supplied" && <label className="field"><span>Music dips while people speak</span><select value={brief.duck_music} onChange={(e) => set("duck_music", e.target.value)}>
                  <option value="">From your style ({eff("duck_music")})</option><option value="on">On</option><option value="off">Off</option></select></label>}
              </div>
              <p className="small muted">Everything here can be changed later in the editor, together with each clip's and track's volume, fades and transitions.</p>
            </Disclosure>
            <fieldset className="stack-3"><legend className="label">4. What must stay or go?</legend>
              <label className="field"><span>Keep (words or topics, comma separated)</span><input value={brief.must_keep} onChange={(e) => set("must_keep", e.target.value)} /></label>
              <label className="field"><span>Remove or avoid</span><input value={brief.avoid} onChange={(e) => set("avoid", e.target.value)} /></label>
            </fieldset>
          </section>
        </div>
        <div className="stack-5">
          <section className="panel" aria-labelledby="mv-style">
            <h2 id="mv-style">Style</h2>
            <StyleSelect value={style} onChange={setStyle} mode="full_video" />
            <ExampleSelect value={example} onChange={setExample} mode="full_video" />
            <label><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Remember this style</label>
            <p className="small muted">Saves your answers to questions 2 and 3 (and the video type) as a style for next time. Your files, what to keep or remove, and where to publish stay in this project only.</p>
            {remember && <label className="field"><span>Style name</span><input value={styleName} maxLength={60} placeholder={`${name || "My video"} style`} onChange={(e) => setStyleName(e.target.value)} /></label>}
            <Disclosure summary="Name this video"><label className="field"><span>Video name</span><input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></label></Disclosure>
          </section>
          <section className="panel" aria-labelledby="mv-brain">
            <h2 id="mv-brain">Used from your Brain</h2>
            <UsedFromBrain snapshot={snapshot} />
          </section>
          {problem && <Banner tone="bad" title="Not started">{problem}</Banner>}
          <button type="button" className="btn btn-primary btn-large" disabled={!ready || busy} onClick={submit}>
            <Icon name="create" />{busy ? "Starting…" : "Build my video"}
          </button>
          {!ready && <p className="small muted">{!ordered.some((f) => f.asset?.kind === "video" || f.file.type.startsWith("video")) ? "Add at least one video." : "Wait until every file has uploaded."}</p>}
        </div>
      </div>
    </div>
  );
}
