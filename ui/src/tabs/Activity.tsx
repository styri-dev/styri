import { useEffect, useMemo, useState } from "react";
import type { PanelContext } from "../App";
import type { ActivityEvent } from "../bridge";
import { clock, csv, download, eventTime } from "../format";
import { auditView, type CommandView } from "../view";
import { Chain } from "./RobotPage";

const AUDIT_EVERY_MS = 2000;

interface Row {
  key: string;
  ts: number;
  user: string;
  robot: string;
  what: string;
  cmd: CommandView | null;
  note: string;
  kind?: string; // an event's kind
}

const isProblem = (r: Row) => r.kind === "warning" || (!!r.cmd && ["warn", "fault"].includes(r.cmd.tone));

function eventRow(e: ActivityEvent, names: Set<string>): Row {
  const [head, ...rest] = e.msg.split(" · ");
  const named = rest.length > 0 && names.has(head);
  return { key: `e${e.id}`, ts: e.ts, user: "—", robot: named ? head : "—", what: named ? rest.join(" · ") : e.msg, cmd: null, note: "", kind: e.kind };
}

function Pick({ label, value, options, onChange }: { label: string; value: string; options: [string, string][]; onChange: (v: string) => void }) {
  const on = value !== "all";
  return (
    <label className={`filter ${on ? "is-on" : ""}`}>
      <span className="text-3">{label}</span><b>{options.find(([v]) => v === value)?.[1] ?? "All"}</b><span className="text-3">▾</span>
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

export function Activity({ ctx }: { ctx: PanelContext }) {
  const { state, send, access, phone, now } = ctx;
  const [robot, setRobot] = useState("all");
  const [user, setUser] = useState("all");
  const [what, setWhat] = useState("all");
  const [status, setStatus] = useState("all");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const loggedIn = access.loggedIn;
  useEffect(() => {
    if (!loggedIn) return;
    const ask = () => send({ action: "AUDIT" });
    ask();
    const t = setInterval(ask, AUDIT_EVERY_MS);
    return () => clearInterval(t);
  }, [loggedIn, send]);

  const site = state.hello?.site;
  const rows = useMemo(() => {
    const names = new Set((state.hello?.robots ?? []).map((r) => r.name));
    const commands: Row[] = (loggedIn ? state.audit : [])
      .filter((a) => !(a.command === "TELEOP" && (a.payload as any)?.event === "start"))
      .map((a) => {
        const { verb, cmd, note } = auditView(a, site);
        return { key: `a${a.id}`, ts: Date.parse(a.time) / 1000, user: a.user ?? "—", robot: a.robot ?? "—", what: verb, cmd, note };
      });
    // Logged in, each stop has its own line: no need for the event as well.
    const events = state.events.filter((e) => !(loggedIn && e.source === "control" && /Operator stop from/.test(e.msg))).map((e) => eventRow(e, names));
    return [...commands, ...events].sort((a, b) => b.ts - a.ts);
  }, [state.audit, state.events, state.hello, loggedIn, site]);

  const shown = rows.filter((r) => (robot === "all" || r.robot === robot) && (user === "all" || r.user === user)
    && (what === "all" || r.what === what) && (status === "all" || isProblem(r)));
  const uniq = (key: (r: Row) => string) => [...new Set(rows.map(key))].filter((v) => v !== "—").sort().map((v): [string, string] => [v, v]);
  const exportCsv = () => {
    const name = `styri-activity-${new Date(now).toISOString().slice(0, 10)}.csv`;
    const events = state.events.filter((e) => shown.some((r) => r.key === `e${e.id}`));
    download(name, csv([["timestamp", "type", "event", "source"], ...events.map((e) => [new Date(e.ts * 1000).toISOString(), e.kind, e.msg, e.source])]));
  };
  const toggle = (k: string) => setOpen({ ...open, [k]: !open[k] });
  const shade = (r: Row) => {
    const bad = r.cmd?.tone === "fault", soft = r.cmd?.tone === "warn" || r.kind === "warning";
    return { background: bad ? "var(--fault-bg)" : soft ? "var(--warn-bg)" : "transparent", borderTopColor: bad ? "var(--fault-line)" : soft ? "var(--warn-line)" : "var(--line)" };
  };
  const statusOf = (r: Row) => (r.cmd
    ? <span className={`status status--sm tone-${r.cmd.tone}`}><span className="mono">{r.cmd.glyph}</span>{r.cmd.label}</span>
    : r.kind === "warning" ? <span className="status status--sm tone-warn"><span className="mono">▲</span>Warning</span>
    : <span className="status status--sm text-3">—</span>);
  const time = (r: Row) => (new Date(r.ts * 1000).toDateString() === new Date(now).toDateString() ? clock(new Date(r.ts * 1000)) : eventTime(r.ts, now));
  return (
    <div className="activity">
      <div className="activity__bar">
        <span className="page-title">Activity</span>
        <Pick label="Robot" value={robot} options={[["all", "All"], ...uniq((r) => r.robot)]} onChange={setRobot} />
        <Pick label="User" value={user} options={[["all", "All"], ...uniq((r) => r.user)]} onChange={setUser} />
        <Pick label="Command" value={what} options={[["all", "All"], ...uniq((r) => (r.cmd ? r.what : "—"))]} onChange={setWhat} />
        <Pick label="Status" value={status} options={[["all", "All"], ["problems", "Refused, Rejected, Failed, Not confirmed"]]} onChange={setStatus} />
        <span className="spacer" />
        {!phone && (
          <div className="activity__export">
            {loggedIn && <a className="btn-outline" href="/audit.jsonl">Export JSONL</a>}
            <button type="button" className="btn-outline" onClick={exportCsv}>Export CSV</button>
          </div>
        )}
      </div>
      <div className="atable" data-testid="activity">
        {!phone && <div className="arow__grid arow__grid--head"><span>TIME</span><span>USER</span><span>ROBOT</span><span>COMMAND</span><span>STATUS</span><span>REASON</span></div>}
        {shown.map((r) => phone ? (
          <button key={r.key} type="button" className="arow arow--phone" style={shade(r)} data-kind={r.kind} onClick={() => toggle(r.key)}>
            <span className="mono xsmall text-2">{time(r)}</span>
            <span className="minw0"><span className="mono strong">{r.robot}</span> · <span className="strong">{r.what}</span></span>
            {statusOf(r)}
            <span className={`mono xsmall arow__wide ${r.user === "anonymous" ? "text-3" : ""}`}>{r.user}</span>
            {r.note && <span className={`small arow__wide tone-${r.cmd?.tone ?? "text-2"}`}>{r.note}</span>}
            {open[r.key] && r.cmd && <span className="arow__wide"><Chain chain={r.cmd.chain} /></span>}
          </button>
        ) : (
          <div key={r.key} className="arow" style={shade(r)} data-kind={r.kind}>
            <button type="button" className="arow__grid" aria-expanded={!!open[r.key]} onClick={() => toggle(r.key)}>
              <span className="mono small text-2">{time(r)}</span>
              <span className={`mono small ${r.user === "anonymous" ? "text-3" : ""}`}>{r.user}</span>
              <span className="mono small strong">{r.robot}</span>
              <span className="strong">{r.what}</span>
              {statusOf(r)}
              <span className={`small ${r.cmd && r.cmd.ended && r.cmd.tone !== "ok" ? `tone-${r.cmd.tone} strong` : "text-2"}`}>{r.note}</span>
            </button>
            {open[r.key] && r.cmd && <div className="arow__chain"><Chain chain={r.cmd.chain} /></div>}
          </div>
        ))}
        {shown.length === 0 && <div className="atable__none">No events match these filters.</div>}
      </div>
    </div>
  );
}
