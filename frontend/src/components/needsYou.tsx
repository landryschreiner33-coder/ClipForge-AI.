import { ReactNode, useState } from "react";
import { errorText } from "../api";
import { ap, AutopilotStatus, NeedsYouItem } from "../autopilot";
import { ConnectAction, OpenVideosFolder } from "./apShared";
import { ConfirmDialog, Icon, IconName, TextPromptDialog, toast } from "./ui";

/**
 * What needs you, as Autopilot reports it (autopilot/home.py `needs_you`, already in the order that matters:
 * stopped background work and account > sleep and GPU > rights > file > approve > publish > needs videos). Home shows the first one as its lead
 * card; Autopilot lists them all. Each item says what happened, what to do, and has its button when one exists.
 */

export type NeedTone = "bad" | "warn" | "info";
const LOOK: Record<NeedsYouItem["type"], [NeedTone, IconName]> = {
  account: ["bad", "link"], sleep: ["bad", "moon"], gpu: ["bad", "cpu"], rights: ["warn", "question"],
  file: ["warn", "folder"], approve: ["warn", "clock"], publish: ["warn", "alert"], videos: ["info", "folder"],
  stopped: ["bad", "stop"], other: ["warn", "alert"],
};
export const needLook = (i: NeedsYouItem): [NeedTone, IconName] => LOOK[i.type] || ["warn", "alert"];

/** The backend still names the older addresses; they redirect, but a link should say where it really goes. */
const NEW_ADDRESS: [RegExp, string][] = [
  [/^#\/publish-center\/problems$/, "#/queue/problems"],
  [/^#\/publish-center.*$/, "#/queue/review"],
];
const address = (link?: string) => {
  if (!link) return "";
  for (const [re, to] of NEW_ADDRESS) if (re.test(link)) return to;
  return link;
};
const LINK_LABEL: Partial<Record<NeedsYouItem["type"], string>> = {
  approve: "Review posts", publish: "Open problems", gpu: "Open GPU settings", stopped: "See details",
  other: "See details",
};

const PATH_HINT = "For example C:\\Users\\you\\Videos\\talk.mp4";

/**
 * The buttons of one item. `primary` makes its main button orange (only the first item on a page); `first` shows
 * only the main button (the short "Also needs you" list).
 */
export function NeedActions({ item, platforms, refresh, primary, first }: {
  item: NeedsYouItem; platforms: AutopilotStatus["platforms"]; refresh: () => void; primary?: boolean; first?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState<"" | "yes" | "file">("");
  const act = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try {
      await fn();
      toast(done);
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
    refresh();
  };
  const cls = (main: boolean) => `btn btn-small ${main && primary ? "btn-primary" : ""}`;
  const src = item.source;
  const view = src?.url
    ? <a key="view" className="btn btn-small btn-quiet" href={src.url} target="_blank" rel="noreferrer">
        <Icon name="external" />View the video<span className="sr-only"> (opens a new tab)</span></a>
    : null;
  const notNow = <button key="dismiss" type="button" className="btn btn-small btn-quiet" disabled={busy}
    onClick={() => act(() => ap.dismiss(item.key), "Hidden for now")}>Not now</button>;

  let buttons: ReactNode[] = [];
  if (item.type === "account" && item.platform) {
    buttons = [<ConnectAction key="connect" platform={item.platform} account={platforms[item.platform]}
      reconnect={item.title.startsWith("Reconnect")} onChange={refresh} />];
  } else if (item.type === "rights" && src) {
    buttons = [
      <button key="yes" type="button" className={cls(true)} disabled={busy} onClick={() => setAsking("yes")}>
        Yes, I have permission…</button>,
      <button key="no" type="button" className="btn btn-small" disabled={busy}
        onClick={() => act(() => ap.permission(src.id, false), "Got it: this video is never used")}>
        No, don't use it</button>,
      view,
    ];
  } else if (item.type === "file" && src) {
    buttons = [
      <button key="file" type="button" className={cls(true)} disabled={busy} onClick={() => setAsking("file")}>
        Add the video file…</button>,
      <button key="skip" type="button" className="btn btn-small" disabled={busy}
        onClick={() => act(() => ap.skipSource(src.id), "Skipped: Autopilot moves on")}>Skip this video</button>,
      view,
    ];
  } else if (item.type === "videos") {
    buttons = [
      <OpenVideosFolder key="open" primary={primary} small onDone={refresh} />,
      <a key="add" className="btn btn-small" href="#/create"><Icon name="plus" />Add a video yourself</a>,
    ];
  } else if (item.type === "sleep") {
    // Nothing to press: it goes away by itself once Windows keeps the PC awake, or Autopilot is turned off. The
    // short list (Home) has no room for the steps, so it links to Autopilot, where the item shows them.
    buttons = first ? [<a key="steps" className="btn btn-small" href="#/missions">See what to do</a>] : [];
  } else {
    const link = address(item.link);
    buttons = [
      link ? <a key="open" className={cls(true)} href={link}>{LINK_LABEL[item.type] || "Open"}</a> : null,
      notNow,
    ];
  }
  const shown = (first ? buttons.slice(0, 1) : buttons).filter(Boolean);
  if (!shown.length && !asking) return null;
  return (
    <>
      {shown}
      {asking === "yes" && src && (
        <ConfirmDialog title="Do you have permission to use this video?" confirmLabel="Yes, I have permission"
          onClose={() => setAsking("")} onConfirm={async () => {
            await ap.permission(src.id, true);
            toast("Thanks: Autopilot will use it");
            refresh();
          }}>
          <p className="muted">“{src.title}”{src.channel ? ` from ${src.channel}` : ""}.</p>
          <p className="small">Autopilot will clip this video and plan posts from it. Only say yes if the creator gave
            you permission, for example through a clipping program you joined. Being public or trending does not make a
            video reusable.</p>
        </ConfirmDialog>
      )}
      {asking === "file" && src && (
        <TextPromptDialog title="Add the video file" label="Full path of the video file on this computer"
          hint={PATH_HINT}
          placeholder="C:\Users\you\Videos\talk.mp4" confirmLabel="Add file" onClose={() => setAsking("")}
          onSubmit={async (path) => {
            await ap.attachFile(src.id, path);
            toast("File added: Autopilot will clip it");
            refresh();
          }}>
          <p className="small muted">ClipFoundry does not download videos from YouTube or other platforms by itself
            (their terms). Choose the original file on this computer; for your own videos, YouTube Studio → Download
            gives you one.</p>
        </TextPromptDialog>
      )}
    </>
  );
}

/** One row of the Needs you list: icon, title, detail, what to do, and its buttons. */
export function NeedRow({ item, platforms, refresh, first }: {
  item: NeedsYouItem; platforms: AutopilotStatus["platforms"]; refresh: () => void; first: boolean;
}) {
  const [tone, icon] = needLook(item);
  const src = item.source;
  return (
    <div className={`need ${tone}`} data-type={item.type}>
      <Icon name={icon} />
      <div className="need-body">
        <span className="need-title">{item.title}</span>
        {src && item.type === "rights" && (
          <span className="small">
            “{src.title}”{src.channel ? <span className="muted"> · {src.channel}</span> : null}
          </span>
        )}
        {item.question && <span className="small strong">{item.question}</span>}
        {item.detail && <span className="small muted">{item.detail}</span>}
        {item.fix && <span className="small"><b>What to do:</b> {item.fix}</span>}
      </div>
      <div className="need-actions">
        <NeedActions item={item} platforms={platforms} refresh={refresh} primary={first} />
      </div>
    </div>
  );
}

/** Every item; only the first one gets the primary button, so one thing stands out. */
export function NeedsYouList({ items, platforms, refresh }: {
  items: NeedsYouItem[]; platforms: AutopilotStatus["platforms"]; refresh: () => void;
}) {
  if (!items.length) {
    return <p className="muted">Nothing right now. Autopilot asks here only when it really needs you.</p>;
  }
  return (
    <div className="rows">
      {items.map((i, n) => <NeedRow key={i.key} item={i} platforms={platforms} refresh={refresh} first={n === 0} />)}
    </div>
  );
}
