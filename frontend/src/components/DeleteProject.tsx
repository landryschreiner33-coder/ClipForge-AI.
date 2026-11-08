import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, errorText, req } from "../api";
import { useAppearance } from "../prefs";
import { Banner, Dialog, Icon, toast } from "./ui";
import "./DeleteProject.css";

/** The two kinds of project the Projects page lists. */
export type ProjectKind = "clips" | "full_video";

/** What deleting a project does, in ClipForge's own words (clipfoundry/studio/project_delete.py). */
export type DeletePlan = {
  id: string; kind: ProjectKind; name: string;
  /** Why it can't be deleted right now (Autopilot or a post is still busy with it); "" when it can. */
  blocked: string;
  /** Work still running on it, which deleting stops first; "" when there is none. */
  working: string;
  goes: string[]; stays: string[]; freed_bytes: number; counts: Record<string, number>;
};

const where = (kind: ProjectKind, id: string) =>
  kind === "clips" ? `/api/projects/${encodeURIComponent(id)}` : `/api/studio/videos/${encodeURIComponent(id)}`;

export const projectDelete = {
  plan: (kind: ProjectKind, id: string) => req<DeletePlan>("GET", `${where(kind, id)}/delete-plan`),
  remove: (kind: ProjectKind, id: string) => req<DeletePlan & { ok: boolean; deleted: boolean }>("DELETE", where(kind, id)),
};

const STOP_WAIT_MS = 90_000;  // how long the window keeps asking while ClipForge stops the project's work
const pause = (ms: number) => new Promise((done) => window.setTimeout(done, ms));

/**
 * Delete a project after saying exactly what goes and what stays. Work running on it is stopped first (the window
 * keeps asking until it has stopped); while Autopilot or a post is busy with it, the window says why it has to wait.
 */
export function DeleteProjectConfirm({ kind, id, name, onClose, onDeleted }: {
  kind: ProjectKind; id: string; name: string; onClose: () => void; onDeleted: (id: string) => void;
}) {
  const { saved, set } = useAppearance();
  const [plan, setPlan] = useState<DeletePlan | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState<"" | "deleting" | "stopping">("");
  const open = useRef(true);
  useEffect(() => () => {
    open.current = false;
  }, []);

  const load = useCallback(async () => {
    setProblem("");
    try {
      const p = await projectDelete.plan(kind, id);
      if (open.current) setPlan(p);
    } catch (e) {
      if (open.current) setProblem(errorText(e));
    }
  }, [kind, id]);
  useEffect(() => {
    void load();
  }, [load]);

  const gone = (already: boolean) => {
    // the server takes it off the pinned list too; this keeps this page's copy of the list the same
    if (saved.pinned.includes(id)) set({ pinned: saved.pinned.filter((x) => x !== id) });
    toast(already ? `“${name}” was already deleted` : `Deleted “${name}”`);
    onDeleted(id);
    if (open.current) onClose();
  };

  const go = async () => {
    setBusy("deleting");
    setProblem("");
    const end = Date.now() + STOP_WAIT_MS;
    for (;;) {
      try {
        await projectDelete.remove(kind, id);
        gone(false);
        return;
      } catch (e) {
        const code = e instanceof ApiError ? e.code : "";
        if (code === "not_found") {
          gone(true);
          return;
        }
        if (!open.current) return;  // closed while waiting: what was stopped stays stopped, nothing else changes
        if (code === "stopping" && Date.now() < end) {
          setBusy("stopping");
          await pause(2000);
          if (!open.current) return;
          continue;
        }
        setProblem(errorText(e));
        setBusy("");
        if (code === "blocked") void load();
        return;
      }
    }
  };

  const blocked = plan?.blocked || "";
  const canDelete = !!plan && !blocked;
  return (
    <Dialog title={`Delete “${name}”?`} onClose={onClose} actions={<>
      {blocked && <button type="button" className="btn" onClick={() => void load()}>Check again</button>}
      <button type="button" className="btn" onClick={onClose}>{canDelete ? "Keep it" : "Close"}</button>
      {canDelete && (
        <button type="button" className="btn btn-danger" disabled={!!busy} onClick={go}>
          {busy && <span className="inline-spinner" aria-hidden="true" />}
          <Icon name="trash" className="sm" />
          {busy === "stopping" ? "Stopping its work…" : busy ? "Deleting…" : "Delete project"}
        </button>
      )}
    </>}>
      {!plan && !problem && (
        <p className="muted del-checking"><span className="inline-spinner" aria-hidden="true" />Checking what deleting it removes…</p>
      )}
      {blocked && <Banner tone="warn" title="It can't be deleted right now">{blocked}</Banner>}
      {canDelete && (
        <div className="del-plan">
          {plan.working && <Banner tone="info" icon="clock">{plan.working}</Banner>}
          <section aria-labelledby={`del-goes-${id}`}>
            <h3 id={`del-goes-${id}`} className="del-head bad"><Icon name="trash" className="sm" />Deleted for good</h3>
            <ul className="del-list">{plan.goes.map((line) => <li key={line}>{line}</li>)}</ul>
          </section>
          <section aria-labelledby={`del-stays-${id}`}>
            <h3 id={`del-stays-${id}`} className="del-head"><Icon name="check" className="sm" />Stays</h3>
            <ul className="del-list">{plan.stays.map((line) => <li key={line}>{line}</li>)}</ul>
          </section>
          <p className="small"><b>This can't be undone.</b></p>
        </div>
      )}
      {busy === "stopping" && (
        <p className="small muted" role="status">
          ClipForge is stopping the work on it first. It deletes the project as soon as that has stopped.
        </p>
      )}
      {problem && <p className="error-text" role="alert"><Icon name="alert" className="sm" />{problem}</p>}
    </Dialog>
  );
}

/** The trash button on a project's card; it opens the confirmation, so nothing is deleted by one click. */
export function DeleteProjectButton({ name, onClick }: { name: string; onClick: () => void }) {
  return (
    <button type="button" className="lib-del-btn" onClick={onClick} aria-label={`Delete ${name}`} title="Delete project">
      <Icon name="trash" size={14} />
    </button>
  );
}
