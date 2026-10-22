import { type ReactNode, useEffect, useRef, useState } from "react";
import { type BridgeState, bridgeUrl, forRobot, useBridge, useNow } from "./bridge";
import { clock } from "./format";
import { Activity } from "./tabs/Activity";
import { Configuration } from "./tabs/Configuration";
import { Controls } from "./tabs/Controls";
import { Overview } from "./tabs/Overview";
import { Topics } from "./tabs/Topics";

const URL = bridgeUrl();
const TABS = [
  ["overview", "Overview"],
  ["topics", "Topics"],
  ["activity", "Activity log"],
  ["controls", "Controls"],
  ["configuration", "Configuration"],
] as const;
// Shorter labels where the tab bar is narrow.
const SHORT: Partial<Record<string, string>> = { activity: "Activity", configuration: "Config" };

/** What an edition built on Styri Core can add to the panel. Core passes none. */
export interface PanelContext {
  state: BridgeState;
  robot: number; // the robot the per-robot tabs show
  setRobot: (index: number, tab?: string) => void;
  send: (payload: Record<string, unknown>) => void;
  now: number;
}

export interface PanelTab {
  key: string;
  label: string;
  short?: string;
  first?: boolean; // before Overview
  visible?: (state: BridgeState) => boolean; // e.g. only once the bridge says there's a fleet
  render: (ctx: PanelContext) => ReactNode;
}

export interface PanelPlugin {
  tabs?: PanelTab[];
  defaultTab?: string; // used while that tab is visible
  hideOnPhones?: string[]; // tab keys
  header?: (ctx: PanelContext) => ReactNode; // in place of the robot name
  banner?: (ctx: PanelContext) => ReactNode; // under the tabs
}

function tabFromHash(keys: string[], fallback: string): string {
  const h = location.hash.replace("#", "");
  return keys.includes(h) ? h : fallback;
}

// Dark by default; ?theme=light (remembered) for bright rooms.
function initialTheme(): "dark" | "light" {
  const q = new URLSearchParams(location.search).get("theme");
  try {
    if (q === "light" || q === "dark") localStorage.setItem("styri.theme", q);
    return localStorage.getItem("styri.theme") === "light" ? "light" : "dark";
  } catch {
    return q === "light" ? "light" : "dark";
  }
}

export function Logo() {
  return (
    <svg viewBox="0 0 32 32" width="26" height="26" className="logo" aria-hidden="true">
      <rect width="32" height="32" rx="6" fill="var(--text-1)" />
      <path d="M22 9H11V16H21V23H10" fill="none" stroke="var(--surface-1)" strokeWidth="4" strokeLinecap="square" />
    </svg>
  );
}

export function App({ plugin = {} }: { plugin?: PanelPlugin }) {
  const { state, select, send, retryNow } = useBridge(URL);
  const now = useNow();
  const extra = (plugin.tabs ?? []).filter((t) => !t.visible || t.visible(state));
  const tabs: { key: string; label: string; short?: string }[] = [
    ...extra.filter((t) => t.first),
    ...TABS.map(([key, label]) => ({ key, label, short: SHORT[key] })),
    ...extra.filter((t) => !t.first),
  ];
  const keys = tabs.map((t) => t.key);
  const fallback = plugin.defaultTab && keys.includes(plugin.defaultTab) ? plugin.defaultTab : "overview";
  const [tab, setTab] = useState(() => tabFromHash(keys, fallback));
  const [robot, setRobotIndex] = useState(0);
  const [theme] = useState(initialTheme);

  const keyList = keys.join(",");
  useEffect(() => {
    const onHash = () => setTab(tabFromHash(keyList.split(","), fallback));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [keyList, fallback]);
  // A tab that appears (or goes) once the bridge says hello: follow it unless the URL picked one.
  useEffect(() => {
    setTab(tabFromHash(keyList.split(","), fallback));
  }, [keyList, fallback]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const setRobot = (index: number, toTab?: string) => {
    setRobotIndex(index);
    if (toTab) location.hash = toTab;
  };
  const view = forRobot(state, robot);

  // When did we last have the bridge? Drives "No data for N s".
  const lostAt = useRef<number | null>(null);
  const disc = state.conn !== "open" && view.snapshot !== undefined;
  if (disc && lostAt.current === null) lostAt.current = now;
  if (!disc) lostAt.current = null;
  const discAge = lostAt.current === null ? 0 : (now - (view.snapshotAt ?? lostAt.current)) / 1000;

  const snap = view.snapshot;
  const noRobot = !!snap && !snap.robot_found && !disc;
  const robotName = state.hello?.robots?.[robot]?.name ?? snap?.robot ?? state.hello?.robot ?? "—";
  const retryIn = state.retryAt ? Math.max(0, Math.ceil((state.retryAt - now) / 1000)) : 0;
  const ctx: PanelContext = { state, robot, setRobot, send, now };
  // The per-robot tabs see the selected robot's name, domain and namespace.
  const picked = state.hello?.robots?.[robot];
  const hello = state.hello && robot > 0 && picked
    ? {
        ...state.hello, robot: picked.name, domain: picked.domain,
        config: state.hello.config && { ...state.hello.config, domain: picked.domain, namespace: picked.namespace },
      }
    : state.hello;

  const conn =
    state.conn === "open"
      ? noRobot ? { word: "Connected · no robot", cls: "dot--idle" } : { word: "Connected", cls: "dot--live" }
      : snap ? { word: "Disconnected", cls: "dot--warn" } : { word: "Connecting…", cls: "dot--idle" };

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <Logo />
          <span className="wordmark">styri</span>
        </div>
        <div className="header__rule" />
        {plugin.header
          ? plugin.header(ctx)
          : <span className="mono header__robot" title={`Robot: ${robotName}`}>{robotName}</span>}
        <span className={`field__conn ${disc ? "is-warn" : ""}`} title={`Bridge at ${location.host}`}>
          <span className={`dot ${conn.cls}`} />
          {conn.word}
        </span>
        <div className="spacer" />
        <span className="chip">Local only · no account · no cloud</span>
        <span className="mono header__clock">{clock(new Date(now))}</span>
      </header>

      <nav className="tabs" aria-label="Sections">
        {tabs.map(({ key, label, short }) => (
          <a key={key} href={`#${key}`}
            className={`tab ${tab === key ? "tab--active" : ""} ${plugin.hideOnPhones?.includes(key) ? "tab--phone-hidden" : ""}`}
            aria-current={tab === key ? "page" : undefined}>
            <span className="tab__long">{label}</span>
            {short && <span className="tab__short">{short}</span>}
            {key === "configuration" && snap?.mappings?.some((m) => m.status === "missing" || m.status === "error") &&
              <span className="tab__alert" aria-label="needs attention">▲</span>}
            {key === "topics" && snap && <span className="tab__note">{snap.topics.length}</span>}
            {key === "controls" && <span className="tab__note tab__note--soon">SOON</span>}
          </a>
        ))}
      </nav>

      {disc && (
        <div className="banner" role="alert">
          <span className="banner__glyph">▲</span>
          <span className="banner__title">Lost connection to bridge — retrying</span>
          <span className="mono">{state.conn === "connecting" ? "now…" : `in ${retryIn} s`}</span>
          <div className="spacer" />
          <button type="button" className="banner__btn" onClick={retryNow}>Retry now</button>
        </div>
      )}
      {plugin.banner?.(ctx)}

      <main className="main">
        {extra.filter((t) => t.key === tab).map((t) => <div key={t.key}>{t.render(ctx)}</div>)}
        {tab === "overview" && (
          <Overview snap={snap} hello={hello} disc={disc} discAge={discAge} noRobot={noRobot}
            latencyMs={state.latencyMs} />
        )}
        {tab === "topics" && (
          <Topics snap={snap} disc={disc} discAge={discAge} robot={robot}
            message={state.message && (state.message.robot_index ?? 0) === robot ? state.message : undefined}
            select={select} />
        )}
        {tab === "activity" && <Activity events={state.events} now={now} />}
        {tab === "controls" && <Controls snap={snap} history={view.history} />}
        {tab === "configuration" && <Configuration snap={snap} hello={hello} />}
      </main>
    </div>
  );
}
