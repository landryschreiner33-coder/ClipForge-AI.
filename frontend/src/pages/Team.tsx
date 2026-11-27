import { useState } from "react";
import { errorText } from "../api";
import { ConfirmDialog, Icon, PageHead, toast } from "../components/ui";
import { useAppearance } from "../prefs";
import { studio } from "../studio";
import { BY_ID, CAST, CORE, DEPARTMENTS, ROOM_NAMES, validateCast } from "../office/cast";
import Portrait from "../office/Portrait";
import { RobotNameEditor } from "../office/RobotName";
import { FRAME_NAMES, FrameName, Pose } from "../office/crew";

/** Team roster: every one of the 25 robots and the Brain Core, who manages whom and what each one really does.
 * Any of them can be renamed here or from the office's robot details; Reset all names asks first. */
export default function Team() {
  const [pose, setPose] = useState<Pose>("idle");
  const [askReset, setAskReset] = useState(false);
  const { refreshNames } = useAppearance();
  const resetAll = async () => {
    try {
      await studio.resetAllRobots();
      await refreshNames();
      toast("Every robot has its original name again");
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  const director = CAST.filter((c) => c.rank === "director");
  const groups = Object.entries(DEPARTMENTS).map(([id, d]) => ({ id, ...d, members: CAST.filter((c) => c.dept === id) }));
  return (
    <div className="page team-page">
      <PageHead kind="Studio" title="Team" crumbs={[{ label: "Studio", href: "#/" }, { label: "Office", href: "#/office" }, { label: "Team" }]}
        sub="Each robot stands for one real part of the work. A robot moves only when that work really happens. Rename any robot; its job stays the same."
        actions={<div className="row wrap">
          <div className="seg" role="group" aria-label="Show the robots">
            {(["idle", "work"] as Pose[]).map((p) => (
              <button key={p} type="button" className={pose === p ? "on" : ""} aria-pressed={pose === p} onClick={() => setPose(p)}>
                {p === "idle" ? "Standing" : "At work"}
              </button>
            ))}
          </div>
          <button type="button" className="btn btn-small" onClick={() => setAskReset(true)}><Icon name="refresh" />Reset all names</button>
        </div>} />
      {askReset && (
        <ConfirmDialog title="Give every robot its original name?" confirmLabel="Reset all names"
          onConfirm={resetAll} onClose={() => setAskReset(false)}>
          <p>All 25 robots and the Brain Core go back to their original names. Their jobs, rooms and work do not change.</p>
        </ConfirmDialog>
      )}
      <section className="team-group" style={{ ["--accent" as string]: "#ffc94a" } as React.CSSProperties}>
        <h2>{ROOM_NAMES.control}</h2>
        <div className="team-grid">{director.map((c) => <RobotCard key={c.id} id={c.id} pose={pose} />)}</div>
      </section>
      {groups.map((g) => (
        <section key={g.id} className="team-group" style={{ ["--accent" as string]: g.accent } as React.CSSProperties}>
          <h2>{g.name}</h2>
          <div className="team-grid">{g.members.sort((a, b) => (a.rank === "manager" ? -1 : 1) - (b.rank === "manager" ? -1 : 1))
            .map((c) => <RobotCard key={c.id} id={c.id} pose={pose} />)}
            {g.id === "brain" && (
              <article className="team-card">
                <div className="team-core" aria-hidden="true"><Icon name="spark" size={40} /></div>
                <div><b>{CORE.name}</b><span className="muted small block">{CORE.title}</span>
                  <RobotNameEditor id={CORE.id} />
                  <p className="small">{CORE.job}</p></div>
              </article>
            )}
          </div>
        </section>
      ))}
    </div>
  );
}

function RobotCard({ id, pose }: { id: string; pose: Pose }) {
  const c = BY_ID[id];
  const manager = c.manager ? BY_ID[c.manager] : null;
  return (
    <article className="team-card">
      <Portrait id={id} pose={pose} scale={2} label={`${c.name}, ${c.title}`} />
      <div>
        <b>{c.name}</b>
        <span className="muted small block">{c.title}{c.rank === "manager" ? " · Manager" : c.rank === "director" ? " · Director" : ""}</span>
        <RobotNameEditor id={id} />
        <p className="small">{c.job}</p>
        <p className="tiny muted">{manager ? `Reports to ${manager.name} (${manager.title})` : "Reports to you"}</p>
      </div>
    </article>
  );
}

/** Developer gallery (#/dev/robots): every robot in every frame, for checking the art. */
export function RobotGallery() {
  const problems = validateCast();
  const names: Record<FrameName, string> = {
    idle: "Standing", blink: "Blink", look_left: "Look left", look_right: "Look right", walk_left_a: "Walk left 1",
    walk_left_b: "Walk left 2", walk_right_a: "Walk right 1", walk_right_b: "Walk right 2", work_0: "Work 1",
    work_1: "Work 2", work_2: "Work 3", work_3: "Work 4",
  };
  return (
    <div className="page">
      <PageHead kind="Developer" title="Robot gallery" sub="All 25 robots in every frame the ship uses: standing, blinking, looking, walking and their own work gesture." />
      {problems.length > 0 && <p className="error-text">{problems.join("; ")}</p>}
      <div className="gallery-wrap">
        <table className="gallery">
          <thead><tr><th>Robot</th>{FRAME_NAMES.map((f) => <th key={f}>{names[f]}</th>)}</tr></thead>
          <tbody>
            {CAST.map((c) => (
              <tr key={c.id}>
                <th scope="row">{c.name}<span className="block muted tiny">{c.title}</span></th>
                {FRAME_NAMES.map((f) => <td key={f}><Portrait id={c.id} frame={f} scale={2} animate={false} /></td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
