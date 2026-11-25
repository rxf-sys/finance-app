import type { Goal } from "@/api/client";
import { CATEGORY_ICONS } from "@/lib/categories";
import { formatDate } from "@/lib/format";
import { formatMoney } from "@/lib/money";

/** Icons offered for a goal; a subset of the category icons so stored names stay valid. */
export const GOAL_ICONS = [
  "piggy-bank",
  "plane",
  "house",
  "car",
  "gift",
  "graduation-cap",
  "baby",
  "shield-check",
  "smartphone",
  "wrench",
  "wallet",
  "banknote",
].filter((name) => Object.hasOwn(CATEGORY_ICONS, name));

export const DEFAULT_GOAL_ICON = "piggy-bank";
export const DEFAULT_GOAL_COLOR = "chart-3";

/** "1.200,00 € von 5.000,00 €" */
export function progressText(goal: Pick<Goal, "progress_cents" | "target_cents">): string {
  return `${formatMoney(goal.progress_cents)} von ${formatMoney(goal.target_cents)}`;
}

/** Progress bar width in percent, clamped to 0..100. */
export function goalBarWidth(percent: number): number {
  return Math.min(100, Math.max(0, percent));
}

/** Target date line, for example "bis 31.12.2026 · noch 200,00 € pro Monat". */
export function targetText(
  goal: Pick<Goal, "achieved" | "target_date" | "monthly_needed_cents" | "remaining_cents">,
): string | null {
  if (goal.achieved) return "Ziel erreicht";
  if (!goal.target_date) return null;
  const date = `bis ${formatDate(goal.target_date)}`;
  if (goal.monthly_needed_cents === null) return date;
  return `${date} · noch ${formatMoney(goal.monthly_needed_cents)} pro Monat`;
}

/** Sort: open goals first (oldest first as delivered), achieved ones after them. */
export function sortGoals<T extends Pick<Goal, "achieved" | "archived">>(goals: readonly T[]): T[] {
  const rank = (g: T) => (g.archived ? 2 : g.achieved ? 1 : 0);
  return [...goals].sort((a, b) => rank(a) - rank(b));
}

/** A goal on a private account has to be private itself. */
export function mustBePrivate(accountVisibility: "shared" | "private" | undefined): boolean {
  return accountVisibility === "private";
}
