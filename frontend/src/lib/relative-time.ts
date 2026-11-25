import { formatDate } from "@/lib/format";

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function ago(value: number, one: string, many: string): string {
  return `vor ${value} ${value === 1 ? one : many}`;
}

/** German relative time: "gerade eben", "vor 5 Minuten", "vor 2 Stunden", "gestern", "vor 3 Tagen". */
export function formatRelativeTime(iso: string, now: Date = new Date()): string {
  const seconds = Math.floor((now.getTime() - new Date(iso).getTime()) / 1000);
  if (seconds < MINUTE) return "gerade eben"; // also covers small clock differences into the future
  if (seconds < HOUR) return ago(Math.floor(seconds / MINUTE), "Minute", "Minuten");
  if (seconds < DAY) return ago(Math.floor(seconds / HOUR), "Stunde", "Stunden");
  const days = Math.floor(seconds / DAY);
  if (days === 1) return "gestern";
  if (days < 7) return ago(days, "Tag", "Tagen");
  return formatDate(iso);
}
