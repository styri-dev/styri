import { useEffect, useState } from "react";
import type { Snapshot, TopicMessage, TopicRow } from "../bridge";
import { ageText } from "../format";

function lastMsg(row: TopicRow, disc: boolean, discAge: number): string {
  if (!row.supported) return "not readable";
  if (disc) return ageText(discAge + (row.age ?? 0));
  if (row.age == null) return "idle";
  if (row.stale) return ageText(row.age);
  return row.age < 0.1 ? "< 0.1 s" : `${row.age.toFixed(1)} s`;
}

export function Topics(props: {
  snap?: Snapshot;
  disc: boolean;
  discAge: number;
  message?: TopicMessage;
  robot?: number;
  select: (topic: string, robot?: number) => void;
}) {
  const { snap, disc, discAge, message, select, robot = 0 } = props;
  const [picked, setPicked] = useState<string | null>(null);
  const topics = snap?.topics ?? [];
  const sel = topics.find((t) => t.name === picked)?.name
    ?? topics.find((t) => t.name.includes("battery"))?.name ?? topics[0]?.name;

  // Refresh the latest message while it is on screen.
  useEffect(() => {
    if (!sel || disc) return;
    select(sel, robot);
    const t = setInterval(() => select(sel, robot), 1000);
    return () => clearInterval(t);
  }, [sel, disc, select, robot]);

  if (!snap) return <p className="empty">Waiting for the bridge…</p>;
  const selRow = topics.find((t) => t.name === sel);
  const shown = message && message.topic === sel ? message : undefined;

  return (
    <div className={`page topics ${disc ? "is-dim" : ""}`}>
      <section className="card topics__list">
        <div className="card__head">
          <span className="card__title">{topics.length} TOPICS DISCOVERED</span>
          <span className="text-3 small">Stale after 5 s · tap a row for the latest message</span>
        </div>
        <div className="trow trow--head" role="row">
          <span>NAME</span><span>TYPE</span><span className="num">RATE</span><span className="num">LAST MSG</span>
        </div>
        {topics.map((row) => {
          const stale = disc || row.stale;
          return (
            <button key={row.name} type="button" className={`trow ${row.name === sel ? "is-selected" : ""}`}
              onClick={() => setPicked(row.name)} data-topic={row.name}>
              <span className="mono trow__name">{row.name}</span>
              <span className="mono trow__type">{row.type}</span>
              <span className="mono num">{!row.supported ? "—" : disc ? "0.0" : row.hz.toFixed(1)}</span>
              <span className={`mono num ${stale ? "warn-fg strong" : "text-2"}`}>{lastMsg(row, disc, discAge)}</span>
            </button>
          );
        })}
        {topics.length === 0 && <p className="empty">No topics yet. Discovery runs every 2 s.</p>}
      </section>

      <section className="card topics__detail" aria-live="polite">
        <div className="card__head card__head--stack">
          <span className="card__title">LATEST MESSAGE</span>
          <span className="mono strong break">{sel ?? "—"}</span>
          {selRow && <span className="mono small text-3">{selRow.type} · {selRow.hz.toFixed(1)} Hz</span>}
        </div>
        <pre className="message">
          {!sel ? "Pick a topic." : shown?.text ?? shown?.note ?? shown?.error ?? "Loading…"}
        </pre>
      </section>
    </div>
  );
}
