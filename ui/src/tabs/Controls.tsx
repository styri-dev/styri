import type { Snapshot } from "../bridge";
import { num } from "../format";

/** Points for an SVG polyline, scaled into w x h between lo and hi. */
export function sparkPoints(values: number[], w: number, h: number, lo: number, hi: number): string {
  if (values.length < 2) return "";
  const span = hi - lo || 1;
  return values
    .map((v, i) => {
      const y = h - ((Math.min(hi, Math.max(lo, v)) - lo) / span) * h;
      return `${((i / (values.length - 1)) * w).toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

function Spark({ values, h, lo, hi, strong }: { values: number[]; h: number; lo: number; hi: number; strong?: boolean }) {
  return (
    <svg className="spark" width="120" height={h} viewBox={`0 0 140 ${h}`} preserveAspectRatio="none">
      <line x1="0" y1={h} x2="140" y2={h} className="spark__base" />
      <polyline points={sparkPoints(values, 140, h, lo, hi)} className={strong ? "spark__line" : "spark__line spark__line--weak"} />
    </svg>
  );
}

// A preview of the planned control panel. Styri Core is read-only: this tab
// renders no live controls and sends nothing to the robot.
export function Controls({ snap, history }: { snap?: Snapshot; history: { cpuTemp: number[]; load: number[] } }) {
  const bat = snap?.battery.value ?? null;
  return (
    <>
      <div className="soon" role="status">
        <span className="soon__chip"><span className="soon__dot" />NOT CONNECTED — COMING SOON</span>
        <span className="soon__text">Preview of the planned control panel. Core is read-only — nothing on this tab can command the robot.</span>
        <a href="https://github.com/styri-dev/styri/blob/main/ROADMAP.md" target="_blank" rel="noreferrer" className="soon__link">See roadmap ↗</a>
      </div>
      <div className="preview" aria-hidden="true" inert>
        <section className="preview__col preview__col--side">
          <div className="preview__block">
            <div className="preview__head"><span className="microlabel">BATTERY</span><span className="mono xsmall text-3">/battery_state</span></div>
            <div className="mono preview__big">{num(bat, 1)}<span className="text-2 preview__unit">%</span></div>
            <div className="bar"><div className="bar__fill bar__fill--ok" style={{ width: `${bat ?? 0}%` }} /></div>
          </div>
          <div className="preview__block">
            <div className="preview__head"><span className="microlabel">CPU TEMP</span><span className="mono xsmall text-3">limit 80 °C</span></div>
            <div className="preview__spark-row">
              <div className="mono preview__mid">{num(snap?.cpu_temp.value, 1)}<span className="text-3 preview__unit"> °C</span></div>
              <Spark values={history.cpuTemp} h={40} lo={40} hi={90} strong />
            </div>
            <div className="preview__spark-row">
              <div><span className="microlabel">CPU LOAD</span><div className="mono preview__small">{num(snap?.host.load_pct, 0)}<span className="small text-3"> %</span></div></div>
              <Spark values={history.load} h={28} lo={0} hi={100} />
            </div>
          </div>
          <div className="preview__block">
            <div className="preview__head"><span className="microlabel">DIAGNOSTICS</span><span className="mono xsmall text-3">/diagnostics</span></div>
            {["/lidar_front", "/imu", "/motor_left", "/motor_right"].map((n) => (
              <div key={n} className="preview__diag"><span className="dot dot--static" /><span className="mono small">{n}</span><span className="xsmall strong">OK</span></div>
            ))}
          </div>
        </section>
        <section className="preview__col preview__col--main">
          <div className="preview__bar">
            <span><strong className="preview__title">Teleop</strong> <span className="mono small text-3">/cmd_vel</span></span>
            <span className="microlabel">IDLE · ZERO TWIST</span>
          </div>
          <div className="preview__pad-wrap">
            <div className="preview__pad"><div className="preview__ring" /><div className="preview__knob" /></div>
            <div className="preview__readouts">
              <div><span className="microlabel">LINEAR.X</span><div className="mono preview__mid">+0.00<span className="small text-3"> m/s</span></div></div>
              <div><span className="microlabel">ANGULAR.Z</span><div className="mono preview__mid">+0.00<span className="small text-3"> rad/s</span></div></div>
            </div>
          </div>
          <p className="small text-3 center">Press and hold to drive. Release returns to zero.</p>
        </section>
        <section className="preview__col preview__col--side">
          <div className="preview__block preview__stop-wrap">
            <span className="preview__stop">SOFTWARE<span>STOP</span></span>
            <span className="small strong center">Software stop. Does not replace the robot's hardware E-stop.</span>
          </div>
          <div className="preview__block">
            <div className="preview__head"><span className="microlabel">AUDIT LOG</span><span className="mono xsmall text-3">local</span></div>
            <p className="small text-3">Every command, with who sent it, kept on this machine.</p>
          </div>
        </section>
      </div>
    </>
  );
}
