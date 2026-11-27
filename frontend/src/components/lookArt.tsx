/**
 * An example of each look of an animated short (makers/looks.py). Each look has a picture of the same small scene
 * (a robot on a hill, a lighthouse behind) made in that look (public/looks/<look>.jpg, made with Higgsfield on
 * 2026-11-27 at the owner's request, replacing their ChatGPT pictures of 2026-11-26), so the cards show the
 * difference at a glance. The drawings below are what a look shows if
 * its picture can't load. LookExample shows the picture maker's own example instead when the owner made one (Make
 * examples with my picture maker).
 */
import { ReactNode, useId, useState } from "react";

/** The looks' example pictures, cropped to 9:16 (720 x 1280). */
export const LOOK_PICTURES: Record<string, string> = {
  cartoon3d: "/looks/cartoon3d.jpg", storybook: "/looks/storybook.jpg", anime: "/looks/anime.jpg",
  comic: "/looks/comic.jpg", cinematic: "/looks/cinematic.jpg", paper: "/looks/paper.jpg", flat: "/looks/flat.jpg",
  eerie: "/looks/eerie.jpg",
};

const W = 180;
const H = 320;
const FAR = "M0 206 Q36 168 84 190 T180 178 V320 H0Z";
const NEAR = "M0 252 Q58 214 118 238 T180 232 V320 H0Z";
const TOWER = "M127 186 L143 186 L139 134 L131 134 Z";
const CAP = "M128 134 h14 l-3 -9 h-8z";
const BODY = "M52 246 Q50 226 72 224 Q92 222 94 240 Q94 254 74 254 Q54 256 52 246Z";
const HEAD = "M84 222 Q84 206 98 208 Q110 210 110 222 Q109 232 97 233 Q85 233 84 222Z";
const EARS = "M88 212 L90 196 L97 209Z M100 209 L106 195 L108 212Z";
const SNOUT = "M107 219 L118 224 L107 229Z";
const TAIL = "M54 244 Q30 246 26 226 Q36 236 52 232Z";
const TAIL_TIP = "M26 226 Q27 236 36 240 Q30 232 31 226Z";
const CHEST = "M96 230 Q92 240 100 244 Q106 238 103 230Z";
const LEGS = "M60 250 h6 v12 h-6z M82 250 h6 v12 h-6z";
const TREE = "M150 250 L152 196 M151 214 L138 202 M151 206 L164 192 M151 226 L166 216";

type Ids = { id: (name: string) => string; url: (name: string) => string };

function useIds(): Ids {
  const base = useId().replace(/[^a-zA-Z0-9]/g, "");
  return { id: (n) => `${base}-${n}`, url: (n) => `url(#${base}-${n})` };
}

/** The fox, in the colours and outline of a look. */
function Fox({ fur, chest, ink, line = 0, tip = chest, eye = "#1b1b1b" }: {
  fur: string; chest: string; ink: string; line?: number; tip?: string; eye?: string;
}) {
  const stroke = line ? { stroke: ink, strokeWidth: line, strokeLinejoin: "round" as const } : {};
  return (
    <g>
      <path d={TAIL} fill={fur} {...stroke} />
      <path d={TAIL_TIP} fill={tip} />
      <path d={LEGS} fill={fur} {...stroke} />
      <path d={BODY} fill={fur} {...stroke} />
      <path d={EARS} fill={fur} {...stroke} />
      <path d={HEAD} fill={fur} {...stroke} />
      <path d={SNOUT} fill={fur} {...stroke} />
      <path d={CHEST} fill={chest} />
      <circle cx="116" cy="223" r="1.8" fill={ink} />
      <circle cx="101" cy="218" r="1.9" fill={eye} />
    </g>
  );
}

function Lighthouse({ body, stripe, cap, light, line = 0, ink = "#000" }: {
  body: string; stripe: string; cap: string; light: string; line?: number; ink?: string;
}) {
  const stroke = line ? { stroke: ink, strokeWidth: line, strokeLinejoin: "round" as const } : {};
  return (
    <g>
      <path d={TOWER} fill={body} {...stroke} />
      <path d="M129.5 168 L140.5 168 L140 160 L130 160Z M130.5 150 L139.5 150 L139 143 L131 143Z" fill={stripe} />
      <path d={CAP} fill={cap} {...stroke} />
      <circle cx="135" cy="120" r="3.2" fill={light} />
    </g>
  );
}

function Frame({ label, children, defs }: { label: string; children: ReactNode; defs?: ReactNode }) {
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} preserveAspectRatio="xMidYMid slice"
      className="look-art">
      {defs && <defs>{defs}</defs>}
      {children}
    </svg>
  );
}

function Cartoon3d({ k, label }: { k: Ids; label: string }) {
  return (
    <Frame label={label} defs={<>
      <linearGradient id={k.id("sky")} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#6fc8ff" /><stop offset="1" stopColor="#c9ecff" /></linearGradient>
      <radialGradient id={k.id("hill")} cx="0.4" cy="0.1" r="0.9">
        <stop offset="0" stopColor="#8be06f" /><stop offset="1" stopColor="#2f9e4f" /></radialGradient>
      <radialGradient id={k.id("far")} cx="0.5" cy="0" r="1">
        <stop offset="0" stopColor="#a6e3a1" /><stop offset="1" stopColor="#4fae7c" /></radialGradient>
      <radialGradient id={k.id("fur")} cx="0.35" cy="0.3" r="0.8">
        <stop offset="0" stopColor="#ffb25c" /><stop offset="1" stopColor="#e2601f" /></radialGradient>
      <radialGradient id={k.id("sun")} cx="0.4" cy="0.35" r="0.7">
        <stop offset="0" stopColor="#fff8c8" /><stop offset="1" stopColor="#ffd34d" /></radialGradient>
      <filter id={k.id("soft")} x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="3" />
      </filter>
    </>}>
      <rect width={W} height={H} fill={k.url("sky")} />
      <circle cx="50" cy="72" r="24" fill={k.url("sun")} />
      <ellipse cx="40" cy="118" rx="26" ry="11" fill="#fff" opacity="0.9" />
      <ellipse cx="60" cy="112" rx="18" ry="12" fill="#fff" opacity="0.9" />
      <path d={FAR} fill={k.url("far")} />
      <Lighthouse body="#fff" stripe="#ff5a5a" cap="#ff5a5a" light="#fff3a6" />
      <path d={NEAR} fill={k.url("hill")} />
      <ellipse cx="74" cy="262" rx="30" ry="5" fill="#1d5e2f" opacity="0.35" filter={k.url("soft")} />
      <Fox fur={k.url("fur")} chest="#fff6ea" ink="#3b2316" />
      <ellipse cx="96" cy="214" rx="3" ry="2" fill="#fff" opacity="0.7" />
      <ellipse cx="66" cy="232" rx="7" ry="3" fill="#fff" opacity="0.35" />
    </Frame>
  );
}

function Storybook({ k, label }: { k: Ids; label: string }) {
  const wash = k.url("wash");
  return (
    <Frame label={label} defs={<>
      <filter id={k.id("wash")} x="-5%" y="-5%" width="110%" height="110%">
        <feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="3" seed="4" />
        <feDisplacementMap in="SourceGraphic" scale="5" />
        <feGaussianBlur stdDeviation="0.6" /></filter>
      <filter id={k.id("paper")}><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="2" />
        <feColorMatrix values="0 0 0 0 0.45  0 0 0 0 0.35  0 0 0 0 0.25  0 0 0 0.18 0" /></filter>
      <linearGradient id={k.id("sky")} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#f6d9b4" /><stop offset="1" stopColor="#fbeeda" /></linearGradient>
    </>}>
      <rect width={W} height={H} fill={k.url("sky")} />
      <g filter={wash} opacity="0.92">
        <circle cx="50" cy="74" r="22" fill="#f7b98c" opacity="0.8" />
        <path d={FAR} fill="#b9c9a0" opacity="0.85" />
        <Lighthouse body="#fdf5e8" stripe="#d9826a" cap="#c9705a" light="#fbe3a4" />
        <path d={NEAR} fill="#93ae7c" opacity="0.9" />
        <Fox fur="#d9844f" chest="#fbefdf" ink="#5b3a26" />
      </g>
      <path d="M8 286 q30 -6 60 2 M100 296 q30 -8 70 0" stroke="#7c9a68" strokeWidth="1.2" fill="none" opacity="0.6" />
      <rect width={W} height={H} filter={k.url("paper")} />
    </Frame>
  );
}

function Anime({ k, label }: { k: Ids; label: string }) {
  const ink = "#2a2140";
  return (
    <Frame label={label} defs={<>
      <linearGradient id={k.id("sky")} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#3f5dff" /><stop offset="0.55" stopColor="#9b7bff" /><stop offset="1" stopColor="#ff9ac1" />
      </linearGradient>
      <clipPath id={k.id("foxclip")}><path d={BODY} /><path d={HEAD} /></clipPath>
    </>}>
      <rect width={W} height={H} fill={k.url("sky")} />
      <g fill="#fff" opacity="0.95">
        <path d="M-10 128 q20 -26 46 -10 q14 -22 38 -6 q22 -8 30 12 q16 2 16 16 h-130z" />
        <path d="M96 84 q14 -14 30 -4 q12 -10 26 2 q16 0 18 14 h-74z" opacity="0.85" />
      </g>
      <path d="M-10 144 h130 q-6 6 -18 6 h-100z" fill="#c9b8ff" opacity="0.8" />
      {[[20, 40], [150, 30], [120, 60], [70, 24]].map(([x, y]) => (
        <path key={`${x}`} d={`M${x} ${y - 4} L${x + 1} ${y - 1} L${x + 4} ${y} L${x + 1} ${y + 1} L${x} ${y + 4} L${x - 1} ${y + 1}
          L${x - 4} ${y} L${x - 1} ${y - 1}Z`} fill="#fffbd0" />
      ))}
      <path d={FAR} fill="#5d4bbf" stroke={ink} strokeWidth="1" />
      <Lighthouse body="#fff" stripe="#ff6b8b" cap="#ff6b8b" light="#fff27a" line={1} ink={ink} />
      <path d="M135 120 L180 104 L180 136Z" fill="#fff27a" opacity="0.35" />
      <path d={NEAR} fill="#3a8f6b" stroke={ink} strokeWidth="1" />
      <path d="M0 270 Q60 238 118 258 T180 252 V320 H0Z" fill="#2c7458" />
      <Fox fur="#ff8a3d" chest="#fff" ink={ink} line={1.2} />
      <g clipPath={k.url("foxclip")}><rect x="50" y="238" width="70" height="30" fill="#c95a1d" opacity="0.6" /></g>
      <circle cx="101.6" cy="217.4" r="0.8" fill="#fff" />
    </Frame>
  );
}

function Comic({ k, label }: { k: Ids; label: string }) {
  const ink = "#141414";
  return (
    <Frame label={label} defs={<>
      <pattern id={k.id("dots")} width="6" height="6" patternUnits="userSpaceOnUse">
        <circle cx="3" cy="3" r="1.4" fill="#ff5e5b" /></pattern>
      <pattern id={k.id("dots2")} width="5" height="5" patternUnits="userSpaceOnUse">
        <circle cx="2.5" cy="2.5" r="1.1" fill={ink} opacity="0.35" /></pattern>
    </>}>
      <rect width={W} height={H} fill="#ffd23f" />
      <rect width={W} height={H} fill={k.url("dots")} opacity="0.55" />
      <g stroke="#fff" strokeWidth="3" opacity="0.8">
        {[-60, -35, -10, 15, 40].map((a) => <line key={a} x1="52" y1="72"
          x2={52 + 220 * Math.cos((a * Math.PI) / 180)} y2={72 + 220 * Math.sin((a * Math.PI) / 180)} />)}
      </g>
      <circle cx="52" cy="72" r="22" fill="#fff6c2" stroke={ink} strokeWidth="3" />
      <path d={FAR} fill="#ff8f3f" stroke={ink} strokeWidth="3" />
      <path d={FAR} fill={k.url("dots2")} />
      <Lighthouse body="#fff" stripe="#ff3b3b" cap="#ff3b3b" light="#fff" line={2.5} ink={ink} />
      <path d={NEAR} fill="#ff5e5b" stroke={ink} strokeWidth="3" />
      <path d={NEAR} fill={k.url("dots2")} />
      <Fox fur="#ff7a1a" chest="#fff" ink={ink} line={2.6} />
      <path d="M118 196 l10 -14 M122 206 l14 -8 M114 190 l2 -16" stroke={ink} strokeWidth="2.4" strokeLinecap="round" />
      <rect x="1.5" y="1.5" width={W - 3} height={H - 3} fill="none" stroke={ink} strokeWidth="3" />
    </Frame>
  );
}

function Cinematic({ k, label }: { k: Ids; label: string }) {
  return (
    <Frame label={label} defs={<>
      <linearGradient id={k.id("sky")} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#0f2233" /><stop offset="0.5" stopColor="#3a4a58" /><stop offset="0.78" stopColor="#d98b4a" />
        <stop offset="1" stopColor="#f2c27a" /></linearGradient>
      <radialGradient id={k.id("vig")} cx="0.5" cy="0.5" r="0.75">
        <stop offset="0.55" stopColor="#000" stopOpacity="0" /><stop offset="1" stopColor="#000" stopOpacity="0.75" />
      </radialGradient>
      <radialGradient id={k.id("glow")} cx="0.5" cy="0.5" r="0.5">
        <stop offset="0" stopColor="#ffe0a8" stopOpacity="0.9" /><stop offset="1" stopColor="#ffe0a8" stopOpacity="0" />
      </radialGradient>
      <filter id={k.id("grain")}><feTurbulence type="fractalNoise" baseFrequency="1.2" numOctaves="1" seed="7" />
        <feColorMatrix values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.12 0" /></filter>
      <linearGradient id={k.id("rim")} x1="1" y1="0" x2="0" y2="0">
        <stop offset="0" stopColor="#f2a65a" /><stop offset="0.35" stopColor="#3b2a22" /></linearGradient>
    </>}>
      <rect width={W} height={H} fill={k.url("sky")} />
      <circle cx="120" cy="196" r="40" fill={k.url("glow")} />
      <path d={FAR} fill="#1f2a30" />
      <Lighthouse body="#2b3236" stripe="#1c2226" cap="#1c2226" light="#ffd38a" />
      <path d="M135 120 L0 96 L0 132Z" fill="#ffe2b0" opacity="0.18" />
      <path d={NEAR} fill="#14191c" />
      <Fox fur={k.url("rim")} chest="#5a4031" ink="#0b0b0b" eye="#f2c27a" />
      <rect width={W} height={H} fill={k.url("vig")} />
      <rect width={W} height={H} filter={k.url("grain")} />
      <rect width={W} height="26" fill="#000" /><rect y={H - 26} width={W} height="26" fill="#000" />
    </Frame>
  );
}

function Paper({ k, label }: { k: Ids; label: string }) {
  const sh = k.url("shadow");
  return (
    <Frame label={label} defs={<>
      <filter id={k.id("shadow")} x="-10%" y="-10%" width="120%" height="130%">
        <feDropShadow dx="0" dy="3" stdDeviation="2.2" floodColor="#1f3b35" floodOpacity="0.35" /></filter>
      <filter id={k.id("fiber")}><feTurbulence type="fractalNoise" baseFrequency="0.6" numOctaves="2" seed="9" />
        <feColorMatrix values="0 0 0 0 0.2  0 0 0 0 0.25  0 0 0 0 0.2  0 0 0 0.1 0" /></filter>
    </>}>
      <rect width={W} height={H} fill="#bde7d8" />
      <circle cx="50" cy="74" r="22" fill="#f6d06f" filter={sh} />
      <path d="M14 118 q14 -14 30 -4 q12 -10 26 2 q8 10 -4 12 h-50 q-10 0 -2 -10z" fill="#fff" filter={sh} />
      <path d="M0 176 Q40 150 90 168 T180 160 V320 H0Z" fill="#8fd1b8" filter={sh} />
      <path d={FAR} fill="#6fbfa5" filter={sh} />
      <g filter={sh}><Lighthouse body="#fffaf0" stripe="#f28c6b" cap="#f28c6b" light="#f6d06f" /></g>
      <path d={NEAR} fill="#4fa58a" filter={sh} />
      <g filter={sh}><Fox fur="#f28c6b" chest="#fff4e6" ink="#1f3b35" /></g>
      <path d="M0 290 Q50 270 110 286 T180 282 V320 H0Z" fill="#3c8a72" filter={sh} />
      <rect width={W} height={H} filter={k.url("fiber")} />
    </Frame>
  );
}

function Flat({ label }: { k: Ids; label: string }) {
  return (
    <Frame label={label}>
      <rect width={W} height={H} fill="#3a86ff" />
      <rect y="150" width={W} height="60" fill="#5ce1e6" opacity="0.5" />
      <circle cx="50" cy="74" r="22" fill="#ffbe0b" />
      <polygon points="0,212 54,160 108,212" fill="#2667d9" />
      <polygon points="70,212 130,150 190,212" fill="#1f56b8" />
      <rect x="0" y="206" width={W} height="20" fill="#2a9d8f" />
      <rect x="130" y="140" width="10" height="66" fill="#fff" />
      <rect x="130" y="160" width="10" height="8" fill="#fb5607" /><rect x="130" y="180" width="10" height="8" fill="#fb5607" />
      <polygon points="127,140 143,140 135,128" fill="#fb5607" />
      <rect y="226" width={W} height={H - 226} fill="#26c485" />
      <polygon points="40,262 58,240 96,240 100,262" fill="#fb8500" />
      <polygon points="88,240 104,220 118,236 104,248" fill="#fb8500" />
      <polygon points="92,224 96,206 102,222" fill="#fb8500" /><polygon points="102,222 110,206 112,226" fill="#fb8500" />
      <polygon points="40,256 14,236 28,262" fill="#fb8500" /><polygon points="14,236 22,244 18,236" fill="#fff" />
      <polygon points="100,240 112,236 106,250" fill="#fff" />
      <rect x="46" y="262" width="6" height="12" fill="#e36414" /><rect x="86" y="262" width="6" height="12" fill="#e36414" />
      <circle cx="104" cy="228" r="2" fill="#1d1d1d" />
    </Frame>
  );
}

function Eerie({ k, label }: { k: Ids; label: string }) {
  return (
    <Frame label={label} defs={<>
      <linearGradient id={k.id("sky")} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#07060c" /><stop offset="0.6" stopColor="#2a2440" /><stop offset="1" stopColor="#3b3357" />
      </linearGradient>
      <filter id={k.id("glow")} x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="8" /></filter>
      <filter id={k.id("fog")} x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur stdDeviation="7" /></filter>
    </>}>
      <rect width={W} height={H} fill={k.url("sky")} />
      <circle cx="56" cy="78" r="30" fill="#c9bfff" opacity="0.5" filter={k.url("glow")} />
      <circle cx="56" cy="78" r="21" fill="#e9e4ff" />
      <circle cx="50" cy="72" r="4" fill="#cfc6f2" /><circle cx="62" cy="86" r="3" fill="#cfc6f2" />
      <path d={FAR} fill="#1a1626" />
      <Lighthouse body="#25203a" stripe="#1a1626" cap="#1a1626" light="#9d7cff" />
      <ellipse cx="90" cy="214" rx="120" ry="14" fill="#e9e4ff" opacity="0.18" filter={k.url("fog")} />
      <path d={TREE} stroke="#0c0a14" strokeWidth="4" strokeLinecap="round" fill="none" />
      <path d={NEAR} fill="#0f0c18" />
      <Fox fur="#0c0a14" chest="#0c0a14" ink="#0c0a14" tip="#0c0a14" eye="#b7a3ff" />
      <circle cx="101" cy="218" r="3.2" fill="#9d7cff" opacity="0.5" filter={k.url("glow")} />
      <ellipse cx="80" cy="282" rx="140" ry="18" fill="#e9e4ff" opacity="0.22" filter={k.url("fog")} />
    </Frame>
  );
}

const ART: Record<string, (p: { k: Ids; label: string }) => JSX.Element> = {
  cartoon3d: Cartoon3d, storybook: Storybook, anime: Anime, comic: Comic, cinematic: Cinematic, paper: Paper,
  flat: Flat, eerie: Eerie,
};

/** Whether ClipForge has an example of this look (a picture or a drawing). */
export const hasLookArt = (look: string) => look in LOOK_PICTURES || look in ART;

/** A look's example: the picture maker's own example when there is one, else the look's picture, else its drawing
 * (also when the picture can't load). */
export function LookExample({ look, name, made }: { look: string; name: string; made?: { url: string; engine: string } }) {
  const k = useIds();
  const [broken, setBroken] = useState(false);
  if (made) {
    return <img className="look-art" src={made.url} alt={`${name}: an example made by ${made.engine}`} loading="lazy" />;
  }
  const picture = LOOK_PICTURES[look];
  if (picture && !broken) {
    return <img className="look-art" src={picture} alt={`${name}: an example of the look`} loading="lazy"
      decoding="async" onError={() => setBroken(true)} />;
  }
  const Art = ART[look];
  if (!Art) return null;
  return <Art k={k} label={`${name}: a drawn example of the look`} />;
}
