import type { Hello, MappingRow, MappingStatus, Snapshot } from "../bridge";
import { shown } from "../format";

const STATUS: Record<MappingStatus, { word: string; cls: string }> = {
  ok: { word: "OK", cls: "pill--ok" },
  waiting: { word: "WAITING", cls: "pill--idle" },
  stale: { word: "STALE", cls: "pill--warn" },
  missing: { word: "NOT FOUND", cls: "pill--fault" },
  error: { word: "CAN'T READ", cls: "pill--fault" },
};

function Row({ r }: { r: MappingRow }) {
  const s = STATUS[r.status];
  const value = r.value === undefined ? "" : shown(r.value, r.kind ?? "number");
  return (
    <div className="crow" data-mapping={r.key} data-status={r.status}>
      <span className="strong crow__label">{r.label}</span>
      <span className="mono crow__where break">{r.where}</span>
      <span className={`pill ${s.cls}`}>{s.word}</span>
      <span className="mono crow__value">{value !== "—" && value ? `${value}${r.unit && r.kind === "number" ? ` ${r.unit}` : ""}` : ""}</span>
      {(r.detail || r.suggestions.length > 0) && (
        <span className="crow__detail text-2">
          {r.detail}
          {r.suggestions.length > 0 && (
            <> Close matches: {r.suggestions.map((t, i) => (
              <span key={t}>{i > 0 && ", "}<span className="mono text-1">{t}</span></span>
            ))}.</>
          )}
        </span>
      )}
    </div>
  );
}

export function Configuration({ snap, hello }: { snap?: Snapshot; hello?: Hello }) {
  if (!snap || !hello) return <p className="empty">Waiting for the bridge…</p>;
  const c = hello.config;
  const fromFile = !!c && c.source !== "environment";
  const rows = snap.mappings ?? [];
  const failing = rows.filter((r) => r.status === "missing" || r.status === "error").length;

  return (
    <div className="page page--narrow config">
      <section className="card">
        <div className="card__head">
          <span className="card__title">CONFIGURATION</span>
          <span className="text-3 small">Read-only. Change styri.yaml and restart Styri.</span>
        </div>
        <dl className="kv">
          <dt>Source</dt>
          <dd className="mono break" data-testid="config-source">
            {fromFile ? c!.source : "Environment variables (no styri.yaml)"}
          </dd>
          <dt>Styri</dt><dd className="mono">v{hello.version}</dd>
          <dt>Robot</dt><dd className="mono">{hello.robot}</dd>
          <dt>Namespace</dt><dd className="mono">{c?.namespace ?? "none"}</dd>
          <dt>ROS domain</dt><dd className="mono">{c?.domain ?? hello.domain}</dd>
          <dt>Stale after</dt>
          <dd><span className="mono">{c?.stale_after ?? hello.stale_after} s</span>
            <span className="text-3"> · custom fields have their own, 3 s unless set</span></dd>
        </dl>
        {c?.error && (
          <div className="config__error" role="alert">
            <span className="strong">The file couldn't be used, so nothing from it is applied:</span>
            <span className="mono break">{c.error}</span>
          </div>
        )}
        {c?.notes.map((n) => <p key={n} className="config__note">{n}</p>)}
      </section>

      <section className="card">
        <div className="card__head">
          <span className="card__title">MAPPINGS</span>
          <span className="text-3 small">
            {failing ? `${failing} not working` : `${rows.length} mapped, all coming through`}
          </span>
        </div>
        {rows.map((r) => <Row key={r.key} r={r} />)}
        <p className="config__hint text-3 small">
          To test a file before you deploy it, run <span className="mono text-2">styri check styri.yaml</span> on a
          machine on the robot's network.
        </p>
      </section>
    </div>
  );
}
