/** Month and date helpers. All dates are plain ISO strings (YYYY-MM-DD) or month keys (YYYY-MM). */

const MONTHS = [
  "Januar",
  "Februar",
  "März",
  "April",
  "Mai",
  "Juni",
  "Juli",
  "August",
  "September",
  "Oktober",
  "November",
  "Dezember",
];

const SHORT_MONTHS = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** Local calendar date as YYYY-MM-DD. */
export function toIsoDate(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function currentMonthKey(now = new Date()): string {
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}`;
}

export function isMonthKey(value: unknown): value is string {
  return typeof value === "string" && /^\d{4}-(0[1-9]|1[0-2])$/.test(value);
}

export function isIsoDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

export function addMonths(key: string, delta: number): string {
  const [year, month] = key.split("-").map(Number);
  const index = year * 12 + (month - 1) + delta;
  return `${Math.floor(index / 12)}-${pad((index % 12) + 1)}`;
}

/** "2026-03" -> "März 2026" */
export function monthLabel(key: string): string {
  const [year, month] = key.split("-").map(Number);
  return `${MONTHS[month - 1]} ${year}`;
}

/** "2026-03" -> "Mär" (or "Mär 26" when the year is requested) */
export function shortMonthLabel(key: string, withYear = false): string {
  const [year, month] = key.split("-").map(Number);
  const name = SHORT_MONTHS[month - 1];
  return withYear ? `${name} ${String(year).slice(2)}` : name;
}

/** First and last day of a month key as ISO dates. */
export function monthRange(key: string): { from: string; to: string } {
  const [year, month] = key.split("-").map(Number);
  const last = new Date(year, month, 0).getDate();
  return { from: `${key}-01`, to: `${key}-${pad(last)}` };
}
