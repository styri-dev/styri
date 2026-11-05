import { useState } from "react";
import type { PanelContext } from "../App";
import { Spinner } from "../control/Header";
import { TaskLine } from "../control/RobotCard";
import { PROTOCOL, type RobotView } from "../view";

const Paused = ({ sm }: { sm?: boolean }) => <span className={`chip-paused ${sm ? "chip-paused--sm" : ""}`}>❚❚ Paused</span>;

/** 1–3 robots: tiles fill the screen, one column each. */
function BigTile({ v, one, ctx, verdictSize }: { v: RobotView; one: boolean; ctx: PanelContext; verdictSize: number }) {
  const r = v.r;
  return (
    <div className={`ftile ftile--big tile-v-${v.key} ${v.unconfirmed ? "is-stop-failed" : ""} ${one ? "ftile--one" : ""}`} role="button" tabIndex={0}
      data-robot={r.name} data-health={v.health} data-task={r.task.state} onClick={() => ctx.openMap(r.name)}
      onKeyDown={(e) => e.key === "Enter" && ctx.openMap(r.name)}>
      <div className="ftile__head">
        <div className="ftile__id"><span className="ftile__name mono">{r.name}</span>{v.paused && <Paused />}</div>
        {v.fresh && <span className={`ftile__fresh ${ctx.disc ? "tone-warn" : "text-3"}`} data-testid="fresh">{v.fresh}</span>}
        <span className="badge-protocol" data-protocol={r.protocol}>{PROTOCOL[r.protocol]}</span>
      </div>
      <div className="ftile__body">
        <div className="ftile__left">
          <span className={`ftile__verdict v-${v.key} ${v.dim ? "is-dim" : ""}`} style={{ fontSize: verdictSize }}><span className="mono">{v.glyph}</span>{v.word}</span>
          {v.hasReason && <span className={`ftile__reason ${v.unconfirmed ? "tone-fault strong" : ""}`}>{v.shownReason}</span>}
          <div className={`ftile__task ${v.dim ? "is-dim" : ""}`}>
            <span className="ftile__t1">{v.t1}</span>
            <TaskLine v={v} size="big" />
          </div>
        </div>
        <div className="ftile__right">
          <div className={`ftile__vitals ${v.dim ? "is-dim" : ""}`}>
            {v.vitals.map((x) => (
              <div key={x.label}>
                <span className="microlabel microlabel--sm ellipsis">{x.label}</span>
                <span className={`ftile__vnum ${x.warn ? "tone-warn" : ""}`}>{x.value}<span className="unit"> {x.unit}</span></span>
              </div>
            ))}
          </div>
          <div className="spacer" />
          <div className={`ftile__bat ${v.dim ? "is-dim" : ""}`}>
            <span className="microlabel microlabel--lg">BATTERY</span>
            <span className={`ftile__batnum ${v.batteryLow ? "tone-warn" : ""}`} data-testid="battery">{v.battery}</span>
            <span className="ftile__pct">%</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/** 4–9 robots. */
function GridTile({ v, ctx }: { v: RobotView; ctx: PanelContext }) {
  const r = v.r;
  return (
    <div className={`ftile ftile--grid tile-v-${v.key} ${v.unconfirmed ? "is-stop-failed" : ""}`} role="button" tabIndex={0}
      data-robot={r.name} data-health={v.health} data-task={r.task.state} onClick={() => ctx.openMap(r.name)}
      onKeyDown={(e) => e.key === "Enter" && ctx.openMap(r.name)}>
      <div className="ftile__head">
        <div className="ftile__id"><span className="ftile__name mono">{r.name}</span>{v.paused && <Paused sm />}</div>
        <div className="ftile__tags">
          {v.fresh && <span className={`ftile__fresh ${ctx.disc ? "tone-warn" : "text-3"}`} data-testid="fresh">{v.fresh}</span>}
          <span className="badge-protocol badge-protocol--grid" data-protocol={r.protocol}>{PROTOCOL[r.protocol]}</span>
        </div>
      </div>
      <div className="ftile__mid">
        <span className={`ftile__verdict v-${v.key} ${v.dim ? "is-dim" : ""}`}><span className="mono">{v.glyph}</span>{v.word}</span>
        {v.hasReason && <span className={`ftile__reason ${v.unconfirmed ? "tone-fault strong" : ""}`}>{v.shownReason}</span>}
      </div>
      <div className={`ftile__foot ${v.dim ? "is-dim" : ""}`}>
        <span className={`ftile__batnum ${v.batteryLow ? "tone-warn" : ""}`} data-testid="battery">{v.battery}<span className="ftile__pct"> %</span></span>
        <div className="ftile__task">
          <span className="ftile__t1">{v.t1}</span>
          <TaskLine v={v} size="grid" />
        </div>
      </div>
    </div>
  );
}

function ListRows({ ctx }: { ctx: PanelContext }) {
  const { robots, phone } = ctx;
  const bg = (v: RobotView) => (v.unconfirmed || v.key === "fault" ? "var(--fault-bg)" : v.key === "warn" ? "var(--warn-bg)" : "transparent");
  return (
    <div className="flist">
      {!phone && <div className="flist__row flist__row--head"><span /><span>ROBOT</span><span>VERDICT</span><span className="right">BATTERY</span><span>TASK</span><span>PROTOCOL</span></div>}
      {robots.map((v) => phone ? (
        <button key={v.r.name} type="button" className="ftile flist__phone" style={{ background: bg(v) }} data-robot={v.r.name} data-health={v.health} data-task={v.r.task.state}
          onClick={() => ctx.openMap(v.r.name)}>
          <span className={`mono flist__glyph v-${v.key}`}>{v.glyph}</span>
          <span className="flist__two">
            <span className="flist__idline"><span className="mono flist__id">{v.r.name}</span>{v.paused && <span className="flist__paused">❚❚ Paused</span>}</span>
            <span className={`flist__side ellipsis ${v.sideTone === "text-2" ? "text-2" : `v-${v.sideTone}`}`}>{v.side}</span>
          </span>
          <span className={`mono flist__bat ${v.batteryLow ? "tone-warn" : ""}`}>{v.battery} %</span>
        </button>
      ) : (
        <button key={v.r.name} type="button" className="ftile flist__row" style={{ background: bg(v) }} data-robot={v.r.name} data-health={v.health} data-task={v.r.task.state}
          onClick={() => ctx.openMap(v.r.name)}>
          <span className={`mono flist__glyph v-${v.key}`}>{v.glyph}</span>
          <span className="flist__idline"><span className="mono flist__id">{v.r.name}</span>{v.paused && <span className="flist__paused">❚❚ Paused</span>}</span>
          <span className={`ellipsis v-${v.unconfirmed ? "fault" : v.key} ${v.hasReason ? "strong" : ""}`}>{v.listVerdict}</span>
          <span className={`mono right flist__bat ${v.dim ? "is-dim" : ""} ${v.batteryLow ? "tone-warn" : ""}`}>{v.battery} %</span>
          <span className={`flist__task ${v.dim ? "is-dim" : ""}`}>
            <span className="strong ellipsis">{v.t1}</span>
            {v.tk && <span className={`status status--sm tone-${v.tk.tone}`}><span className="mono">{v.tk.glyph}</span>{v.tk.label}{v.tk.spin && <Spinner />}</span>}
            {v.tk?.prog && <span className="mono xsmall text-3 nowrap">{v.tk.prog}</span>}
            {v.t2 && <span className="mono xsmall text-2 nowrap">{v.t2}</span>}
          </span>
          <span className="mono xsmall text-2 nowrap" data-protocol={v.r.protocol}>{PROTOCOL[v.r.protocol]}</span>
        </button>
      ))}
    </div>
  );
}

/** One row for the robots over the cap. */
function CapRow({ ctx }: { ctx: PanelContext }) {
  const list = ctx.state.notShown;
  if (!list.length) return null;
  const n = list.length;
  const covers = list[0].reason.replace(/^Not shown: /, "");
  const text = `${n} robot${n > 1 ? "s" : ""} not shown. ${covers[0].toUpperCase()}${covers.slice(1)}.`;
  return (
    <div className="caprow" data-testid="not-shown" title={list.map((r) => r.name).join(", ")} data-names={list.map((r) => r.name).join(" ")}>
      <span>{text}</span>
      <a href={list[0].link} target="_blank" rel="noreferrer">Pilot pricing →</a>
    </div>
  );
}

function Wall({ ctx }: { ctx: PanelContext }) {
  const n = ctx.robots.length;
  return (
    <div className="wall" data-testid="wall" style={{ gridTemplateColumns: n <= 3 ? `repeat(${Math.max(1, n)},minmax(0,1fr))` : "repeat(auto-fit,minmax(400px,1fr))" }}>
      {ctx.robots.map((v) => (
        <div key={v.r.name} className={`walltile tile-v-${v.key} ${v.unconfirmed ? "is-stop-failed" : ""}`}>
          <div className="walltile__head">
            <span className="walltile__id"><span className="mono">{v.r.name}</span>{v.paused && <span className="walltile__paused">❚❚ Paused</span>}</span>
            {v.fresh && <span className="mono walltile__fresh">{v.fresh}</span>}
          </div>
          <span className={`walltile__verdict v-${v.key} ${v.dim ? "is-dim" : ""}`}><span className="mono">{v.glyph}</span>{v.word}</span>
          {v.hasReason && <span className="walltile__reason">{v.shownReason}</span>}
          <div className="spacer" />
          <div className={`walltile__bat ${v.dim ? "is-dim" : ""}`}>
            <span className="microlabel">BATTERY</span>
            <span className={`mono walltile__num ${v.batteryLow ? "tone-warn" : ""}`}>{v.battery}</span>
            <span className="mono walltile__pct">%</span>
          </div>
        </div>
      ))}
    </div>
  );
}

export function Fleet({ ctx }: { ctx: PanelContext }) {
  const { robots, phone, width, wall, plugin } = ctx;
  const [picked, setPicked] = useState<"grid" | "list" | null>(null);
  if (wall) return <Wall ctx={ctx} />;
  const n = robots.length;
  const mode = picked ?? (n > 9 ? "list" : "grid");
  const rows = mode === "list";
  const big = !rows && n <= 3 && !phone;
  const count = `${n} ROBOT${n === 1 ? "" : "S"}`;
  const capped = ctx.state.notShown.length > 0;
  const license = plugin.license?.(ctx) ?? (capped ? "Core · free · 3 robots" : "Core · free");
  return (
    <div className="fleet">
      <div className="fleet__head">
        <div className="fleet__count"><span className="microlabel">FLEET · {count}</span><span className="mono xsmall text-3">{license}</span></div>
        {n > 3 && (
          <div className="segment" role="group" aria-label="Fleet layout">
            {(["grid", "list"] as const).map((m) => (
              <button key={m} type="button" aria-pressed={mode === m} className={mode === m ? "is-on" : ""} onClick={() => setPicked(m)}>{m === "grid" ? "Grid" : "List"}</button>
            ))}
          </div>
        )}
      </div>
      {big && (
        <div className="fleet__big" style={{ gridTemplateColumns: `repeat(${Math.max(1, n)},minmax(0,1fr))` }}>
          {robots.map((v) => <BigTile key={v.r.name} v={v} ctx={ctx} one={n === 1} verdictSize={n >= 3 && width < 1200 ? 50 : 64} />)}
        </div>
      )}
      {!big && !rows && <div className="fleet__grid">{robots.map((v) => <GridTile key={v.r.name} v={v} ctx={ctx} />)}</div>}
      {rows && <ListRows ctx={ctx} />}
      <CapRow ctx={ctx} />
    </div>
  );
}
