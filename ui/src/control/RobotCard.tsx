import { type Ref, useRef } from "react";
import type { PanelContext } from "../App";
import { clock } from "../format";
import { destOf, HARDWARE_STOP, progressOf, PROTOCOL, type RobotView, stopOnly, verbOf } from "../view";
import { Spinner } from "./Header";
import { Joystick } from "./Joystick";

const NOTICE_MS = 8000; // a refusal says its piece, then the card's own line comes back

type Key = "details" | "login" | "send" | "drive" | "pause" | "resume" | "cancel";
const LABEL: Record<Key, string> = { details: "Details", login: "Log in to control", send: "Send to…", drive: "Drive", pause: "Pause", resume: "Resume", cancel: "Cancel task" };

/** The main action, the row under it, and the line that replaces a refusal, for a robot's state. */
function actionsFor(v: RobotView, ctx: PanelContext, where: "map" | "detail") {
  const { access, disc, ui, now } = ctx;
  const r = v.r, c = r.capabilities;
  const ros = r.protocol === "ros2";
  const hasTask = r.task.state === "active" || r.task.state === "paused";
  const blocked = r.stop === "sent" || v.unconfirmed;
  const canDrive = access.command && !disc && !r.stop && ros && c.can_teleop && !hasTask && !r.paused && !v.driven
    && (v.key === "ok" || v.key === "warn");
  let main: Key | null = null, sec: Key[] = [], line = "";
  const seen = r.last_seen == null ? 0 : Math.round(now / 1000 - r.last_seen);
  if (!access.control || disc || blocked) { /* the stop block says it all */ }
  else if (stopOnly(r)) line = "No speed feedback configured: this robot only has Operator stop.";
  else if (!access.command) { main = "login"; line = "Log in as an operator to send commands"; }
  else if (v.key === "stale") { sec = ["details"]; line = `No data for ${seen} s. Stop is still available.`; }
  else if (v.key === "offline") { sec = ["details"]; line = `${v.reason.split(". ")[0]}. Stop is still available.`; }
  else if (v.driven) { sec = ["details"]; line = `Being driven by ${r.driver}`; }
  else if (r.unsupported) { sec = ["details"]; line = `Unsupported: ${r.unsupported}. Only Operator stop is available.`; }
  else if (v.key === "fault") { main = "details"; if (hasTask && c.can_cancel) sec = ["cancel"]; line = "Next: check the robot and reset it from its own panel"; }
  else if (r.off_graph != null) {
    main = "details";
    if (hasTask && c.can_cancel) sec = ["cancel"];
    line = `${r.off_graph.toFixed(1)} m from the route. Move it onto the route with its own controls.`;
  } else if (r.paused) {
    main = c.can_pause ? "resume" : null;
    sec = hasTask && c.can_cancel ? ["cancel", "details"] : ["details"];
    line = r.stop === "stopped" ? "" : r.paused_by ? `Paused by ${r.paused_by} · Resume to send` : "Paused · Resume to send";
  } else if (hasTask) {
    main = c.can_pause ? "pause" : null;
    sec = [...(c.can_cancel ? ["cancel" as const] : []), ...(c.can_waypoint ? ["send" as const] : [])];
    if (ros && c.can_teleop) line = "Cancel the task to drive";
  } else {
    main = c.can_waypoint ? "send" : null;
    sec = canDrive ? ["drive", "details"] : ["details"];
  }
  if (where === "detail") {
    sec = sec.filter((k) => k !== "details");
    if (main === "details") main = null;
  }
  if (ui.send) { main = null; sec = []; line = ""; }
  return { main, sec, line, canDrive };
}

export function TaskPanel({ ctx, v }: { ctx: PanelContext; v: RobotView }) {
  const r = v.r, site = ctx.state.hello?.site;
  const active = r.task.state === "active" || r.task.state === "paused";
  const prog = progressOf(r);
  const c = r.command;
  const cmdLine = active && v.tk ? v.tk : null;
  return (
    <div className="task" data-testid="current-task">
      <div className="task__head">
        <span className="microlabel">CURRENT TASK</span>
        {active && prog && <span className="mono small text-2">{prog.done} of {prog.total} nodes reached</span>}
      </div>
      <span className="task__dest" data-testid="detail-task" data-task={r.task.state}>{active ? `→ ${destOf(r, site)}` : v.t1}</span>
      {active && prog && (
        <div className="task__segs">
          {Array.from({ length: prog.total }, (_, i) => (
            <span key={i} style={{ background: i < prog.done ? (r.paused ? "var(--text-3)" : "var(--accent)") : "var(--surface-3)" }} />
          ))}
        </div>
      )}
      {cmdLine && c && (
        <div className="task__cmd">
          <span className="text-2">{verbOf(c.action, c.node, site, c.point ? "point" : undefined)}</span>
          <span className={`status tone-${cmdLine.tone}`}><span className="mono">{cmdLine.glyph}</span>{cmdLine.label}{cmdLine.spin && <Spinner />}</span>
        </div>
      )}
    </div>
  );
}

export function TaskLine({ v, size }: { v: RobotView; size: "big" | "grid" | "card" }) {
  const tk = v.tk;
  return (
    <>
      {tk && (
        <div className={`cmdline cmdline--${size}`}>
          {tk.bars.length > 0 && <div className="bars">{tk.bars.map((c, i) => <span key={i} style={{ background: c }} />)}</div>}
          <span className={`status tone-${tk.tone}`}><span className="mono">{tk.glyph}</span>{tk.label}{tk.spin && <Spinner />}</span>
          {tk.prog && <span className="cmdline__prog mono">{tk.prog}</span>}
        </div>
      )}
      {v.t2 && <span className={`mono t2 t2--${size}`}>{v.t2}</span>}
    </>
  );
}

export function RobotCard({ ctx, v, where, ref }: { ctx: PanelContext; v: RobotView; where: "map" | "detail"; ref?: Ref<HTMLElement> }) {
  const { access, disc, phone, ui, state } = ctx;
  const r = v.r;
  const { main, sec: secondary, line, canDrive } = actionsFor(v, ctx, where);
  const drive = ui.drive && canDrive;
  const collapsed = phone && !drive && (where === "detail" || !ui.sheetOpen);
  const stopHere = access.stop && r.capabilities.can_stop;
  const notice = state.notice && state.notice.robot === r.id && ctx.now - state.notice.at < NOTICE_MS ? state.notice.text : "";
  const shownLine = notice || line;
  const send = (action: string) => ctx.send({ action, robot: r.id });
  const act = (k: Key) => {
    if (k === "details") ctx.openRobot(r.name);
    else if (k === "login") ctx.go("login");
    else if (k === "send") { ui.setSend({ step: "pick" }); ui.setSheetOpen(false); if (ctx.view !== "map") ctx.go("map"), ui.setSend({ step: "pick" }); }
    else if (k === "drive") ui.setDrive(true);
    else send(k === "pause" ? "PAUSE" : k === "resume" ? "RESUME" : "CANCEL");
  };
  const stop = () => {
    if (disc) return;
    send("OPERATOR_STOP");
    ui.setDrive(false);
  };
  const st = r.stop;
  const stopLabel = st === "sent" ? "Stop sent…" : st === "stopped" ? "Stopped" : "Operator stop";
  const stoppedAt = r.stop_at ? clock(new Date(r.stop_at * 1000)) : "";
  const stopSub = disc ? "Panel disconnected" : st === "sent" ? `Waiting for ${r.name}`
    : st === "stopped" ? `Stopped at ${stoppedAt}${r.paused ? " · robot is paused" : ""}`
    : v.unconfirmed ? "Tap to retry" : st === "cant_confirm" ? "Stop sent · can't confirm: no speed feedback configured" : "";
  const stopTone = st === "stopped" ? "ok" : v.unconfirmed ? "fault" : "text-2";
  const swipe = useRef<number | null>(null);
  const showReason = where === "map" && !collapsed && !drive && (v.key !== "ok" || r.off_graph != null) && !!v.reason;
  const showTask = where === "map" && !collapsed && !drive && !(v.unconfirmed && !r.task.route.length && v.t1 === "Operator stop");
  const showVitals = where === "map" && !collapsed && !drive;
  const vit = [{ l: "BATTERY", v: v.battery, u: "%", warn: v.batteryLow }, { l: "SPEED", v: v.speed, u: "m/s", warn: false },
    ...(v.cpu ? [{ l: "CPU", v: v.cpu.value.toFixed(0), u: "°C", warn: v.cpu.warn }] : [])];
  const cardClass = `card card--${where} ${phone ? "card--sheet" : ""} ${v.unconfirmed ? "is-stop-failed" : ""} ${drive && where === "map" && phone ? "card--drive" : ""}`;
  return (
    <aside ref={ref} className={cardClass} data-testid="control-drawer" aria-label={`Control ${r.name}`} data-collapsed={collapsed}>
      <div className={`card__in ${disc ? "is-frozen" : ""}`}>
        {phone && where === "map" && !drive && (
          <button type="button" className="card__grab" aria-label={collapsed ? "Show task and vitals" : "Show less"}
            data-testid="sheet-grab" onClick={() => ui.setSheetOpen(!ui.sheetOpen)}
            onPointerDown={(e) => { swipe.current = e.clientY; }}
            onPointerUp={(e) => {
              const moved = swipe.current == null ? 0 : e.clientY - swipe.current;
              swipe.current = null;
              if (Math.abs(moved) > 24) { e.preventDefault(); ui.setSheetOpen(moved < 0); }
            }}><span /></button>
        )}
        {where === "map" && (
          <div className="card__head">
            <div className="card__row">
              <div className="card__title">
                <span className="card__name mono">{r.name}</span>
                <span className={`card__verdict v-${v.key}`} data-health={v.health} data-testid="card-verdict"><span className="mono">{v.glyph}</span>{v.word}</span>
                {v.paused && <span className="chip-paused chip-paused--sm">❚❚ Paused</span>}
                {drive && <span className="chip-driving">Driving</span>}
              </div>
              {!drive && <button type="button" className="btn-ghost" onClick={() => ctx.openRobot(r.name)}>Details</button>}
              {!drive && <button type="button" className="btn-x" aria-label="Close" onClick={() => ui.select(null)}>×</button>}
            </div>
            {!collapsed && !drive && (
              <div className="card__meta">
                <span className="badge-protocol badge-protocol--sm" data-protocol={r.protocol}>{PROTOCOL[r.protocol]}</span>
                <span className="card__vendor">{[r.vendor, r.model].filter(Boolean).join(" · ")}</span>
                {v.fresh && <span className={`card__fresh ${disc ? "tone-warn" : "text-3"}`}>{v.fresh}</span>}
              </div>
            )}
          </div>
        )}
        {showReason && <span className={`card__reason v-${v.key}`}>{v.reason}</span>}

        {stopHere && (
          <div className="stopblock">
            {v.unconfirmed && <span className="stopblock__alert" role="alert" data-testid="stop-alert">◆ {HARDWARE_STOP[st!]}</span>}
            <button type="button" className={`opstop ${disc ? "is-off" : ""}`} data-testid="operator-stop" aria-disabled={disc} onClick={stop}>
              <span className="opstop__sq" /><span data-testid="stop-label">{stopLabel}</span>{st === "sent" && !disc && <Spinner />}
            </button>
            {stopSub && <span className={`stopblock__sub tone-${stopTone}`} role="status" data-testid="stop-status">{stopSub}</span>}
            <span className="stopblock__note">Software stop, not a safety function.</span>
          </div>
        )}

        {drive && (
          <>
            <Joystick robot={r} send={ctx.send} phone={phone} />
            <button type="button" className="btn-done" onClick={() => ui.setDrive(false)}>Done driving</button>
          </>
        )}
        {!drive && main && <button type="button" className="btn-main" onClick={() => act(main)}>{LABEL[main]}</button>}
        {!drive && shownLine && !(collapsed && !main) && (
          <span className={`card__line ${notice ? "tone-warn" : "text-2"}`} data-testid={notice ? "notice" : "card-line"}>{shownLine}</span>
        )}
        {!drive && !collapsed && secondary.length > 0 && (
          <div className="card__sec" style={{ gridTemplateColumns: `repeat(${secondary.length},minmax(0,1fr))` }}>
            {secondary.map((k) => <button key={k} type="button" className="btn-sec" onClick={() => act(k)}>{LABEL[k]}</button>)}
          </div>
        )}
        {where === "detail" && !phone && <div className="card__task"><TaskPanel ctx={ctx} v={v} /></div>}
        {showTask && (
          <div className={`card__tasksum ${v.dim ? "is-dim" : ""}`}>
            <span className="card__t1">{v.t1}</span>
            {!v.unconfirmed && <TaskLine v={v} size="card" />}
          </div>
        )}
        {showVitals && (
          <div className="card__vit">
            {vit.map((x) => (
              <div key={x.l} className={v.dim ? "is-dim" : ""}>
                <span className="microlabel microlabel--sm">{x.l}</span>
                <span className={`card__vnum ${x.warn ? "tone-warn" : ""}`} data-vital={x.l}>{x.v}<span className="unit"> {x.u}</span></span>
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
