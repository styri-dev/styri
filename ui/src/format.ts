export const clock = (d: Date) => d.toTimeString().slice(0, 8);

export function ageText(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? `${s} s ago` : s < 3600 ? `${Math.floor(s / 60)} min ago` : `${Math.floor(s / 3600)} h ago`;
}

export function num(value: unknown, digits: number): string {
  return typeof value !== "number" || !Number.isFinite(value) ? "—" : value.toFixed(digits);
}

/** A mapped value as text: numbers to sensible digits, true/false, or the text itself. */
export function shown(value: unknown, kind: string): string {
  if (value == null) return "—";
  if (kind === "bool") return value ? "true" : "false";
  if (typeof value === "number") return num(value, Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 10 ? 1 : 2);
  return String(value);
}

/** Time for a log row: HH:MM:SS today, with the date for older rows. */
export function eventTime(ts: number, now: number): string {
  const d = new Date(ts * 1000);
  const sameDay = new Date(now).toDateString() === d.toDateString();
  return sameDay ? clock(d) : `${d.toISOString().slice(5, 10)} ${clock(d).slice(0, 5)}`;
}

export function csv(rows: (string | number)[][]): string {
  return rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
}

export function download(name: string, text: string, type = "text/csv") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
