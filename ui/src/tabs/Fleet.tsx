import type { PanelContext } from "../App";
import type { Health, NotShown, RobotModel } from "../bridge";
import { STOP_WORDS, stopFailed } from "../control/ControlDrawer";
import { ageText, num } from "../format";

const WORD: Record<Health, { glyph: string; word: string }> = {
  ok: { glyph: "✓", word: "OK" },
  warn: { glyph: "▲", word: "WARNING" },
  fault: { glyph: "✕", word: "FAULT" },
  unknown: { glyph: "⊘", word: "OFFLINE" },
};

export const PROTOCOL = { ros2: "ROS 2", vda5050: "VDA 5050" } as const;

export function levelOf(r?: RobotModel): Health {
  return !r ? "unknown" : r.verdict === "OK" ? "ok" : r.verdict === "WARNING" ? "warn" : r.verdict === "FAULT" ? "fault" : "unknown";
}

function RobotTile({ index, name, r, ctx }: { index: number; name: string; r?: RobotModel; ctx: PanelContext }) {
  const disc = ctx.state.conn !== "open";
  const level = disc ? "unknown" : levelOf(r);
  const word = disc ? "NO DATA" : WORD[level].word; // the bridge is lost, not the robot
  const line = !r ? "Waiting for the first update…" : disc ? "No data from the bridge." : r.reason;
  const age = r?.last_seen == null ? null : Math.max(0, ctx.now / 1000 - r.last_seen);
  const stale = disc || !!r?.stale;
  return (
    <button type="button" className={`ftile ftile--${level} ${stopFailed(r) ? "is-stop-failed" : ""}`} data-robot={name} data-health={level}
      onClick={() => ctx.setRobot(index, "overview")} aria-label={`${name}: ${word}. Open its detail.`}>
      <div className="ftile__head">
        <span className={`ftile__glyph ftile__glyph--${level}`}>{WORD[level].glyph}</span>
        <span className="ftile__word">{word}</span>
        <span className="mono ftile__name ellipsis">{name}</span>
      </div>
      {r && <span className="badge-protocol" data-protocol={r.protocol}>{PROTOCOL[r.protocol]}</span>}
      <p className="ftile__line">{line}</p>
      {r?.stop && <span className={`stopline stopline--${r.stop}`}>{STOP_WORDS[r.stop]}</span>}
      <dl className="ftile__facts">
        <div>
          <dt>Battery</dt>
          <dd className="mono">{r?.battery == null ? "—" : `${num(r.battery, 0)} %`}</dd>
        </div>
        <div>
          <dt>Task</dt>
          <dd className="mono" data-testid="task-state">{r?.task.state ?? "—"}</dd>
        </div>
        <div>
          <dt>Last seen</dt>
          <dd className={`mono ${stale ? "warn-fg strong" : ""}`} data-testid="last-seen">
            {age == null ? "—" : stale ? `STALE · ${ageText(age)}` : `${num(age, 1)} s`}
          </dd>
        </div>
      </dl>
      <span className="ftile__open">Open robot →</span>
    </button>
  );
}

function NotShownRow({ robot }: { robot: NotShown }) {
  return (
    <div className="notshown" data-testid="not-shown">
      <span className="mono ellipsis">{robot.name}</span>
      <span className="text-2">{robot.reason}</span>
      <a href={robot.link} target="_blank" rel="noreferrer">See pricing ↗</a>
    </div>
  );
}

export function Fleet({ ctx }: { ctx: PanelContext }) {
  const hello = ctx.state.hello;
  const robots = hello?.robots ?? [];
  if (!hello) return <p className="empty">Waiting for the bridge…</p>;
  const model = (i: number) => ctx.state.fleet.find((r) => r.index === i);
  const counts = { ok: 0, warn: 0, fault: 0, unknown: 0 } as Record<Health, number>;
  robots.forEach((r) => { counts[levelOf(model(r.index))] += 1; });
  return (
    <div className="page fleet">
      <div className="fleet__head">
        <span className="card__title">FLEET · {robots.length} ROBOT{robots.length === 1 ? "" : "S"}</span>
        <span className="text-3 small">
          {(["fault", "warn", "unknown", "ok"] as Health[]).filter((k) => counts[k])
            .map((k) => `${counts[k]} ${WORD[k].word.toLowerCase()}`).join(" · ")}
        </span>
      </div>
      <div className="fleet__grid">
        {robots.map((r) => <RobotTile key={r.index} index={r.index} name={r.name} r={model(r.index)} ctx={ctx} />)}
      </div>
      {(hello.not_shown ?? []).map((r) => <NotShownRow key={r.name} robot={r} />)}
    </div>
  );
}
