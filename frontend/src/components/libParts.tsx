import { useEffect, useState } from "react";
import { api, Clip, ClipVersion, downloadZip, errorText, Project, versionDownloadUrl } from "../api";
import { ap, ScheduledItem } from "../autopilot";
import { plural, when } from "../format";
import { ConfirmDialog, Icon, MenuItem, Pill, Segmented, toast } from "./ui";

/** Shared by the Library, the Source video page and the clip editor. */

/** Fields the projects list has but `Project` in api.ts does not declare. */
export type LibProject = Project & { origin?: "manual" | "autopilot" | "live" | string; source_id?: string };

/** Still copying, waiting or making clips: deleting is not possible yet. */
export const isWorking = (p: Project) => ["created", "uploading", "queued", "processing"].includes(p.status);

/** Autopilot made it, so Autopilot (not this page) runs its processing. */
export const byAutopilot = (p: LibProject) => p.origin === "autopilot" || p.origin === "live";

export function originLabel(p: LibProject): string {
  if (p.origin === "autopilot") return "Added by Autopilot";
  if (p.origin === "live") return "Added by Autopilot from a live stream";
  return p.source_url ? "Imported from a link" : "Added by you";
}

export const addedLine = (p: LibProject) => `${originLabel(p)} · ${when(p.created_at)}`;

/** A source video's state in a word or two, with its icon. Processing shows the backend's own step. */
export function ProjectStatus({ p, clipCount }: { p: Project; clipCount?: number }) {
  switch (p.status) {
    case "uploading":
      return <Pill tone="info" icon="upload">Copying into ClipFoundry</Pill>;
    case "created":
    case "queued":
      return <Pill tone="neutral" icon="clock">Waiting to start</Pill>;
    case "processing": {
      const msg = p.message && p.message !== "Starting" ? p.message : "Making clips";
      return /^waiting/i.test(msg) ? <Pill tone="warn" icon="clock">{msg}</Pill>
        : <Pill tone="info" icon="refresh">{msg}</Pill>;
    }
    case "error":
      return <Pill tone="bad" icon="alert">Couldn't make clips</Pill>;
    case "cancelled":
      return <Pill tone="neutral" icon="x">Canceled</Pill>;
    case "ready": {
      const n = clipCount ?? p.clip_count ?? p.clips?.length ?? 0;
      return n ? <Pill tone="good" icon="check">Ready · {plural(n, "clip")}</Pill>
        : <Pill tone="neutral" icon="info">Ready · no clip passed the quality bar</Pill>;
    }
    default:
      return <Pill tone="neutral">{p.status}</Pill>;
  }
}

/** The More menu of a source video. Delete is never offered while the video is still being worked on. */
export function projectMenu(
  p: LibProject, act: { cancel: () => void; remake?: () => void; remove: () => void },
): MenuItem[] {
  const busy = isWorking(p);
  const items: MenuItem[] = [];
  if (busy && !byAutopilot(p)) items.push({ label: "Cancel processing", icon: "stop", onSelect: act.cancel });
  if (busy && byAutopilot(p)) {
    items.push({
      label: "Cancel processing", icon: "stop",
      disabled: "Autopilot is making these clips. You can stop it on the Autopilot page.",
    });
    items.push({ label: "Open Autopilot", icon: "autopilot", href: "#/autopilot" });
  }
  if (act.remake) {
    items.push({
      label: "Make clips again…", icon: "refresh", onSelect: act.remake,
      disabled: busy ? "Wait until processing ends" : undefined,
    });
  }
  if (items.length) items.push("separator");
  items.push({
    label: "Delete video and clips…", icon: "trash", danger: true, onSelect: act.remove,
    disabled: !busy ? undefined
      : byAutopilot(p) ? "Wait until Autopilot finishes this video" : "Cancel processing first",
  });
  return items;
}

/** Stops a manual project at its next safe point (the backend's own cancel). */
export async function cancelProcessing(p: Project, after: () => void) {
  try {
    await api.cancelProject(p.id);
    toast("Canceling. It stops at the next safe point.");
  } catch (e) {
    toast(errorText(e), true);
  }
  after();
}

/** Delete, with what goes and what stays. The backend refuses while the video is processing; that shows inline. */
export function DeleteProjectDialog({ p, clipCount, onClose, onDeleted }: {
  p: Project; clipCount: number; onClose: () => void; onDeleted: () => void;
}) {
  return (
    <ConfirmDialog title={`Delete “${p.name}”?`} danger onClose={onClose}
      confirmLabel={clipCount ? `Delete video and ${plural(clipCount, "clip")}` : "Delete video"}
      onConfirm={async () => {
        await api.deleteProject(p.id);
        toast(`Deleted “${p.name}”`);
        onDeleted();
      }}>
      <p className="muted">
        This deletes ClipFoundry's copy of the video, its transcript
        {clipCount ? ` and its ${plural(clipCount, "clip")} with their versions` : ""} from this computer. It can't
        be undone.
      </p>
      <p className="small">Not affected: the original file you added, and posts already on YouTube or TikTok.</p>
    </ConfirmDialog>
  );
}

const COUNTS = [3, 5, 10];

/** "Make clips again": new moments from the same transcript. The current clips are replaced. */
export function RemakeDialog({ p, clipCount, onClose, onDone }: {
  p: Project; clipCount: number; onClose: () => void; onDone: () => void;
}) {
  const opts = (p.options || {}) as Record<string, any>;
  const startCount = typeof opts.clip_count === "number" ? opts.clip_count : 5;
  const [count, setCount] = useState<number>(startCount);
  const [minD, setMinD] = useState(String(opts.min_duration ?? 15));
  const [maxD, setMaxD] = useState(String(opts.max_duration ?? 60));
  const lo = Number(minD);
  const hi = Number(maxD);
  const problem = !minD || !Number.isFinite(lo) || lo < 5 || lo > 170 ? "The shortest clip must be 5 to 170 seconds."
    : !maxD || !Number.isFinite(hi) || hi < 10 || hi > 180 ? "The longest clip must be 10 to 180 seconds."
      : hi < lo + 5 ? "The longest clip must be at least 5 seconds longer than the shortest." : "";
  const choices = [...new Set([...COUNTS, startCount])].sort((a, b) => a - b);
  return (
    <ConfirmDialog title="Make clips again" confirmLabel="Make clips again" disabled={!!problem} onClose={onClose}
      onConfirm={async () => {
        await api.reprocess(p.id, {
          clip_count: count, min_duration: lo, max_duration: hi, target_duration: (lo + hi) / 2,
        });
        toast("Making clips again");
        onDone();
      }}>
      <p className="muted small">
        ClipFoundry looks for the best moments again. The transcript is reused, so this is much faster than the first
        time.
      </p>
      {clipCount > 0 && (
        <div className="consequence">
          <span>
            The current {plural(clipCount, "clip")} {clipCount === 1 ? "is" : "are"} replaced. Edits and versions
            of {clipCount === 1 ? "it" : "them"} are lost. Posts already on YouTube or TikTok stay there.
          </span>
        </div>
      )}
      <div className="field">
        <span className="label" id="remake-count">Clips at most</span>
        <Segmented labelledBy="remake-count" value={count} onChange={setCount}
          options={choices.map((n) => ({ value: n, label: String(n) }))} />
      </div>
      <div className="row wrap top">
        <div className="field" style={{ flex: "1 1 160px" }}>
          <label htmlFor="remake-min">Shortest clip (seconds)</label>
          <input id="remake-min" type="number" min={5} max={170} value={minD}
            aria-invalid={problem.includes("shortest") || undefined} onChange={(e) => setMinD(e.target.value)} />
        </div>
        <div className="field" style={{ flex: "1 1 160px" }}>
          <label htmlFor="remake-max">Longest clip (seconds)</label>
          <input id="remake-max" type="number" min={10} max={180} value={maxD}
            aria-invalid={problem.includes("longest") || undefined} onChange={(e) => setMaxD(e.target.value)} />
        </div>
      </div>
      {problem && <p className="error-text"><Icon name="alert" className="sm" />{problem}</p>}
    </ConfirmDialog>
  );
}

/**
 * Export one clip: its MP4, or a ZIP with the MP4, its captions (SRT) and its post text. Both use the version
 * chosen for export and posts (the backend falls back to the original while that version isn't rendered).
 */
export function ExportDialog({ clip, onClose }: { clip: Clip; onClose: () => void }) {
  const [data, setData] = useState<{ active: string; versions: ClipVersion[] } | null>(null);
  const [err, setErr] = useState("");
  const [kind, setKind] = useState<"mp4" | "zip">("mp4");
  useEffect(() => {
    api.versions(clip.id).then(setData).catch((e) => setErr(errorText(e)));
  }, [clip.id]);
  const chosen = data?.versions.find((v) => v.id === data.active && v.id && v.status === "ready" && v.has_video);
  const used = chosen || data?.versions.find((v) => v.id === "");
  return (
    <ConfirmDialog title="Export clip" confirmLabel="Download" disabled={!data} onClose={onClose}
      onConfirm={async () => {
        if (kind === "zip") {
          await downloadZip(clip.project_id, [clip.id]);
        } else {
          const a = document.createElement("a");
          a.href = versionDownloadUrl(clip, chosen);
          a.download = "";
          document.body.appendChild(a);
          a.click();
          a.remove();
        }
        toast("Download started");
      }}>
      <p className="muted small">
        “{clip.title}”{used ? `, the version used for export and posts (${used.label}).` : "."}
      </p>
      {err && <p className="error-text"><Icon name="alert" className="sm" />{err}</p>}
      <fieldset>
        <legend className="sr-only">What to download</legend>
        <label className="choice-card">
          <input type="radio" name="export-kind" checked={kind === "mp4"} onChange={() => setKind("mp4")} />
          <span className="stack" style={{ gap: 2 }}>
            <b>MP4 video</b><span className="small muted">The vertical video, ready to upload anywhere.</span>
          </span>
        </label>
        <label className="choice-card">
          <input type="radio" name="export-kind" checked={kind === "zip"} onChange={() => setKind("zip")} />
          <span className="stack" style={{ gap: 2 }}>
            <b>ZIP with the video and its text</b>
            <span className="small muted">
              The MP4, its captions as an SRT file, and its title, caption and hashtags.
            </span>
          </span>
        </label>
      </fieldset>
    </ConfirmDialog>
  );
}

// ------------------------------------------------------------------ the posts of a clip (Autopilot's planned posts)
const POST_WORD: Record<ScheduledItem["status"], string> = {
  awaiting_approval: "needs your OK",
  approved: "approved",
  publishing: "uploading now",
  reconciling: "upload not confirmed",
  published: "published",
  failed: "failed",
  canceled: "canceled",
  replaced: "replaced by a stronger clip",
  blocked: "blocked by the final check",
  action_needed: "finish in the TikTok app",
};

/** "YouTube: needs your OK". An approval that no longer matches the file says so. */
export function postWord(x: ScheduledItem): string {
  if (x.status === "approved" && x.approval_valid === false) return "needs your OK again";
  return POST_WORD[x.status] || x.status;
}

/**
 * Posts per clip, joined on the page from Autopilot's list (the backend has no per-clip filter). Null while
 * loading or when the list is not available, so nothing is claimed then.
 */
export function useClipPosts(deps: unknown[] = []): Map<string, ScheduledItem[]> | null {
  const [map, setMap] = useState<Map<string, ScheduledItem[]> | null>(null);
  useEffect(() => {
    let alive = true;
    ap.scheduled("all").then((r) => {
      if (!alive) return;
      const m = new Map<string, ScheduledItem[]>();
      for (const x of r.items) {
        if (x.status === "canceled" || x.status === "replaced") continue;
        m.set(x.clip_id, [...(m.get(x.clip_id) || []), x]);
      }
      setMap(m);
    }).catch(() => alive && setMap(null));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return map;
}

export const PLATFORM: Record<string, string> = { youtube: "YouTube", tiktok: "TikTok" };
