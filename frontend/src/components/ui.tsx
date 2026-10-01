import {
  createContext, KeyboardEvent as ReactKeyboardEvent, ReactNode, useContext, useEffect, useId, useLayoutEffect, useRef,
  useState,
} from "react";
import { errorText, fmtTime, type Status } from "../api";

// ------------------------------------------------------------------ icons (one stroke style, 24 px grid)
const PATHS = {
  home: "M4 11l8-7 8 7M6 9.5V20h12V9.5M10 20v-6h4v6",
  autopilot: "M12 3a9 9 0 1 0 9 9M12 7v5l3 2M17 3h4v4M21 3l-5 5",
  library: "M4 5h6v14H4zM14 5l6 1.5-3 13-6-1.5",
  posts: "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4M8 14h3v3H8z",
  settings:
    "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  plus: "M12 5v14M5 12h14",
  upload: "M12 16V4M7 9l5-5 5 5M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2",
  play: "M8 5l11 7-11 7z",
  pause: "M8 5h3v14H8zM13 5h3v14h-3z",
  edit: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
  download: "M12 4v12M7 11l5 5 5-5M4 20h16",
  trash: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13",
  check: "M5 12l5 5 9-10",
  x: "M6 6l12 12M18 6L6 18",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6",
  film: "M4 4h16v16H4zM8 4v16M16 4v16M4 8h4M4 12h4M4 16h4M16 8h4M16 12h4M16 16h4",
  link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
  cpu: "M7 7h10v10H7zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4",
  back: "M15 5l-7 7 7 7",
  scissors: "M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM8.1 7.9L20 20M8.1 16.1L20 4",
  stop: "M6 6h12v12H6z",
  shield: "M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6zM9 12l2 2 4-4",
  alert: "M12 4l9 16H3zM12 10v4M12 17.5v.5",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v6M12 7.5v.5",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  moon: "M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z",
  menu: "M4 7h16M4 12h16M4 17h16",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  chev: "M9 6l6 6-6 6",
  external: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
  offline: "M3 3l18 18M8.5 16.5a5 5 0 0 1 7 0M5 12.5a10 10 0 0 1 4-2.4M19 12.5a10 10 0 0 0-3.3-2.1M2 8.8a15 15 0 0 1 4.5-2.9M22 8.8A15 15 0 0 0 12 5M12 20h.01",
  question: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.5V14M12 17.5v.5",
  dot: "M12 12h.01",
  spark: "M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2z",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  sliders: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4",
  zip: "M6 3h9l4 4v14H6zM11 3v2M11 7v2M11 11v2M10 15h2v3h-2z",
  copy: "M8 8h12v12H8zM4 16V4h12",
  // older names, kept so existing parts keep working
  dashboard: "M4 11l8-7 8 7M6 9.5V20h12V9.5M10 20v-6h4v6",
  create: "M12 5v14M5 12h14",
  projects: "M4 5h6v14H4zM14 5l6 1.5-3 13-6-1.5",
  calendar: "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4M8 14h3v3H8z",
};
export type IconName = keyof typeof PATHS;

export function Icon({ name, size, fill = false, className = "" }: { name: IconName; size?: number; fill?: boolean; className?: string }) {
  return (
    <svg className={`icon ${fill ? "fill" : ""} ${className}`} viewBox="0 0 24 24" aria-hidden="true" focusable="false"
      style={size ? { width: size, height: size } : undefined}>
      <path d={PATHS[name]} />
    </svg>
  );
}

export function Logo({ size = 32 }: { size?: number }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id={`lg${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffb13b" />
          <stop offset=".55" stopColor="#ff6a2b" />
          <stop offset="1" stopColor="#ff3d7f" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="16" fill="#1b1c21" />
      <path d="M22 14h20a4 4 0 0 1 4 4v28a4 4 0 0 1-4 4H22a4 4 0 0 1-4-4V18a4 4 0 0 1 4-4z" fill="none" stroke={`url(#lg${id})`} strokeWidth="4" />
      <path d="M28 25l11 7-11 7z" fill={`url(#lg${id})`} />
    </svg>
  );
}

// ------------------------------------------------------------------ connection: no green while the app is not answering
export const ConnectionContext = createContext<{ lost: boolean; lastOk: number | null }>({ lost: false, lastOk: null });
export const useConnection = () => useContext(ConnectionContext);

export type Tone = "good" | "warn" | "bad" | "info" | "neutral" | "accent";
const TONE_ICON: Record<Tone, IconName> = { good: "check", warn: "alert", bad: "alert", info: "info", neutral: "info", accent: "spark" };

/** A status: always an icon plus a word. While ClipFoundry is not answering, nothing reads as confirmed good. */
export function Pill({ tone = "neutral", icon, children, className = "", title }: {
  tone?: Tone; icon?: IconName; children: ReactNode; className?: string; title?: string;
}) {
  const { lost } = useConnection();
  const t = tone === "good" && lost ? "neutral" : tone;
  return <span className={`pill ${t} ${className}`} title={title}><Icon name={icon || TONE_ICON[tone]} />{children}</span>;
}

export const PLATFORM_LABEL: Record<string, string> = { youtube: "YouTube", tiktok: "TikTok" };

/** "YT YouTube" with an optional quieter detail ("@morningmic"). */
export function PlatformName({ platform, extra }: { platform: string; extra?: ReactNode }) {
  return (
    <span className="platform">
      <span className={`pmark ${platform}`} aria-hidden="true">{platform === "youtube" ? "YT" : "TT"}</span>
      {PLATFORM_LABEL[platform] || platform}
      {extra ? <span className="muted"> {extra}</span> : null}
    </span>
  );
}

// ------------------------------------------------------------------ controls
/** An on/off switch (role="switch"). The label is its accessible name; pass ariaLabel when there is no label. */
export function Toggle({ on, onChange, label, ariaLabel, disabled, showState, id, describedBy }: {
  on: boolean; onChange: (v: boolean) => void; label?: ReactNode; ariaLabel?: string; disabled?: boolean;
  showState?: boolean; id?: string; describedBy?: string;
}) {
  return (
    <button type="button" role="switch" aria-checked={on} className="switch" disabled={disabled} id={id}
      aria-label={ariaLabel} aria-describedby={describedBy} onClick={() => onChange(!on)}>
      <span className="track" aria-hidden="true" />
      {showState && <span className="state-word" aria-hidden="true">{on ? "On" : "Off"}</span>}
      {label != null && <span>{label}</span>}
    </button>
  );
}

/** A segmented choice: a radio group, so arrow keys move between the options. */
export function Segmented<T extends string | number>({ value, options, onChange, label, labelledBy, disabled }: {
  value: T; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void; label?: string; labelledBy?: string;
  disabled?: boolean; big?: boolean;
}) {
  const name = useId();
  return (
    <div className="seg" role="radiogroup" aria-label={label} aria-labelledby={labelledBy}>
      {options.map((o) => (
        <label key={String(o.value)}>
          <input type="radio" name={name} checked={o.value === value} disabled={disabled} onChange={() => onChange(o.value)} />
          {o.label}
        </label>
      ))}
    </div>
  );
}

/** Viral Potential: ClipFoundry's own estimate for ranking clips, never a prediction of views. */
export function ScoreBadge({ score, compact }: { score: number; compact?: boolean }) {
  return (
    <span className="score" title="Viral Potential: an estimate from the clip's transcript and audio, used to rank clips. Not a guarantee of views.">
      {!compact && <span>Viral Potential</span>}
      <b>{Math.round(score)}</b>
      <span>estimate</span>
    </span>
  );
}

const STATUS_LABEL: Record<string, [string, Tone]> = {
  created: ["Waiting to start", "neutral"],
  uploading: ["Copying", "info"],
  queued: ["Waiting to start", "info"],
  processing: ["Making clips", "info"],
  rendering: ["Rendering", "info"],
  ready: ["Ready", "good"],
  error: ["Problem", "bad"],
  cancelled: ["Canceled", "neutral"],
};

/** A source video's state, as a pill. */
export function StatusBadge({ status }: { status: Status | string }) {
  const [label, tone] = STATUS_LABEL[status] || [status, "neutral"];
  return <Pill tone={tone} icon={tone === "info" ? "clock" : undefined}>{label}</Pill>;
}

/** A progress bar that reports its value to assistive technology but is never announced on its own. */
export function ProgressBar({ value, label, tone }: { value: number; label: string; tone?: "good" }) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div className={`bar ${tone || ""}`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={label}>
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}

/** A thumbnail: 16:9 for a source video, 9:16 (vertical) for a clip. A missing picture says so. */
export function Thumb({ src, vertical, duration, children, className = "" }: {
  src?: string | null; vertical?: boolean; duration?: number | null; children?: ReactNode; className?: string;
}) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  return (
    <span className={`thumb ${vertical ? "v" : ""} ${className}`}>
      {src && !failed ? <img src={src} alt="" loading="lazy" onError={() => setFailed(true)} />
        : <span className="missing"><Icon name="film" />No preview yet</span>}
      {duration != null && duration > 0 && <span className="corner tnum">{fmtTime(duration)}</span>}
      {children}
    </span>
  );
}

/** A label, a value with its icon and tone, and one line that explains it. */
export function Fact({ label, value, tone = "neutral", icon, desc }: {
  label: string; value: ReactNode; tone?: Tone; icon?: IconName; desc?: ReactNode;
}) {
  const { lost } = useConnection();
  const t = tone === "good" && lost ? "neutral" : tone;
  return (
    <div className="fact">
      <span className="k">{label}</span>
      <span className={`v ${t}`}><Icon name={icon || TONE_ICON[tone]} /><span>{value}</span></span>
      {desc && <span className="d">{desc}</span>}
    </div>
  );
}

export function Banner({ tone = "info", icon, title, children, actions }: {
  tone?: "info" | "warn" | "bad" | "neutral"; icon?: IconName; title?: ReactNode; children?: ReactNode; actions?: ReactNode;
}) {
  return (
    <div className={`banner ${tone}`} role={tone === "bad" ? "alert" : undefined}>
      <Icon name={icon || (tone === "info" || tone === "neutral" ? "info" : "alert")} />
      <div className="grow">
        {title && <b>{title}</b>}
        {children && <div className="small">{children}</div>}
        {actions && <div className="actions">{actions}</div>}
      </div>
    </div>
  );
}

/** A quiet "more details" disclosure. */
export function Disclosure({ summary, children, plain, open }: { summary: ReactNode; children: ReactNode; plain?: boolean; open?: boolean }) {
  return (
    <details className={plain ? "plain" : "more"} open={open}>
      <summary><Icon name="chev" className="chev sm" />{summary}</summary>
      <div className="more-body">{children}</div>
    </details>
  );
}

export function EmptyState({ icon = "film", title, children, actions, level = 2 }: {
  icon?: IconName; title: ReactNode; children?: ReactNode; actions?: ReactNode; level?: 2 | 3;
}) {
  const H = level === 2 ? "h2" : "h3";
  return (
    <div className="empty">
      <Icon name={icon} className="lg" />
      <H>{title}</H>
      {children && <div className="muted">{children}</div>}
      {actions && <div className="row wrap">{actions}</div>}
    </div>
  );
}

// ------------------------------------------------------------------ page structure
export type Crumb = { label: ReactNode; href?: string };

/** The page's kind label, its one H1 (focused after navigation), one supporting line and at most one action. */
export function PageHead({ kind, title, sub, actions, crumbs }: {
  kind?: ReactNode; title: ReactNode; sub?: ReactNode; actions?: ReactNode; crumbs?: Crumb[];
}) {
  return (
    <div className="page-head">
      <div>
        {crumbs && crumbs.length > 0 && (
          <nav className="crumbs" aria-label="Breadcrumb">
            {crumbs.map((c, i) => (
              <span key={i} className="row" style={{ gap: 6 }}>
                {c.href ? <a href={c.href}>{c.label}</a> : <span aria-current="page">{c.label}</span>}
                {i < crumbs.length - 1 && <span aria-hidden="true">/</span>}
              </span>
            ))}
          </nav>
        )}
        {kind && <span className="kind-label">{kind}</span>}
        <h1 tabIndex={-1} className="break">{title}</h1>
        {sub && <p className="muted">{sub}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}

export type LinkTab = { id: string; href: string; label: ReactNode; count?: number; countTone?: "warn" | "bad" };

/** Page sections as links: they change the address, so Back works and a section can be bookmarked. */
export function LinkTabs({ label, tabs, current }: { label: string; tabs: LinkTab[]; current: string }) {
  return (
    <nav className="tabs" aria-label={label}>
      {tabs.map((t) => (
        <a key={t.id} href={t.href} aria-current={t.id === current ? "page" : undefined}>
          {t.label}
          {t.count ? <span className={`count ${t.countTone === "bad" ? "bad" : ""}`}>{t.count}</span> : null}
        </a>
      ))}
    </nav>
  );
}

/** ARIA tabs for groups inside one page (the editor): arrow keys, Home and End move between them. */
export function Tabs<T extends string>({ label, tabs, current, onChange, idPrefix }: {
  label: string; tabs: { id: T; label: ReactNode }[]; current: T; onChange: (id: T) => void; idPrefix: string;
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const key = (e: ReactKeyboardEvent, i: number) => {
    const n = tabs.length;
    const to = e.key === "ArrowRight" ? (i + 1) % n : e.key === "ArrowLeft" ? (i - 1 + n) % n
      : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : -1;
    if (to < 0) return;
    e.preventDefault();
    onChange(tabs[to].id);
    refs.current[tabs[to].id]?.focus();
  };
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((t, i) => {
        const on = t.id === current;
        return (
          <button key={t.id} type="button" role="tab" id={`${idPrefix}-tab-${t.id}`} ref={(el) => { refs.current[t.id] = el; }}
            aria-selected={on} aria-controls={on ? `${idPrefix}-panel-${t.id}` : undefined} tabIndex={on ? 0 : -1}
            onClick={() => onChange(t.id)} onKeyDown={(e) => key(e, i)}>
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({ idPrefix, id, children, className = "tabpanel" }: { idPrefix: string; id: string; children: ReactNode; className?: string }) {
  return <div role="tabpanel" id={`${idPrefix}-panel-${id}`} aria-labelledby={`${idPrefix}-tab-${id}`} className={className} tabIndex={0}>{children}</div>;
}

export function Skel({ className = "", style }: { className?: string; style?: React.CSSProperties }) {
  return <div className={`skel ${className}`} style={style} aria-hidden="true" />;
}

/** Flat skeleton blocks while a page loads (never a spinner on a blank page). */
export function LoadingPage({ label = "Loading" }: { label?: string }) {
  return (
    <div className="page" aria-busy="true">
      <span className="sr-only" role="status">{label}…</span>
      <Skel className="skel-title" />
      <Skel className="skel-line" style={{ width: "40%" }} />
      <Skel className="skel-block" />
      <Skel className="skel-block" />
    </div>
  );
}

// ------------------------------------------------------------------ dialogs
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"]), summary';

/**
 * A modal dialog: focus moves in, Tab stays inside, Escape closes, and focus returns to what opened it.
 * Pass `label` (or `labelledBy`) so it has a name.
 */
export function Modal({ children, onClose, label, labelledBy, wide, className = "" }: {
  children: ReactNode; onClose: () => void; label?: string; labelledBy?: string; wide?: boolean; className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useLayoutEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const box = ref.current!;
    const first = box.querySelector<HTMLElement>("[data-autofocus]") || box.querySelector<HTMLElement>(FOCUSABLE);
    (first || box).focus();
    return () => {
      if (opener && document.contains(opener)) opener.focus();
    };
  }, []);
  const onKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      close.current();
      return;
    }
    if (e.key !== "Tab") return;
    const items = Array.from(ref.current!.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };
  return (
    <div className="dialog-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} className={`dialog ${wide ? "wide" : ""} ${className}`} role="dialog" aria-modal="true"
        aria-label={label} aria-labelledby={labelledBy} tabIndex={-1} onKeyDown={onKey}>
        {children}
      </div>
    </div>
  );
}

/** A dialog with a title, its content, and actions (Cancel on the left, the action on the right). */
export function Dialog({ title, children, actions, onClose, wide }: {
  title: ReactNode; children?: ReactNode; actions?: ReactNode; onClose: () => void; wide?: boolean;
}) {
  const id = useId();
  return (
    <Modal onClose={onClose} labelledBy={id} wide={wide}>
      <h2 id={id}>{title}</h2>
      {children}
      {actions && <div className="dialog-actions">{actions}</div>}
    </Modal>
  );
}

/**
 * Consequences before commitment: says exactly what will happen, then Cancel or the action. The action may throw;
 * the dialog then stays open and says why.
 */
export function ConfirmDialog({ title, children, confirmLabel, danger, onConfirm, onClose, cancelLabel = "Cancel", disabled, wide }: {
  title: ReactNode; children?: ReactNode; confirmLabel: string; danger?: boolean; onConfirm: () => Promise<unknown> | unknown;
  onClose: () => void; cancelLabel?: string; disabled?: boolean; wide?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const go = async () => {
    setBusy(true);
    setErr("");
    try {
      await onConfirm();
      onClose();
    } catch (e) {
      setErr(errorText(e));
      setBusy(false);
    }
  };
  return (
    <Dialog title={title} onClose={onClose} wide={wide} actions={<>
      <button type="button" className="btn" onClick={onClose}>{cancelLabel}</button>
      <button type="button" className={`btn ${danger ? "btn-danger" : "btn-primary"}`} disabled={busy || disabled} onClick={go}>
        {busy && <span className="inline-spinner" aria-hidden="true" />}{confirmLabel}
      </button>
    </>}>
      {children}
      {err && <p className="error-text" role="alert"><Icon name="alert" className="sm" />{err}</p>}
    </Dialog>
  );
}

/** Asks for one line of text (a file path, a link) in place of the browser's prompt. */
export function TextPromptDialog({ title, label, hint, placeholder, confirmLabel, initial = "", onSubmit, onClose, children }: {
  title: ReactNode; label: string; hint?: ReactNode; placeholder?: string; confirmLabel: string; initial?: string;
  onSubmit: (value: string) => Promise<unknown> | unknown; onClose: () => void; children?: ReactNode;
}) {
  const [value, setValue] = useState(initial);
  const id = useId();
  return (
    <ConfirmDialog title={title} confirmLabel={confirmLabel} onClose={onClose} disabled={!value.trim()}
      onConfirm={() => onSubmit(value.trim().replace(/^"|"$/g, ""))}>
      {children}
      <div className="field">
        <label htmlFor={id}>{label}</label>
        <input id={id} type="text" value={value} placeholder={placeholder} data-autofocus onChange={(e) => setValue(e.target.value)} />
        {hint && <span className="hint">{hint}</span>}
      </div>
    </ConfirmDialog>
  );
}

// ------------------------------------------------------------------ the More menu
export type MenuItem =
  | { label: ReactNode; onSelect?: () => void; href?: string; external?: boolean; danger?: boolean; icon?: IconName; disabled?: string }
  | "separator";

/**
 * Rare and destructive actions: "⋯" with a name that says whose menu it is ("More for Morning Mic episode 12").
 * A disabled item says why ("Cancel processing first").
 */
export function MoreMenu({ label, items, up, text }: { label: string; items: MenuItem[]; up?: boolean; text?: string }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const first = wrap.current?.querySelector<HTMLElement>('[role="menuitem"]');
    first?.focus();
    const away = (e: MouseEvent) => wrap.current && !wrap.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  const onKey = (e: ReactKeyboardEvent) => {
    if (!open) return;
    const all = Array.from(wrap.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') || []);
    const i = all.indexOf(document.activeElement as HTMLElement);
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
      button.current?.focus();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      all[(i + (e.key === "ArrowDown" ? 1 : all.length - 1)) % all.length]?.focus();
    } else if (e.key === "Home" || e.key === "End") {
      e.preventDefault();
      all[e.key === "Home" ? 0 : all.length - 1]?.focus();
    } else if (e.key === "Tab") {
      setOpen(false);
    }
  };
  const pick = (fn?: () => void) => {
    setOpen(false);
    button.current?.focus();
    fn?.();
  };
  return (
    <div className="menu-wrap" ref={wrap} onKeyDown={onKey}>
      <button ref={button} type="button" className={`btn btn-small ${text ? "" : "btn-icon"}`} aria-haspopup="menu"
        aria-expanded={open} aria-controls={open ? id : undefined} aria-label={text ? undefined : label} title={label}
        onClick={() => setOpen(!open)}>
        <Icon name="more" />{text}
      </button>
      {open && (
        <div className={`menu ${up ? "up" : ""}`} role="menu" id={id} aria-label={label}>
          {items.map((it, i) => {
            if (it === "separator") return <hr key={i} />;
            if (it.disabled) {
              return (
                <button key={i} type="button" role="menuitem" aria-disabled="true" onClick={(e) => e.preventDefault()}>
                  <span className="row" style={{ gap: 8 }}>{it.icon && <Icon name={it.icon} className="sm" />}{it.label}</span>
                  <span className="why">{it.disabled}</span>
                </button>
              );
            }
            if (it.href) {
              return (
                <a key={i} role="menuitem" href={it.href} className={it.danger ? "danger" : ""} onClick={() => setOpen(false)}
                  target={it.external ? "_blank" : undefined} rel={it.external ? "noreferrer" : undefined}>
                  {it.icon && <Icon name={it.icon} className="sm" />}{it.label}
                </a>
              );
            }
            return (
              <button key={i} type="button" role="menuitem" className={it.danger ? "danger" : ""} onClick={() => pick(it.onSelect)}>
                {it.icon && <Icon name={it.icon} className="sm" />}{it.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ toasts and the live region
let pushToast: ((msg: string, bad?: boolean) => void) | null = null;
let pushAnnounce: ((msg: string) => void) | null = null;
/** A short visible message about an action; screen readers hear it through the one polite live region. */
export const toast = (msg: string, bad = false) => pushToast?.(msg, bad);
/** Say something to screen readers only (finished work: "3 clips are ready"). Never for polling ticks. */
export const announce = (msg: string) => pushAnnounce?.(msg);

export function ToastHost() {
  const [t, setT] = useState<{ msg: string; bad: boolean; id: number } | null>(null);
  const [said, setSaid] = useState("");
  useEffect(() => {
    pushToast = (msg, bad = false) => {
      setT({ msg, bad, id: Date.now() });
      setSaid(msg);
    };
    pushAnnounce = (msg) => setSaid(msg);
    return () => {
      pushToast = null;
      pushAnnounce = null;
    };
  }, []);
  useEffect(() => {
    if (!t) return;
    const h = setTimeout(() => setT(null), t.bad ? 8000 : 4500);
    return () => clearTimeout(h);
  }, [t]);
  return (
    <>
      <div className="sr-only" role="status" aria-live="polite">{said}</div>
      {t && (
        <div className={`toast ${t.bad ? "bad" : ""}`} aria-hidden="true">
          <Icon name={t.bad ? "alert" : "check"} />
          <span>{t.msg}</span>
        </div>
      )}
    </>
  );
}

// ------------------------------------------------------------------ polling
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

// ------------------------------------------------------------------ caption styles and framing
export const CAPTION_STYLES = [
  { value: "clean", label: "Clean", demo: <span className="demo-clean">this is <em>clean</em></span> },
  { value: "bold", label: "Bold", demo: <span className="demo-bold">BIG <em>BOLD</em></span> },
  { value: "high_energy", label: "High energy", demo: <span className="demo-high"><em>HYPE!</em></span> },
  { value: "minimal", label: "Minimal", demo: <span className="demo-min">a quiet, minimal line</span> },
];

export const TRACKING = [
  { value: "auto", label: "Auto" },
  { value: "center", label: "Center" },
  { value: "face", label: "Face" },
  { value: "speaker", label: "Active speaker" },
  { value: "screen", label: "Screen content" },
];

/** The caption style, as a radio group of small previews. */
export function StylePicker({ value, onChange, label = "Caption style" }: { value: string; onChange: (v: string) => void; label?: string }) {
  const name = useId();
  return (
    <div className="style-cards" role="radiogroup" aria-label={label}>
      {CAPTION_STYLES.map((s) => (
        <label key={s.value} className="style-card">
          <input type="radio" name={name} value={s.value} checked={value === s.value} onChange={() => onChange(s.value)} />
          <span className="caption-demo" aria-hidden="true">{s.demo}</span>
          <span className="name">{s.label}</span>
        </label>
      ))}
    </div>
  );
}
