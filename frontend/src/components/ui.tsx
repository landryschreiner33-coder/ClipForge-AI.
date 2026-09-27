import { ReactNode, useEffect, useState } from "react";
import type { Status } from "../api";

type IconName =
  | "dashboard" | "create" | "projects" | "settings" | "upload" | "play" | "edit" | "download" | "trash"
  | "check" | "x" | "zip" | "spark" | "refresh" | "film" | "link" | "cpu" | "back" | "scissors";

const PATHS: Record<IconName, string> = {
  dashboard: "M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z",
  create: "M12 5v14M5 12h14",
  projects: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  settings:
    "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  upload: "M12 16V4M7 9l5-5 5 5M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2",
  play: "M7 4l13 8-13 8z",
  edit: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
  download: "M12 4v12M7 11l5 5 5-5M4 20h16",
  trash: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13",
  check: "M5 12l5 5 9-10",
  x: "M6 6l12 12M18 6L6 18",
  zip: "M6 3h9l4 4v14H6zM11 3v2M11 7v2M11 11v2M10 15h2v3h-2z",
  spark: "M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2z",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6",
  film: "M4 4h16v16H4zM8 4v16M16 4v16M4 8h4M4 12h4M4 16h4M16 8h4M16 12h4M16 16h4",
  link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
  cpu: "M7 7h10v10H7zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4",
  back: "M15 5l-7 7 7 7",
  scissors: "M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM8.1 7.9L20 20M8.1 16.1L20 4",
};

export function Icon({ name, size = 18, fill = false }: { name: IconName; size?: number; fill?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={fill ? "currentColor" : "none"} stroke="currentColor"
      strokeWidth={fill ? 0 : 2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={PATHS[name]} />
    </svg>
  );
}

export function Logo({ size = 34 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-label="ClipFoundry">
      <defs>
        <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffb13b" />
          <stop offset=".55" stopColor="#ff6a2b" />
          <stop offset="1" stopColor="#ff3d7f" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="16" fill="#1b1a24" />
      <path d="M22 14h20a4 4 0 0 1 4 4v28a4 4 0 0 1-4 4H22a4 4 0 0 1-4-4V18a4 4 0 0 1 4-4z" fill="none" stroke="url(#lg)" strokeWidth="4" />
      <path d="M28 25l11 7-11 7z" fill="url(#lg)" />
    </svg>
  );
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label?: ReactNode }) {
  return (
    <span className={`toggle ${on ? "on" : ""}`} role="switch" aria-checked={on} tabIndex={0}
      onClick={() => onChange(!on)} onKeyDown={(e) => (e.key === " " || e.key === "Enter") && onChange(!on)}>
      <span className="track" />
      {label}
    </span>
  );
}

export function Segmented<T extends string | number>({
  value, options, onChange, big,
}: { value: T; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void; big?: boolean }) {
  return (
    <div className={`segmented ${big ? "big" : ""}`}>
      {options.map((o) => (
        <button key={String(o.value)} type="button" className={o.value === value ? "on" : ""} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function ScoreBadge({ score, compact }: { score: number; compact?: boolean }) {
  const cls = score >= 75 ? "hi" : score >= 55 ? "mid" : "lo";
  return (
    <span className={`score ${cls}`} title="Viral Potential: an estimate from the clip's transcript and audio, used to rank clips. Not a guarantee of views.">
      {Math.round(score)}
      {!compact && <small>Viral Potential</small>}
    </span>
  );
}

const STATUS_LABEL: Record<string, [string, string]> = {
  created: ["Created", ""],
  uploading: ["Uploading", "info"],
  queued: ["Queued", "info"],
  processing: ["Processing", "warn"],
  rendering: ["Rendering", "warn"],
  ready: ["Ready", "good"],
  error: ["Error", "bad"],
  cancelled: ["Cancelled", ""],
};

export function StatusBadge({ status }: { status: Status | string }) {
  const [label, cls] = STATUS_LABEL[status] || [status, ""];
  return (
    <span className={`badge ${cls}`}>
      <span className="dot" /> {label}
    </span>
  );
}

export function Modal({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">{children}</div>
    </div>
  );
}

let pushToast: ((msg: string, bad?: boolean) => void) | null = null;
export const toast = (msg: string, bad = false) => pushToast?.(msg, bad);

export function ToastHost() {
  const [t, setT] = useState<{ msg: string; bad: boolean; id: number } | null>(null);
  useEffect(() => {
    pushToast = (msg, bad = false) => setT({ msg, bad, id: Date.now() });
    return () => {
      pushToast = null;
    };
  }, []);
  useEffect(() => {
    if (!t) return;
    const h = setTimeout(() => setT(null), 4500);
    return () => clearTimeout(h);
  }, [t]);
  return t ? <div className={`toast ${t.bad ? "bad" : ""}`}>{t.msg}</div> : null;
}

export function usePoll<T>(fn: () => Promise<T>, deps: unknown[], intervalMs: number, active: (v: T | null) => boolean) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string>("");
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const run = async () => {
      try {
        const v = await fn();
        if (!alive) return;
        setData(v);
        setError("");
        if (active(v)) timer = setTimeout(run, intervalMs);
      } catch (e) {
        if (!alive) return;
        setError((e as Error).message);
        timer = setTimeout(run, intervalMs * 3);
      }
    };
    run();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, refresh: () => setTick((x) => x + 1), setData };
}

export const CAPTION_STYLES = [
  { value: "clean", label: "Clean", demo: <span className="demo-clean">this is <em>clean</em></span> },
  { value: "bold", label: "Bold", demo: <span className="demo-bold">BIG <em>BOLD</em></span> },
  { value: "high_energy", label: "High Energy", demo: <span className="demo-high"><em>HYPE!</em></span> },
  { value: "minimal", label: "Minimal", demo: <span className="demo-min">a quiet, minimal line</span> },
];

export const TRACKING = [
  { value: "auto", label: "Auto" },
  { value: "center", label: "Center" },
  { value: "face", label: "Face" },
  { value: "speaker", label: "Active speaker" },
  { value: "screen", label: "Screen content" },
];

export function StylePicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="style-cards">
      {CAPTION_STYLES.map((s) => (
        <div key={s.value} className={`style-card ${value === s.value ? "on" : ""}`} onClick={() => onChange(s.value)}>
          <div className="demo">{s.demo}</div>
          <div className="name">{s.label}</div>
        </div>
      ))}
    </div>
  );
}
