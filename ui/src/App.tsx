import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { type BridgeState, bridgeUrl, useBridge, useNow } from "./bridge";
import { Banners, Header, StopAllBanner } from "./control/Header";
import { RobotCard } from "./control/RobotCard";
import { Activity } from "./tabs/Activity";
import { Configuration } from "./tabs/Configuration";
import { Empty } from "./tabs/Empty";
import { Fleet } from "./tabs/Fleet";
import { Login } from "./tabs/Login";
import { RobotPage } from "./tabs/RobotPage";
import { SiteMap } from "./tabs/SiteMap";
import { Topics } from "./tabs/Topics";
import { Users } from "./tabs/Users";
import { type Access, accessOf, type RobotView, robotView, sorted } from "./view";

const URL = bridgeUrl();
export const TABS = [["fleet", "Fleet"], ["map", "Map"], ["activity", "Activity"], ["topics", "Topics"]] as const;
const PHONE = 640;
const WIDE = 1280; // the fleet list beside the map

export type View = "fleet" | "map" | "activity" | "topics" | "robot" | "login" | "users" | "configuration";

/** Send to…: tap the map, then confirm. */
export interface SendPlan {
  step: "pick" | "confirm";
  dest?: string;
  via?: string;
  node?: string;
  point?: [number, number];
  path?: [number, number][]; // site metres
}

export interface PanelUi {
  sel: string | null;
  select: (name: string | null) => void;
  send: SendPlan | null;
  setSend: (s: SendPlan | null) => void;
  drive: boolean;
  setDrive: (on: boolean) => void;
  sheetOpen: boolean;
  setSheetOpen: (open: boolean) => void;
  sheetH: number;
}

/** What an edition built on Styri Core can add to the panel. Core passes none. */
export interface PanelPlugin {
  banner?: (ctx: PanelContext) => ReactNode; // under the tabs
  license?: (ctx: PanelContext) => string | undefined; // the line beside FLEET
}

export interface PanelContext {
  state: BridgeState;
  send: (payload: Record<string, unknown>) => void;
  select: (topic: string, robot?: number) => void;
  retryNow: () => void;
  now: number;
  width: number;
  phone: boolean;
  wide: boolean;
  disc: boolean;
  access: Access;
  robots: RobotView[]; // sorted for the screen
  ui: PanelUi;
  view: View;
  go: (view: View, id?: string) => void;
  openMap: (name: string) => void;
  openRobot: (name: string) => void;
  hasMap: boolean;
  noRobots: boolean; // the bridge is up, and no robot has ever reported
  theme: "dark" | "light";
  toggleTheme: () => void;
  setWall: (on: boolean) => void;
  wall: boolean;
  plugin: PanelPlugin;
}

interface Route { view: View; id?: string }

function parseRoute(): Route {
  const [view, id] = location.hash.replace(/^#/, "").split("/");
  const known: View[] = ["fleet", "map", "activity", "topics", "robot", "login", "users", "configuration"];
  return known.includes(view as View) && (view !== "robot" || id) ? { view: view as View, id: id && decodeURIComponent(id) } : { view: "fleet" };
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

function useWidth(): number {
  const [w, setW] = useState(window.innerWidth);
  useEffect(() => {
    const on = () => setW(window.innerWidth);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return w;
}

export function logout(send: PanelContext["send"]) {
  send({ action: "LOGOUT" });
  void fetch("/api/logout", { cache: "no-store" });
}

export function App({ plugin = {} }: { plugin?: PanelPlugin }) {
  const { state, select, send, retryNow } = useBridge(URL);
  const now = useNow();
  const width = useWidth();
  const phone = width < PHONE, wide = width >= WIDE;
  const [route, setRoute] = useState(parseRoute);
  const [from, setFrom] = useState<View>("fleet"); // where the robot page and login go back to
  const [theme, setTheme] = useState(initialTheme);
  const [wall, setWall] = useState(() => new URLSearchParams(location.search).has("wall"));
  const [sel, setSel] = useState<string | null>(null);
  const [plan, setPlan] = useState<SendPlan | null>(null);
  const [drive, setDrive] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [sheetH, setSheetH] = useState(0);
  const sheetRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const on = () => setRoute(parseRoute());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  useEffect(() => {
    if (!wall) return;
    const on = (e: KeyboardEvent) => e.key === "Escape" && setWall(false);
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [wall]);

  const go = useCallback((view: View, id?: string) => {
    setPlan(null);
    setDrive(false);
    if (view === "robot" || view === "login") setFrom((f) => (route.view === "robot" || route.view === "login" ? f : route.view));
    location.hash = id ? `${view}/${encodeURIComponent(id)}` : view;
  }, [route.view]);

  const access = useMemo(() => accessOf(state.control), [state.control]);
  const robots = useMemo(() => sorted(state.fleet.map((r) => robotView(r, { state, now, name: access.name }))), [state, now, access.name]);
  const site = state.hello?.site;
  const hasMap = !!(site?.graph || site?.background);

  const pick = useCallback((name: string | null) => {
    setSel(name);
    setPlan(null);
    setDrive(false);
    setSheetOpen(false);
  }, []);
  const ui: PanelUi = { sel, select: pick, send: plan, setSend: setPlan, drive, setDrive, sheetOpen, setSheetOpen, sheetH };

  const noRobots = !!state.hello && state.fleet.length > 0 && state.fleet.every((r) => r.last_seen == null && r.online !== true);
  const view = route.view === "users" && !access.admin ? "fleet"
    : route.view === "login" && state.hello && (!access.auth || (access.loggedIn && access.role !== "viewer")) ? from
    : route.view;
  // Logged in from #login: the address follows, so a reload doesn't land back there.
  useEffect(() => {
    if (route.view === "login" && view !== "login") {
      history.replaceState(null, "", `#${view}`);
      setRoute({ view });
    }
  }, [route.view, view]);
  const disc = state.conn !== "open";
  const openRobot = (name: string) => { setSel(name); go("robot", name); };
  const openMap = (name: string) => {
    if (!hasMap) return openRobot(name); // nothing to show it on
    pick(name);
    go("map");
  };
  const ctx: PanelContext = {
    state, send, select, retryNow, now, width, phone, wide, disc, access, robots, ui, view, go, openMap, openRobot, hasMap, noRobots,
    theme, toggleTheme: () => setTheme((t) => {
      const next = t === "dark" ? "light" : "dark";
      try { localStorage.setItem("styri.theme", next); } catch { /* private window */ }
      return next;
    }), setWall, wall, plugin,
  };

  // The card shows on the map and, with control on, beside the robot page.
  const detailName = view === "robot" ? route.id : null;
  const cardRobot = robots.find((v) => v.r.name === (view === "robot" ? detailName : sel));
  const showCard = !!cardRobot && !wall && ((view === "map" && hasMap) || (view === "robot" && access.control));
  useEffect(() => {
    const el = sheetRef.current;
    if (!el) { setSheetH(0); return; }
    const ro = new ResizeObserver(() => setSheetH(Math.round(el.getBoundingClientRect().height)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [showCard, phone]);

  const locked = !!state.hello?.locked;
  const driving = drive && view === "map" && !!cardRobot;
  const tabsAt = wall ? null : phone ? (driving ? null : "bottom") : "top";
  const curTab = view === "robot" || view === "login" ? from : view;
  const tabBar = (
    <nav className={`tabs tabs--${tabsAt}`} aria-label="Sections">
      {TABS.map(([key, label]) => (
        <a key={key} href={`#${key}`} className={`tab ${curTab === key ? "tab--active" : ""}`} aria-current={curTab === key ? "page" : undefined}
          onClick={() => { setPlan(null); setDrive(false); }}>{label}</a>
      ))}
    </nav>
  );

  if (locked) {
    return (
      <div className="app">
        <Header ctx={ctx} bare />
        <main className="main"><Login ctx={ctx} locked /></main>
      </div>
    );
  }

  let page: ReactNode;
  if (!state.hello) page = <p className="waiting">Waiting for the bridge…</p>;
  else if (view === "login") page = <Login ctx={ctx} />;
  else if (view === "users") page = <Users ctx={ctx} />;
  else if (view === "configuration") page = <Configuration ctx={ctx} />;
  else if (view === "activity") page = <Activity ctx={ctx} />;
  else if (view === "topics") page = <Topics ctx={ctx} />;
  else if (view === "robot") page = <RobotPage ctx={ctx} name={route.id!} back={from} />;
  else if (noRobots) page = <Empty ctx={ctx} />;
  else if (view === "map") page = <SiteMap ctx={ctx} />;
  else page = <Fleet ctx={ctx} />;

  return (
    <div className="app" data-view={view}>
      <Header ctx={ctx} hideStrip={driving} />
      {tabsAt === "top" && tabBar}
      <Banners ctx={ctx} />
      {plugin.banner?.(ctx)}
      <StopAllBanner ctx={ctx} />
      <div className="main">
        <div className={`main__page ${disc ? "is-frozen" : ""}`}>{page}</div>
        {showCard && <RobotCard ref={sheetRef} ctx={ctx} v={cardRobot!} where={view === "robot" ? "detail" : "map"} />}
      </div>
      {tabsAt === "bottom" && tabBar}
    </div>
  );
}
