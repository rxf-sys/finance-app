import type { BudgetStatus } from "@/api/client";

export type BudgetState = "ok" | "warning" | "exceeded";

export function budgetState(state: string): BudgetState {
  return state === "exceeded" || state === "warning" ? state : "ok";
}

/** Red only for an exceeded budget; warning from 80 %. */
export const BUDGET_BAR_COLOR: Record<BudgetState, string> = {
  ok: "var(--primary)",
  warning: "var(--warning)",
  exceeded: "var(--negative)",
};

export const BUDGET_STATE_LABEL: Record<BudgetState, string> = {
  ok: "Im Rahmen",
  warning: "Fast aufgebraucht",
  exceeded: "Überschritten",
};

/** The budgets closest to or over their limit first (by usage in percent). */
export function mostCritical(budgets: BudgetStatus[], count: number): BudgetStatus[] {
  return [...budgets]
    .sort((a, b) => b.pct - a.pct || a.category_name.localeCompare(b.category_name, "de"))
    .slice(0, count);
}

/** Width of the progress bar in percent, clamped to 0..100. */
export function barWidth(pct: number): number {
  return Math.min(100, Math.max(0, pct));
}

/** Extra limit carried over from last month (0 without rollover). */
export function rolloverCents(
  budget: Pick<BudgetStatus, "limit_cents" | "amount_cents" | "rollover">,
): number {
  return budget.rollover ? Math.max(0, budget.limit_cents - budget.amount_cents) : 0;
}
