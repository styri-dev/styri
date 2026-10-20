import { useState } from "react";
import type { ActivityEvent, EventKind } from "../bridge";
import { csv, download, eventTime } from "../format";

const KIND: Record<EventKind, { glyph: string; label: string; cls: string }> = {
  connection: { glyph: "⇄", label: "Connection", cls: "text-2" },
  state: { glyph: "●", label: "State change", cls: "text-2" },
  warning: { glyph: "▲", label: "Warning", cls: "warn-fg" },
};
const TYPES: [EventKind | "all", string][] = [["all", "All"], ["connection", "Connections"], ["state", "State changes"], ["warning", "Warnings"]];
const RANGES: [string, string, number][] = [["1h", "Last hour", 3600], ["24h", "24 h", 86400], ["all", "All", Infinity]];

function Segmented<T extends string>(props: { options: [T, string][]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div className="segmented" role="group" aria-label={props.label}>
      {props.options.map(([v, label]) => (
        <button key={v} type="button" className={props.value === v ? "is-on" : ""} aria-pressed={props.value === v}
          onClick={() => props.onChange(v)}>{label}</button>
      ))}
    </div>
  );
}

export function Activity({ events, now }: { events: ActivityEvent[]; now: number }) {
  const [kind, setKind] = useState<EventKind | "all">("all");
  const [range, setRange] = useState("24h");
  const [exportMsg, setExportMsg] = useState("");

  const limit = RANGES.find(([v]) => v === range)![2];
  const rows = events.filter((e) => now / 1000 - e.ts <= limit && (kind === "all" || e.kind === kind));

  const exportCsv = () => {
    const name = `styri-activity-${new Date(now).toISOString().slice(0, 10)}.csv`;
    download(name, csv([["timestamp", "type", "event", "source"],
      ...rows.map((e) => [new Date(e.ts * 1000).toISOString(), e.kind, e.msg, e.source])]));
    setExportMsg(`${name} · ${rows.length} rows`);
  };

  return (
    <div className="page">
      <div className="toolbar">
        <Segmented label="Event type" options={TYPES} value={kind} onChange={setKind} />
        <Segmented label="Time range" options={RANGES.map(([v, l]) => [v, l] as [string, string])} value={range}
          onChange={setRange} />
        <div className="spacer" />
        <span className="mono small text-3">{exportMsg}</span>
        <button type="button" className="btn-primary" onClick={exportCsv}>Export CSV</button>
      </div>
      <section className="card">
        <div className="lrow lrow--head"><span>TIME</span><span>TYPE</span><span>EVENT</span><span>SOURCE</span></div>
        {rows.map((e) => (
          <div key={e.id} className="lrow" data-kind={e.kind}>
            <span className="mono text-2 small">{eventTime(e.ts, now)}</span>
            <span className={`lrow__type ${KIND[e.kind].cls}`}><span className="lrow__glyph">{KIND[e.kind].glyph}</span>{KIND[e.kind].label}</span>
            <span className="lrow__msg">{e.msg}</span>
            <span className="mono xsmall text-3 break">{e.source}</span>
          </div>
        ))}
        {rows.length === 0 && <div className="empty empty--center">No events match these filters.</div>}
      </section>
      <span className="small text-3">Stored locally in SQLite on this machine. Export writes a file in your browser; nothing is uploaded.</span>
    </div>
  );
}
