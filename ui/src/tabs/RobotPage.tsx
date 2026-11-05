import { useEffect, useState } from "react";
import type { PanelContext, View } from "../App";
import type { AuditRow, MappingRow, RobotModel, Snapshot } from "../bridge";
import { TaskPanel } from "../control/RobotCard";
import { auditView, PROTOCOL, type RobotView } from "../view";

const AUDIT_EVERY_MS = 2000;
const HISTORY_ROWS = 10;

interface Tile { label: string; value: string; unit: string; bar?: number; warn?: boolean; source?: string | null }

/** Only what this robot actually reports: a value the bridge doesn't have is left out, not made up. */
function vitals(v: RobotView, snap?: Snapshot): Tile[] {
  const r = v.r;
  const out: Tile[] = [{ label: "BATTERY", value: v.battery, unit: "%", bar: r.battery ?? 0, warn: v.batteryLow, source: snap?.battery.source },
    { label: "SPEED", value: v.speed, unit: "m/s" }];
  if (v.cpu) out.push({ label: "CPU TEMP", value: v.cpu.value.toFixed(0), unit: "°C", warn: v.cpu.warn, source: v.cpu.source });
  if (r.voltage != null) out.push({ label: "VOLTAGE", value: r.voltage.toFixed(2), unit: "V", warn: snap?.voltage.level !== "ok", source: snap?.voltage.source });
  const scan = snap?.topics.find((t) => t.name.endsWith("/scan") || t.name === "scan");
  if (scan && r.protocol === "ros2") out.push({ label: "LIDAR", value: scan.hz.toFixed(1), unit: "Hz", source: scan.name });
  if (r.load != null) out.push({ label: "LOAD", value: r.load.toFixed(0), unit: "kg" });
  if (r.mode) out.push({ label: "MODE", value: r.mode.replace("AUTOMATIC", "AUTO"), unit: "" });
  for (const t of [snap?.status, ...(snap?.fields ?? [])]) {
    if (t && t.value != null) {
      const text = typeof t.value === "number" ? t.value.toFixed(Math.abs(t.value) >= 100 ? 0 : 2) : String(t.value);
      const tile = { label: (t.label ?? "").toUpperCase(), value: text, unit: t.kind === "number" ? t.unit : "", warn: t.level !== "ok", source: t.source };
      const same = out.findIndex((o) => o.label === tile.label); // a custom field beats a built-in with no reading
      if (same < 0) out.push(tile);
      else if (out[same].value === "—") out[same] = tile;
    }
  }
  return out;
}

function History({ ctx, r }: { ctx: PanelContext; r: RobotModel }) {
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const site = ctx.state.hello?.site;
  const shown = (a: AuditRow) => a.robot === r.id && !(a.command === "TELEOP" && (a.payload as any)?.event === "start");
  const rows = ctx.state.audit.filter(shown).slice(-HISTORY_ROWS).reverse();
  return (
    <section className="panel" data-testid="audit">
      <div className="panel__head"><span className="microlabel">COMMAND HISTORY</span><a href="#activity" className="linksm">All in Activity →</a></div>
      {rows.length === 0 && <p className="panel__none">No commands for this robot yet.</p>}
      {rows.map((a) => {
        const { verb, cmd, note } = auditView(a, site);
        const bad = a.status === "failed" ? "var(--fault-bg)" : a.status === "refused" || a.status === "rejected" ? "var(--warn-bg)" : "transparent";
        return (
          <button key={a.id} type="button" className="hist" style={{ background: bad }} aria-expanded={!!open[a.id]} onClick={() => setOpen({ ...open, [a.id]: !open[a.id] })}>
            <span className="mono small text-3">{new Date(a.time).toTimeString().slice(0, 8)}</span>
            <span className="minw0"><span className="strong">{verb}</span> <span className="mono xsmall text-3">{a.user}</span></span>
            <span className={`status status--sm tone-${cmd?.tone ?? "text-3"}`}><span className="mono">{cmd?.glyph}</span>{cmd?.label ?? "Event"}</span>
            {note && <span className={`hist__wide small tone-${cmd?.tone ?? "text-3"}`}>{note}</span>}
            {open[a.id] && cmd && <Chain chain={cmd.chain} wide />}
          </button>
        );
      })}
    </section>
  );
}

export function Chain({ chain, wide }: { chain: { label: string; tone: string; strong: boolean }[]; wide?: boolean }) {
  return (
    <span className={`chain ${wide ? "hist__wide" : ""}`}>
      {chain.map((g, i) => <span key={i} className={`tone-${g.tone} ${g.strong ? "strong" : ""}`}>{i > 0 ? "→ " : ""}{g.label}</span>)}
    </span>
  );
}

function Factsheet({ r }: { r: RobotModel }) {
  const f = r.factsheet ?? {};
  const type = f.typeSpecification ?? {};
  const actions = (f.protocolFeatures?.agvActions ?? []).map((a: any) => a.actionType).filter(Boolean);
  const facts: [string, unknown][] = [["Manufacturer", r.vendor ?? f.manufacturer], ["Model", r.model ?? type.seriesName], ["Series", type.seriesName],
    ["Class", type.agvClass], ["Kinematic", type.agvKinematic], ["Spec version", f.version],
    ["Max speed", f.physicalParameters?.speedMax != null ? `${Number(f.physicalParameters.speedMax).toFixed(2)} m/s` : null],
    ["Max load", type.maxLoadMass != null ? `${type.maxLoadMass} kg` : null], ["Supported actions", actions.join(" · ")]];
  return (
    <section className="panel panel--flat" data-testid="factsheet">
      <span className="microlabel panel__title">FACTSHEET</span>
      {facts.filter(([, v]) => v != null && v !== "").map(([k, v]) => (
        <div key={k} className="fact"><span className="text-3">{k}</span><span className="mono small break">{String(v)}</span></div>
      ))}
    </section>
  );
}

function Errors({ r }: { r: RobotModel }) {
  return (
    <section className="panel panel--flat" data-testid="errors">
      <span className="microlabel panel__title">ERRORS · VDA 5050</span>
      {r.errors.length === 0 && <span className="panel__line">No errors reported.</span>}
      {r.errors.map((e) => (
        <div key={`${e.type}-${e.description}`} className="err">
          <span className={`mono small strong ${e.level === "FATAL" ? "tone-fault" : "tone-warn"}`}>{e.level === "FATAL" ? "◆" : "▲"} {e.level}</span>
          <span className="err__text"><span className="mono">{e.type}</span><span className="text-2">{e.description}</span></span>
        </div>
      ))}
    </section>
  );
}

/** Mapped topics that aren't working, with what to do about it. */
function MappingBanner({ rows }: { rows: MappingRow[] }) {
  const bad = rows.filter((r) => r.status === "missing" || r.status === "error");
  if (bad.length === 0) return null;
  return (
    <section className="mapbanner" role="status" data-testid="mapping-banner">
      <div className="mapbanner__head">
        <span className="tone-warn mono" aria-hidden="true">▲</span>
        <span className="strong">{bad.length === 1 ? "One mapped value isn't coming through" : `${bad.length} mapped values aren't coming through`}</span>
        <a href="#configuration" className="linksm">Configuration</a>
      </div>
      <ul>
        {bad.slice(0, 4).map((r) => (
          <li key={r.key}>
            <span className="strong">{r.label}</span>{" "}
            {r.status === "missing" && r.topic ? (
              <><span className="mono">{r.topic}</span> not found.{r.suggestions.length > 0 && <> Did you mean <span className="mono">{r.suggestions[0]}</span>?</>}</>
            ) : <span>{r.detail}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function RobotPage({ ctx, name, back }: { ctx: PanelContext; name: string; back: View }) {
  const { state, phone, wide, access, width, ui } = ctx;
  const v = ctx.robots.find((x) => x.r.name === name);
  const id = v?.r.id;
  const { send } = ctx;
  const loggedIn = access.loggedIn;
  // Not every command makes an Activity event (a drive doesn't), so ask on a timer.
  useEffect(() => {
    if (!loggedIn || !id) return;
    const ask = () => send({ action: "AUDIT", robot: id });
    ask();
    const t = setInterval(ask, AUDIT_EVERY_MS);
    return () => clearInterval(t);
  }, [loggedIn, id, send]);
  if (!v) return <p className="waiting">Waiting for {name}…</p>;
  const r = v.r;
  const snap = state.snapshots[r.index];
  const showCol = access.control;
  const cols = phone ? 2 : (wide && showCol) || (!showCol && width >= 1100) ? 6 : 3;
  const reason = v.key !== "ok" || r.off_graph != null ? (v.reason || r.reason) : "";
  const backTo = back === "map" ? "Map" : "Fleet";
  return (
    <div className="detail" style={phone && showCol ? { paddingBottom: ui.sheetH + 16 } : undefined} data-testid="robot-page">
      <div className="detail__in">
        <div className="detail__head">
          <button type="button" className="btn-back" onClick={() => ctx.go(back === "map" ? "map" : "fleet")}>← {backTo}</button>
          <span className="detail__name mono">{r.name}</span>
          <span className="badge-protocol" data-protocol={r.protocol}>{PROTOCOL[r.protocol]}</span>
          {v.paused && <span className="chip-paused chip-paused--detail">❚❚ Paused</span>}
          <span className="small text-3">{[r.vendor, r.model].filter(Boolean).join(" · ")}</span>
        </div>
        <div className={`verdict tile-v-${v.key} ${v.unconfirmed ? "is-stop-failed" : ""}`} data-testid="verdict" data-health={v.health} aria-live="polite">
          <span className={`verdict__word v-${v.key}`}><span className="mono">{v.glyph}</span>{v.word}</span>
          {reason && <span className="verdict__reason">{reason}</span>}
          {v.fresh && <span className={`mono small ${ctx.disc ? "tone-warn" : "text-3"}`}>{v.fresh}</span>}
        </div>
        {!ctx.disc && <MappingBanner rows={snap?.mappings ?? []} />}
        <div className="vitals" style={{ gridTemplateColumns: `repeat(${cols},minmax(0,1fr))` }}>
          {vitals(v, snap).map((t) => (
            <div key={t.label} className={`vital ${t.warn ? "is-warn" : ""}`} data-label={t.label} title={t.source ?? undefined}>
              <span className="vital__label">{t.warn && "▲ "}{t.label}</span>
              <span className={`vital__value ${v.dim ? "is-dim" : ""}`}>{t.value}<span className="unit"> {t.unit}</span></span>
              {t.bar != null && <div className="meter meter--thin"><div style={{ width: `${t.bar}%`, background: v.batteryLow ? "var(--caution-500)" : "var(--text-2)" }} /></div>}
            </div>
          ))}
        </div>
        {(phone || !showCol) && <div className="panel"><TaskPanel ctx={ctx} v={v} /></div>}
        {r.vehicle_stop && <p className="vstop" role="alert">Vehicle safety stop active. Reset it at the vehicle.</p>}
        {r.warnings.map((w) => <p key={w} className="tone-warn small" role="status">{w}</p>)}
        {loggedIn && <History ctx={ctx} r={r} />}
        {r.protocol === "vda5050" && <div className="detail__pair"><Factsheet r={r} /><Errors r={r} /></div>}
        {r.protocol === "ros2" && (
          <section className="panel panel--ros">
            <span className="microlabel">ROS 2</span>
            <span className="small text-2">Domain {snap?.domain ?? state.hello?.domain} · {snap?.topics.length ?? 0} topics{r.capabilities.can_teleop ? <> · <span className="mono">cmd_vel</span> limited to {r.limits.max_linear.toFixed(2)} m/s, {r.limits.max_angular.toFixed(2)} rad/s</> : ""}.</span>
            <a href="#topics" className="linksm">Open Topics →</a>
          </section>
        )}
      </div>
    </div>
  );
}
