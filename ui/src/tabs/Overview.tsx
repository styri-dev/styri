import { useEffect, useState } from "react";
import type { Health, Hello, Level, Snapshot, Tile } from "../bridge";
import { ageText, num } from "../format";

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
}

function StatTile({ label, value, unit, source, level = "ok", badge, bar, stale, staleAge, waiting }: TileProps) {
  return (
    <div className={`tile tile--${stale ? "ok" : level}`} data-label={label}>
      <div className="tile__head">
        <span className="tile__label">{label}</span>
        {!stale && level !== "ok" && badge && <span className={`badge badge--${level}`}>{badge}</span>}
      </div>
      <div className={`tile__value ${stale ? "is-stale" : ""}`}>
        <span className="mono tile__number">{value}</span>
        <span className="mono tile__unit">{value === "—" ? "" : unit}</span>
      </div>
      {bar != null && (
        <div className={`bar ${stale ? "is-stale" : ""}`}>
          <div className={`bar__fill bar__fill--${level}`} style={{ width: `${Math.max(0, Math.min(100, bar))}%` }} />
        </div>
      )}
      <div className="tile__foot">
        <span className={stale ? "warn-fg strong" : "text-3 strong"}>
          {stale ? `STALE · ${ageText(staleAge ?? 0)}` : waiting ? "WAITING" : "LIVE"}
        </span>
        <span className="mono text-3 ellipsis">{source}</span>
      </div>
    </div>
  );
}

function tileProps(t: Tile, disc: boolean, discAge: number) {
  return { stale: disc || t.stale, staleAge: disc ? discAge + (t.age ?? 0) : t.age, waiting: t.value == null };
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
  if (noRobot) return <NoRobot snap={snap} domain={hello?.domain ?? snap.domain} />;

  const level: Health = disc ? "unknown" : snap.health.level;
  const lastKnown = HERO[snap.health.level].word;
  const line = disc ? `No data from the bridge for ${Math.round(discAge)} s. Last known status: ${lastKnown}.` : snap.health.line;
  const sub = disc
    ? `${snap.robot} · last update ${ageText(discAge)}`
    : `${snap.robot} · updated ${num(snap.last_message.age ?? 0, 1)} s ago`;
  const { battery, voltage, cpu_temp } = snap;

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

      <div className="tiles">
        <StatTile label="BATTERY" value={num(battery.value, 0)} unit="%" source={battery.source}
          level={battery.level} badge={battery.level === "fault" ? "✕ CRITICAL" : "▲ LOW"} bar={battery.value}
          {...tileProps(battery, disc, discAge)} />
        <StatTile label="VOLTAGE" value={num(voltage.value, 2)} unit="V" source={voltage.source}
          {...tileProps(voltage, disc, discAge)} />
        <StatTile label="CPU TEMP" value={num(cpu_temp.value, 1)} unit="°C" source={cpu_temp.source}
          level={cpu_temp.level} badge={cpu_temp.level === "fault" ? "✕ HIGH" : "▲ HIGH"}
          {...tileProps(cpu_temp, disc, discAge)} />
        <StatTile label="LAST MESSAGE" value={disc ? "—" : num(snap.last_message.age, 1)} unit="s"
          source={snap.last_message.topic ? `from ${snap.last_message.topic}` : "no messages yet"}
          stale={disc} staleAge={discAge} />
        <StatTile label="LINK LATENCY" value={disc || latencyMs == null ? "—" : String(latencyMs)} unit="ms"
          source={`${snap.topics.length} topics · domain ${snap.domain}`} stale={disc} staleAge={discAge} />
      </div>
    </div>
  );
}

function NoRobot({ snap, domain }: { snap: Snapshot; domain: string }) {
  // Discovery runs every 2 s on the bridge; count down to the next pass.
  const [scanIn, setScanIn] = useState(2);
  useEffect(() => {
    const t = setInterval(() => setScanIn((n) => (n <= 1 ? 2 : n - 1)), 1000);
    return () => clearInterval(t);
  }, []);

  const checks = [
    {
      title: "ROS_DOMAIN_ID",
      body: `The bridge is on domain ${domain}. It only sees robots on the same domain — check the value on the robot and pass it in.`,
      code: "echo $ROS_DOMAIN_ID\ndocker run -e ROS_DOMAIN_ID=7 …",
    },
    {
      title: "--network host",
      body: "DDS discovery uses UDP multicast. Without host networking the container can't see the robot's nodes.",
      code: "docker run --network host … ghcr.io/styri-dev/styri",
    },
    {
      title: "Topic names",
      body: "Styri looks for /battery_state and /diagnostics. If your robot uses other names, set STYRI_BATTERY_TOPIC and STYRI_DIAGNOSTICS_TOPIC.",
      code: 'ros2 topic list | grep -E "battery|diag"',
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
