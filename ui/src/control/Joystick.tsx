import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { PanelContext } from "../App";
import type { RobotModel } from "../bridge";

const SEND_EVERY_MS = 66; // 15 Hz, inside the bridge's 300 ms watchdog gap
const RELEASED_MS = 1400;
const KEYS: Record<string, [number, number]> = {
  w: [1, 0], arrowup: [1, 0], s: [-1, 0], arrowdown: [-1, 0], a: [0, 1], arrowleft: [0, 1], d: [0, -1], arrowright: [0, -1],
};
const signed = (v: number) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2);

/** Hold to drive. Commands go only while held; the bridge caps speed and holds the watchdog. */
export function Joystick({ robot, send, phone }: { robot: RobotModel; send: PanelContext["send"]; phone: boolean }) {
  const [held, setHeld] = useState<[number, number] | null>(null); // -1..1 forward, left
  const [released, setReleased] = useState(false);
  const heldRef = useRef(held);
  heldRef.current = held;
  const keys = useRef(new Set<string>());
  const pad = useRef<HTMLDivElement>(null);
  const after = useRef<ReturnType<typeof setTimeout>>(undefined);
  const id = robot.id;
  const maxLinear = robot.limits.max_linear, maxAngular = robot.limits.max_angular;

  const release = useCallback(() => {
    if (heldRef.current) {
      send({ action: "TELEOP_RELEASE", robot: id });
      setReleased(true);
      clearTimeout(after.current);
      after.current = setTimeout(() => setReleased(false), RELEASED_MS);
    }
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

  const fromKeys = useCallback(() => {
    let f = 0, l = 0;
    keys.current.forEach((k) => { f += KEYS[k][0]; l += KEYS[k][1]; });
    if (keys.current.size) {
      setReleased(false);
      setHeld([Math.max(-1, Math.min(1, f)), Math.max(-1, Math.min(1, l))]);
    } else release();
  }, [release]);

  useEffect(() => {
    const typing = (e: KeyboardEvent) => e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement;
    const down = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase();
      if (!(k in KEYS) || typing(e)) return;
      e.preventDefault();
      if (!keys.current.has(k)) { keys.current.add(k); fromKeys(); }
    };
    const up = (e: KeyboardEvent) => {
      if (keys.current.delete(e.key.toLowerCase())) fromKeys();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  }, [fromKeys]);

  const place = (e: ReactPointerEvent) => {
    const box = pad.current!.getBoundingClientRect();
    const x = ((e.clientX - box.left) / box.width) * 2 - 1;
    const y = ((e.clientY - box.top) / box.height) * 2 - 1;
    const len = Math.max(1, Math.hypot(x, y));
    setReleased(false);
    setHeld([-y / len, -x / len]);
  };

  const lin = (held?.[0] ?? 0) * maxLinear, ang = (held?.[1] ?? 0) * maxAngular;
  const hint = held ? `${signed(lin)} m/s` : released ? "Released — stopping" : "Hold to drive";
  return (
    <div className="drive">
      <div ref={pad} className={`joy ${held ? "is-held" : ""}`} data-testid="joystick" role="application" aria-label="Hold to drive"
        style={{ maxWidth: phone ? 250 : 272 }}
        onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); place(e); }}
        onPointerMove={(e) => { if (heldRef.current && e.buttons + e.pressure > 0) place(e); }}
        onPointerUp={release} onPointerCancel={release} onLostPointerCapture={release}>
        <div className="joy__v" /><div className="joy__h" /><div className="joy__ring" />
        <span className="joy__fwd">FWD</span>
        <div className="joy__knob" style={{ left: `${50 - (held?.[1] ?? 0) * 35}%`, top: `${50 - (held?.[0] ?? 0) * 35}%` }} />
        <span className={`joy__hint ${held ? "tone-link" : released ? "tone-warn" : "tone-text-2"}`} data-testid="joy-hint">{hint}</span>
      </div>
      <div className="drive__read">
        <div className="drive__num">
          <span className="microlabel microlabel--sm">LINEAR</span>
          <span className="drive__value"><span data-testid="speed">{signed(lin)}</span><span className="unit"> / {maxLinear.toFixed(2)} m/s</span></span>
          <div className="meter"><div style={{ width: `${Math.min(100, (Math.abs(lin) / maxLinear) * 100)}%` }} /></div>
        </div>
        <div className="drive__num">
          <span className="microlabel microlabel--sm">ANGULAR</span>
          <span className="drive__value">{signed(ang)}<span className="unit"> / {maxAngular.toFixed(2)} rad/s</span></span>
          <div className="meter"><div style={{ width: `${Math.min(100, (Math.abs(ang) / maxAngular) * 100)}%` }} /></div>
        </div>
      </div>
    </div>
  );
}
