import type { PanelContext } from "./App";

/** The header's robot name; with several, a picker for which robot the tabs show. */
export function RobotSwitcher({ ctx }: { ctx: PanelContext }) {
  const robots = ctx.state.hello?.robots ?? [];
  const current = robots[ctx.robot]?.name ?? ctx.state.hello?.robot ?? "—";
  if (robots.length < 2) return <span className="mono header__robot" title={`Robot: ${current}`}>{current}</span>;
  const level = (i: number) => ctx.state.snapshots[i]?.health.level ?? "unknown";
  return (
    <label className="switcher" title="Which robot the Overview, Topics and Configuration show">
      <span className={`switcher__dot switcher__dot--${level(ctx.robot)}`} aria-hidden="true" />
      <select className="mono switcher__select" value={ctx.robot} aria-label="Robot"
        onChange={(e) => ctx.setRobot(Number(e.target.value))}>
        {robots.map((r) => (
          <option key={r.index} value={r.index}>
            {r.name}{level(r.index) === "ok" ? "" : ` · ${level(r.index) === "unknown" ? "no data" : level(r.index)}`}
          </option>
        ))}
      </select>
    </label>
  );
}
