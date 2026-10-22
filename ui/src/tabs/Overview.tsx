import { useEffect, useState } from "react";
import type { Health, Hello, Level, MappingRow, Snapshot, Tile } from "../bridge";
import { ageText, num, shown } from "../format";

const HERO: Record<Health, { glyph: string; word: string }> = {
  ok: { glyph: "✓", word: "OK" },
  warn: { glyph: "▲", word: "WARNING" },
  fault: { glyph: "✕", word: "FAULT" },
  unknown: { glyph: "?", word: "NO DATA" },
};

interface TileProps {
  label: string;
  value: string;
  unit: string;
  source: string;
  level?: Level;
  badge?: string;
  bar?: number | null;
  stale: boolean;
  staleAge?: number | null;
  waiting?: boolean;
  text?: boolean; // a word, not a number: smaller type
  problem?: string; // the mapping isn't working: say so in the foot
}

function StatTile({ label, value, unit, source, level = "ok", badge, bar, stale, staleAge, waiting, text, problem }: TileProps) {
  return (
    <div className={`tile tile--${stale ? "ok" : level}`} data-label={label}>
      <div className="tile__head">
        <span className="tile__label">{label}</span>
        {!stale && level !== "ok" && badge && <span className={`badge badge--${level}`}>{badge}</span>}
      </div>
      <div className={`tile__value ${stale ? "is-stale" : ""}`}>
        <span className={`mono tile__number ${text ? "tile__number--text" : ""}`} title={text ? value : undefined}>{value}</span>
        <span className="mono tile__unit">{value === "—" ? "" : unit}</span>
      </div>
      {bar != null && (
        <div className={`bar ${stale ? "is-stale" : ""}`}>
          <div className={`bar__fill bar__fill--${level}`} style={{ width: `${Math.max(0, Math.min(100, bar))}%` }} />
        </div>
      )}
      <div className="tile__foot">
        <span className={stale || problem ? "warn-fg strong" : "text-3 strong"}>
          {problem ?? (stale ? `STALE · ${ageText(staleAge ?? 0)}` : waiting ? "WAITING" : "LIVE")}
        </span>
        <span className="mono text-3 ellipsis">{source}</span>
      </div>
    </div>
  );
}

function tileProps(t: Tile, disc: boolean, discAge: number) {
  return { stale: disc || t.stale, staleAge: disc ? discAge + (t.age ?? 0) : t.age, waiting: t.value == null };
}

const sourceText = (t: Tile) => (t.source === "host" ? "this machine's sensor" : t.source ?? "");

/** Status and custom fields: numbers, words, or true/false. */
const PROBLEM: Record<string, string> = { missing: "NOT FOUND", error: "CAN'T READ" };

function FieldTile({ t, disc, discAge, row }: { t: Tile; disc: boolean; discAge: number; row?: MappingRow }) {
  const value = shown(t.value, t.kind);
  const badge = t.level === "fault" ? "✕ FAULT" : "▲ WARN";
  return (
    <StatTile label={(t.label ?? "").toUpperCase()} value={value} unit={t.kind === "number" ? t.unit : ""}
      source={sourceText(t)} level={t.level} badge={badge} text={t.kind !== "number"}
      problem={!disc && row ? PROBLEM[row.status] : undefined} {...tileProps(t, disc, discAge)} />
  );
}

/** Mapped topics that aren't working, with what to do about it. */
function MappingBanner({ rows }: { rows: MappingRow[] }) {
  const bad = rows.filter((r) => r.status === "missing" || r.status === "error");
  if (bad.length === 0) return null;
  return (
    <section className="mapbanner" role="status" data-testid="mapping-banner">
      <div className="mapbanner__head">
        <span className="mapbanner__glyph" aria-hidden="true">▲</span>
        <span className="strong">
          {bad.length === 1 ? "One mapped value isn't coming through" : `${bad.length} mapped values aren't coming through`}
        </span>
        <div className="spacer" />
        <a href="#configuration">Configuration</a>
      </div>
      <ul className="mapbanner__list">
        {bad.slice(0, 4).map((r) => (
          <li key={r.key}>
            <span className="strong">{r.label}</span>{" "}
            {r.status === "missing" && r.topic ? (
              <>
                <span className="mono">{r.topic}</span> not found.
                {r.suggestions.length > 0 && <> Did you mean <span className="mono">{r.suggestions[0]}</span>?</>}
              </>
            ) : (
              <span>{r.detail}</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function Overview(props: {
  snap?: Snapshot;
  hello?: Hello;
  disc: boolean;
  discAge: number;
  noRobot: boolean;
  latencyMs?: number;
}) {
  const { snap, hello, disc, discAge, noRobot, latencyMs } = props;
  if (!snap) return <p className="empty">Waiting for the bridge…</p>;
  if (noRobot) return <NoRobot snap={snap} domain={hello?.domain ?? snap.domain} version={hello?.version}
    fromFile={!!hello?.config && hello.config.source !== "environment"} />;

  const level: Health = disc ? "unknown" : snap.health.level;
  const lastKnown = HERO[snap.health.level].word;
  const line = disc ? `No data from the bridge for ${Math.round(discAge)} s. Last known status: ${lastKnown}.` : snap.health.line;
  const sub = disc
    ? `${snap.robot} · last update ${ageText(discAge)}`
    : `${snap.robot} · updated ${num(snap.last_message.age ?? 0, 1)} s ago`;
  const { battery, voltage, cpu_temp } = snap;
  const extra = [snap.status, ...(snap.fields ?? [])].filter((t): t is Tile => !!t);

  return (
    <div className={`page ${disc ? "is-dim" : ""}`}>
      <section className={`hero hero--${level}`} aria-live="polite" data-health={level}>
        <div className="hero__mark">
          <span className="hero__glyph">{HERO[level].glyph}</span>
          <span className="hero__word">{HERO[level].word}</span>
        </div>
        <div className="hero__text">
          <span className="hero__line">{line}</span>
          <span className="mono hero__sub">{sub}</span>
        </div>
      </section>

      {!disc && <MappingBanner rows={snap.mappings ?? []} />}

      <div className="tiles">
        {battery.mapped !== false && (
          <StatTile label="BATTERY" value={num(battery.value, 0)} unit="%" source={sourceText(battery)}
            level={battery.level} badge={battery.level === "fault" ? "✕ CRITICAL" : "▲ LOW"}
            bar={typeof battery.value === "number" ? battery.value : null} {...tileProps(battery, disc, discAge)} />
        )}
        {voltage.mapped !== false && (
          <StatTile label="VOLTAGE" value={num(voltage.value, 2)} unit="V" source={sourceText(voltage)}
            level={voltage.level} badge="▲ LOW" {...tileProps(voltage, disc, discAge)} />
        )}
        {cpu_temp.mapped !== false && (
          <StatTile label={(cpu_temp.label ?? "CPU temp").toUpperCase()} value={num(cpu_temp.value, 1)} unit="°C"
            source={sourceText(cpu_temp)} level={cpu_temp.level}
            badge={cpu_temp.level === "fault" ? "✕ HIGH" : "▲ HIGH"} {...tileProps(cpu_temp, disc, discAge)} />
        )}
        <StatTile label="LAST MESSAGE" value={disc ? "—" : num(snap.last_message.age, 1)} unit="s"
          source={snap.last_message.topic ? `from ${snap.last_message.topic}` : "no messages yet"}
          stale={disc} staleAge={discAge} />
        <StatTile label="LINK LATENCY" value={disc || latencyMs == null ? "—" : String(latencyMs)} unit="ms"
          source={`${snap.topics.length} topics · domain ${snap.domain}`} stale={disc} staleAge={discAge} />
      </div>

      {extra.length > 0 && (
        <div className="tiles tiles--extra">
          {extra.map((t) => (
            <FieldTile key={t.key ?? "status"} t={t} disc={disc} discAge={discAge}
              row={snap.mappings?.find((m) => m.key === (t.key ?? "status"))} />
          ))}
        </div>
      )}
    </div>
  );
}

function NoRobot({ snap, domain, version, fromFile }: { snap: Snapshot; domain: string; version?: string; fromFile: boolean }) {
  // The image this bridge came from, so the advice always matches what's running.
  const image = `ghcr.io/styri-dev/styri-core${version ? `:v${version}` : ""}`;
  // Discovery runs every 2 s on the bridge; count down to the next pass.
  const [scanIn, setScanIn] = useState(2);
  useEffect(() => {
    const t = setInterval(() => setScanIn((n) => (n <= 1 ? 2 : n - 1)), 1000);
    return () => clearInterval(t);
  }, []);

  const mapped = [...new Set((snap.mappings ?? []).map((m) => m.topic).filter((t): t is string => !!t))];
  const looking = mapped.length ? mapped.join(", ") : "/battery_state and /diagnostics";
  const checks = [
    {
      title: "ROS_DOMAIN_ID",
      body: `The bridge is on domain ${domain}. It only sees robots on the same domain — check the value on the robot and pass it in.`,
      code: "echo $ROS_DOMAIN_ID\ndocker run -e ROS_DOMAIN_ID=7 …",
    },
    {
      title: "--network host",
      body: "DDS discovery uses UDP multicast. Without host networking the container can't see the robot's nodes.",
      code: `docker run --rm --network host ${image}`,
    },
    {
      title: "Topic names",
      body: `Styri looks for ${looking}. ${fromFile
        ? "Check the names in your styri.yaml, then run styri check."
        : "If your robot uses other names, map them in a styri.yaml file (see the README)."}`,
      code: fromFile ? "styri check /etc/styri/styri.yaml" : 'ros2 topic list | grep -E "battery|diag"',
    },
  ];

  return (
    <div className="page page--narrow norobot">
      <div className="norobot__intro">
        <span className="microlabel norobot__scan"><span className="mono">○</span>SCANNING · NEXT CHECK IN {scanIn} S</span>
        <h1 className="norobot__title">No robot topics found</h1>
        <p className="norobot__lead">
          The bridge is running and listening on <span className="mono text-1">ROS_DOMAIN_ID={domain}</span>, but
          none of the expected topics have appeared. Work through these three checks — most first installs fail on
          one of them.
        </p>
      </div>
      <div className="checks">
        {checks.map((c, i) => (
          <div key={c.title} className="check">
            <div className="check__head">
              <span className="mono check__n">{i + 1}</span>
              <span className="mono check__title">{c.title}</span>
            </div>
            <p className="check__body">{c.body}</p>
            <code className="codeblock">{c.code}</code>
          </div>
        ))}
      </div>
      <div className="norobot__foot">
        <span>
          Seen so far:{" "}
          {snap.seen.length === 0 ? "nothing yet" : snap.seen.map((t, i) => (
            <span key={t}>{i > 0 && ", "}<span className="mono text-1">{t}</span></span>
          ))}
        </span>
        <div className="spacer" />
        <a href="https://github.com/styri-dev/styri/blob/main/docs/TROUBLESHOOTING.md" target="_blank" rel="noreferrer">Setup guide ↗</a>
      </div>
    </div>
  );
}
