import { useEffect } from "react";
import type { PanelContext } from "../App";
import { PROTOCOL } from "../tabs/Fleet";
import { ControlDrawer } from "./ControlDrawer";

const AUDIT_EVERY_MS = 2000;

/** Under the Overview: task, vehicle details, this robot's commands, and the drawer. */
export function RobotDetail({ ctx, onLogin }: { ctx: PanelContext; onLogin: () => void }) {
  const robot = ctx.state.fleet.find((r) => r.index === ctx.robot);
  const loggedIn = !!ctx.state.control?.logged_in;
  const id = robot?.id;
  const { send } = ctx;
  // Not every command makes an Activity event (a drive doesn't), so ask on a timer.
  useEffect(() => {
    if (!loggedIn || !id) return;
    const ask = () => send({ action: "AUDIT", robot: id });
    ask();
    const t = setInterval(ask, AUDIT_EVERY_MS);
    return () => clearInterval(t);
  }, [loggedIn, id, send]);
  if (!robot) return null;
  const sheet = robot.factsheet;
  const type = sheet?.typeSpecification;
  const rows = ctx.state.audit.filter((r) => r.robot === robot.id).slice(-8).reverse();
  return (
    <div className="page detail">
      <ControlDrawer ctx={ctx} robot={robot} onLogin={onLogin} />
      {robot.vehicle_stop && <p className="banner-inline" role="alert">Vehicle safety stop active. Reset it at the vehicle.</p>}
      <section className="card">
        <div className="card__title">TASK</div>
        <dl className="kv">
          <div><dt>Protocol</dt><dd>{PROTOCOL[robot.protocol]}</dd></div>
          <div><dt>State</dt><dd className="mono" data-testid="detail-task">{robot.task.state}</dd></div>
          {robot.task.id && <div><dt>Goal or order</dt><dd className="mono ellipsis">{robot.task.id}</dd></div>}
          {robot.task.last_node && <div><dt>Last node</dt><dd className="mono">{robot.task.last_node}</dd></div>}
        </dl>
      </section>
      {sheet && (
        <section className="card" data-testid="factsheet">
          <div className="card__title">FACTSHEET</div>
          <dl className="kv">
            <div><dt>Series</dt><dd>{type?.seriesName ?? "—"}</dd></div>
            <div><dt>Class</dt><dd>{type?.agvClass ?? "—"}</dd></div>
            <div><dt>Kinematic</dt><dd>{type?.agvKinematic ?? "—"}</dd></div>
            <div><dt>Top speed</dt><dd className="mono">{sheet.physicalParameters?.speedMax ?? "—"} m/s</dd></div>
            <div><dt>Max load</dt><dd className="mono">{type?.maxLoadMass ?? "—"} kg</dd></div>
            <div><dt>Protocol version</dt><dd className="mono">{sheet.version ?? "—"}</dd></div>
          </dl>
        </section>
      )}
      {loggedIn && (
        <section className="card" data-testid="audit">
          <div className="card__title">COMMANDS <a className="small" href="/audit.jsonl">Export JSONL</a></div>
          {rows.length === 0 ? <p className="small text-3">No commands for this robot yet.</p> : (
            <ul className="audit">
              {rows.map((r) => (
                <li key={r.id}>
                  <span className="mono xsmall text-3">{r.time.slice(11, 19)}</span>
                  <span className={`mono small ${r.kind === "command_rejected" ? "warn-fg" : ""}`}>{r.command}</span>
                  <span className="small text-3 ellipsis">{r.kind === "command_rejected" ? r.reason : r.user}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
