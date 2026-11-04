import { useState } from "react";
import { errorText } from "../api";
import { FileDrop, Picked, StyleSelect, UploadRow } from "../components/studioParts";
import { Banner, Disclosure, Icon, PageHead } from "../components/ui";
import { useAppearance } from "../prefs";
import { navigate } from "../router";
import { studio } from "../studio";

/** Make a YouTube video: a media bin and four questions. The timeline comes after, on the review page. */
export default function MakeVideo() {
  const { appearance } = useAppearance();
  const [files, setFiles] = useState<Picked[]>([]);
  const [order, setOrder] = useState<string[]>([]);
  const [music, setMusic] = useState<Picked | null>(null);
  const [name, setName] = useState("");
  const [style, setStyle] = useState("saved");
  const [brief, setBrief] = useState({ video_type: "General YouTube video", audience: "", goal: "", target_min: "",
    aspect_ratio: "16:9", feel: "balanced", captions: true, music: "none", must_keep: "", avoid: "" });
  const [remember, setRemember] = useState(appearance.remember_style);
  const [styleName, setStyleName] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [dragging, setDragging] = useState<string | null>(null);

  const byKey = Object.fromEntries(files.map((f) => [f.key, f]));
  const ordered = order.map((k) => byKey[k]).filter(Boolean);
  const ready = ordered.length > 0 && ordered.every((f) => f.asset) && ordered.some((f) => f.asset?.kind === "video")
    && (brief.music !== "supplied" || !!music?.asset);
  const move = (key: string, by: number) => setOrder((o) => {
    const i = o.indexOf(key);
    const j = Math.max(0, Math.min(o.length - 1, i + by));
    const next = [...o];
    next.splice(i, 1);
    next.splice(j, 0, key);
    return next;
  });
  const set = (k: string, v: unknown) => setBrief((b) => ({ ...b, [k]: v }));

  const submit = async () => {
    setBusy(true);
    setProblem("");
    try {
      const minutes = parseFloat(brief.target_min);
      const v = await studio.makeVideo({
        name: name.trim() || ordered[0]?.file.name.replace(/\.[^.]+$/, "") || "My video",
        asset_ids: ordered.map((f) => f.asset!.id), style_id: style,
        brief: { video_type: brief.video_type, audience: brief.audience, goal: brief.goal,
          target_duration_s: Number.isFinite(minutes) && minutes > 0 ? minutes * 60 : 0, aspect_ratio: brief.aspect_ratio,
          feel: brief.feel, captions: brief.captions, music: brief.music,
          ...(brief.music === "supplied" && music?.asset ? { music_asset_id: music.asset.id } : {}),
          must_keep: brief.must_keep, avoid: brief.avoid },
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
        sub="Add your clips and answer four questions. ClipForge builds a rough cut you can preview and change." />
      <div className="studio-grid">
        <div className="stack-5">
          <section className="panel" aria-labelledby="mv-bin">
            <h2 id="mv-bin">Your clips and images</h2>
            <FileDrop accept="video/*,image/png,image/jpeg,image/webp,.mkv,.m4v" multiple label="Drop videos and images here"
              onAssets={(rows) => { setFiles(rows); setOrder((o) => [...o.filter((k) => rows.some((r) => r.key === k)),
                ...rows.map((r) => r.key).filter((k) => !o.includes(k))]); }} />
            {ordered.length > 1 && <p className="small muted">This order is where you start; you can change it any time.</p>}
            <ol className="file-list" aria-label="Order of your clips">
              {ordered.map((f, i) => (
                <li key={f.key} draggable onDragStart={() => setDragging(f.key)} onDragEnd={() => setDragging(null)}
                  onDragOver={(e) => e.preventDefault()} onDrop={() => dragging && dragging !== f.key && move(dragging, order.indexOf(f.key) - order.indexOf(dragging))}
                  className={dragging === f.key ? "dragging" : ""}>
                  <UploadRow row={f} onRetry={() => {}} extra={<>
                    <button type="button" className="btn btn-small btn-icon" aria-label={`Move ${f.file.name} up`} disabled={i === 0} onClick={() => move(f.key, -1)}><Icon name="chev" className="rot-up" /></button>
                    <button type="button" className="btn btn-small btn-icon" aria-label={`Move ${f.file.name} down`} disabled={i === ordered.length - 1} onClick={() => move(f.key, 1)}><Icon name="chev" /></button>
                    <button type="button" className="btn btn-small btn-icon" aria-label={`Remove ${f.file.name}`} onClick={() => setOrder((o) => o.filter((k) => k !== f.key))}><Icon name="x" /></button>
                  </>} />
                </li>
              ))}
            </ol>
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
                  <option value="16:9">16:9 widescreen</option><option value="9:16">9:16 vertical</option><option value="1:1">1:1 square</option><option value="4:5">4:5 portrait</option>
                </select></label>
              </div>
            </fieldset>
            <fieldset className="stack-3"><legend className="label">3. What should it feel like?</legend>
              <div className="mode-pick">
                {[["calm", "Calm / storytelling", "Slow dissolves"], ["balanced", "Balanced", "Short dissolves"], ["energetic", "Energetic", "Straight cuts"]].map(([v, t, d]) => (
                  <label key={v}><input type="radio" name="feel" checked={brief.feel === v} onChange={() => set("feel", v)} /><b>{t}</b><span>{d}</span></label>
                ))}
              </div>
              <label><input type="checkbox" checked={brief.captions} onChange={(e) => set("captions", e.target.checked)} /> Burn in captions</label>
              <label><input type="checkbox" checked={brief.music === "supplied"} onChange={(e) => set("music", e.target.checked ? "supplied" : "none")} /> Add my own music (it dips while people speak)</label>
              {brief.music === "supplied" && <FileDrop accept="audio/*" label="Drop the music file" onAssets={(rows) => setMusic(rows[0] || null)} />}
            </fieldset>
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
            <label><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Remember this style</label>
            <p className="small muted">Saves your answers to questions 2 and 3 (and the video type) as a style for next time. Your files, what to keep or remove, and where to publish stay in this project only.</p>
            {remember && <label className="field"><span>Style name</span><input value={styleName} maxLength={60} placeholder={`${name || "My video"} style`} onChange={(e) => setStyleName(e.target.value)} /></label>}
            <Disclosure summary="Name this video"><label className="field"><span>Video name</span><input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></label></Disclosure>
          </section>
          {problem && <Banner tone="bad" title="Not started">{problem}</Banner>}
          <button type="button" className="btn btn-primary btn-large" disabled={!ready || busy} onClick={submit}>
            <Icon name="create" />{busy ? "Starting…" : "Build my video"}
          </button>
          {!ready && <p className="small muted">{ordered.length === 0 ? "Add at least one video." : "Wait until every file has uploaded."}</p>}
        </div>
      </div>
    </div>
  );
}
