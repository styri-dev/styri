// What each screen shows for a robot, in one place: the verdict, the stop, the task line.
// Pure. Every string the operator reads comes from the design's copy table.
import type { AuditRow, BridgeState, Command, ControlStatus, RobotModel, Role, Site, StopStatus } from "./bridge";
import { clock } from "./format";

export type VerdictKey = "ok" | "warn" | "fault" | "stale" | "offline";

export const VERDICT: Record<VerdictKey, { word: string; glyph: string }> = {
  ok: { word: "OK", glyph: "●" },
  warn: { word: "WARNING", glyph: "▲" },
  fault: { word: "FAULT", glyph: "◆" },
  stale: { word: "STALE", glyph: "◌" },
  offline: { word: "OFFLINE", glyph: "⊘" },
};

export const PROTOCOL = { ros2: "ROS 2", vda5050: "VDA 5050" } as const;

export const HARDWARE_STOP: Partial<Record<StopStatus, string>> = {
  no_reply: "No reply from robot — use the robot's own hardware stop",
  not_confirmed: "Stop NOT confirmed: still moving — use the robot's own hardware stop",
};
const SHORT_UNCONFIRMED: Partial<Record<StopStatus, string>> = { no_reply: "No reply from robot", not_confirmed: "Stop NOT confirmed" };

/** The only stop states that tint a card. Health stays what it is. */
export const stopFailed = (robot?: RobotModel) => robot?.stop === "not_confirmed" || robot?.stop === "no_reply";

/** Who may do what here. No `hello.control` at all is the default view-only install. */
export interface Access {
  auth: boolean; // this panel has logins
  control: boolean; // robot control is on
  loggedIn: boolean;
  name?: string;
  role?: Role;
  admin: boolean;
  command: boolean; // send, pause, drive
  stop: boolean;
}

export function accessOf(control?: ControlStatus): Access {
  const role = control?.logged_in ? control.user?.role : undefined;
  const on = !!control?.enabled;
  return {
    auth: !!control, control: on, loggedIn: !!control?.logged_in, name: control?.user?.name, role,
    admin: role === "admin", command: on && (role === "operator" || role === "admin"),
    stop: on && (!!control?.logged_in || !control?.stop_requires_login),
  };
}

export const ROLE_LABEL: Record<Role, string> = { viewer: "Viewer", operator: "Operator", admin: "Admin" };

export const agoText = (seconds: number) => {
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? `${s} s ago` : s < 3600 ? `${Math.floor(s / 60)} min ago` : s < 86400 ? `${Math.floor(s / 3600)} h ago` : `${Math.floor(s / 86400)} days ago`;
};
const ageShort = (s: number) => (s < 60 ? `${Math.round(s)} s` : s < 3600 ? `${Math.floor(s / 60)} min` : `${Math.floor(s / 3600)} h`);
const hhmm = (unix: number) => clock(new Date(unix * 1000)).slice(0, 5);

export const nodeName = (site: Site | undefined, id: string | null | undefined) =>
  (id && site?.graph?.nodes.find((n) => n.id === id)?.name) || id || "";

// ---- commands ---------------------------------------------------------------

export interface CommandView {
  label: string;
  glyph: string;
  tone: "text-1" | "text-2" | "text-3" | "link" | "ok" | "warn" | "fault";
  spin: boolean;
  bars: string[]; // colours
  chain: { label: string; tone: CommandView["tone"]; strong: boolean }[];
  ended: boolean;
}

const STEP = ["sent", "accepted", "running", "done"];
const STEP_WORD: Record<string, string> = { sent: "Sent", accepted: "Accepted", running: "Running", done: "Done" };
const LOOK: Record<string, Pick<CommandView, "label" | "glyph" | "tone"> & { spin?: boolean }> = {
  sent: { label: "Sent", glyph: "", tone: "text-2", spin: true },
  accepted: { label: "Accepted", glyph: "○", tone: "text-1" },
  running: { label: "Running", glyph: "▸", tone: "link" },
  done: { label: "Done", glyph: "✓", tone: "ok" },
  refused: { label: "Refused by Styri", glyph: "⊘", tone: "warn" },
  rejected: { label: "Rejected by robot", glyph: "▲", tone: "warn" },
  failed: { label: "Failed", glyph: "◆", tone: "fault" },
  not_confirmed: { label: "Not confirmed", glyph: "▲", tone: "warn" },
  cancelled: { label: "Cancelled", glyph: "", tone: "text-3" },
};
const STOP_LOOK: Record<string, Pick<CommandView, "label" | "glyph" | "tone"> & { spin?: boolean }> = {
  sent: { label: "Stop sent…", glyph: "", tone: "text-1", spin: true },
  stopped: { label: "Stopped", glyph: "■", tone: "ok" },
  no_reply: { label: "No reply", glyph: "◆", tone: "fault" },
  not_confirmed: { label: "Not confirmed", glyph: "◆", tone: "fault" },
  cant_confirm: { label: "Stop sent · can't confirm", glyph: "", tone: "text-2" },
};

export function commandView(status: string, steps: string[] | undefined, stop: boolean): CommandView {
  const look = (stop ? STOP_LOOK : LOOK)[status] ?? LOOK.sent;
  const ended = !["sent", "accepted", "running"].includes(status);
  if (status === "refused") {
    return { ...look, spin: false, ended, bars: [], chain: [{ label: "Refused by Styri · never sent to the robot", tone: look.tone, strong: true }] };
  }
  if (stop) {
    const chain = [{ label: "Stop sent", tone: (ended ? "text-2" : look.tone) as CommandView["tone"], strong: !ended }];
    if (ended) chain.push({ label: look.label, tone: look.tone, strong: true });
    return { ...look, spin: !!look.spin, ended, bars: [], chain };
  }
  const passed = (steps ?? [status]).filter((s) => STEP.includes(s));
  const failed = !STEP.includes(status);
  const chain = passed.map((s, i) => {
    const current = i === passed.length - 1 && !failed;
    return { label: STEP_WORD[s], tone: current ? look.tone : ("text-2" as const), strong: current };
  });
  if (failed) chain.push({ label: look.label, tone: look.tone, strong: true });
  const reached = passed.length - 1;
  const live = status === "done" ? "var(--ok-500)" : status === "running" ? "var(--accent)" : "var(--text-2)";
  const end = status === "failed" ? "var(--stop-500)" : "var(--caution-500)";
  const bars = STEP.map((_, i) => (failed
    ? (i <= reached ? "var(--text-3)" : i === reached + 1 ? end : "var(--surface-3)")
    : (i <= reached ? live : "var(--surface-3)")));
  return { ...look, spin: !!look.spin, ended, bars, chain };
}

export function verbOf(action: string, node: string | null | undefined, site: Site | undefined, point?: unknown): string {
  switch (action) {
    case "GOAL": return node ? `Send to ${nodeName(site, node)}` : point ? `Send to ${point}` : "Send to point";
    case "PAUSE": return "Pause";
    case "RESUME": return "Resume";
    case "CANCEL": return "Cancel task";
    case "OPERATOR_STOP": return "Operator stop";
    case "OPERATOR_STOP_ALL": return "Stop all";
    case "TELEOP": return "Drive";
    case "GRAPH_SAVE": return "Graph saved";
    case "USER_ADD": return "User added";
    case "USER_REMOVE": return "User removed";
    case "USER_ROLE": return "Role changed";
    case "USER_PASSWORD": return "Password reset";
    case "SWITCHES": return "Control settings";
    default: return action;
  }
}

/** One audit line in the operator's words. */
export function auditView(row: AuditRow, site: Site | undefined) {
  const p = (row.payload ?? {}) as Record<string, any>;
  const nodes = Array.isArray(p.nodes) ? p.nodes : [];
  const verb = verbOf(row.command, p.node ?? nodes[nodes.length - 1], site, p.point);
  const status = row.status ?? (row.command === "TELEOP" || row.command === "GRAPH_SAVE" ? "done" : undefined);
  const stop = row.command === "OPERATOR_STOP";
  const cmd = status ? commandView(status, row.steps, stop) : null;
  let note = row.reason ?? "";
  if (row.command === "TELEOP" && typeof p.seconds === "number") {
    note = p.seconds < 60 ? `${p.seconds} s` : `${Math.floor(p.seconds / 60)} min ${p.seconds % 60} s`;
  }
  if (row.command === "GRAPH_SAVE") note = `${p.nodes} nodes, ${p.edges} edges`;
  if (row.command.startsWith("USER_") && p.name) note = `${p.name}${p.role ? ` → ${ROLE_LABEL[p.role as Role] ?? p.role}` : ""}`;
  if (stop && (status === "no_reply" || status === "not_confirmed")) note = HARDWARE_STOP[status as StopStatus]!;
  return { verb, cmd, note };
}

// ---- a robot ----------------------------------------------------------------

export interface Vital {
  label: string;
  value: string;
  unit: string;
  warn?: boolean;
  source?: string;
}

export interface RobotView {
  r: RobotModel;
  key: VerdictKey;
  word: string;
  glyph: string;
  health: "ok" | "warn" | "fault" | "unknown";
  unconfirmed: boolean;
  reason: string; // the robot's own reason
  shownReason: string; // what a tile says: an unconfirmed stop goes first
  hasReason: boolean;
  fresh: string; // "STALE · 12 s" or "Frozen 14:09:31", only when it applies
  dim: boolean;
  paused: boolean;
  driven: boolean; // by someone else
  stoppedNow: boolean;
  battery: string;
  batteryLow: boolean;
  t1: string;
  tk: (CommandView & { prog: string }) | null;
  t2: string;
  side: string; // the one line a narrow row has room for
  sideTone: "text-2" | VerdictKey;
  listVerdict: string;
  vitals: Vital[]; // SPEED, CPU and whichever other is closest to its limit
  speed: string;
  cpu: { value: number; source: string | null; warn: boolean } | null;
  nextNode?: string;
}

export interface RobotEnv {
  state: BridgeState;
  now: number;
  name?: string; // who's looking
}

const compact = (s: string) => s.replace(/(\d+) of (\d+) nodes/, "$1/$2 nodes");

export function progressOf(r: RobotModel): { done: number; total: number } | null {
  const total = r.task.nodes_total;
  return total > 0 ? { done: total - r.task.route.length, total } : null;
}

export function destOf(r: RobotModel, site: Site | undefined): string {
  const last = r.task.route[r.task.route.length - 1];
  if (last) return nodeName(site, last);
  const c = r.command;
  if (c?.action === "GOAL" && c.node) return nodeName(site, c.node);
  if (c?.action === "GOAL" && c.point) return `Point ${c.point[0].toFixed(1)}, ${c.point[1].toFixed(1)} m`;
  return r.task.id ?? "task";
}

export function offlineReason(r: RobotModel, brokerDown: boolean): string {
  const since = r.last_seen != null ? `Offline since ${hhmm(r.last_seen)}. ` : "Offline. ";
  return since + (brokerDown ? "Broker unreachable." : "VDA 5050 connection lost.");
}

export function robotView(r: RobotModel, env: RobotEnv): RobotView {
  const { state, now } = env;
  const site = state.hello?.site;
  const disc = state.conn !== "open";
  const brokerDown = !!state.broker && !state.broker.connected;
  // Off the graph is a warning however healthy the robot says it is.
  const key: VerdictKey = r.online === false ? "offline" : r.verdict === "OFFLINE" ? "stale"
    : r.verdict === "FAULT" ? "fault" : r.verdict === "WARNING" || r.off_graph != null ? "warn" : "ok";
  const unconfirmed = stopFailed(r);
  const seenAgo = r.last_seen == null ? null : Math.max(0, now / 1000 - r.last_seen);

  let reason = r.verdict === "OK" ? "" : r.reason;
  if (key === "stale") reason = seenAgo == null ? r.reason : `No data for ${Math.round(seenAgo)} s. Showing last known values.`;
  if (key === "offline") reason = offlineReason(r, brokerDown);
  if (r.off_graph != null && !reason) reason = `Off graph — ${r.off_graph.toFixed(1)} m from the route.`;
  const shownReason = unconfirmed ? HARDWARE_STOP[r.stop!]! : reason;
  const hasReason = !!shownReason;

  const fresh = disc && state.frozenAt ? `Frozen ${clock(new Date(state.frozenAt))}`
    : key === "stale" && seenAgo != null ? `STALE · ${ageShort(seenAgo)}` : "";
  const paused = r.paused;

  // The task line.
  const c: Command | null = r.command;
  const stopping = c?.action === "OPERATOR_STOP" && !!r.stop;
  const cv = c ? commandView(stopping ? r.stop! : c.status, c.steps, c.action === "OPERATOR_STOP") : null;
  const active = r.task.state === "active" || r.task.state === "paused";
  const prog = progressOf(r);
  const progText = prog ? `${prog.done} of ${prog.total} nodes` : "";
  let t1 = "No task", t2 = "";
  let tk: RobotView["tk"] = null;
  if (stopping) {
    t1 = active ? `→ ${destOf(r, site)}` : "Operator stop";
    tk = { ...cv!, prog: "" };
  } else if (active) {
    t1 = `→ ${destOf(r, site)}`;
    if (c?.action === "GOAL" && !cv!.ended) tk = { ...cv!, prog: progText };
    else t2 = progText + (paused ? `${progText ? " · " : ""}paused` : "");
  } else if (c && cv && (c.action === "GOAL" || c.action === "CANCEL")) {
    t1 = `Last: ${verbOf(c.action, c.node, site, c.point ? "point" : undefined)}`;
    tk = { ...cv, prog: cv.ended ? agoText(now / 1000 - c.at) : "" };
  } else if (r.driver && r.driver !== env.name) {
    t1 = `Driven by ${r.driver}`;
  }
  if (tk) {
    tk = { ...tk, prog: compact(tk.prog) };
    if (disc) tk = { ...tk, tone: "text-3", spin: false, bars: tk.bars.map((b) => (b === "var(--surface-3)" ? b : "var(--text-3)")) };
  }
  t2 = compact(t2);

  // Vitals: only what the robot itself can honestly report.
  const snap = state.snapshots[r.index];
  const cpuTile = snap?.cpu_temp;
  const cpu = cpuTile && cpuTile.mapped !== false && cpuTile.source !== "host" && typeof cpuTile.value === "number"
    ? { value: cpuTile.value, source: cpuTile.source, warn: cpuTile.level !== "ok" } : null;
  const speedValue = r.velocity ? Math.abs(r.velocity.linear) : null;
  const vitals: Vital[] = [{ label: "SPEED", value: speedValue == null ? "—" : speedValue.toFixed(1), unit: "m/s" }];
  if (cpu) vitals.push({ label: "CPU", value: cpu.value.toFixed(0), unit: "°C", warn: cpu.warn });
  if (r.voltage != null) {
    const min = state.hello?.min_voltage;
    vitals.push({ label: "VOLTAGE", value: r.voltage.toFixed(1), unit: "V", warn: min != null && r.voltage < min });
  }
  const fieldTile = (snap?.fields ?? []).find((f) => typeof f.value === "number");
  if (vitals.length < 3 && fieldTile) vitals.push({ label: (fieldTile.label ?? "").toUpperCase(), value: Number(fieldTile.value).toFixed(1), unit: fieldTile.unit, warn: fieldTile.level !== "ok" });

  const battery = r.battery == null ? "—" : r.battery.toFixed(0);
  const short = unconfirmed ? SHORT_UNCONFIRMED[r.stop!]! : reason;
  return {
    r, key, word: VERDICT[key].word, glyph: VERDICT[key].glyph,
    health: key === "stale" || key === "offline" ? "unknown" : key,
    unconfirmed, reason, shownReason, hasReason, fresh, dim: key === "stale" || key === "offline", paused,
    driven: !!r.driver && r.driver !== env.name,
    stoppedNow: r.stop === "stopped",
    battery, batteryLow: r.battery != null && r.battery < 25,
    t1, tk, t2,
    side: hasReason ? short : t1 + (tk ? ` · ${tk.label}` : ""),
    sideTone: hasReason ? (unconfirmed ? "fault" : key) : "text-2",
    listVerdict: hasReason ? short : "OK",
    vitals, speed: speedValue == null ? "—" : speedValue.toFixed(2), cpu,
  };
}

/** Unconfirmed stop and FAULT first, then WARNING, then the configured order. */
export function sorted(views: RobotView[]): RobotView[] {
  const rank = (v: RobotView) => (v.unconfirmed || v.key === "fault" ? 0 : v.key === "warn" ? 1 : 2);
  return [...views].sort((a, b) => rank(a) - rank(b) || a.r.index - b.r.index);
}


/** A ROS 2 robot with no speed feedback has Operator stop and nothing else. */
export const stopOnly = (r: RobotModel) => {
  const c = r.capabilities;
  return r.protocol === "ros2" && c.can_stop && !c.can_teleop && !c.can_waypoint && !c.can_pause && !c.can_cancel;
};
