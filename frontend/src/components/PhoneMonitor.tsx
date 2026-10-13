import { useEffect, useRef, useState } from "react";
import { errorText, req } from "../api";
import { SettingsPanel } from "./settingsFields";
import { Banner, Disclosure, Pill, toast } from "./ui";

type Mode = "tailscale" | "wifi";
interface Monitor {
  enabled: boolean; running: boolean; state: string; mode: Mode; address: string;
  bind_address: string; port: number; error: string; paired_devices: number;
  addresses: { mode: Mode; address: string }[];
}
interface Pairing { code: string; expires_at: number; address: string }
const ROOT = "/api/phone-monitor";

/** Owner-only controls for the separate, read-only phone listener. No secrets are put in its URL. */
export function PhoneMonitorPanel() {
  const [view, setView] = useState<Monitor | null>(null);
  const [mode, setMode] = useState<Mode>("tailscale");
  const [address, setAddress] = useState("");
  const [pair, setPair] = useState<Pairing | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now() / 1000);
  const generation = useRef(0);
  const pending = useRef(false);
  useEffect(() => {
    let mounted = true;
    const read = () => {
      if (document.hidden || pending.current) return;
      const expected = generation.current;
      req<Monitor>("GET", ROOT).then((v) => {
        if (!mounted || expected !== generation.current) return;
        setView(v); setError("");
        if (!v.running) setPair(null);
      }).catch((e) => { if (mounted && expected === generation.current) setError(errorText(e)); });
    };
    read();
    const timer = window.setInterval(read, 15_000);
    document.addEventListener("visibilitychange", read);
    return () => { mounted = false; clearInterval(timer); document.removeEventListener("visibilitychange", read); };
  }, []);
  useEffect(() => {
    if (!pair) return;
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(timer);
  }, [pair]);
  const action = async (path: string, body: unknown = {}) => {
    generation.current++; pending.current = true;
    setBusy(true); setError(""); setPair(null);
    try { setView(await req<Monitor>("POST", ROOT + path, body)); }
    catch (e) { setError(errorText(e)); }
    finally { pending.current = false; setBusy(false); }
  };
  const pairing = async () => {
    generation.current++; pending.current = true;
    setBusy(true); setError(""); setPair(null);
    try {
      setPair(await req<Pairing>("POST", ROOT + "/pairing", {}));
      setNow(Date.now() / 1000);
    } catch (e) { setError(errorText(e)); }
    finally { pending.current = false; setBusy(false); }
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(view?.address || ""); toast("Phone address copied"); }
    catch { toast("Select the address below and copy it", true); }
  };
  const activePair = pair && pair.expires_at > now && view?.running;
  const candidates = (view?.addresses || []).filter((a) => a.mode === mode);
  return (
    <SettingsPanel id="int-phone" title="Check from your phone"
      intro="A private, read-only dashboard for progress, today's posts and anything needing attention.">
      <div className="stack-4">
        <div className="row wrap" style={{ justifyContent: "space-between" }}>
          <Pill tone={view?.running ? "good" : "neutral"}>
            {view?.running ? "Phone dashboard is on" : "Phone dashboard is off"}
          </Pill>
          {view && <span className="small muted">{view.paired_devices} paired phones</span>}
        </div>
        {error && <Banner tone="bad" title="Phone connection needs attention">{error}</Banner>}
        {view?.error && <Banner tone="warn" title="Dashboard could not start">{view.error}</Banner>}
        {view?.running ? (
          <>
            <label className="stack" htmlFor="phone-url">Open this address on your phone
              <input id="phone-url" className="input" readOnly value={view.address}
                onFocus={(e) => e.target.select()} />
            </label>
            <p className="small muted">
              {view.mode === "tailscale" ? "Keep Tailscale connected on your PC and phone, using the same account."
                : "Use the same trusted Wi-Fi network as this PC. Wi-Fi mode uses unencrypted HTTP."}
              {" "}Keep ClipFoundry open and the PC awake.
            </p>
            <div className="row wrap">
              <button type="button" className="btn btn-small" onClick={copy}>Copy phone address</button>
              <button type="button" className="btn btn-primary btn-small" disabled={busy} onClick={pairing}>
                {activePair ? "New pairing code" : "Get pairing code"}
              </button>
              <button type="button" className="btn btn-small" disabled={busy} onClick={() => action("/disable")}>
                Turn off phone access
              </button>
            </div>
            {activePair && (
              <div className="banner info" aria-live="polite">
                <div>
                  <b>Enter this code on your phone</b>
                  <p className="phone-pair-code" aria-label="Phone pairing code">{pair.code}</p>
                  <p className="small">Single use · expires in {Math.max(1, Math.ceil((pair.expires_at - now) / 60))}
                    {" "}minutes. A new code replaces the previous one.</p>
                </div>
              </div>
            )}
            {pair && !activePair && <p className="small muted">Code expired. Get a new pairing code to connect.</p>}
          </>
        ) : (
          <>
            <label className="stack" htmlFor="phone-mode">Connect through
              <select id="phone-mode" className="input" value={mode}
                onChange={(e) => { setMode(e.target.value as Mode); setAddress(""); }}>
                <option value="tailscale">Tailscale · at home or away (recommended)</option>
                <option value="wifi">Home Wi-Fi · same network only</option>
              </select>
            </label>
            <p className="small muted">
              {mode === "tailscale" ? "Install Tailscale on this PC and your phone, then sign into the same account. "
                + "It encrypts the connection and gives this PC a private address."
                : "Use a trusted home network. Anyone with a paired device key can read the dashboard; "
                  + "HTTP traffic is not encrypted. Tailscale is the safer choice."}
            </p>
            <label className="stack" htmlFor="phone-ip">PC network address (optional)
              <input id="phone-ip" className="input" value={address} list="phone-addresses"
                placeholder={candidates[0]?.address || "Choose automatically"}
                onChange={(e) => setAddress(e.target.value)} autoComplete="off" spellCheck={false} />
              <datalist id="phone-addresses">
                {candidates.map((a) => <option key={a.address} value={a.address} />)}
              </datalist>
              <span className="small muted">Only this PC's private IPv4 address is accepted.</span>
            </label>
            <button type="button" className="btn btn-primary" disabled={busy || !view}
              onClick={() => action("/enable", { mode, ...(address.trim() ? { address: address.trim() } : {}) })}>
              {busy ? "Starting…" : "Turn on phone dashboard"}
            </button>
          </>
        )}
        {view && view.paired_devices > 0 && (
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => action("/revoke")}>
            Unpair all phones
          </button>
        )}
        <Disclosure summary="Connection help and what the phone can see">
          <p className="small">The phone shows status, video titles, progress and posting counts. Make changes,
            connect accounts and approve posts on this PC. Pairing lasts up to 90 days; Unpair all phones removes
            access immediately.</p>
          <p className="small">If the address will not open, check that Tailscale is connected on both devices,
            or that both use the same Wi-Fi. Windows may ask you to allow ClipFoundry/Python on private networks.
            There is no need to forward a router port or expose the desktop app.</p>
          <p className="small">In your phone's browser you can bookmark the address or add a Home Screen shortcut.
            Refreshing this dashboard never starts work or uploads a video.</p>
        </Disclosure>
      </div>
    </SettingsPanel>
  );
}
