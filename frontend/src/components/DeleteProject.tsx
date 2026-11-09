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

/** What a delete answers: the same words, and whether some files were in use (they go at the next start). */
export type DeleteResult = DeletePlan & { ok: boolean; deleted: boolean; left_behind?: boolean };

const where = (kind: ProjectKind, id: string) =>
  kind === "clips" ? `/api/projects/${encodeURIComponent(id)}` : `/api/studio/videos/${encodeURIComponent(id)}`;

export const projectDelete = {
  plan: (kind: ProjectKind, id: string) => req<DeletePlan>("GET", `${where(kind, id)}/delete-plan`),
  remove: (kind: ProjectKind, id: string) => req<DeleteResult>("DELETE", where(kind, id)),
};

const STOP_WAIT_MS = 90_000;  // how long the window keeps asking while ClipForge stops the project's work
const pause = (ms: number) => new Promise((done) => window.setTimeout(done, ms));
const codeOf = (e: unknown) => (e instanceof ApiError ? e.code : "");

/**
 * Delete a project after saying exactly what goes and what stays. Work running on it is stopped first (the window
 * keeps asking until it has stopped); while Autopilot or a post is busy with it, the window says why it has to wait.
 * Once Delete is pressed the window stays open until there is an answer, so closing it never looks like "kept".
 */
export function DeleteProjectConfirm({ kind, id, name, onClose, onDeleted }: {
  kind: ProjectKind; id: string; name: string; onClose: () => void; onDeleted: (id: string) => void;
}) {
  const { forgetPin } = useAppearance();
  const [plan, setPlan] = useState<DeletePlan | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState<"" | "deleting" | "stopping">("");
  const open = useRef(true);
  useEffect(() => {
    open.current = true;  // set again on every mount: React's development mode mounts twice
    return () => {
      open.current = false;
    };
  }, []);

  const gone = (already: boolean, left = false) => {
    forgetPin(id);
    toast(already ? `“${name}” was already deleted`
      : left ? `Deleted “${name}”. A few of its files were open in another program; ClipForge removes them the next time it starts.`
        : `Deleted “${name}”`);
    onDeleted(id);
    if (open.current) onClose();
  };
  const goneRef = useRef(gone);
  goneRef.current = gone;

  const load = useCallback(async () => {
    try {
      const p = await projectDelete.plan(kind, id);
      if (open.current) setPlan(p);
    } catch (e) {
      if (!open.current) return;
      if (codeOf(e) === "not_found") goneRef.current(true);  // deleted elsewhere in the meantime
      else setProblem(errorText(e));
    }
  }, [kind, id]);
  useEffect(() => {
    void load();
  }, [load]);

  const go = async () => {
    setBusy("deleting");
    setProblem("");
    const end = Date.now() + STOP_WAIT_MS;
    for (;;) {
      try {
        const done = await projectDelete.remove(kind, id);
        gone(false, !!done.left_behind);
        return;
      } catch (e) {
        const code = codeOf(e);
        if (code === "not_found") {
          gone(true);
          return;
        }
        if (!open.current) return;  // the page was left: what was stopped stays stopped, nothing else changes
        if (code === "stopping" && Date.now() < end) {
          setBusy("stopping");
          await pause(2000);
          if (!open.current) return;
          continue;
        }
        setBusy("");
        if (code === "blocked") {
          // the reason shows at once (and is read out); what goes and stays is then checked again
          setPlan((p) => p && { ...p, blocked: errorText(e) });
          void load();
        } else {
          setProblem(errorText(e));
        }
        return;
      }
    }
  };

  const close = busy ? () => {} : onClose;  // Escape and a click outside wait for the answer too
  const blocked = plan?.blocked || "";
  const canDelete = !!plan && !blocked;
  return (
    <Dialog title={`Delete “${name}”?`} onClose={close} actions={<>
      {blocked && (
        <button type="button" className="btn" onClick={() => {
          setProblem("");
          void load();
        }}>Check again</button>
      )}
      <button type="button" className="btn" disabled={!!busy} onClick={close}>{canDelete ? "Keep it" : "Close"}</button>
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
      <div className="del-alert" role="alert">
        {blocked && <Banner tone="warn" title="It can't be deleted right now">{blocked}</Banner>}
      </div>
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
