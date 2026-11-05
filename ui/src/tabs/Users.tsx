import { type FormEvent, useEffect, useState } from "react";
import type { PanelContext } from "../App";
import type { Account, Role } from "../bridge";
import { agoText, ROLE_LABEL } from "../view";

const ROLES: Role[] = ["viewer", "operator", "admin"];
const WHAT_THEY_GET: Record<Role, string> = {
  viewer: "can watch, but can no longer send, pause or drive robots.",
  operator: "can send, pause and drive robots, but can no longer manage users or settings.",
  admin: "can manage users and settings, and turn robot control on or off.",
};

type Ask = { name: string; kind: "role"; role: Role } | { name: string; kind: "remove" } | { name: string; kind: "password" };

function Confirm({ title, note, yes, onYes, onNo }: { title: string; note: string; yes: string; onYes: () => void; onNo: () => void }) {
  return (
    <div className="ask" data-testid="user-confirm">
      <div className="ask__text"><span className="ask__title">{title}</span><span className="small text-2">{note}</span></div>
      <div className="ask__btns">
        <button type="button" className="btn-outline" onClick={onNo}>Cancel</button>
        <button type="button" className="btn-solid" data-testid="confirm-yes" onClick={onYes}>{yes}</button>
      </div>
    </div>
  );
}

function PasswordForm({ name, onSave, onCancel }: { name: string; onSave: (password: string) => void; onCancel: () => void }) {
  const [password, setPassword] = useState("");
  const submit = (e: FormEvent) => { e.preventDefault(); onSave(password); };
  return (
    <form className="ask" onSubmit={submit} data-testid="password-form">
      <label className="field ask__text">
        <span className="ask__title">New password for {name}</span>
        <input className="input input--small" type="password" autoComplete="new-password" aria-label="New password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} />
        <span className="small text-2">At least 8 characters. {name} is logged out everywhere.</span>
      </label>
      <div className="ask__btns">
        <button type="button" className="btn-outline" onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn-solid" disabled={!password}>Reset password</button>
      </div>
    </form>
  );
}

function AddUser({ onAdd, onCancel }: { onAdd: (name: string, password: string, role: Role) => void; onCancel: () => void }) {
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("operator");
  const submit = (e: FormEvent) => { e.preventDefault(); onAdd(name, password, role); };
  return (
    <form className="ask ask--add" onSubmit={submit} data-testid="add-user-form">
      <label className="field"><span className="microlabel">USERNAME</span>
        <input className="input input--small input--mono" type="text" autoComplete="off" autoCapitalize="none" autoFocus value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label className="field"><span className="microlabel">PASSWORD</span>
        <input className="input input--small" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
      <label className="field"><span className="microlabel">ROLE</span>
        <select className="input input--small role" aria-label="New user's role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
          {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
        </select></label>
      <div className="ask__btns">
        <button type="button" className="btn-outline" onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn-solid" disabled={!name || !password}>Add user</button>
      </div>
    </form>
  );
}

function Toggle({ on, onClick, testid }: { on: boolean; onClick: () => void; testid: string }) {
  return (
    <button type="button" className={`toggle ${on ? "is-on" : ""}`} aria-pressed={on} data-testid={testid} onClick={onClick}>
      <span className="toggle__word">{on ? "ON" : "OFF"}</span>
      <span className="toggle__track"><span className="toggle__knob" /></span>
    </button>
  );
}

function lastActive(u: Account, nowS: number) {
  return u.active ? "Now" : u.last_login ? agoText(nowS - u.last_login) : "Never";
}

/** Admins only: the App sends everyone else to the Fleet. */
export function Users({ ctx }: { ctx: PanelContext }) {
  const { state, send, phone, now } = ctx;
  const [ask, setAsk] = useState<Ask | null>(null);
  const [adding, setAdding] = useState(false);
  const [switchAsk, setSwitchAsk] = useState<"control" | "anonymous" | null>(null);
  useEffect(() => { send({ action: "USERS" }); }, [send]);
  const control = state.control!;
  const anonymous = control.anonymous_view !== false;
  const error = state.notice?.action?.match(/^(USER|SWITCHES)/) ? state.notice.text : "";
  // The bridge answers with the new list: only then does a form close.
  useEffect(() => { setAdding(false); setAsk(null); }, [state.users]);
  const apply = (message: Record<string, unknown>) => send(message);

  return (
    <div className="users" data-testid="users">
      <div className="users__head">
        <span className="page-title">Users</span>
        <button type="button" className="btn-solid btn-solid--tall" data-testid="add-user" onClick={() => { setAdding(true); setAsk(null); }}>Add user</button>
      </div>
      {error && <p className="users__error" role="alert" data-testid="users-error">▲ {error}</p>}
      {adding && <AddUser onCancel={() => setAdding(false)} onAdd={(name, password, role) => apply({ action: "USER_ADD", name, password, role })} />}
      <div className="utable">
        {!phone && <div className="urow__grid urow__grid--head"><span>NAME</span><span>ROLE</span><span>LAST ACTIVE</span><span /></div>}
        {state.users.map((u) => {
          const mine = ask?.name === u.name ? ask : null;
          const pending = mine?.kind === "role" ? mine.role : null;
          return (
            <div key={u.name} className={`urow ${mine ? "is-asking" : ""}`} data-user={u.name}>
              <div className={phone ? "urow__grid urow__grid--phone" : "urow__grid"}>
                <span className="urow__name"><span className="mono">{u.name}</span>{phone && <span className="small text-3">{lastActive(u, now / 1000)}</span>}</span>
                <select className="role" aria-label={`Role for ${u.name}`} value={pending ?? u.role}
                  onChange={(e) => { const role = e.target.value as Role; setAsk(role === u.role ? null : { name: u.name, kind: "role", role }); }}>
                  {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                </select>
                {!phone && <span className="small text-2">{lastActive(u, now / 1000)}</span>}
                <div className="urow__acts">
                  <button type="button" className="btn-row" onClick={() => setAsk({ name: u.name, kind: "password" })}>Reset password</button>
                  <button type="button" className="btn-row btn-row--remove" onClick={() => setAsk({ name: u.name, kind: "remove" })}>Remove</button>
                </div>
              </div>
              {mine?.kind === "role" && (
                <Confirm title={`Make ${u.name} a${mine.role === "viewer" ? "" : "n"} ${ROLE_LABEL[mine.role]}?`} note={`${u.name} ${WHAT_THEY_GET[mine.role]}`}
                  yes={`Make ${ROLE_LABEL[mine.role]}`} onNo={() => setAsk(null)} onYes={() => apply({ action: "USER_ROLE", name: u.name, role: mine.role })} />
              )}
              {mine?.kind === "remove" && (
                <Confirm title={`Remove ${u.name}?`} note={`${u.name} can no longer log in. Their past commands stay in Activity.`}
                  yes={`Remove ${u.name}`} onNo={() => setAsk(null)} onYes={() => apply({ action: "USER_REMOVE", name: u.name })} />
              )}
              {mine?.kind === "password" && (
                <PasswordForm name={u.name} onCancel={() => setAsk(null)} onSave={(password) => apply({ action: "USER_PASSWORD", name: u.name, password })} />
              )}
            </div>
          );
        })}
      </div>
      <div className="settings">
        <span className="microlabel">CONTROL SETTINGS</span>
        <div className="setting" data-setting="control">
          <div className="setting__row">
            <div className="setting__text">
              <span className="setting__title">Robot control</span>
              <span className="small text-2">When on, operators and admins can send, pause and drive robots, and anyone can use Operator stop. When off, Styri is view-only and no control appears anywhere.</span>
            </div>
            <Toggle testid="switch-control" on={control.enabled} onClick={() => (control.enabled ? setSwitchAsk("control") : apply({ action: "SWITCHES", control: true }))} />
          </div>
          {switchAsk === "control" && control.enabled && (
            <div className="warnask" data-testid="switch-confirm">
              <div className="warnask__text">
                <span className="warnask__title">▲ Turn robot control off?</span>
                <span className="small">Operators and admins lose Send to, Pause, Resume, Cancel task and Drive on every robot. Operator stop and Stop all disappear from every screen. Robots keep running the tasks they have.</span>
              </div>
              <div className="ask__btns">
                <button type="button" className="btn-small" onClick={() => setSwitchAsk(null)}>Keep control on</button>
                <button type="button" className="btn-warn" data-testid="switch-off" onClick={() => { setSwitchAsk(null); apply({ action: "SWITCHES", control: false }); }}>Turn control off</button>
              </div>
            </div>
          )}
        </div>
        <div className="setting" data-setting="anonymous">
          <div className="setting__row">
            <div className="setting__text">
              <span className="setting__title">Anonymous viewing</span>
              <span className="small text-2">When on, anyone on this network can see the panel without logging in — useful for wall displays. Anyone looking at the panel can use Operator stop.</span>
            </div>
            <Toggle testid="switch-anonymous" on={anonymous} onClick={() => (anonymous ? setSwitchAsk("anonymous") : apply({ action: "SWITCHES", anonymous_view: true }))} />
          </div>
          {switchAsk === "anonymous" && anonymous && (
            <div className="warnask" data-testid="switch-confirm">
              <div className="warnask__text">
                <span className="warnask__title">▲ Turn anonymous viewing off?</span>
                <span className="small">Anyone not logged in sees only the login, on every screen, wall displays included. They can't use Operator stop or Stop all from this panel until they log in.</span>
              </div>
              <div className="ask__btns">
                <button type="button" className="btn-small" onClick={() => setSwitchAsk(null)}>Keep viewing on</button>
                <button type="button" className="btn-warn" data-testid="switch-off" onClick={() => { setSwitchAsk(null); apply({ action: "SWITCHES", anonymous_view: false }); }}>Turn viewing off</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
