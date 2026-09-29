import { useEffect, useRef, useState } from "react";
import { Accounts, api, errorText, Platform, PlatformAccount } from "../api";
import { Icon, toast } from "./ui";

export const PLATFORM_NAME: Record<Platform, string> = { youtube: "YouTube", tiktok: "TikTok" };

/**
 * Opens the platform's own sign-in page in a new tab (OAuth). ClipFoundry never sees the password; the tab reports
 * back through the local callback and this component notices the new connection.
 */
export function ConnectButton({ platform, account, onChange, beforeConnect, big }: {
  platform: Platform;
  account?: PlatformAccount;
  onChange: (a: Accounts) => void;
  beforeConnect?: () => Promise<void>;
  big?: boolean;
}) {
  const [waiting, setWaiting] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(timer.current), []);

  const connect = async () => {
    const tab = window.open("about:blank", "_blank"); // opened right away so pop-up blockers allow it
    try {
      await beforeConnect?.();
      const { auth_url } = await api.connect(platform);
      if (tab) tab.location.href = auth_url;
      else window.location.href = auth_url;
      setWaiting(true);
      const started = Date.now();
      const poll = async () => {
        try {
          const a = await api.accounts();
          const acc = a[platform];
          if (acc?.connected && acc.connected_at !== account?.connected_at) {
            setWaiting(false);
            onChange(a);
            toast(`${PLATFORM_NAME[platform]} connected: ${acc.name}`);
            return;
          }
        } catch {
          /* keep waiting */
        }
        if (Date.now() - started < 5 * 60_000) timer.current = setTimeout(poll, 2000);
        else setWaiting(false);
      };
      timer.current = setTimeout(poll, 2000);
    } catch (e) {
      tab?.close();
      toast(errorText(e), true);
    }
  };

  const disconnect = async () => {
    if (!window.confirm(`Disconnect ${PLATFORM_NAME[platform]}? ClipFoundry revokes its access and deletes the stored tokens.`)) return;
    try {
      onChange(await api.disconnect(platform));
      toast(`${PLATFORM_NAME[platform]} disconnected`);
    } catch (e) {
      toast(errorText(e), true);
    }
  };

  if (account?.connected && !account.needs_reconnect) {
    return <button className="btn ghost sm" onClick={disconnect}>Disconnect</button>;
  }
  const label = account?.needs_reconnect ? `RECONNECT ${PLATFORM_NAME[platform].toUpperCase()}` : `CONNECT ${PLATFORM_NAME[platform].toUpperCase()}`;
  return (
    <button className={`btn ${big ? "primary lg" : "primary"}`} disabled={waiting || (!account?.configured && !beforeConnect)} onClick={connect}
      title={account?.configured || beforeConnect ? "" : "Enter your app credentials first"}>
      <Icon name="link" size={16} /> {waiting ? "Waiting for sign-in..." : label}
    </button>
  );
}

export function AccountBadge({ platform, account }: { platform: Platform; account?: PlatformAccount }) {
  if (!account) return null;
  if (account.connected && !account.needs_reconnect) {
    return (
      <span className="account">
        {account.avatar ? <img src={account.avatar} alt="" referrerPolicy="no-referrer" /> : <Icon name="check" size={14} />}
        <span>Connected{platform === "youtube" ? " channel" : ""}: <b>{account.name || account.account_id}</b></span>
      </span>
    );
  }
  if (account.needs_reconnect) return <span className="badge warn">Connection expired: connect again</span>;
  return <span className="badge">{account.configured ? "Not connected" : "Not set up"}</span>;
}

/** How to create your own free Google Cloud app for YouTube publishing (ClipFoundry has no shared app). */
export function YouTubeSetupSteps({ testingNote }: { testingNote?: string }) {
  return (
    <>
      <ol>
        <li>Open <b>console.cloud.google.com</b> and create a project (any name).</li>
        <li><b>APIs &amp; Services → Library</b>: enable <b>YouTube Data API v3</b>. Optional: also enable <b>YouTube Analytics API</b> so ClipFoundry can read watch time and retention of your videos.</li>
        <li><b>OAuth consent screen</b>: choose <i>External</i>, fill in the app name and your e-mail, and add your Google account under <i>Test users</i>.</li>
        <li><b>Credentials → Create credentials → OAuth client ID</b>, application type <b>Desktop app</b>. Copy the client ID and client secret into the fields and save.</li>
        <li>Click <b>CONNECT YOUTUBE</b>, sign in with Google and allow access. Google may show “Google hasn't verified this app”: that is your own app, choose <i>Continue</i>.</li>
      </ol>
      {testingNote && <p className="small muted">{testingNote}</p>}
      <p className="small muted">
        Until Google audits your project, YouTube keeps every upload from it Private. Private uploads are fine for
        testing. Uploads count against your project's daily YouTube API quota.
      </p>
    </>
  );
}

/** How to create your own free TikTok developer app. */
export function TikTokSetupSteps() {
  return (
    <>
      <ol>
        <li>Sign in at <b>developers.tiktok.com</b> and create an app (any name, category "Video").</li>
        <li>Add the products <b>Login Kit</b> (platform <i>Desktop</i>) and <b>Content Posting API</b>. In Content Posting API, turn on <b>Direct Post</b> if you want to post directly.</li>
        <li>Add the scopes <code>user.info.basic</code>, <code>video.upload</code>, <code>video.publish</code> (Direct Post) and <code>video.list</code> (statistics).</li>
        <li>In Login Kit, register the redirect URI shown here. If you start ClipFoundry on another port, register that port too.</li>
        <li>Add your TikTok account as a <b>target user</b> (sandbox) while the app is not reviewed, paste the client key and secret and save.</li>
        <li>Click <b>CONNECT TIKTOK</b>, sign in on TikTok's page and allow access.</li>
      </ol>
      <p className="small muted">
        Until TikTok audits your app, Direct Post only works when your TikTok account is private, every post is
        “Only me”, and at most 5 users can post per day. <b>Send to TikTok inbox</b> works without the audit: the
        video arrives as a draft in the TikTok app and you post it from there. You can also export the clip and
        upload it on tiktok.com/tiktokstudio/upload.
      </p>
    </>
  );
}

/**
 * Connect an account on a computer where the platform is not set up yet: paste the two codes of your own free
 * developer app once, then sign in. With the platform set up, this is just the CONNECT button.
 */
export function SetupAndConnect({ platform, account, onChange }: {
  platform: Platform;
  account?: PlatformAccount;
  onChange: (a: Accounts) => void;
}) {
  const [id, setId] = useState("");
  const [secret, setSecret] = useState("");
  const yt = platform === "youtube";
  const redirect = `${window.location.origin}/api/oauth/tiktok/callback`;
  const save = async () => {
    if (!id.trim() || !secret.trim()) throw new Error(`Paste both codes of your ${PLATFORM_NAME[platform]} app first.`);
    await api.saveSettings(yt ? { youtube_client_id: id.trim(), youtube_client_secret: secret.trim() }
      : { tiktok_client_key: id.trim(), tiktok_client_secret: secret.trim() });
  };
  return (
    <div className="setup-connect">
      <p className="small">
        {PLATFORM_NAME[platform]} only lets apps like ClipFoundry post through <b>your own free developer app</b>. Create it
        once (steps below), paste its two codes here, then sign in. ClipFoundry never sees your password.
      </p>
      <label className="field">{yt ? "OAuth client ID" : "Client key"}
        <input type="text" value={id} placeholder={yt ? "1234567890-abc.apps.googleusercontent.com" : ""} onChange={(e) => setId(e.target.value)} />
      </label>
      <label className="field mt-s">Client secret
        <input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} />
      </label>
      {!yt && <div className="small muted mt-s">Redirect URI to register in your TikTok app: <code className="uri">{redirect}</code></div>}
      <div className="row mt"><ConnectButton platform={platform} account={account} onChange={onChange} beforeConnect={save} big /></div>
      <details className="setup">
        <summary>How to get these codes (free, about 10 minutes)</summary>
        {yt ? <YouTubeSetupSteps testingNote={account?.testing_note} /> : <TikTokSetupSteps />}
      </details>
    </div>
  );
}
