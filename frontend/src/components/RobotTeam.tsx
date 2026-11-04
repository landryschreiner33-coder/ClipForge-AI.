import { useEffect, useState } from "react";
import { BY_ID, CAST } from "../office/cast";
import { office, RoleRow } from "../office/api";
import { STATE_WORDS } from "../office/OfficeMap";
import { POSE_OF } from "../office/panels";
import Portrait from "../office/Portrait";
import { useMotion } from "../motion";

/** The robot team on Home: who is really working right now (from the office's job feed), otherwise the managers
 * on standby. States come from real jobs only; nothing here starts or fakes work. */
export default function RobotTeam() {
  const [rows, setRows] = useState<Record<string, RoleRow> | null>(null);
  const motion = useMotion();
  useEffect(() => {
    let alive = true;
    const load = () => office.snapshot().then((s) => alive && setRows(Object.fromEntries(s.roles.map((r) => [r.id, r]))))
      .catch(() => alive && setRows(null));
    load();
    const t = window.setInterval(load, 5000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);
  const ACTIVE = ["working", "reviewing", "retrying"];
  const busy = CAST.filter((c) => ACTIVE.includes(rows?.[c.id]?.state || ""));
  const shown = (busy.length ? busy : CAST.filter((c) => c.rank !== "worker")).slice(0, 8);
  const animate = !motion.reduceMotion && !motion.pageHidden;  // Reduced motion and hidden pages freeze the robots
  return (
    <section className="panel robot-team" aria-labelledby="home-team">
      <div className="panel-head">
        <h2 id="home-team">Your robot team</h2>
        <div className="row-actions"><a className="btn btn-small" href="#/office/team">Team</a><a className="btn btn-small btn-primary" href="#/office">Open the Office</a></div>
      </div>
      <p className="small muted">{busy.length ? `${busy.length} robot${busy.length > 1 ? "s are" : " is"} working on real jobs.` :
        "Nobody is working right now. Robots move only when real work happens."}</p>
      <ul className="robot-strip">
        {shown.map((c) => {
          const r = rows?.[c.id];
          const state = r?.state || "idle";
          return (
            <li key={c.id}>
              <Portrait id={c.id} pose={POSE_OF[state] || "idle"} scale={2} animate={animate} label={`${BY_ID[c.id].name}, ${c.title}`} />
              <b className="clamp-1">{BY_ID[c.id].name}</b>
              <span className="tiny muted clamp-1">{c.title}</span>
              <span className={`tiny state-${state}`}>{STATE_WORDS[state]}{r?.task?.message ? `: ${r.task.message}` : ""}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
