import { type FormEvent, useEffect, useState } from "react";
import type { PanelContext } from "../App";

export const SOFTWARE_STOP = "Software stop, not a safety function";

/** Stop all, in the header whenever control is enabled. */
export function StopAll({ ctx, onLogin }: { ctx: PanelContext; onLogin: () => void }) {
  const control = ctx.state.control;
  if (!control?.enabled) return null;
  return (
    <button type="button" className="stopall" data-testid="stop-all" title={SOFTWARE_STOP}
      onClick={() => (control.logged_in ? ctx.send({ action: "OPERATOR_STOP_ALL" }) : onLogin())}>
      Stop all
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
