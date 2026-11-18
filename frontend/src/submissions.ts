import { ApiError, req } from "./api";
import type { AutopilotLink } from "./autopilot";
import type { Connection } from "./studio";

/** A connected YouTube channel a submitted video or stream can upload to. */
export interface SubmissionChannel {
  id: string;
  account_id: string;
  name: string;
  avatar: string;
  is_default: boolean;
  post_by_default: boolean;
  /** Connected and signed in; otherwise `text` says why it can't be chosen. */
  ok: boolean;
  text: string;
}

export interface SubmissionSetup {
  /** The default channel (kept for older screens); `channels` lists every connected channel. */
  account_id: string;
  account_name: string;
  connected: boolean;
  channels: SubmissionChannel[];
  audience: { group_version: number; label: string; detail: string; confirmed: boolean };
  privacy: "private" | "public";
  can_upload: boolean;
  blocker: string;
  /** `text_many` is what the statement says (and saves) when more than one channel is ticked. */
  reuse_bases: { id: SubmissionOptions["reuse_basis"]; label: string; text: string; text_many?: string }[];
  input_mode: string;
}

export interface SubmissionOptions {
  auto_upload: boolean;
  /** The first chosen channel (older servers read only this one). */
  account_id: string;
  /** Every chosen channel, in the owner's order, each with the account behind it when it was chosen. */
  connections: { id: string; account_id: string }[];
  privacy: "private" | "public";
  made_for_kids: boolean | null;
  audience_version: number;
  reuse_basis: "owned" | "permission" | "legal_exception" | "";
  reuse_statement: string;
  agreed: boolean;
}

export interface Submission {
  id: string;
  auto_upload: boolean;
  account_id: string;
  /** The channels this request uploads to (one for a request made before channels could be chosen). */
  channels?: { id: string; name: string; account_id: string }[];
  privacy: "private" | "public";
  made_for_kids: boolean | null;
  created_at: number;
  status: "creating" | "local_ready" | "waiting" | "uploading" | "uploaded" | "needs_attention";
  hold_reason?: string;
  progress: { clips_ready: number; posts_waiting: number; posts_uploading: number;
    posts_uploaded: number; posts_failed: number };
}

export interface SubmittedVideo extends AutopilotLink { submission: Submission }

/** A stream added in Live streams: its recording, live clips and the uploads of its clips. */
export interface LiveStream extends SubmittedVideo {
  live: { recording: boolean; finishing: boolean; minutes: number; live_clips: number; ended: boolean;
    stopped: boolean };
}
export interface SubmissionResult { item: SubmittedVideo; already_added: boolean; submission: Submission }

/** The setup's channels in the shape the channel picker takes. */
export const channelRows = (setup: SubmissionSetup | null): Connection[] => (setup?.channels || []).map((c) => ({
  id: c.id, platform: "youtube", label: "YouTube", account_id: c.account_id, display_name: c.name, nickname: "",
  avatar: c.avatar, scopes: [], is_default: c.is_default, status: c.ok ? "connected" : "needs_reconnect",
  health: { state: c.ok ? "ok" : "needs_reconnect", text: c.text, action: c.ok ? "" : "reconnect" }, connected_at: 0,
  active_uploads: 0, post_by_default: c.post_by_default, postable: c.ok, can_direct_post: false, can_inbox: false,
}));

/** "A and B": the names of the channels a request uploads to. */
export const channelNames = (s: Submission) => (s.channels || []).map((c) => c.name || c.account_id);

const ROOT = "/api/autopilot/submissions";
export const submissions = {
  setup: () => req<SubmissionSetup>("GET", `${ROOT}/setup`),
  list: () => req<SubmittedVideo[]>("GET", ROOT),
  link: (url: string, options: SubmissionOptions, live = false) =>
    req<SubmissionResult>("POST", `${ROOT}/link`, { url, ...options, live }),
  live: () => req<LiveStream[]>("GET", `${ROOT}/live`),
  file: (file: File, options: SubmissionOptions, onProgress: (fraction: number) => void) =>
    new Promise<SubmissionResult>((resolve, reject) => {
      const form = new FormData();
      form.append("file", file);
      form.append("options", JSON.stringify(options));
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${ROOT}/file`);
      xhr.setRequestHeader("X-ClipFoundry", "1");
      xhr.upload.onprogress = event => {
        if (event.lengthComputable) onProgress(event.loaded / event.total);
      };
      xhr.onload = () => {
        try {
          const body = JSON.parse(xhr.responseText);
          if (xhr.status >= 200 && xhr.status < 300) resolve(body);
          else reject(new ApiError(typeof body.detail === "string" ? body.detail : "The video could not be added.",
            body.fix || "", body.code || ""));
        } catch {
          reject(new Error("The video could not be added. Check that ClipForge is still open."));
        }
      };
      xhr.onerror = () => reject(new Error("Could not reach ClipForge. Keep the app open and try again."));
      xhr.send(form);
    }),
};
