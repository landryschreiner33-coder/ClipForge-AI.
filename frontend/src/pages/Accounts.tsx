import { useCallback, useEffect, useState } from "react";
import { errorText } from "../api";
import { Banner, ConfirmDialog, EmptyState, Icon, PageHead, Pill, TextPromptDialog, toast } from "../components/ui";
import { Connection, studio } from "../studio";

/** Several YouTube channels and TikTok accounts at once. Adding one never replaces another. */
export default function Accounts() {
  const [rows, setRows] = useState<Connection[] | null>(null);
  const [protection, setProtection] = useState("");
  const [problem, setProblem] = useState("");
  const [confirm, setConfirm] = useState<Connection | null>(null);
  const [renaming, setRenaming] = useState<Connection | null>(null);
  const load = useCallback(() => studio.connections().then((r) => { setRows(r.connections); setProtection(r.protection); })
    .catch((e) => setProblem(errorText(e))), []);
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
  const groups: [string, string][] = [["youtube", "YouTube channels"], ["tiktok", "TikTok accounts"]];
  return (
    <div className="page">
      <PageHead kind="Publishing" title="Accounts" sub="Connect every channel and account you publish to. Each project chooses its own."
        actions={<><button type="button" className="btn" onClick={() => open(studio.addConnection("youtube"))}><Icon name="plus" />Add YouTube account</button>
          <button type="button" className="btn" onClick={() => open(studio.addConnection("tiktok"))}><Icon name="plus" />Add TikTok account</button></>} />
      {problem && <Banner tone="bad" title="Accounts could not be loaded">{problem}</Banner>}
      {protection && <p className="small muted">Sign-in tokens are {protection}. ClipForge never sees your passwords.</p>}
      {groups.map(([platform, title]) => {
        const list = (rows || []).filter((r) => r.platform === platform);
        return (
          <section key={platform} className="stack-3" aria-labelledby={`acc-${platform}`}>
            <h2 id={`acc-${platform}`}>{title}</h2>
            {rows && list.length === 0 ? <EmptyState icon="user" title="None connected" level={3}>Use Add {platform === "youtube" ? "YouTube" : "TikTok"} account.</EmptyState> : (
              <div className="acct-grid">{list.map((r) => (
                <article key={r.id} className="acct">
                  <div className="head">
                    {r.avatar ? <img src={r.avatar} alt="" className="avatar" referrerPolicy="no-referrer" onError={(e) => { e.currentTarget.removeAttribute("src"); }} /> : <span className="avatar" aria-hidden="true" />}
                    <div className="break"><b>{r.nickname || r.display_name || r.account_id}</b>
                      <span className="block small muted">{r.label}{r.nickname ? ` · ${r.display_name}` : ""} · {r.account_id}</span></div>
                  </div>
                  <div className="row-actions" style={{ justifyContent: "flex-start" }}>
                    <Pill tone={r.health.state === "ok" ? "good" : "warn"} icon={r.health.state === "ok" ? "check" : "alert"}>{r.health.text}</Pill>
                    {r.is_default && <Pill tone="accent">Default</Pill>}
                    {r.active_uploads > 0 && <Pill tone="info">{r.active_uploads} uploading</Pill>}
                  </div>
                  <div className="row-actions" style={{ justifyContent: "flex-start" }}>
                    <button type="button" className="btn btn-small" onClick={() => open(studio.reconnect(r.id))}><Icon name="refresh" />Reconnect</button>
                    {!r.is_default && r.health.state === "ok" && <button type="button" className="btn btn-small" onClick={async () => {
                      try { await studio.patchConnection(r.id, { make_default: true }); await load(); toast(`${r.display_name} is now the default`); }
                      catch (e) { toast(errorText(e), true); } }}>Make default</button>}
                    <button type="button" className="btn btn-small" onClick={() => setRenaming(r)}>Rename</button>
                    {r.status !== "disconnected" && <button type="button" className="btn btn-small btn-danger" onClick={() => setConfirm(r)}>Disconnect</button>}
                  </div>
                </article>))}</div>
            )}
          </section>
        );
      })}
      {renaming && <TextPromptDialog title={`Rename ${renaming.display_name}`} label="Your name for this account"
        hint="Shown in ClipForge only; the channel itself is not renamed." initial={renaming.nickname || renaming.display_name}
        confirmLabel="Save name" onClose={() => setRenaming(null)} onSubmit={async (name: string) => {
          try { await studio.patchConnection(renaming.id, { nickname: name }); await load(); toast("Name saved"); }
          catch (e) { toast(errorText(e), true); }
          setRenaming(null);
        }} />}
      {confirm && <ConfirmDialog title={`Disconnect ${confirm.display_name}?`} danger confirmLabel="Disconnect" onClose={() => setConfirm(null)}
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
