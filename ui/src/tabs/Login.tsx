import { type FormEvent, useState } from "react";
import type { PanelContext } from "../App";

/** Login, and the first run's admin password. */
export function Login({ ctx, locked }: { ctx: PanelContext; locked?: boolean }) {
  const control = ctx.state.control;
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const setup = !!control?.needs_setup;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    ctx.send(setup ? { action: "SETUP", password } : { action: "LOGIN", username, password });
    setPassword("");
  };
  const lead = setup ? "This is the first login. Choose an admin password of at least 8 characters. It stays on this machine."
    : locked ? "Log in to see the panel."
    : control?.stop_requires_login ? "Operators and admins log in to send commands."
    : "Operators and admins log in to send commands. Operator stop works without logging in.";
  return (
    <div className="login">
      <form className="login__box" onSubmit={submit}>
        <div className="login__head">
          <span className="login__title">{setup ? "Set the admin password" : "Log in"}</span>
          <span className="login__lead">{lead}</span>
        </div>
        {!setup && (
          <label className="field">
            <span className="microlabel">USERNAME</span>
            <input className="input input--mono" type="text" autoComplete="username" autoCapitalize="none" placeholder="m.lind" autoFocus
              value={username} onChange={(e) => setUsername(e.target.value)} />
          </label>
        )}
        <label className="field">
          <span className="microlabel">PASSWORD</span>
          <input className="input" type="password" autoComplete={setup ? "new-password" : "current-password"} autoFocus={setup}
            value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {ctx.state.authError && <p className="login__error" role="alert" data-testid="login-error">▲ {ctx.state.authError}</p>}
        <button type="submit" className="btn-main" disabled={!password}>{setup ? "Set password" : "Log in"}</button>
        {!setup && (
          <div className="login__foot">
            <span>Accounts are stored on this machine.</span>
            <span>Forgot your password? Ask your Styri admin to reset it.</span>
          </div>
        )}
      </form>
    </div>
  );
}
