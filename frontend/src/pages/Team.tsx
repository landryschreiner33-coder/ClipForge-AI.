import { useState } from "react";
import { Icon, PageHead } from "../components/ui";
import { BY_ID, CAST, CORE, DEPARTMENTS, Dir, validateCast } from "../office/cast";
import Portrait from "../office/Portrait";
import { FRAMES, Pose } from "../office/sprites";

/** Team roster: every one of the 25 robots, who manages whom and what each one really does. */
export default function Team() {
  const [dir, setDir] = useState<Dir>("down");
  const director = CAST.filter((c) => c.rank === "director");
  const groups = Object.entries(DEPARTMENTS).map(([id, d]) => ({ id, ...d, members: CAST.filter((c) => c.dept === id) }));
  return (
    <div className="page team-page">
      <PageHead kind="Office" title="Team" crumbs={[{ label: "Office", href: "#/" }, { label: "Team" }]}
        sub="Each robot stands for one real part of the work. A robot moves only when that work really happens."
        actions={<div className="seg" role="group" aria-label="Facing">
          {(["down", "left", "up", "right"] as Dir[]).map((d) => (
            <button key={d} type="button" className={dir === d ? "on" : ""} aria-pressed={dir === d} onClick={() => setDir(d)}>
              {{ down: "Front", left: "Left", up: "Back", right: "Right" }[d]}
            </button>
          ))}
        </div>} />
      <section className="team-group" style={{ ["--accent" as string]: "#ffc94a" } as React.CSSProperties}>
        <h2>Boss Hub</h2>
        <div className="team-grid">{director.map((c) => <RobotCard key={c.id} id={c.id} dir={dir} />)}</div>
      </section>
      {groups.map((g) => (
        <section key={g.id} className="team-group" style={{ ["--accent" as string]: g.accent } as React.CSSProperties}>
          <h2>{g.name}</h2>
          <div className="team-grid">{g.members.sort((a, b) => (a.rank === "manager" ? -1 : 1) - (b.rank === "manager" ? -1 : 1))
            .map((c) => <RobotCard key={c.id} id={c.id} dir={dir} />)}
            {g.id === "brain" && (
              <article className="team-card">
                <div className="team-core" aria-hidden="true"><Icon name="spark" size={40} /></div>
                <div><b>{CORE.name}</b><span className="muted small block">{CORE.title}</span><p className="small">{CORE.job}</p></div>
              </article>
            )}
          </div>
        </section>
      ))}
    </div>
  );
}

function RobotCard({ id, dir }: { id: string; dir: Dir }) {
  const c = BY_ID[id];
  const manager = c.manager ? BY_ID[c.manager] : null;
  return (
    <article className="team-card">
      <Portrait id={id} dir={dir} scale={2} label={`${c.name}, ${c.title}`} />
      <div>
        <b>{c.name}</b>
        <span className="muted small block">{c.title}{c.rank === "manager" ? " · Manager" : c.rank === "director" ? " · Director" : ""}</span>
        <p className="small">{c.job}</p>
        <p className="tiny muted">{manager ? `Reports to ${manager.name}` : "Reports to you"}</p>
      </div>
    </article>
  );
}

/** Developer gallery (#/dev/robots): every robot in every direction and pose, for checking the art. */
export function RobotGallery() {
  const poses = Object.keys(FRAMES) as Pose[];
  const [pose, setPose] = useState<Pose>("idle");
  const problems = validateCast();
  return (
    <div className="page">
      <PageHead kind="Developer" title="Robot gallery" sub="All 25 robots in four directions. Choose a pose to check its frames."
        actions={<label className="small">Pose{" "}
          <select value={pose} onChange={(e) => setPose(e.target.value as Pose)}>
            {poses.map((p) => <option key={p} value={p}>{p} ({FRAMES[p].n} frame{FRAMES[p].n > 1 ? "s" : ""})</option>)}
          </select></label>} />
      {problems.length > 0 && <p className="error-text">{problems.join("; ")}</p>}
      <table className="gallery">
        <thead><tr><th>Robot</th>{(["down", "right", "up", "left"] as Dir[]).map((d) => <th key={d}>{d}</th>)}</tr></thead>
        <tbody>
          {CAST.map((c) => (
            <tr key={c.id}>
              <th scope="row">{c.name}<span className="block muted tiny">{c.title}</span></th>
              {(["down", "right", "up", "left"] as Dir[]).map((d) => (
                <td key={d}><Portrait id={c.id} dir={d} pose={pose} scale={2} /></td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
