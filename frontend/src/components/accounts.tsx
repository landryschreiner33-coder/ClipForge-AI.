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
