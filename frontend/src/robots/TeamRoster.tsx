/**
 * Read-only team roster: every robot grouped by department with its portrait, name, job,
 * manager and one-line duty. No controls; purely descriptive.
 */
import { RobotPortrait, RobotSprite } from "./RobotSprite";
import { DEPARTMENTS, type RobotRole, roleById } from "./registry";

export interface TeamRosterProps {
  className?: string;
  /** Portrait scale (default 2 = 96x128). */
  portraitScale?: number;
  /** Also show the 1x office-scale sprite next to each portrait (default false). */
  showOfficeScale?: boolean;
  reducedMotion?: boolean;
}

const ink = "var(--text, #F3F4F7)";
const muted = "var(--muted, #9AA3B8)";
const panel = "var(--panel, #141D31)";

function RosterCard({
  role,
  portraitScale,
  showOfficeScale,
  reducedMotion,
}: {
  role: RobotRole;
  portraitScale: number;
  showOfficeScale: boolean;
  reducedMotion?: boolean;
}) {
  const manager = role.managerId ? roleById(role.managerId) : undefined;
  return (
    <li
      style={{
        display: "flex",
        gap: 12,
        alignItems: "center",
        padding: 10,
        borderRadius: 10,
        background: panel,
        border: `1px solid ${role.palette.trim}40`,
        listStyle: "none",
        minWidth: 0,
      }}
    >
      <RobotPortrait role={role.id} scale={portraitScale} reducedMotion={reducedMotion} />
      {showOfficeScale && <RobotSprite role={role.id} scale={1} reducedMotion={reducedMotion} />}
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 800, letterSpacing: "0.06em", color: role.palette.trim }}>{role.name}</div>
        <div style={{ color: ink, fontWeight: 600 }}>{role.job}</div>
        <div style={{ color: muted, fontSize: "0.85em" }}>
          {role.rank === "director" ? "Runs the whole studio" : `Reports to ${manager?.name ?? "-"}`}
        </div>
        <p style={{ margin: "4px 0 0", color: ink, fontSize: "0.9em", lineHeight: 1.35 }}>{role.duty}</p>
      </div>
    </li>
  );
}

export function TeamRoster({ className, portraitScale = 2, showOfficeScale = false, reducedMotion }: TeamRosterProps) {
  return (
    <div className={["team-roster", className].filter(Boolean).join(" ")} style={{ display: "grid", gap: 20 }}>
      {DEPARTMENTS.map((d) => {
        const members = [d.managerId, ...d.workerIds].map((id) => roleById(id)).filter((r): r is RobotRole => !!r);
        return (
          <section key={d.id} aria-labelledby={`roster-${d.id}`}>
            <h3
              id={`roster-${d.id}`}
              style={{
                margin: "0 0 8px",
                color: d.color,
                fontSize: "1rem",
                letterSpacing: "0.08em",
                textTransform: "uppercase",
              }}
            >
              {d.label}
            </h3>
            <ul
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 300px), 1fr))",
                gap: 10,
                padding: 0,
                margin: 0,
              }}
            >
              {members.map((r) => (
                <RosterCard
                  key={r.id}
                  role={r}
                  portraitScale={portraitScale}
                  showOfficeScale={showOfficeScale}
                  reducedMotion={reducedMotion}
                />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

export default TeamRoster;
