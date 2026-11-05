import { type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import { logout, type PanelContext } from "../App";
import type { StopStatus } from "../bridge";
import { clock, panelHost } from "../format";
import { HARDWARE_STOP, ROLE_LABEL } from "../view";

const HOLD_MS = 1000;
const NOTE_KEY = "styri.controlNote";

export function Logo() {
  return (
    <svg viewBox="0 0 32 32" width="28" height="28" className="logo" aria-label="Styri">
      <rect width="32" height="32" rx="6" fill="var(--text-1)" />
      <path d="M22 9H11V16H21V23H10" fill="none" stroke="var(--bg)" strokeWidth="4" strokeLinecap="square" />
    </svg>
  );
}

export const Spinner = () => <span className="spinner" aria-hidden="true" />;

/** The progress of a Stop all: the bridge's, so every panel shows the same. */
function stopAllProgress(ctx: PanelContext) {
  const run = ctx.state.stopAll;
  if (!run) return null;
  const list = Object.entries(run.robots) as [string, StopStatus][];
  const done = list.filter(([, s]) => s === "stopped").length;
  const unconfirmed = list.filter(([, s]) => s === "no_reply" || s === "not_confirmed").length;
  const settled = list.every(([, s]) => s !== "sent");
  return { id: run.id, list, done, unconfirmed, settled };
}

/** Stop all, whenever control is on. Press and hold, so a stray tap can't halt the fleet. */
function StopAll({ ctx }: { ctx: PanelContext }) {
  const [p, setP] = useState(0);
  const start = useRef<number | null>(null);
  const raf = useRef(0);
  const { send, disc, phone } = ctx;
  const up = useCallback(() => {
    start.current = null;
    cancelAnimationFrame(raf.current);
    setP(0);
  }, []);
  const down = useCallback(() => {
    if (disc || start.current !== null) return;
    start.current = performance.now();
    const tick = () => {
      if (start.current === null) return;
      const done = Math.min(1, (performance.now() - start.current) / HOLD_MS);
      if (done >= 1) {
        up();
        send({ action: "OPERATOR_STOP_ALL" });
        return;
      }
      setP(done);
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
  }, [disc, send, up]);
  useEffect(() => up, [up]);
  const run = stopAllProgress(ctx);
  const label = !run ? "Stop all" : !run.settled ? `Stopping ${run.done}/${run.list.length}`
    : run.unconfirmed ? `${run.unconfirmed} NOT confirmed` : run.done === run.list.length ? "All stopped" : "Stop all";
  const hint = p > 0 ? "Keep holding" : run ? "" : phone ? "" : "Hold 1 s";
  const key = (e: KeyboardEvent) => (e.key === " " || e.key === "Enter") && (e.preventDefault(), true);
  return (
    <button type="button" className={`stopall ${disc ? "is-off" : ""}`} data-testid="stop-all" aria-disabled={disc}
      aria-label="Stop all — press and hold for 1 second"
      onPointerDown={down} onPointerUp={up} onPointerLeave={up} onPointerCancel={up}
      onKeyDown={(e) => { if (key(e) && !e.repeat) down(); }} onKeyUp={(e) => { if (key(e)) up(); }} onBlur={up}>
      <span className="stopall__ring" style={{ "--deg": `${run ? 360 : Math.round(p * 360)}deg` } as React.CSSProperties}>
        <span className="stopall__hole"><span className="stopall__sq" /></span>
      </span>
      <span className="stopall__text">
        <span className="stopall__word">{label}</span>
        {hint && <span className="stopall__hint">{hint}</span>}
      </span>
    </button>
  );
}

function roleNote(role?: string) {
  return role === "viewer" ? "Can watch. Operator stop works for anyone."
    : role === "operator" ? "Can send, pause and drive robots." : role === "admin" ? "Can also manage users and settings." : "";
}

function Menu({ ctx }: { ctx: PanelContext }) {
  const { access, phone, go } = ctx;
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const out = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", out);
    return () => document.removeEventListener("pointerdown", out);
  }, [open]);
  const pick = (fn: () => void) => () => { setOpen(false); fn(); };
  const name = access.name ?? "";
  const label = !access.loggedIn ? "Menu" : phone ? name.replace(".", "").slice(0, 2).toUpperCase() : name;
  return (
    <div className="menu" ref={box}>
      <button type="button" className="btn-outline btn-outline--header btn-user" data-testid="user-menu" aria-label="User menu" aria-expanded={open}
        onClick={() => setOpen(!open)}><span className={access.loggedIn ? "mono" : ""}>{label}</span><span className="btn-user__caret">▾</span></button>
      {open && (
        <div className="menu__box" role="menu">
          {access.loggedIn && (
            <span className="menu__who">
              <span className="menu__name"><span className="mono">{name}</span> · {ROLE_LABEL[access.role!]}</span>
              <span className="menu__note">{roleNote(access.role)}</span>
            </span>
          )}
          {access.admin && <button type="button" role="menuitem" onClick={pick(() => go("users"))}>Users and settings</button>}
          <button type="button" role="menuitem" onClick={pick(() => go("configuration"))}>Configuration</button>
          <button type="button" role="menuitem" onClick={pick(ctx.toggleTheme)}>{ctx.theme === "dark" ? "Light theme" : "Dark theme"}</button>
          <button type="button" role="menuitem" onClick={pick(() => { ctx.setWall(true); go("fleet"); })}>Wall display</button>
          {access.loggedIn && <button type="button" role="menuitem" data-testid="log-out" onClick={pick(() => logout(ctx.send))}>Log out</button>}
        </div>
      )}
    </div>
  );
}

function summary(ctx: PanelContext) {
  const { robots, phone } = ctx;
  const n = ctx.noRobots ? 0 : robots.length;
  const count = (k: string[]) => (ctx.noRobots ? [] : robots).filter((v) => k.includes(v.key)).length;
  const f = count(["fault"]), w = count(["warn"]), s = count(["stale", "offline"]);
  const out = [{ t: `${n} robot${n === 1 ? "" : "s"}`, ts: `${n} robot${n === 1 ? "" : "s"}`, g: "", tone: "text-1" }];
  if (f) out.push({ t: `${f} fault`, ts: `${f} fault`, g: "◆", tone: "fault" });
  if (w) out.push({ t: `${w} warning${w > 1 ? "s" : ""}`, ts: `${w} warn`, g: "▲", tone: "warn" });
  if (s) out.push({ t: `${s} stale`, ts: `${s} stale`, g: "◌", tone: "text-3" });
  if (!f && !w && !s && n && !phone) out.push({ t: "all OK", ts: "all OK", g: "●", tone: "ok" });
  return out;
}

export function Header({ ctx, bare, hideStrip }: { ctx: PanelContext; bare?: boolean; hideStrip?: boolean }) {
  const { phone, disc, access, view, wall, state, robots } = ctx;
  const host = panelHost();
  const site = state.site ?? "";
  const connected = !disc;
  const sum = summary(ctx);
  const needsLogin = access.auth && !access.loggedIn && view !== "login" && !wall;
  const conn = <span className={`conn__dot ${connected ? "" : "is-warn"}`} />;
  return (
    <>
      <header className="header">
        <div className="brand">
          <div className="brand__mark"><Logo /><span className="wordmark">styri</span></div>
          {!phone && (
            <div className="brand__site">
              {site && <span className="brand__name">{site}</span>}
              <span className={`conn ${connected ? "" : "conn--warn"}`} data-testid="conn">{conn}{connected ? host : `Reconnecting · ${host}`}</span>
            </div>
          )}
        </div>
        <div className="header__mid">
          {!phone && !bare && (
            <div className="summary" data-testid="summary">
              {sum.map((x, i) => (
                <span key={x.t} className={`summary__item tone-${x.tone}`}>
                  {i > 0 && <span className="summary__sep">·</span>}
                  {x.g && <span className="mono summary__glyph">{x.g}</span>}{x.t}
                </span>
              ))}
            </div>
          )}
        </div>
        {!bare && !wall && (
          <div className="header__right">
            {access.stop && robots.length > 0 && !ctx.noRobots && view !== "login" && <StopAll ctx={ctx} />}
            {access.loggedIn || !access.auth ? <Menu ctx={ctx} /> : needsLogin &&
              <button type="button" className="btn-outline btn-outline--header" data-testid="log-in" onClick={() => ctx.go("login")}>Log in</button>}
          </div>
        )}
      </header>
      {phone && !bare && !hideStrip && (
        <div className="strip">
          <span className={`conn ${connected ? "" : "conn--warn"}`} data-testid="conn">{conn}{connected ? site || host : "Reconnecting"}</span>
          <span className="strip__sum">
            {sum.map((x) => <span key={x.t} className={`tone-${x.tone}`}>{x.g && <span className="mono">{x.g} </span>}{x.ts}</span>)}
          </span>
        </div>
      )}
    </>
  );
}

function Banner({ tone, glyph, title, body, action, onAction, testid }: {
  tone: "fault" | "warn" | "info" | "ok"; glyph: string; title: string; body: string; action?: string; onAction?: () => void; testid?: string;
}) {
  return (
    <div className={`banner banner--${tone}`} role="status" data-testid={testid}>
      <span className="banner__title"><span className="mono">{glyph}</span>{title}</span>
      <span className="banner__body">{body}</span>
      {action && <button type="button" className="btn-small" onClick={onAction}>{action}</button>}
    </div>
  );
}

export function Banners({ ctx }: { ctx: PanelContext }) {
  const { state, disc, now, access } = ctx;
  const [noted, setNoted] = useState(() => {
    try { return !!localStorage.getItem(NOTE_KEY); } catch { return false; }
  });
  const seenOnce = !!state.hello;
  const ends = state.sessionEndsAt;
  const left = ends ? Math.max(0, ends - now) : 0;
  return (
    <>
      {disc && seenOnce && (
        <Banner testid="reconnecting" tone="fault" glyph="◆" title={`Reconnecting… attempt ${Math.max(1, state.attempts)}`}
          body={`Panel disconnected: stop robots with their own controls. Values below are frozen at ${clock(new Date(state.frozenAt ?? now))}.`} />
      )}
      {state.broker && !state.broker.connected && !disc && (
        <Banner testid="broker" tone="warn" glyph="▲" title="Broker unreachable"
          body={`${state.broker.url} is not answering. VDA 5050 robots show as offline. ROS 2 robots are unaffected.`} />
      )}
      {ends && access.loggedIn && left > 0 && (
        <Banner testid="session" tone="info" glyph="i" title={`Session ends in ${Math.max(1, Math.ceil(left / 60000))} min`}
          body={`You will be logged out at ${clock(new Date(ends)).slice(0, 5)}. If you are driving, the session waits until you let go.`}
          action="Stay logged in" onAction={() => ctx.send({ action: "SESSION_KEEP" })} />
      )}
      {access.control && !noted && !disc && (
        <Banner testid="control-note" tone="info" glyph="i" title="Robot control is on"
          body="Operators and admins can send, pause and drive robots. Viewers can watch. Operator stop works for anyone looking at the panel — it is a software stop, not a safety function."
          action="Got it" onAction={() => {
            setNoted(true);
            try { localStorage.setItem(NOTE_KEY, "1"); } catch { /* private window */ }
          }} />
      )}
    </>
  );
}

const CHIP: Record<StopStatus, { g: string; l: string; tone: string }> = {
  sent: { g: "", l: "Stop sent…", tone: "text-1" },
  stopped: { g: "■ ", l: "Stopped", tone: "ok" },
  no_reply: { g: "◆ ", l: "NOT confirmed", tone: "fault" },
  not_confirmed: { g: "◆ ", l: "NOT confirmed", tone: "fault" },
  cant_confirm: { g: "", l: "Sent · can't confirm", tone: "text-2" },
};

export function StopAllBanner({ ctx }: { ctx: PanelContext }) {
  const [dismissed, setDismissed] = useState<number | null>(null);
  const run = stopAllProgress(ctx);
  if (!run || run.id === dismissed) return null;
  const n = run.list.length;
  const title = !run.settled ? `${run.done} of ${n} confirmed. Robots stay paused after they stop.`
    : `${run.done} of ${n} stopped. Not every robot confirmed.`;
  const failed = run.list.find(([, s]) => s === "no_reply" || s === "not_confirmed");
  if (run.settled && run.done === n) {
    // Done: one slim line. A ROS 2 robot stops without pausing, so say paused only if they all are.
    const paused = run.list.every(([name]) => ctx.state.fleet.find((r) => r.name === name)?.paused);
    return (
      <div className="sabanner sabanner--slim" role="status" data-testid="stop-all-banner">
        <span className="sabanner__body"><span className="sabanner__sq" />All stopped{paused ? " · robots paused" : ""}</span>
        <button type="button" className="btn-small" onClick={() => setDismissed(run.id)}>Dismiss</button>
      </div>
    );
  }
  return (
    <div className="sabanner" role="status" data-testid="stop-all-banner">
      <div className="sabanner__head">
        <span className="sabanner__title"><span className="sabanner__sq" />Stop all</span>
        <span className="sabanner__body">{title}</span>
        {run.settled && <button type="button" className="btn-small" onClick={() => setDismissed(run.id)}>Dismiss</button>}
      </div>
      <div className="sabanner__chips">
        {run.list.map(([name, s]) => (
          <span key={name} className={`sachip ${CHIP[s].tone === "fault" ? "is-fault" : ""}`} data-robot={name} data-stop={s}>
            <span className="mono strong">{name}</span>
            <span className={`sachip__state tone-${CHIP[s].tone}`}>{CHIP[s].g}{CHIP[s].l}{s === "sent" && <Spinner />}</span>
          </span>
        ))}
      </div>
      {failed && <span className="sabanner__alert">◆ {HARDWARE_STOP[failed[1]]}</span>}
    </div>
  );
}
