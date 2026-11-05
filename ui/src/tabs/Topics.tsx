import { useEffect, useState } from "react";
import type { PanelContext } from "../App";
import type { TopicRow } from "../bridge";
import { ageText } from "../format";

function flag(row: TopicRow, disc: boolean, drives: boolean): { text: string; tone: string } {
  if (!row.supported) return { text: "not readable", tone: "text-3" };
  if (drives && row.name.endsWith("cmd_vel")) return { text: "Styri", tone: "link" };
  if (disc) return { text: "", tone: "text-3" };
  if (row.stale && row.age != null) return { text: `STALE · ${ageText(row.age)}`, tone: "text-3" };
  return { text: "", tone: "text-3" };
}

export function Topics({ ctx }: { ctx: PanelContext }) {
  const { state, ui, disc, select } = ctx;
  const ros = (state.hello?.robots ?? []).filter((r) => (r.protocol ?? "ros2") === "ros2");
  const [choice, setChoice] = useState<number | null>(null);
  const picked = ros.find((r) => r.index === choice) ?? ros.find((r) => r.name === ui.sel) ?? ros[0];
  const robot = picked?.index ?? 0;
  const snap = state.snapshots[robot];
  const topics = snap?.topics ?? [];
  const model = state.fleet.find((r) => r.index === robot);
  const [open, setOpen] = useState<string | null>(null);
  const message = state.message && (state.message.robot_index ?? 0) === robot && state.message.topic === open ? state.message : undefined;

  // Refresh the latest message while it is on screen.
  useEffect(() => {
    if (!open || disc) return;
    select(open, robot);
    const t = setInterval(() => select(open, robot), 1000);
    return () => clearInterval(t);
  }, [open, disc, select, robot]);

  if (!picked) {
    return <div className="topics"><div className="topics__head"><span className="page-title">Topics</span><span className="small text-2">ROS 2 robots only. This fleet has none.</span></div></div>;
  }
  return (
    <div className="topics">
      <div className="topics__head">
        <span className="page-title">Topics</span>
        <span className="small text-2">ROS 2 robots only · <span className="mono">{picked.name}</span> · domain {picked.domain}</span>
        {ros.length > 1 && (
          <label className="filter">
            <span className="text-3">Robot</span><b>{picked.name}</b><span className="text-3">▾</span>
            <select aria-label="Robot" value={robot} onChange={(e) => setChoice(Number(e.target.value))}>
              {ros.map((r) => <option key={r.index} value={r.index}>{r.name}</option>)}
            </select>
          </label>
        )}
      </div>
      <div className="ttable">
        <div className="ttable__in">
          <div className="trow trow--head"><span>TOPIC</span><span>TYPE</span><span>RATE</span><span /></div>
          {topics.map((row) => {
            const f = flag(row, disc, !!model?.capabilities.can_teleop);
            return (
              <div key={row.name} className="trow__wrap">
                <button type="button" className={`trow ${row.name === open ? "is-selected" : ""}`} aria-expanded={row.name === open} data-topic={row.name}
                  onClick={() => setOpen(row.name === open ? null : row.name)}>
                  <span className="strong break">{row.name}</span>
                  <span className="text-2 break">{row.type}</span>
                  <span className="num">{!row.supported || disc || row.hz === 0 ? "—" : `${row.hz.toFixed(row.hz >= 100 ? 0 : 1)} Hz`}</span>
                  <span className={`tone-${f.tone}`}>{f.text}</span>
                </button>
                {row.name === open && (
                  <pre className="message" aria-live="polite">{message?.text ?? message?.note ?? message?.error ?? "Loading…"}</pre>
                )}
              </div>
            );
          })}
          {topics.length === 0 && <p className="atable__none">No topics yet. Discovery runs every 2 s.</p>}
        </div>
      </div>
    </div>
  );
}
