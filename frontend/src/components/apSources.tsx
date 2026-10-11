import { cloneElement, ReactElement, ReactNode, useId, useState } from "react";
import { errorText, Platform } from "../api";
import {
  Agreement, AgreementIn, ap, AutopilotStatus, Feed, RIGHTS_BADGE, RIGHTS_LABEL, RightsRule, Source,
} from "../autopilot";
import { plural } from "../format";
import { navigate } from "../router";
import { PLATFORM_NAME } from "./accounts";
import {
  ConfirmDialog, Icon, MenuItem, MoreMenu, Pill, Segmented, TextPromptDialog, toast, Toggle, Tone, usePoll,
} from "./ui";

/**
 * Autopilot → Permissions & sources: creator agreements, where videos come from (folders, channels, streams, lists),
 * permission rules, and every video Autopilot found with its permission. Only confirm permission you really have:
 * being public, trending or downloadable does not make a video reusable.
 */

const STATUSES = ["OWNED", "LICENSED", "ALLOWLISTED", "CREATIVE_COMMONS", "PUBLIC_DOMAIN", "BLOCKED"];
const STATUS_WORD: Record<string, string> = {
  discovered: "Checking", eligible: "May be used", needs_rights: "Not covered", needs_file: "Needs the file",
  queued: "Up next", ingesting: "Getting the video", analyzing: "Finding the best moments", analyzed: "Done",
  weak: "No strong moments", exhausted: "Done", failed: "Could not be processed", skipped: "Skipped",
  blocked: "Blocked",
};
const FILTERS = ["", "eligible", "needs_rights", "needs_file", "queued", "ingesting", "analyzing", "analyzed", "weak",
  "failed", "skipped", "blocked"];
const FEED_KIND: Record<string, string> = {
  watch_folder: "Folder", youtube_channel: "YouTube channel", stream_url: "Stream", signal_feed: "Trend list",
};
const SCOPE: Record<string, string> = {
  channel: "YouTube channel", folder: "Folder", url_prefix: "Links starting with", source: "One video",
};

/** "Not covered" is not a problem (such videos are skipped by design), so it reads neutral, not as a warning. */
export const rightsTone = (status: string): Tone =>
  status === "MANUAL_CONFIRMATION_REQUIRED" ? "neutral" : ((RIGHTS_BADGE[status] || "neutral") as Tone);

/** A labeled form field: the label names the control, the hint describes it. */
function Field({ label, hint, optional, children }: {
  label: ReactNode; hint?: ReactNode; optional?: boolean; children: ReactElement;
}) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}{optional && <span className="hint"> (optional)</span>}</label>
      {cloneElement(children, { id, "aria-describedby": hint ? `${id}-h` : undefined })}
      {hint && <span className="hint" id={`${id}-h`}>{hint}</span>}
    </div>
  );
}

function Check({ checked, onChange, children }: {
  checked: boolean; onChange: (v: boolean) => void; children: ReactNode;
}) {
  return (
    <label className="choice small">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>{children}</span>
    </label>
  );
}

export default function SourcesView({ st, refreshStatus }: { st: AutopilotStatus; refreshStatus: () => void }) {
  const [filter, setFilter] = useState("");
  const { data: sources, refresh } = usePoll(() => ap.sources(filter), [filter], 5000, () => true);
  const { data: rights, refresh: refreshRights } = usePoll(() => ap.rights(), [], 30000, () => true);
  const { data: feeds, refresh: refreshFeeds } = usePoll(() => ap.feeds(), [], 15000, () => true);
  const { data: agreements, refresh: refreshAgreements } = usePoll(() => ap.agreements(), [], 30000, () => true);
  const [dialog, setDialog] = useState<
    | { kind: "agreement" | "feed" | "rule" | "source" | "content" }
    | { kind: "rights" | "file"; source: Source }
    | { kind: "remove-agreement"; agreement: Agreement }
    | { kind: "remove-feed"; feed: Feed }
    | { kind: "remove-rule"; rule: RightsRule }
    | null>(null);
  const all = () => {
    refresh();
    refreshRights();
    refreshFeeds();
    refreshAgreements();
    refreshStatus();
  };
  const act = async (fn: () => Promise<unknown>, msg: string) => {
    try {
      await fn();
      toast(msg);
      all();
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  const close = () => setDialog(null);
  const counts = Object.entries(st.rights);

  return (
    <>
      <section className="panel agreements" aria-labelledby="agr">
        <div className="panel-head">
          <h2 id="agr">Creator agreements</h2>
          <button type="button" className="btn" onClick={() => setDialog({ kind: "agreement" })}>
            <Icon name="plus" />Record an agreement…</button>
        </div>
        <p className="small muted">A creator who allows you to clip their videos (an agreement, or a clipping program
          you joined): record it once, with what shows it and its conditions, and every video it covers is used
          without asking. It covers the creator's own material only, unless you say it also covers other people's
          music or footage.</p>
        {agreements === null ? <div className="skel skel-line" /> : agreements.length ? (
          <div className="rows">
            {agreements.map((a) => (
              <div key={a.id} className="row top wrap agreement" style={{ padding: "12px 0" }}>
                <span className="grow stack" style={{ gap: 2 }}>
                  <b className="break">{a.creator}</b>
                  <span className="tiny faint break">{[...a.channels, a.conditions.media_folder && "shared folder",
                    a.conditions.media_url_prefix && "file link"].filter(Boolean).join(" · ")}</span>
                  <span className="small">
                    {a.conditions.commercial ? "Commercial use allowed" : "No commercial use"}
                    {a.conditions.platforms?.length ? " · only on "
                      + a.conditions.platforms.map((p) => PLATFORM_NAME[p as Platform] || p).join(", ") : ""}
                    {a.conditions.attribution ? ` · credit: “${a.conditions.attribution}”` : ""}
                    {a.conditions.third_party ? " · also covers other people's material" : ""}
                    {a.expires_at ? ` · ends ${new Date(a.expires_at * 1000 - 1000).toLocaleDateString()}` : ""}
                  </span>
                  <span className="tiny faint break">Evidence: {a.evidence || a.evidence_url}</span>
                </span>
                <button type="button" className="btn btn-small btn-danger"
                  onClick={() => setDialog({ kind: "remove-agreement", agreement: a })}>
                  <Icon name="trash" />Remove…<span className="sr-only"> the agreement with {a.creator}</span>
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="small muted">None yet. Without agreements, Autopilot uses your own videos and videos with a
            free license (public domain, CC0, CC BY).</p>
        )}
      </section>

      <div className="cols-2">
        {/* align-content: start keeps each list at the top when the panel next to it is taller */}
        <section className="panel" aria-labelledby="feeds" style={{ alignContent: "start" }}>
          <div className="panel-head">
            <h2 id="feeds">Where videos come from</h2>
            <MoreMenu label="Add a place videos come from" text="Add…" items={[
              { label: "A video, link or folder of yours…", icon: "plus",
                onSelect: () => setDialog({ kind: "content" }) },
              { label: "A channel, stream or trend list…", icon: "link",
                onSelect: () => setDialog({ kind: "feed" }) },
            ]} />
          </div>
          <p className="small muted">Folders (your recordings; a file that is still growing is a live recording),
            YouTube channels you follow, streams you may use, and trend lists you may use.</p>
          {feeds === null ? <div className="skel skel-line" /> : feeds.length ? (
            <div className="rows">
              {feeds.map((f) => (
                <div key={f.id} className="row wrap feed" style={{ padding: "10px 0" }}>
                  <span className="grow stack" style={{ gap: 0 }}>
                    <b className="break">{f.name}</b>
                    <span className="tiny faint break">{FEED_KIND[f.kind] || f.kind} · {f.config.path || f.config.url
                      || f.config.channel_id}</span>
                    {f.last_error && <span className="small bad-text">{f.last_error}</span>}
                  </span>
                  <Toggle on={!!f.enabled} showState ariaLabel={`Use ${f.name}`}
                    onChange={(v) => act(() => ap.setFeed(f.id, v),
                      v ? `${f.name} is used again` : `${f.name} is not used now`)} />
                  <button type="button" className="btn btn-small btn-icon btn-quiet" aria-label={`Remove ${f.name}`}
                    title={`Remove ${f.name}`} onClick={() => setDialog({ kind: "remove-feed", feed: f })}>
                    <Icon name="trash" /></button>
                </div>
              ))}
            </div>
          ) : <p className="small muted">None yet.</p>}
        </section>

        <section className="panel" aria-labelledby="rules" style={{ alignContent: "start" }}>
          <div className="panel-head">
            <h2 id="rules">Permission rules</h2>
            <button type="button" className="btn btn-small" onClick={() => setDialog({ kind: "rule" })}>
              <Icon name="plus" />Add rule…</button>
          </div>
          <p className="small muted">Record what you may use, and why: a channel whose clipping program you joined, a
            folder of your own recordings, a licensed source. Blocked always wins.</p>
          {rights === null ? <div className="skel skel-line" /> : rights.rules.length ? (
            <div className="rows">
              {rights.rules.map((r) => (
                <div key={r.id} className="row wrap rule" style={{ padding: "10px 0" }}>
                  <Pill tone={rightsTone(r.status)} icon="shield">{RIGHTS_LABEL[r.status] || r.status}</Pill>
                  <span className="grow stack" style={{ gap: 0 }}>
                    <b className="break">{r.label || r.value}</b>
                    <span className="tiny faint break">{SCOPE[r.scope] || r.scope}{r.label ? ` · ${r.value}` : ""}
                      {r.basis ? ` · ${r.basis}` : ""}</span>
                  </span>
                  <button type="button" className="btn btn-small btn-icon btn-quiet"
                    aria-label={`Remove the rule for ${r.label || r.value}`} title="Remove this rule"
                    onClick={() => setDialog({ kind: "remove-rule", rule: r })}><Icon name="trash" /></button>
                </div>
              ))}
            </div>
          ) : <p className="small muted">No rules yet: videos nothing covers are never posted.</p>}
        </section>
      </div>

      <section className="panel" aria-labelledby="srcs">
        <div className="panel-head">
          <h2 id="srcs">Found videos and their permission</h2>
          <div className="row wrap">
            <label className="sr-only" htmlFor="src-filter">Show</label>
            <select id="src-filter" value={filter} onChange={(e) => setFilter(e.target.value)}
              style={{ width: "auto" }}>
              {FILTERS.map((f) => <option key={f} value={f}>{f ? STATUS_WORD[f] : "All videos"}</option>)}
            </select>
            <button type="button" className="btn btn-small" onClick={() => setDialog({ kind: "source" })}>
              <Icon name="plus" />Add a video…</button>
          </div>
        </div>
        {counts.length > 0 && (
          <div className="row wrap" role="group" aria-label="Permission of the videos it knows">
            {counts.map(([k, n]) => (
              <Pill key={k} tone={rightsTone(k)} icon="shield">{RIGHTS_LABEL[k] || k}: {n}</Pill>
            ))}
          </div>
        )}
        {sources === null ? <div className="skel skel-block" /> : sources.length ? (
          <div className="rows">
            {sources.map((s) => (
              <SourceRow key={s.id} s={s} open={(kind) => setDialog({ kind, source: s })} act={act} />
            ))}
          </div>
        ) : <p className="small muted">No videos{filter ? " with this status" : " yet"}.</p>}
        <p className="tiny faint">Only confirm permission you actually have. Being public, trending or downloadable
          does not make a video reusable. Source Score is ClipFoundry's own estimate of how promising a video is for
          clips, not a platform number.</p>
      </section>

      {dialog?.kind === "agreement" && <AgreementDialog onClose={close} onDone={all} />}
      {dialog?.kind === "feed" && <AddFeedDialog onClose={close} onDone={all} />}
      {dialog?.kind === "rule" && <AddRuleDialog onClose={close} onDone={all} />}
      {dialog?.kind === "source" && <AddSourceDialog onClose={close} onDone={all} />}
      {dialog?.kind === "content" && <AddContentDialog onClose={close} onDone={all} />}
      {dialog?.kind === "rights" && <RightsDialog source={dialog.source} onClose={close} onDone={all} />}
      {dialog?.kind === "file" && (
        <TextPromptDialog title="Add the video file" label="Full path of the video file on this computer"
          hint="For example C:\Users\you\Videos\talk.mp4" confirmLabel="Add file" onClose={close}
          onSubmit={async (path) => {
            await ap.attachFile(dialog.source.id, path);
            toast("File added");
            all();
          }}>
          <p className="small muted">“{dialog.source.title}”. ClipFoundry does not download videos from YouTube or
            other platforms by itself (their terms): choose the original file on this computer.</p>
        </TextPromptDialog>
      )}
      {dialog?.kind === "remove-agreement" && (
        <ConfirmDialog title={`Remove the agreement with ${dialog.agreement.creator}?`} confirmLabel="Remove agreement"
          danger cancelLabel="Keep it" onClose={close} onConfirm={async () => {
            await ap.removeAgreement(dialog.agreement.id);
            toast("Agreement removed");
            all();
          }}>
          <p className="muted">Videos it covers are no longer used automatically. Clips and posts already made from
            them stay where they are.</p>
        </ConfirmDialog>
      )}
      {dialog?.kind === "remove-feed" && (
        <ConfirmDialog title={`Remove “${dialog.feed.name}”?`} confirmLabel="Remove" danger cancelLabel="Keep it"
          onClose={close} onConfirm={async () => {
            await ap.deleteFeed(dialog.feed.id);
            toast("Removed");
            all();
          }}>
          <p className="muted">Autopilot stops looking there for new videos. Nothing is deleted from your computer, and
            videos it already found stay listed. To pause it instead, use its switch.</p>
        </ConfirmDialog>
      )}
      {dialog?.kind === "remove-rule" && (
        <ConfirmDialog title="Remove this permission rule?" confirmLabel="Remove rule" danger cancelLabel="Keep it"
          onClose={close} onConfirm={async () => {
            await ap.deleteRule(dialog.rule.id);
            toast("Rule removed");
            all();
          }}>
          <p className="muted">“{dialog.rule.label || dialog.rule.value}” ({RIGHTS_LABEL[dialog.rule.status]}).
            Videos it covered are checked again; without another rule or agreement they are no longer used.</p>
        </ConfirmDialog>
      )}
    </>
  );
}

function SourceRow({ s, open, act }: {
  s: Source; open: (kind: "rights" | "file") => void; act: (fn: () => Promise<unknown>, msg: string) => void;
}) {
  const title = s.title || s.external_id;
  const parts = Object.entries(s.components || {}).map(([k, c]) => `${k}: ${c.note || c.value}`).join("\n");
  return (
    <div className="row top wrap source" style={{ padding: "12px 0" }}>
      <Pill tone={rightsTone(s.rights_status)} icon="shield" title={s.rights_explain}>{s.rights_label}</Pill>
      <div className="grow stack" style={{ gap: 2, flexBasis: 260 }}>
        {s.url ? <a className="post-title break" href={s.url} target="_blank" rel="noreferrer">{title}
          <span className="sr-only"> (opens a new tab)</span></a> : <b className="break">{title}</b>}
        <span className="tiny faint">{[PLATFORM_NAME[s.platform as Platform] || s.platform, s.channel_title,
          STATUS_WORD[s.status] || s.status.replace(/_/g, " "), s.kind === "live" ? "Live" : ""]
          .filter(Boolean).join(" · ")}</span>
        {(s.rights_basis || s.status_note) && (
          <span className="small muted break">{[s.rights_basis, s.status_note].filter(Boolean).join(" · ")}</span>
        )}
        {Object.keys(s.components || {}).length > 0 && <details className="small muted">
          <summary>Why this video was considered</summary>
          <ul className="small" style={{ margin: "8px 0", paddingLeft: 20 }}>
            {Object.entries(s.components || {}).map(([key, part]) => <li key={key}>
              {key === "discovery_filter" ? "Filter: " : key === "evidence" ? "Evidence: "
                : part.status === "observed" ? "Reported fact: " : "Estimate: "}
              {part.note || "No explanation recorded"}
            </li>)}
          </ul>
          <p className="tiny">Estimates describe why it is worth reading. They do not promise views or virality.
            Posting permission is checked separately.</p>
        </details>}
      </div>
      <span className="small" title={parts || undefined}>
        Source Score <b>{s.source_score != null ? Math.round(s.source_score) : "—"}</b>{" "}
        <span className="faint">
          (estimate{s.expected_clips != null ? `, ≈ ${plural(Math.round(s.expected_clips), "strong clip")}` : ""})
        </span>
        {s.clips_selected > 0 && <span className="faint"> · {s.clips_selected} made</span>}
      </span>
      <span className="row">
        <button type="button" className="btn btn-small" onClick={() => open("rights")}>Permission…</button>
        <MoreMenu label={`More for ${title}`} items={moreItems(s, open, act)} />
      </span>
    </div>
  );
}

/** The less common actions on a found video. Skip stays listed when it can't be used, with the reason. */
function moreItems(s: Source, open: (kind: "rights" | "file") => void,
  act: (fn: () => Promise<unknown>, msg: string) => void): MenuItem[] {
  const items: MenuItem[] = [];
  if (s.status === "needs_file") items.push({ label: "Add the file…", icon: "folder", onSelect: () => open("file") });
  if (["eligible", "weak", "failed", "skipped"].includes(s.status)) {
    items.push({ label: "Clip now", icon: "scissors",
      onSelect: () => act(() => ap.huntSource(s.id), "Sent to be clipped") });
  }
  if (s.project_id) items.push({ label: "Open its clips", icon: "film", href: `#/project/${s.project_id}` });
  if (s.url) items.push({ label: "Open the video", icon: "external", href: s.url, external: true });
  items.push(!["ingesting", "analyzing", "skipped"].includes(s.status)
    ? { label: "Skip this video", icon: "x", onSelect: () => act(() => ap.skipSource(s.id), "Skipped") }
    : { label: "Skip this video", icon: "x",
      disabled: s.status === "skipped" ? "Already skipped" : "Wait until it is processed" });
  return items;
}

// ------------------------------------------------------------------ dialogs
function RightsFields({ status, setStatus, basis, setBasis, empty = "Choose…" }: {
  status: string; setStatus: (s: string) => void; basis: string; setBasis: (s: string) => void; empty?: string;
}) {
  return (
    <>
      <Field label="Permission">
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="" disabled={empty === "Choose…"}>{empty}</option>
          {STATUSES.map((s) => <option key={s} value={s}>{RIGHTS_LABEL[s]}</option>)}
        </select>
      </Field>
      <Field label="What gives you the right" hint={"Required for Licensed and Allowlisted. For example: my own "
        + "recordings, an official clipping program joined 2026-09-01, license #123."}>
        <input type="text" value={basis} onChange={(e) => setBasis(e.target.value)} />
      </Field>
    </>
  );
}

function RightsDialog({ source, onClose, onDone }: { source: Source; onClose: () => void; onDone: () => void }) {
  const [status, setStatus] = useState(source.rights_status === "MANUAL_CONFIRMATION_REQUIRED" ? ""
    : source.rights_status);
  const [basis, setBasis] = useState(source.rights_basis || "");
  return (
    <ConfirmDialog title={`Permission for “${source.title.slice(0, 60)}”`} confirmLabel="Save permission"
      onClose={onClose} disabled={!status} onConfirm={async () => {
        await ap.confirmRights(source.id, status, basis);
        toast("Saved");
        onDone();
      }}>
      {source.rights_explain && <p className="small muted">{source.rights_explain}</p>}
      <p className="small">Only confirm permission you actually have. Being public, trending or downloadable does not
        make a video reusable. Owned, Licensed, Allowlisted and free licenses are clipped automatically; Blocked is
        never used.</p>
      <RightsFields status={status} setStatus={setStatus} basis={basis} setBasis={setBasis} />
    </ConfirmDialog>
  );
}

function AgreementDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [a, setA] = useState<AgreementIn>({
    creator: "", channels: [], evidence: "", evidence_url: "", attribution: "", commercial: true,
    platforms: ["youtube", "tiktok"], third_party: false, expires: "", media_folder: "", media_url_prefix: "",
  });
  const [channels, setChannels] = useState("");
  const set = (p: Partial<AgreementIn>) => setA({ ...a, ...p });
  const plat = (p: string, on: boolean) => {
    const others = a.platforms.filter((x) => x !== p);
    set({ platforms: on ? [...others, p] : others });
  };
  return (
    <ConfirmDialog title="Record an agreement with a creator" confirmLabel="Save agreement" wide onClose={onClose}
      onConfirm={async () => {
        if (!a.creator.trim()) throw new Error("Enter the creator's name first.");
        if (!a.evidence.trim()) throw new Error("Say what shows the agreement: where and when they agreed.");
        if (!a.platforms.length) throw new Error("Choose at least one platform it allows.");
        await ap.addAgreement({ ...a, channels: channels.split(/[\s,]+/).filter(Boolean) });
        toast("Agreement saved: videos it covers are used without asking");
        onDone();
      }}>
      <Field label="Creator"><input type="text" value={a.creator} onChange={(e) => set({ creator: e.target.value })}
        placeholder="Their name or channel name" /></Field>
      <Field label="YouTube channel IDs and TikTok handles" hint="UC… or @name, separated by commas">
        <input type="text" value={channels} onChange={(e) => setChannels(e.target.value)}
          placeholder="UCxxxxxxxxxxxxxxxxxxxxxx, @theirname" />
      </Field>
      <Field label="What shows the agreement" hint="Required: where and when they agreed, or the program's terms">
        <textarea rows={2} value={a.evidence} onChange={(e) => set({ evidence: e.target.value })}
          placeholder="Email from them on 2026-09-01: “You may clip and post my podcast episodes”" />
      </Field>
      <Field label="Link to it" optional>
        <input type="url" value={a.evidence_url} onChange={(e) => set({ evidence_url: e.target.value })}
          placeholder="https://…" />
      </Field>
      <Field label="Credit line they want" optional hint="Added to every post">
        <input type="text" value={a.attribution} onChange={(e) => set({ attribution: e.target.value })}
          placeholder="Clip from @theirname's podcast" />
      </Field>
      <fieldset>
        <legend className="label">What it allows</legend>
        <Check checked={a.commercial} onChange={(v) => set({ commercial: v })}>Commercial use</Check>
        <Check checked={a.platforms.includes("youtube")} onChange={(v) => plat("youtube", v)}>Posting on YouTube</Check>
        <Check checked={a.platforms.includes("tiktok")} onChange={(v) => plat("tiktok", v)}>Posting on TikTok</Check>
        <Check checked={a.third_party} onChange={(v) => set({ third_party: v })}>It also covers other people's music or
          footage in their videos <span className="muted">(only if the agreement says so)</span></Check>
      </fieldset>
      <Field label="Ends on" optional>
        <input type="date" value={a.expires} onChange={(e) => set({ expires: e.target.value })} />
      </Field>
      <Field label="Folder with their files on this computer" optional
        hint="For example a Dropbox or Google Drive folder they share">
        <input type="text" value={a.media_folder} onChange={(e) => set({ media_folder: e.target.value })}
          placeholder="C:\Users\you\Dropbox\Their raw videos" />
      </Field>
      <Field label="Address of their file links" optional hint="Direct file links they give you start with this">
        <input type="text" value={a.media_url_prefix} onChange={(e) => set({ media_url_prefix: e.target.value })}
          placeholder="https://files.example.com/raw/" />
      </Field>
      <p className="small muted">Without a shared folder or file link, their YouTube videos are still skipped: YouTube
        does not allow downloading its videos without its permission.</p>
    </ConfirmDialog>
  );
}

function AddFeedDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [kind, setKind] = useState("watch_folder");
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [status, setStatus] = useState("");
  const [basis, setBasis] = useState("");
  const key = kind === "watch_folder" ? "path" : kind === "youtube_channel" ? "channel_id"
    : kind === "stream_url" ? "url" : value.startsWith("http") ? "url" : "path";
  const withRights = kind !== "signal_feed";
  return (
    <ConfirmDialog title="Add a place videos come from" confirmLabel="Add" onClose={onClose} disabled={!value.trim()}
      onConfirm={async () => {
        await ap.addFeed({ kind, name, config: { [key]: value.trim() }, rights_status: withRights ? status : "",
          rights_basis: withRights ? basis : "" });
        toast("Added");
        onDone();
      }}>
      <Field label="Kind">
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="watch_folder">A folder on this computer (your recordings)</option>
          <option value="youtube_channel">A YouTube channel (its new uploads)</option>
          <option value="stream_url">A stream you may use (HLS, RTMP or SRT)</option>
          <option value="signal_feed">A trend list (JSON or CSV file or link)</option>
        </select>
      </Field>
      <Field label="Name"><input type="text" value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label={kind === "watch_folder" ? "Folder on this computer"
        : kind === "youtube_channel" ? "Channel ID (starts with UC)"
          : kind === "stream_url" ? "Stream address" : "File path or link"}>
        <input type="text" value={value} onChange={(e) => setValue(e.target.value)} />
      </Field>
      {withRights && <RightsFields status={status} setStatus={setStatus} basis={basis} setBasis={setBasis}
        empty="Not decided: not used until something covers it" />}
      {kind === "youtube_channel" && (
        <p className="small muted">Following a channel finds its new uploads. Using them still needs a permission that
          covers them and, for YouTube, the original file or an agreement's shared folder.</p>
      )}
    </ConfirmDialog>
  );
}

function AddRuleDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [scope, setScope] = useState("channel");
  const [value, setValue] = useState("");
  const [label, setLabel] = useState("");
  const [status, setStatus] = useState("ALLOWLISTED");
  const [basis, setBasis] = useState("");
  const [evidence, setEvidence] = useState("");
  return (
    <ConfirmDialog title="Add a permission rule" confirmLabel="Add rule" onClose={onClose} disabled={!value.trim()}
      onConfirm={async () => {
        await ap.addRule({ scope: scope as RightsRule["scope"], value: value.trim(), label,
          status: status as RightsRule["status"], basis, evidence_url: evidence,
          platform: scope === "channel" ? "youtube" : "" });
        toast("Rule added");
        onDone();
      }}>
      <Field label="Applies to">
        <select value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="channel">A YouTube channel (channel ID)</option>
          <option value="folder">A folder on this computer</option>
          <option value="url_prefix">Links starting with…</option>
        </select>
      </Field>
      <Field label={scope === "channel" ? "Channel ID" : scope === "folder" ? "Folder" : "Start of the links"}>
        <input type="text" value={value} onChange={(e) => setValue(e.target.value)} />
      </Field>
      <Field label="Label" optional>
        <input type="text" value={label} onChange={(e) => setLabel(e.target.value)}
          placeholder="For example the creator's name" />
      </Field>
      <RightsFields status={status} setStatus={setStatus} basis={basis} setBasis={setBasis} />
      <Field label="Evidence link" optional>
        <input type="url" value={evidence} onChange={(e) => setEvidence(e.target.value)} />
      </Field>
    </ConfirmDialog>
  );
}

function AddSourceDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [where, setWhere] = useState("");
  const [title, setTitle] = useState("");
  const [status, setStatus] = useState("");
  const [basis, setBasis] = useState("");
  return (
    <ConfirmDialog title="Add a video" confirmLabel="Add" onClose={onClose} disabled={!where.trim()}
      onConfirm={async () => {
        const isUrl = /^(https?|rtmps?|srt):\/\//i.test(where.trim());
        await ap.addSource({ [isUrl ? "url" : "path"]: where.trim().replace(/^"|"$/g, ""), title,
          rights_status: status, basis });
        toast("Added");
        onDone();
      }}>
      <Field label="Video file path or link">
        <input type="text" value={where} onChange={(e) => setWhere(e.target.value)} />
      </Field>
      <Field label="Title" optional>
        <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      <RightsFields status={status} setStatus={setStatus} basis={basis} setBasis={setBasis}
        empty="Decide later (not clipped until then)" />
    </ConfirmDialog>
  );
}

const CAN_USE = [
  { value: "OWNED", label: "Yes, it's my own content" },
  { value: "ALLOWLISTED", label: "Yes, I have permission from the creator" },
  { value: "", label: "Not sure: don't use it until I decide" },
];

/** The simple way to add something by hand: a link, a file, a folder to watch, or an upload on Add video. */
export function AddContentDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [mode, setMode] = useState("link");
  const [where, setWhere] = useState("");
  const [title, setTitle] = useState("");
  const [canUse, setCanUse] = useState<string | null>(null);
  const name = useId();
  const basis = canUse === "OWNED" ? "My own content (added by hand)"
    : "You said you have permission from the creator (added by hand)";
  const upload = mode === "upload";
  return (
    <ConfirmDialog title="Add a video Autopilot may use" confirmLabel={upload ? "Open Add video" : "Add"}
      onClose={onClose} onConfirm={async () => {
        if (upload) {
          navigate("create");
          return;
        }
        if (!where.trim()) {
          throw new Error(mode === "link" ? "Paste the link first."
            : mode === "folder" ? "Enter the folder first." : "Enter the file's path first.");
        }
        if (canUse === null) throw new Error("Say whether ClipFoundry may use it.");
        const path = where.trim().replace(/^"|"$/g, "");
        if (mode === "folder") {
          await ap.addFeed({ kind: "watch_folder", name: title || "My videos", config: { path },
            rights_status: canUse, rights_basis: canUse ? basis : "" });
        } else {
          await ap.addSource({ [mode === "link" ? "url" : "path"]: path, title, rights_status: canUse,
            basis: canUse ? basis : "" });
        }
        toast(canUse ? "Added: Autopilot will pick it up"
          : "Added. It is not used until you record a permission for it.");
        onDone();
      }}>
      <p className="small muted">Optional: Autopilot finds videos by itself. Use this for your own videos or links you
        may use.</p>
      <Segmented label="What to add" value={mode} onChange={setMode} options={[
        { value: "link", label: "A link" }, { value: "file", label: "A file" },
        { value: "folder", label: "A folder to watch" }, { value: "upload", label: "Upload a video" },
      ]} />
      {upload ? (
        <p className="small">Upload a video on the Add video page and make clips from it yourself.</p>
      ) : (
        <>
          <Field label={mode === "link" ? "Link to the video"
            : mode === "folder" ? "Folder on this computer (new videos in it are clipped)"
              : "Full path of the video file"}>
            <input type="text" value={where} onChange={(e) => setWhere(e.target.value)}
              placeholder={mode === "link" ? "https://…" : mode === "folder" ? "C:\\Users\\you\\Videos\\Recordings"
                : "C:\\Users\\you\\Videos\\talk.mp4"} />
          </Field>
          <Field label="Name" optional>
            <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <fieldset>
            <legend className="label">Can ClipFoundry use it?</legend>
            {CAN_USE.map((c) => (
              <label key={c.value} className="choice small">
                <input type="radio" name={name} checked={canUse === c.value} onChange={() => setCanUse(c.value)} />
                <span>{c.label}</span>
              </label>
            ))}
          </fieldset>
        </>
      )}
    </ConfirmDialog>
  );
}
