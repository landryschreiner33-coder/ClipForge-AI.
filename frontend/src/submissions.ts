import { ApiError, req } from "./api";
import type { AutopilotLink } from "./autopilot";

export interface SubmissionSetup {
  account_id: string;
  account_name: string;
  connected: boolean;
  audience: { group_version: number; label: string; detail: string; confirmed: boolean };
  privacy: "private" | "public";
  can_upload: boolean;
  blocker: string;
  reuse_bases: { id: SubmissionOptions["reuse_basis"]; label: string; text: string }[];
  input_mode: string;
}

export interface SubmissionOptions {
  auto_upload: boolean;
  account_id: string;
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
  privacy: "private" | "public";
  made_for_kids: boolean | null;
  created_at: number;
  status: "creating" | "local_ready" | "waiting" | "uploading" | "uploaded" | "needs_attention";
  hold_reason?: string;
  progress: { clips_ready: number; posts_waiting: number; posts_uploading: number;
    posts_uploaded: number; posts_failed: number };
}

export interface SubmittedVideo extends AutopilotLink { submission: Submission }
export interface SubmissionResult { item: SubmittedVideo; already_added: boolean; submission: Submission }

const ROOT = "/api/autopilot/submissions";
export const submissions = {
  setup: () => req<SubmissionSetup>("GET", `${ROOT}/setup`),
  list: () => req<SubmittedVideo[]>("GET", ROOT),
  link: (url: string, options: SubmissionOptions) => req<SubmissionResult>("POST", `${ROOT}/link`, { url, ...options }),
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
          reject(new Error("The video could not be added. Check that ClipFoundry is still open."));
        }
      };
      xhr.onerror = () => reject(new Error("Could not reach ClipFoundry. Keep the app open and try again."));
      xhr.send(form);
    }),
};
