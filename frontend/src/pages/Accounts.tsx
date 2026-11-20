import { useCallback, useEffect, useRef, useState } from "react";
import { errorText } from "../api";
import { Banner, ConfirmDialog, Icon, PageHead, Skel, TextPromptDialog, toast } from "../components/ui";
import { accountName, isPostable } from "../components/channelPicker";
import { Connection, studio } from "../studio";
import "./Accounts.css";

/** A short word for an account's sign-in state; the full sentence from the server shows under it when it is not ok. */
const STATE_WORD: Record<string, string> = { ok: "Connected", disconnected: "Disconnected",
  needs_reconnect: "Sign-in expired" };

/**
 * Several YouTube channels and TikTok accounts at once. Adding one never replaces another.
 *
 * The space studio (2026-11-19): the default YouTube channel is the big card, with the satellite over the Earth beside
 * it (decoration); other channels and every TikTok account are rows. Each account's tools (tick for new posts, rename,
 * reconnect, make default, disconnect) open under its Manage button; a signed-out account shows Reconnect right away.
 */
export default function Accounts() {
  const [rows, setRows] = useState<Connection[] | null>(null);
  const [protection, setProtection] = useState("");
  const [problem, setProblem] = useState("");
  const [confirm, setConfirm] = useState<Connection | null>(null);
  const [renaming, setRenaming] = useState<Connection | null>(null);
  const [ticking, setTicking] = useState("");
  const [managing, setManaging] = useState("");
  // The satellite sends one signal pulse when an account newly reads Connected (after signing in or reconnecting).
  const [pulse, setPulse] = useState(0);
  const connected = useRef<Set<string> | null>(null);
  const load = useCallback(() => studio.connections().then((r) => {
    const ok = r.connections.filter((c) => c.health.state === "ok");
    const before = connected.current;
    connected.current = new Set(ok.map((c) => c.id));
    const fresh = before ? ok.filter((c) => !before.has(c.id)) : [];
    if (fresh.length) {
      setPulse((n) => n + 1);
      toast(fresh.length === 1 ? `${accountName(fresh[0])} is connected` : `${fresh.length} accounts are connected`);
    }
    setRows(r.connections);
    setProtection(r.protection);
  }).catch((e) => setProblem(errorText(e))), []);
  useEffect(() => {
    void load();
    const back = () => document.visibilityState === "visible" && void load();  // after the sign-in tab closes
    document.addEventListener("visibilitychange", back);
    window.addEventListener("focus", back);
    return () => {
      document.removeEventListener("visibilitychange", back);
      window.removeEventListener("focus", back);
    };
  }, [load]);
  const open = async (call: Promise<{ auth_url: string }>) => {
    try {
      const { auth_url } = await call;
      window.open(auth_url, "_blank", "noopener");
      toast("Finish signing in on the page that opened, then come back here.");
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  /** "Tick for new posts": whether this account starts ticked where you choose accounts. */
  const tick = async (r: Connection, on: boolean) => {
    setTicking(r.id);
    setRows((list) => list && list.map((x) => (x.id === r.id ? { ...x, post_by_default: on } : x)));
    try {
      await studio.patchConnection(r.id, { post_by_default: on });
      toast(on ? `${accountName(r)} starts ticked for new posts` : `${accountName(r)} starts unticked for new posts`);
    } catch (e) {
      toast(errorText(e), true);
    }
    setTicking("");
    await load();
  };
  const makeDefault = async (r: Connection) => {
    try {
      await studio.patchConnection(r.id, { make_default: true });
      await load();
      toast(`${accountName(r)} is now the default`);
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  const youtube = (rows || []).filter((r) => r.platform === "youtube");
  const tiktok = (rows || []).filter((r) => r.platform === "tiktok");
  const main = youtube.find((r) => r.is_default) || youtube[0];
  const others = youtube.filter((r) => r !== main);
  const tools = (r: Connection) => ({
    open: managing === r.id, onToggle: () => setManaging((id) => (id === r.id ? "" : r.id)),
    ticking: ticking === r.id, onTick: (on: boolean) => void tick(r, on), onReconnect: () => open(studio.reconnect(r.id)),
    onDefault: () => void makeDefault(r), onRename: () => setRenaming(r), onDisconnect: () => setConfirm(r),
  });
  const addYouTube = () => open(studio.addConnection("youtube"));
  const addTikTok = () => open(studio.addConnection("tiktok"));
  return (
    <div className="page acc-space">
      <PageHead title="Accounts" sub="Choose where each project publishes." />
      {problem && <Banner tone="bad" title="Accounts could not be loaded">{problem}</Banner>}
      <section className="acc-hero" aria-labelledby="acc-youtube">
        <span className="acc-art" aria-hidden="true">
          <img className="acc-earth" src="/space/orbit.png" alt="" width={694} height={426} />
          <span className="acc-sat">
            <img src="/space/satellite.png" alt="" width={415} height={180} />
            {pulse > 0 && <i key={pulse} className="acc-pulse" />}
          </span>
        </span>
        <h2 id="acc-youtube" className="acc-platform">
          <span className="acc-logo youtube" aria-hidden="true"><Icon name="play" fill /></span>
          {youtube.length > 1 ? "YouTube channels" : "YouTube channel"}
        </h2>
        {!rows ? <Skel className="acc-skel" /> : main ? (
          <>
            <div className="acc-main">
              <Avatar r={main} big />
              <div className="acc-main-words">
                <p className="acc-name">{accountName(main)}</p>
                {main.nickname && <p className="acc-real small">{main.display_name}</p>}
                <States r={main} />
              </div>
            </div>
            {main.health.state !== "ok" && <p className="acc-fix">{main.health.text}</p>}
            <div className="acc-actions">
              {main.health.state !== "ok" && <button type="button" className="btn btn-primary"
                onClick={() => open(studio.reconnect(main.id))}><Icon name="refresh" />Reconnect</button>}
              <ManageButton r={main} {...tools(main)} word="Manage channel" />
              <button type="button" className="btn btn-quiet acc-add" onClick={addYouTube}>
                <Icon name="plus" />Add YouTube account</button>
            </div>
            {managing === main.id && <Manage r={main} {...tools(main)} />}
          </>
        ) : (
          <div className="acc-none">
            <p className="acc-name">No channel connected yet</p>
            <p className="muted">Connect your YouTube channel so finished clips can upload to it.</p>
            <div className="acc-actions">
              <button type="button" className="btn btn-primary" onClick={addYouTube}><Icon name="plus" />Connect YouTube</button>
            </div>
          </div>
        )}
        {others.length > 0 && (
          <ul className="acc-rows" aria-label="Your other YouTube channels">
            {others.map((r) => <AccountRow key={r.id} r={r} {...tools(r)} />)}
          </ul>
        )}
      </section>
      <section className="acc-tiktok" aria-labelledby="acc-tiktok">
        <div className="acc-tiktok-head">
          <h2 id="acc-tiktok" className="acc-platform">
            <span className="acc-logo tiktok" aria-hidden="true">♪</span>TikTok</h2>
          {rows && !tiktok.length && <p className="acc-tiktok-none">No account connected</p>}
          <button type="button" className="btn btn-outline" onClick={addTikTok}>
            <Icon name="plus" />{tiktok.length ? "Add TikTok account" : "Connect TikTok"}</button>
        </div>
        {tiktok.length > 0 && (
          <ul className="acc-rows" aria-label="Your TikTok accounts">
            {tiktok.map((r) => <AccountRow key={r.id} r={r} {...tools(r)} />)}
          </ul>
        )}
      </section>
      {protection && (
        <p className="acc-store"><Icon name="lock" />Sign-in tokens are {protection}. ClipForge never sees your passwords.</p>
      )}
      {renaming && <TextPromptDialog title={`Rename ${renaming.display_name}`} label="Your name for this account"
        hint="Shown in ClipForge only; the channel itself is not renamed." initial={renaming.nickname || renaming.display_name}
        confirmLabel="Save name" onClose={() => setRenaming(null)} onSubmit={async (name: string) => {
          try { await studio.patchConnection(renaming.id, { nickname: name }); await load(); toast("Name saved"); }
          catch (e) { toast(errorText(e), true); }
          setRenaming(null);
        }} />}
      {confirm && <ConfirmDialog title={`Disconnect ${confirm.display_name}?`} danger confirmLabel="Disconnect"
        onClose={() => setConfirm(null)}
        onConfirm={async () => {
          try { await studio.disconnect(confirm.id); toast(`${confirm.display_name} disconnected`); }
          catch (e) { toast(errorText(e), true); }
          setConfirm(null);
          await load();
        }}>
        <p>Posts to this account pause until you reconnect it. Your other accounts and their posts are not affected.</p>
      </ConfirmDialog>}
    </div>
  );
}

type Tools = {
  open: boolean; onToggle: () => void; ticking: boolean; onTick: (on: boolean) => void; onReconnect: () => void;
  onDefault: () => void; onRename: () => void; onDisconnect: () => void;
};

function Avatar({ r, big = false }: { r: Connection; big?: boolean }) {
  const [failed, setFailed] = useState(false);
  const cls = `acc-avatar${big ? " big" : ""}`;
  if (!r.avatar || failed) return <span className={`${cls} none`} aria-hidden="true"><Icon name="user" /></span>;
  return <img src={r.avatar} alt="" className={cls} referrerPolicy="no-referrer" onError={() => setFailed(true)} />;
}

/** Connected (or what is wrong), Default, and uploads under way: each as a word with its sign. */
function States({ r }: { r: Connection }) {
  const ok = r.health.state === "ok";
  return (
    <p className="acc-states">
      <span className={ok ? "acc-ok" : "acc-warn"}><Icon name={ok ? "check" : "alert"} />
        {STATE_WORD[r.health.state] || r.health.text}</span>
      {r.is_default && <span className="acc-default"><Icon name="star" fill />Default</span>}
      {r.active_uploads > 0 && <span><Icon name="upload" />{r.active_uploads} uploading</span>}
    </p>
  );
}

function ManageButton({ r, open, onToggle, word = "Manage" }: Tools & { r: Connection; word?: string }) {
  return (
    <button type="button" className="btn btn-outline acc-manage-btn" aria-expanded={open}
      aria-controls={`acc-manage-${r.id}`} onClick={onToggle}>
      {word}<span className="sr-only"> {accountName(r)}</span><Icon name="chev" />
    </button>
  );
}

/** One account's tools, under its Manage button. */
function Manage({ r, ticking, onTick, onReconnect, onDefault, onRename, onDisconnect }: Tools & { r: Connection }) {
  return (
    <div id={`acc-manage-${r.id}`} className="acc-manage" role="group" aria-label={`Manage ${accountName(r)}`}>
      <label className="choice">
        <input type="checkbox" checked={r.post_by_default ?? r.is_default}
          disabled={!isPostable(r) || ticking} onChange={(e) => onTick(e.target.checked)} />
        <span>Tick for new posts
          {!isPostable(r) && <span className="muted"> (reconnect it to post again)</span>}</span>
      </label>
      <p className="small muted">Ticked accounts start ticked on Prepare post, Make clips and Missions. You can change it
        each time, or pick All.</p>
      <p className="small muted acc-id">{r.label} · {r.account_id}</p>
      <div className="row-actions">
        <button type="button" className="btn btn-small" onClick={onReconnect}><Icon name="refresh" />Reconnect</button>
        {!r.is_default && r.health.state === "ok" && (
          <button type="button" className="btn btn-small" onClick={onDefault}><Icon name="star" />Make default</button>
        )}
        <button type="button" className="btn btn-small" onClick={onRename}><Icon name="edit" />Rename</button>
        {r.status !== "disconnected" && (
          <button type="button" className="btn btn-small btn-danger" onClick={onDisconnect}>Disconnect</button>
        )}
      </div>
    </div>
  );
}

/** Another channel, or a TikTok account: one row, with its tools under Manage. */
function AccountRow({ r, ...t }: Tools & { r: Connection }) {
  return (
    <li className="acc-row">
      <div className="acc-row-line">
        <Avatar r={r} />
        <div className="acc-row-words">
          <b>{accountName(r)}</b>
          <States r={r} />
        </div>
        {r.health.state !== "ok" && (
          <button type="button" className="btn btn-small btn-primary" onClick={t.onReconnect}>
            <Icon name="refresh" />Reconnect</button>
        )}
        <ManageButton r={r} {...t} />
      </div>
      {r.health.state !== "ok" && <p className="acc-fix small">{r.health.text}</p>}
      {t.open && <Manage r={r} {...t} />}
    </li>
  );
}
