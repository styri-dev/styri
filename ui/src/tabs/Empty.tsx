import { useState } from "react";
import type { PanelContext } from "../App";
import { copyText, panelHost } from "../format";

type Mark = "pass" | "warn" | "fail";
const MARK: Record<Mark, { g: string; w: string; tone: string }> = {
  pass: { g: "●", w: "Pass", tone: "ok" },
  warn: { g: "▲", w: "Check", tone: "warn" },
  fail: { g: "◆", w: "Fail", tone: "fault" },
};

function Check({ mark, label, detail }: { mark: Mark; label: string; detail: string }) {
  const m = MARK[mark];
  return (
    <div className="check" data-check={label} data-mark={mark}>
      <span className={`check__mark tone-${m.tone}`}><span className="mono">{m.g}</span>{m.w}</span>
      <div className="check__text"><span className="check__label">{label}</span><span className="check__detail">{detail}</span></div>
    </div>
  );
}

function Seen({ who }: { who: string }) {
  const [copied, setCopied] = useState(false);
  const [manufacturer, serial] = who.split("/");
  const line = `- {name: ${serial.toLowerCase()}, protocol: vda5050, manufacturer: ${manufacturer}, serial: "${serial}"}`;
  return (
    <div className="seen">
      <span className="mono small break">{who}</span>
      <button type="button" className="btn-small" onClick={() => { void copyText(line); setCopied(true); }}>{copied ? "Copied" : "Copy config line"}</button>
    </div>
  );
}

/** Nothing has reported yet: what's been checked, what to check, and it updates by itself. */
export function Empty({ ctx }: { ctx: PanelContext }) {
  const { state } = ctx;
  const hello = state.hello!;
  const ros = (hello.robots ?? []).filter((r) => (r.protocol ?? "ros2") === "ros2");
  const vda = (hello.robots ?? []).filter((r) => r.protocol === "vda5050");
  const snap = state.snapshots[ros[0]?.index ?? 0];
  const topics = [...new Set((snap?.mappings ?? []).map((m) => m.topic).filter((t): t is string => !!t))];
  const looking = topics.length ? topics.slice(0, 2).join(" or ") : "/battery_state or /diagnostics";
  const broker = state.broker;
  const fromFile = !!hello.config && hello.config.source !== "environment";
  const unlisted = broker?.unconfigured ?? [];
  return (
    <div className="empty-page" data-testid="no-robots">
      <div className="empty-page__in">
        <div className="empty-page__head">
          <span className="empty-page__listen"><span className="pulse" />Listening on {panelHost()} · checking every 2 s</span>
          <span className="empty-page__title">No robots found</span>
          <span className="empty-page__lead">Styri is running, but nothing has reported yet. Work through the checks below. This page updates on its own.</span>
        </div>
        <div className="checks">
          {ros.length > 0 && (
            <section className="checks__card">
              <span className="checks__title">ROS 2</span>
              <Check mark="pass" label="ROS_DOMAIN_ID" detail={`${hello.domain}. The bridge only sees robots on the same domain.`} />
              <Check mark="warn" label="Host network" detail="DDS discovery needs the container on --network host." />
              <Check mark="warn" label="Topic names" detail={`No ${looking} seen yet. ${fromFile ? "Check the names in styri.yaml." : "If your robot uses other names, map them in a styri.yaml file."}`} />
            </section>
          )}
          {broker && (
            <section className="checks__card">
              <span className="checks__title">VDA 5050</span>
              <Check mark={broker.connected ? "pass" : "fail"} label="Broker reachable" detail={`${broker.url} ${broker.connected ? "answered." : "isn't answering."}`} />
              <Check mark={vda.length ? "pass" : "fail"} label="Robots configured"
                detail={`${vda.length} vehicle${vda.length === 1 ? "" : "s"} in styri.yaml.${unlisted.length ? ` ${unlisted.length} more on the broker.` : ""}`} />
              {unlisted.length > 0 && (
                <div className="seen-box">
                  <span className="microlabel">SEEN ON BROKER, NOT CONFIGURED</span>
                  {unlisted.map((who) => <Seen key={who} who={who} />)}
                </div>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
