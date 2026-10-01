import { useState } from "react";
import { errorText, Platform, PlatformAccount } from "../api";
import { ap, UpcomingPost } from "../autopilot";
import { when } from "../format";
import { ConnectButton, PLATFORM_NAME, SetupAndConnect } from "./accounts";
import { Dialog, Icon, IconName, PlatformName, Pill, toast, Tone } from "./ui";

/** Parts shared by Home, Autopilot and Setup. */

export const PLATFORMS: Platform[] = ["youtube", "tiktok"];
export const connectedOk = (a?: PlatformAccount) => !!a?.connected && !a.needs_reconnect;

/**
 * Open videos folder: creates the folder if needed, watches it, and shows it in File Explorer. Where Explorer cannot
 * open (another system), the toast says where the folder is instead.
 */
export function OpenVideosFolder({ primary, small, onDone, label = "Open videos folder" }: {
  primary?: boolean; small?: boolean; onDone?: () => void; label?: string;
}) {
  const [busy, setBusy] = useState(false);
  const open = async () => {
    setBusy(true);
    try {
      const f = await ap.openMyVideos();
      toast(f.opened ? "Your videos folder is open. Put videos you made in it." : `Your videos folder is ${f.path}`);
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
    onDone?.();
  };
  return (
    <button type="button" className={`btn ${primary ? "btn-primary" : ""} ${small ? "btn-small" : ""}`} disabled={busy}
      onClick={open}>
      <Icon name="folder" />{label}
    </button>
  );
}

/**
 * Connect (or reconnect) an account. When this computer already has the platform's app codes, the platform's own
 * sign-in page opens; otherwise a dialog asks for the two codes of your own free developer app first.
 */
export function ConnectAction({ platform, account, onChange, reconnect }: {
  platform: Platform; account: PlatformAccount; onChange: () => void; reconnect?: boolean;
}) {
  const [setup, setSetup] = useState(false);
  // Always offered as a connect button here (never Disconnect): these places only ever ask you to connect.
  const acc = { ...account, connected: false, needs_reconnect: !!reconnect || account.needs_reconnect };
  if (account.configured) return <ConnectButton platform={platform} account={acc} onChange={onChange} />;
  const name = PLATFORM_NAME[platform];
  return (
    <>
      <button type="button" className="btn" onClick={() => setSetup(true)}>
        <Icon name="link" />{acc.needs_reconnect ? `Reconnect ${name}…` : `Connect ${name}…`}
      </button>
      {setup && (
        <Dialog title={`Connect ${name}`} wide onClose={() => setSetup(false)}
          actions={<button type="button" className="btn" onClick={() => setSetup(false)}>Close</button>}>
          <SetupAndConnect platform={platform} account={acc} onChange={() => { setSetup(false); onChange(); }} />
        </Dialog>
      )}
    </>
  );
}

/** A planned post's exact state, as a pill: never softened, and "approved" says by whom. */
export function upcomingStatus(u: UpcomingPost): [Tone, string, IconName] {
  if (u.on_platform) return ["info", "Uploaded, waiting for its time", "clock"];
  switch (u.status) {
    case "awaiting_approval": return ["warn", "Needs your OK", "clock"];
    case "approved":
      return u.auto ? ["good", "Approved automatically", "shield"] : ["good", "Approved by you", "check"];
    case "publishing": return ["info", "Uploading now", "upload"];
    case "reconciling": return ["warn", "Upload not confirmed", "question"];
    case "action_needed": return ["bad", "Needs you", "alert"];
    default: return ["neutral", u.status.replace(/_/g, " "), "info"];
  }
}

/** One planned post: its local time, the post's text, its platform and its exact state. */
export function UpcomingRow({ u, tz }: { u: UpcomingPost; tz: string }) {
  const [tone, word, icon] = upcomingStatus(u);
  return (
    <div className="upcoming-row" data-auto={u.auto ? "1" : "0"}>
      <span className="when">{u.planned_at ? when(u.planned_at, tz).replace(/^Today, /, "") : "No time yet"}</span>
      <span className="stack" style={{ gap: 4, minWidth: 0 }}>
        <a className="post-title clamp-2 small" href={`#/post/${u.id}`}>{u.title || "Untitled post"}</a>
        <span className="meta"><PlatformName platform={u.platform} /><Pill tone={tone} icon={icon}>{word}</Pill></span>
      </span>
    </div>
  );
}
