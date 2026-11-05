import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { PanelContext } from "../App";
import type { RobotModel } from "../bridge";
import { num } from "../format";
import { SOFTWARE_STOP } from "./Header";

export const STOP_WORDS = {
  sent: "Stop sent…",
  stopped: "Stopped",
  no_reply: "No reply from robot",
  not_confirmed: "Stop NOT confirmed: still moving",
  cant_confirm: "Stop sent · can't confirm: no speed feedback configured",
} as const;

/** The only stop states that tint a card red. Health stays what it is. */
export const stopFailed = (robot?: RobotModel) => robot?.stop === "not_confirmed" || robot?.stop === "no_reply";

const SEND_EVERY_MS = 66; // 15 Hz, inside the bridge's 300 ms watchdog gap
const PAD = 200;
const KEYS: Record<string, [number, number]> = {
  w: [1, 0], arrowup: [1, 0], s: [-1, 0], arrowdown: [-1, 0], a: [0, 1], arrowleft: [0, 1], d: [0, -1], arrowright: [0, -1],
};

/** Hold to drive. Commands go only while held; the bridge caps speed and holds the watchdog. */
function Joystick({ robot, send, maxLinear, maxAngular, blocked }: {
  robot: RobotModel; send: PanelContext["send"]; maxLinear: number; maxAngular: number; blocked: boolean;
}) {
  const [held, setHeld] = useState<[number, number] | null>(null); // -1..1 forward, left
  const heldRef = useRef(held);
  heldRef.current = held;
  const keys = useRef(new Set<string>());
  const pad = useRef<HTMLDivElement>(null);
  const id = robot.id;

  const release = useCallback(() => {
    if (heldRef.current) send({ action: "TELEOP_RELEASE", robot: id });
    setHeld(null);
  }, [id, send]);

  // While held, stream; the first command goes out at once.
  const active = held !== null;
  useEffect(() => {
    if (!active) return;
    const tick = () => {
      const v = heldRef.current;
      if (v) send({ action: "TELEOP", robot: id, linear: v[0] * maxLinear, angular: v[1] * maxAngular });
    };
    tick();
    const t = setInterval(tick, SEND_EVERY_MS);
    return () => clearInterval(t);
  }, [active, id, maxAngular, maxLinear, send]);

  // Anything that takes the page away lets go.
  useEffect(() => {
    const letGo = () => { keys.current.clear(); release(); };
    const onVisible = () => document.hidden && letGo();
    window.addEventListener("blur", letGo);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("blur", letGo);
      document.removeEventListener("visibilitychange", onVisible);
      letGo();
    };
  }, [release]);

  useEffect(() => {
    if (blocked) { keys.current.clear(); release(); }
  }, [blocked, release]);

  const fromKeys = useCallback(() => {
    let f = 0, l = 0;
    keys.current.forEach((k) => { f += KEYS[k][0]; l += KEYS[k][1]; });
    setHeld(keys.current.size ? [Math.max(-1, Math.min(1, f)), Math.max(-1, Math.min(1, l))] : null);
    if (!keys.current.size) send({ action: "TELEOP_RELEASE", robot: id });
  }, [id, send]);

  useEffect(() => {
    const typing = (e: KeyboardEvent) => e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement;
    const down = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase();
      if (!(k in KEYS) || typing(e) || blocked) return;
      e.preventDefault();
      if (!keys.current.has(k)) { keys.current.add(k); fromKeys(); }
    };
    const up = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase();
      if (keys.current.delete(k)) fromKeys();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  }, [blocked, fromKeys]);

  const place = (e: ReactPointerEvent) => {
    const box = pad.current!.getBoundingClientRect();
    const x = ((e.clientX - box.left) / box.width) * 2 - 1;
    const y = ((e.clientY - box.top) / box.height) * 2 - 1;
    const len = Math.max(1, Math.hypot(x, y));
    setHeld([-y / len, -x / len]);
  };

  const knob = held ? { transform: `translate(${-held[1] * PAD * 0.36}px, ${-held[0] * PAD * 0.36}px)` } : undefined;
  return (
    <div className="teleop">
      <div ref={pad} className={`pad ${blocked ? "is-off" : ""}`} data-testid="joystick" role="application"
        aria-label="Hold to drive"
        onPointerDown={(e) => { if (blocked) return; e.currentTarget.setPointerCapture(e.pointerId); place(e); }}
        onPointerMove={(e) => { if (heldRef.current && e.buttons + e.pressure > 0) place(e); }}
        onPointerUp={release} onPointerCancel={release} onLostPointerCapture={release}>
        <div className="pad__ring" />
        <div className="pad__knob" style={knob} />
      </div>
      <div className="teleop__read">
        <div><span className="microlabel">SPEED</span>
          <div className="mono teleop__big" data-testid="speed">{num(held ? held[0] * maxLinear : robot.velocity?.linear ?? 0, 2)}<span className="small text-3"> m/s</span></div></div>
        <div><span className="microlabel">TURN</span>
          <div className="mono teleop__big">{num(held ? held[1] * maxAngular : robot.velocity?.angular ?? 0, 2)}<span className="small text-3"> rad/s</span></div></div>
        <p className="small text-3">Press and hold to drive, or hold W A S D. Let go to stop.</p>
      </div>
    </div>
  );
}

export function ControlDrawer({ ctx, robot, onLogin }: { ctx: PanelContext; robot: RobotModel; onLogin: () => void }) {
  const control = ctx.state.control;
  if (!control?.enabled) return null;
  const caps = robot.capabilities;
  const send = (action: string, extra: Record<string, unknown> = {}) => ctx.send({ action, robot: robot.id, ...extra });
  const stopButton = caps.can_stop && (
    <div className="drawer__stop">
      <button type="button" className="opstop" data-testid="operator-stop" onClick={() => send("OPERATOR_STOP")}>Operator stop</button>
      <span className="small strong center">{SOFTWARE_STOP}</span>
      {robot.stop && <span className={`stopline stopline--${robot.stop}`} role="status" data-testid="stop-status">{STOP_WORDS[robot.stop]}</span>}
    </div>
  );
  if (!control.logged_in) {
    // Stopping needs no login, unless the site says so. Undoing one always does.
    return (
      <section className={`drawer drawer--locked ${stopFailed(robot) ? "is-stop-failed" : ""}`} data-testid="control-drawer">
        <div className="drawer__main">
          <button type="button" className="btn btn--solid" onClick={onLogin}>Log in to control robots</button>
        </div>
        {!control.stop_requires_login && stopButton}
      </section>
    );
  }
  const notice = ctx.state.notice && (ctx.state.notice.robot == null || ctx.state.notice.robot === robot.id) ? ctx.state.notice : undefined;
  const stale = robot.stale;
  const active = robot.task.state === "active" || robot.task.state === "paused";
  return (
    <section className={`drawer ${stopFailed(robot) ? "is-stop-failed" : ""}`} data-testid="control-drawer" aria-label={`Control ${robot.name}`}>
      <div className="drawer__main">
        {stale && <p className="warn-fg strong small" role="alert">Data is STALE: driving and waypoints are off. Operator stop stays available.</p>}
        {robot.warnings.map((w) => <p key={w} className="warn-fg small" role="status">{w}</p>)}
        {notice && <p className="warn-fg small" role="alert" data-testid="notice">{notice.text}</p>}
        {caps.can_teleop && <Joystick robot={robot} send={ctx.send} maxLinear={robot.limits.max_linear} maxAngular={robot.limits.max_angular} blocked={stale} />}
        <div className="drawer__row">
          {caps.can_waypoint && robot.points.map((p) => (
            <button key={p} type="button" className="btn btn--plain" disabled={stale} onClick={() => send("GOAL", { point: p })}>Go to {p}</button>
          ))}
          {caps.can_pause && !robot.paused && <button type="button" className="btn btn--plain" disabled={!active} onClick={() => send("PAUSE")}>Pause</button>}
          {caps.can_pause && robot.paused && <button type="button" className="btn btn--plain" onClick={() => send("RESUME")}>Resume</button>}
          {caps.can_cancel && <button type="button" className="btn btn--plain" disabled={!active} onClick={() => send("CANCEL")}>Cancel task</button>}
        </div>
      </div>
      {stopButton}
    </section>
  );
}
