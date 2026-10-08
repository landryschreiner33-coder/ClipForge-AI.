/**
 * Development-only character gallery / contact sheet. Mount at #/dev/characters.
 * Shows every role x 4 directions x representative states, plus CORE activities.
 * Everything here is synthetic: no live data is read.
 */
import { type ReactNode, useMemo, useState } from "react";
import { ART_SOURCES } from "./art";
import { CoreChamber, RobotSprite } from "./RobotSprite";
import {
  ANIM_STATES,
  CORE,
  DEPARTMENTS,
  DIRECTIONS,
  ROLES,
  type AnimState,
  type RobotRole,
  validateRegistry,
} from "./registry";

const REPRESENTATIVE: AnimState[] = [
  "idle",
  "walk",
  "work",
  "carry",
  "review",
  "waiting",
  "approved",
  "revise",
  "error",
  "retrying",
  "paused",
  "unavailable",
];

const ink = "#F3F4F7",
  muted = "#9AA3B8",
  panel = "#141D31",
  navy = "#0B1020",
  line = "#26324D";

type Mode = "animate" | "frames";

function Cell({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
      <div style={{ background: panel, borderRadius: 4, lineHeight: 0 }}>{children}</div>
      {label && <span style={{ fontSize: 10, color: muted, whiteSpace: "nowrap" }}>{label}</span>}
    </div>
  );
}

function RoleSheet({
  role,
  states,
  scale,
  mode,
  reduced,
  card,
}: {
  role: RobotRole;
  states: AnimState[];
  scale: number;
  mode: Mode;
  reduced: boolean;
  card: string;
}) {
  return (
    <section style={{ borderTop: `1px solid ${line}`, padding: "12px 0" }} id={`dev-${role.id}`}>
      <header style={{ display: "flex", gap: 12, alignItems: "baseline", flexWrap: "wrap", marginBottom: 8 }}>
        <strong style={{ color: role.palette.trim, letterSpacing: "0.06em" }}>{role.name}</strong>
        <span style={{ color: ink }}>{role.job}</span>
        <code style={{ color: muted, fontSize: 11 }}>id: {role.id}</code>
        <code style={{ color: muted, fontSize: 11 }}>{ART_SOURCES[role.id]}</code>
        <span style={{ color: muted, fontSize: 11 }}>
          {role.rank} · {role.department} · x{role.scale}
        </span>
      </header>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {states.map((s) => {
          const n = role.anim[s].frames;
          return (
            <div key={s} style={{ display: "flex", gap: 6, alignItems: "flex-end", flexWrap: "wrap" }}>
              <span style={{ width: 72, fontSize: 11, color: muted }}>
                {s}
                {mode === "frames" ? ` (${n}f)` : ""}
              </span>
              {DIRECTIONS.map((d) =>
                mode === "animate" ? (
                  <Cell key={d} label={d}>
                    <RobotSprite role={role.id} dir={d} state={s} scale={scale} reducedMotion={reduced} card={card} />
                  </Cell>
                ) : (
                  Array.from({ length: n }, (_, f) => (
                    <Cell key={`${d}${f}`} label={`${d} ${f}`}>
                      <RobotSprite role={role.id} dir={d} state={s} frame={f} scale={scale} card={card} />
                    </Cell>
                  ))
                ),
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default function DevGallery() {
  // Starts from the OS setting; the checkbox then overrides it for this page.
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
  );
  const [scale, setScale] = useState(2);
  const [mode, setMode] = useState<Mode>("animate");
  const [roleFilter, setRoleFilter] = useState<string>("all");
  const [allStates, setAllStates] = useState(false);
  const [card, setCard] = useState("#FFE7A8");
  const problems = useMemo(() => validateRegistry(), []);
  const roles = roleFilter === "all" ? ROLES : ROLES.filter((r) => r.id === roleFilter || r.department === roleFilter);
  const states = allStates ? [...ANIM_STATES] : REPRESENTATIVE;

  const control = { background: panel, color: ink, border: `1px solid ${line}`, borderRadius: 6, padding: "4px 8px" };
  return (
    <div style={{ background: navy, color: ink, minHeight: "100vh", padding: 16, fontFamily: "system-ui, sans-serif" }}>
      <h1 style={{ margin: 0, fontSize: 20 }}>Robot characters</h1>
      <p
        role="note"
        style={{
          margin: "6px 0 12px",
          padding: "6px 10px",
          background: "#2A2110",
          color: "#FFD08F",
          borderRadius: 6,
          display: "inline-block",
        }}
      >
        Development gallery: synthetic animation states, not live activity.
      </p>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
        <label>
          <input type="checkbox" checked={reduced} onChange={(e) => setReduced(e.target.checked)} /> Reduced motion
        </label>
        <label>
          Scale{" "}
          <select style={control} value={scale} onChange={(e) => setScale(Number(e.target.value))}>
            {[1, 2, 3, 4].map((s) => (
              <option key={s} value={s}>
                {s}x
              </option>
            ))}
          </select>
        </label>
        <label>
          View{" "}
          <select style={control} value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
            <option value="animate">Animated</option>
            <option value="frames">Every frame (contact sheet)</option>
          </select>
        </label>
        <label>
          Show{" "}
          <select style={control} value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
            <option value="all">All roles</option>
            <optgroup label="Departments">
              {DEPARTMENTS.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.label}
                </option>
              ))}
            </optgroup>
            <optgroup label="Roles">
              {ROLES.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </optgroup>
          </select>
        </label>
        <label>
          <input type="checkbox" checked={allStates} onChange={(e) => setAllStates(e.target.checked)} /> All 12 states
        </label>
        <label>
          Card tint <input type="color" value={card} onChange={(e) => setCard(e.target.value)} />
        </label>
      </div>
      <p style={{ color: problems.length ? "#FF7A86" : "#57EEA0", fontSize: 12, margin: "0 0 12px" }}>
        Registry check: {problems.length ? problems.join("; ") : "OK (1 director, 8 managers, 16 workers)"}
      </p>

      <h2 style={{ fontSize: 15, margin: "16px 0 8px" }}>Line-up at office scale (2x and 1x)</h2>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
        {ROLES.map((r) => (
          <div key={r.id} style={{ display: "flex", gap: 4, alignItems: "flex-end" }}>
            <Cell label={r.name}>
              <RobotSprite role={r.id} scale={2} reducedMotion={reduced} />
            </Cell>
            <Cell label="1x">
              <RobotSprite role={r.id} scale={1} reducedMotion={reduced} />
            </Cell>
          </div>
        ))}
      </div>

      <h2 style={{ fontSize: 15, margin: "20px 0 8px" }}>CORE: Brain Core (stationary)</h2>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {CORE.activities.map((a) =>
          mode === "animate" ? (
            <Cell key={a} label={`core · ${a}`}>
              <CoreChamber activity={a} scale={scale} reducedMotion={reduced} />
            </Cell>
          ) : (
            Array.from({ length: CORE.anim.frames }, (_, f) => (
              <Cell key={`${a}${f}`} label={`${a} ${f}`}>
                <CoreChamber activity={a} frame={f} scale={scale} />
              </Cell>
            ))
          ),
        )}
      </div>

      <h2 style={{ fontSize: 15, margin: "20px 0 0" }}>Every role x 4 directions</h2>
      {roles.map((r) => (
        <RoleSheet key={r.id} role={r} states={states} scale={scale} mode={mode} reduced={reduced} card={card} />
      ))}
    </div>
  );
}
