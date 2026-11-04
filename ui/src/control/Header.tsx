import { type FormEvent, type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import type { PanelContext } from "../App";

export const SOFTWARE_STOP = "Software stop, not a safety function";

const HOLD_MS = 1000;

/** Stop all, in the header whenever control is enabled. Press and hold, so a stray tap can't halt the fleet. */
export function StopAll({ ctx, onLogin }: { ctx: PanelContext; onLogin: () => void }) {
  const control = ctx.state.control;
  const [holding, setHolding] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const { send } = ctx;
  const stop = useCallback(() => { clearTimeout(timer.current); setHolding(false); }, []);
  const hold = useCallback(() => {
    clearTimeout(timer.current);
    setHolding(true);
    timer.current = setTimeout(() => { setHolding(false); send({ action: "OPERATOR_STOP_ALL" }); }, HOLD_MS);
  }, [send]);
  useEffect(() => stop, [stop]);
  if (!control?.enabled) return null;
  if (control.stop_requires_login && !control.logged_in) {
    return <button type="button" className="stopall" data-testid="stop-all" title={SOFTWARE_STOP} onClick={onLogin}>Stop all</button>;
  }
  const key = (e: KeyboardEvent) => (e.key === " " || e.key === "Enter") && (e.preventDefault(), true);
  return (
    <button type="button" className={`stopall ${holding ? "is-holding" : ""}`} data-testid="stop-all"
      title={`Press and hold. ${SOFTWARE_STOP}`} aria-label="Stop all: press and hold for one second"
      onPointerDown={hold} onPointerUp={stop} onPointerLeave={stop} onPointerCancel={stop}
      onKeyDown={(e) => { if (key(e) && !e.repeat) hold(); }} onKeyUp={(e) => { if (key(e)) stop(); }} onBlur={stop}>
      <span className="stopall__fill" aria-hidden="true" />
      <span className="stopall__word">{holding ? "Hold…" : "Stop all"}</span>
    </button>
  );
}

export function Login({ ctx, onClose }: { ctx: PanelContext; onClose: () => void }) {
  const control = ctx.state.control;
  const [password, setPassword] = useState("");
  const setup = !!control?.needs_setup;
  useEffect(() => {
    if (control?.logged_in) onClose();
  }, [control?.logged_in, onClose]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    ctx.send({ action: setup ? "SETUP" : "LOGIN", password });
    setPassword("");
  };
  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label={setup ? "Set the admin password" : "Log in"}>
      <form className="modal__box" onSubmit={submit}>
        <h2 className="modal__title">{setup ? "Set the admin password" : "Log in to control robots"}</h2>
        <p className="small text-2">
          {setup ? "This is the first login. Choose a password of at least 8 characters. It stays on this machine."
            : "Viewing needs no login. Commands do, and each one is logged."}
        </p>
        <input className="field-input" type="password" autoFocus autoComplete="current-password" aria-label="Password"
          value={password} onChange={(e) => setPassword(e.target.value)} />
        {ctx.state.authError && <p className="warn-fg small" role="alert">{ctx.state.authError}</p>}
        <div className="modal__actions">
          <button type="button" className="btn btn--plain" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn--solid" disabled={!password}>{setup ? "Set password" : "Log in"}</button>
        </div>
      </form>
    </div>
  );
}
