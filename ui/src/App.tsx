import { useEffect, useRef, useState } from "react";
import { bridgeUrl, useBridge, useNow } from "./bridge";
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
type Tab = (typeof TABS)[number][0];

function tabFromHash(): Tab {
  const h = location.hash.replace("#", "");
  return (TABS.find(([k]) => k === h)?.[0] ?? "overview") as Tab;
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

export function App() {
  const { state, select, retryNow } = useBridge(URL);
  const now = useNow();
  const [tab, setTab] = useState<Tab>(tabFromHash);
  const [theme] = useState(initialTheme);

  useEffect(() => {
    const onHash = () => setTab(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  // When did we last have the bridge? Drives "No data for N s".
  const lostAt = useRef<number | null>(null);
  const disc = state.conn !== "open" && state.snapshot !== undefined;
  if (disc && lostAt.current === null) lostAt.current = now;
  if (!disc) lostAt.current = null;
  const discAge = lostAt.current === null ? 0 : (now - (state.snapshotAt ?? lostAt.current)) / 1000;

  const snap = state.snapshot;
  const noRobot = !!snap && !snap.robot_found && !disc;
  const robot = state.hello?.robot ?? snap?.robot ?? "—";
  const retryIn = state.retryAt ? Math.max(0, Math.ceil((state.retryAt - now) / 1000)) : 0;

  const conn =
    state.conn === "open"
      ? noRobot ? { word: "Connected · no robot", cls: "dot--idle" } : { word: "Connected", cls: "dot--live" }
      : state.snapshot ? { word: "Disconnected", cls: "dot--warn" } : { word: "Connecting…", cls: "dot--idle" };

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <Logo />
          <span className="wordmark">styri</span>
        </div>
        <div className="header__rule" />
        <span className="mono header__robot" title={`Robot: ${robot}`}>{robot}</span>
        <span className={`field__conn ${disc ? "is-warn" : ""}`} title={`Bridge at ${location.host}`}>
          <span className={`dot ${conn.cls}`} />
          {conn.word}
        </span>
        <div className="spacer" />
        <span className="chip">Local only · no account · no cloud</span>
        <span className="mono header__clock">{clock(new Date(now))}</span>
      </header>

      <nav className="tabs" aria-label="Sections">
        {TABS.map(([key, label]) => (
          <a key={key} href={`#${key}`} className={`tab ${tab === key ? "tab--active" : ""}`}
            aria-current={tab === key ? "page" : undefined}>
            <span className="tab__long">{label}</span>
            {SHORT[key] && <span className="tab__short">{SHORT[key]}</span>}
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

      <main className="main">
        {tab === "overview" && (
          <Overview snap={snap} hello={state.hello} disc={disc} discAge={discAge} noRobot={noRobot}
            latencyMs={state.latencyMs} />
        )}
        {tab === "topics" && <Topics snap={snap} disc={disc} discAge={discAge} message={state.message} select={select} />}
        {tab === "activity" && <Activity events={state.events} now={now} />}
        {tab === "controls" && <Controls snap={snap} history={state.history} />}
        {tab === "configuration" && <Configuration snap={snap} hello={state.hello} />}
      </main>
    </div>
  );
}
