import { useEffect, useId, useRef, useState } from "react";
import { Accounts, api, errorText, Platform, PlatformAccount } from "../api";
import { ConfirmDialog, Disclosure, Icon, Pill, toast } from "./ui";

export const PLATFORM_NAME: Record<Platform, string> = { youtube: "YouTube", tiktok: "TikTok" };

/**
 * Connect, Reconnect or Disconnect… for one platform. Connecting opens the platform's own sign-in page in a new tab
 * (OAuth): ClipFoundry never sees the password; the tab reports back through the local callback and this button
 * notices the new connection. Disconnecting asks first and says what it does.
 */
export function ConnectButton({ platform, account, onChange, beforeConnect, big }: {
  platform: Platform;
  account?: PlatformAccount;
  onChange: (a: Accounts) => void;
  beforeConnect?: () => Promise<void>;
  big?: boolean;
}) {
  const name = PLATFORM_NAME[platform];
  const [waiting, setWaiting] = useState(false);
  const [asking, setAsking] = useState(false);
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
            toast(`${name} connected: ${acc.name}`);
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

  if (account?.connected && !account.needs_reconnect) {
    return (
      <>
        <button type="button" className="btn btn-small" onClick={() => setAsking(true)}>Disconnect…</button>
        {asking && (
          <ConfirmDialog title={`Disconnect ${name}?`} confirmLabel={`Disconnect ${name}`} cancelLabel="Stay connected"
            danger
            onClose={() => setAsking(false)}
            onConfirm={async () => {
              onChange(await api.disconnect(platform));
              toast(`${name} disconnected`);
            }}>
            <p className="muted">
              ClipFoundry asks {name} to revoke its access and deletes the stored sign-in. Nothing already posted is
              removed. Planned {name} posts can't go out until you connect again, and their numbers stop updating.
            </p>
          </ConfirmDialog>
        )}
      </>
    );
  }
  const can = !!account?.configured || !!beforeConnect;
  const label = account?.needs_reconnect ? `Reconnect ${name}` : `Connect ${name}`;
  return (
    <button type="button" className={`btn btn-primary ${big ? "" : "btn-small"}`}
      aria-disabled={waiting || !can || undefined}
      title={can ? undefined : `Paste your ${name} app codes first`}
      onClick={() => {
        if (waiting) return;
        if (!can) toast(`Paste your ${name} app codes first (Settings, Accounts).`, true);
        else connect();
      }}>
      {waiting ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="link" />}
      {waiting ? `Waiting for you to sign in to ${name}…` : label}
    </button>
  );
}

/** The account's state as a pill: icon plus word, never color alone. */
export function AccountBadge({ account }: { platform: Platform; account?: PlatformAccount }) {
  if (!account) return null;
  if (account.connected && !account.needs_reconnect) {
    return (
      <span className="account">
        {account.avatar && (
          <img src={account.avatar} alt="" referrerPolicy="no-referrer"
            onError={(e) => { e.currentTarget.style.display = "none"; }} />
        )}
        <Pill tone="good" icon="check">Connected: {account.name || account.account_id}</Pill>
      </span>
    );
  }
  if (account.needs_reconnect) return <Pill tone="bad" icon="alert">Sign-in expired: connect again</Pill>;
  return <Pill tone="neutral" icon="link">{account.configured ? "Not connected" : "Not set up"}</Pill>;
}

/** How to create your own free Google Cloud app for YouTube publishing (ClipFoundry has no shared app). */
export function YouTubeSetupSteps({ testingNote }: { testingNote?: string }) {
  return (
    <div className="setup">
      <ol>
        <li>Open <b>console.cloud.google.com</b> and create a project (any name).</li>
        <li>In <b>APIs &amp; Services, Library</b>, enable <b>YouTube Data API v3</b>. Optional: also enable <b>YouTube
          Analytics API</b> so ClipFoundry can read the watch time and retention of your videos.</li>
        <li>On the <b>OAuth consent screen</b>, choose <i>External</i>, fill in the app name and your e-mail, and add
          your Google account under <i>Test users</i> for initial testing. For continuous posting, change the
          publishing status to <b>Production</b> before connecting again; Testing sign-ins expire after seven days.</li>
        <li>In <b>Credentials, Create credentials, OAuth client ID</b>, choose the application type <b>Desktop app</b>.
          Copy the client ID and client secret into the fields here and save.</li>
        <li>Press <b>Connect YouTube</b>, sign in with Google and allow access. Google may say “Google hasn't verified
          this app”: it is your own app, so choose <i>Continue</i>.</li>
      </ol>
      {testingNote && <p className="small muted">{testingNote}</p>}
      <p className="small muted">
        Public uploads do not require YouTube's API audit under its current documentation. The app checks the
        returned visibility. An API audit is needed to request more quota; uploads use your project's daily allowance.
      </p>
    </div>
  );
}

/** How to create your own free TikTok developer app. */
export function TikTokSetupSteps() {
  return (
    <div className="setup">
      <ol>
        <li>Sign in at <b>developers.tiktok.com</b> and create an app (any name, category “Video”).</li>
        <li>Add the products <b>Login Kit</b> (platform <i>Desktop</i>) and <b>Content Posting API</b>. In Content
          Posting API, turn on <b>Direct Post</b> if you want to post directly.</li>
        <li>Add the scopes <code>user.info.basic</code>, <code>video.upload</code>, <code>video.publish</code> (Direct
          Post) and <code>video.list</code> (statistics).</li>
        <li>In Login Kit, register the redirect address shown here. If you start ClipFoundry on another port, register
          that port too.</li>
        <li>While the app is not reviewed, create a <b>Sandbox</b> in it and add your TikTok account as a target user
          (there Direct Post can only post “Only me”). Paste the client key and secret here and save.</li>
        <li>Press <b>Connect TikTok</b>, sign in on TikTok's page and allow access.</li>
      </ol>
      <p className="small muted">
        Until TikTok audits your app, Direct Post only works when your TikTok account is private, every post is
        “Only me”, and at most 5 users can post a day. <b>Send to TikTok inbox</b> needs no audit, but TikTok must
        have approved your app for it; the video arrives as a draft and you choose the confirmed audience in TikTok.
        Public posts need Everyone and an account that allows it. TikTok's rules
        turn down apps for personal use, so expect to post clips yourself: ClipFoundry prepares each one (video,
        caption, who to post it for) in the Queue.
      </p>
    </div>
  );
}

/**
 * Connect an account on a computer where the platform is not set up yet: paste the two codes of your own free
 * developer app once, then sign in. With the platform set up, this is just the Connect button.
 */
export function SetupAndConnect({ platform, account, onChange }: {
  platform: Platform;
  account?: PlatformAccount;
  onChange: (a: Accounts) => void;
}) {
  const [id, setId] = useState("");
  const [secret, setSecret] = useState("");
  const uid = useId();
  const yt = platform === "youtube";
  const name = PLATFORM_NAME[platform];
  const redirect = account?.redirect_uri || `${window.location.origin}/api/oauth/tiktok/callback`;
  const save = async () => {
    if (!id.trim() || !secret.trim()) throw new Error(`Paste both codes of your ${name} app first.`);
    await api.saveSettings(yt ? { youtube_client_id: id.trim(), youtube_client_secret: secret.trim() }
      : { tiktok_client_key: id.trim(), tiktok_client_secret: secret.trim() });
    setSecret(""); // stored encrypted now; the page doesn't keep it any longer than needed
  };
  return (
    <div className="stack-3">
      <p className="small">
        {name} only lets apps like ClipFoundry post through <b>your own free developer app</b>. Create it once (steps
        below), paste its two codes here, then sign in. ClipFoundry never sees your password.
      </p>
      <div className="field">
        <label htmlFor={`${uid}-id`}>{yt ? "OAuth client ID" : "Client key"}</label>
        <input id={`${uid}-id`} type="text" autoComplete="off" spellCheck={false} value={id}
          placeholder={yt ? "1234567890-abc.apps.googleusercontent.com" : ""} onChange={(e) => setId(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor={`${uid}-secret`}>
          Client secret <span className="hint">stored encrypted and never shown again</span>
        </label>
        <input id={`${uid}-secret`} type="password" autoComplete="new-password" spellCheck={false} value={secret}
          onChange={(e) => setSecret(e.target.value)} />
      </div>
      {!yt && (
        <p className="small muted">
          Redirect address to register in your TikTok app: <code className="uri break">{redirect}</code>
        </p>
      )}
      <div className="row wrap">
        <ConnectButton platform={platform} account={account} onChange={onChange} beforeConnect={save} big />
      </div>
      <Disclosure plain summary="How to get these codes (free, about 10 minutes)">
        {yt ? <YouTubeSetupSteps testingNote={account?.testing_note} /> : <TikTokSetupSteps />}
      </Disclosure>
    </div>
  );
}
