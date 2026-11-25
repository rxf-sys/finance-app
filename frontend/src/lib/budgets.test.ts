import { describe, expect, it } from "vitest";
import type { BudgetStatus } from "@/api/client";
import { barWidth, budgetState, mostCritical, rolloverCents } from "./budgets";

const make = (name: string, pct: number): BudgetStatus =>
  ({ category_name: name, pct, limit_cents: 10000, amount_cents: 10000, rollover: false }) as BudgetStatus;

describe("budget helpers", () => {
  it("picks the budgets closest to their limit", () => {
    const list = [make("A", 10), make("B", 120), make("C", 85), make("D", 50)];
    expect(mostCritical(list, 3).map((b) => b.category_name)).toEqual(["B", "C", "D"]);
  });
  it("clamps the bar width", () => {
    expect(barWidth(250)).toBe(100);
    expect(barWidth(-5)).toBe(0);
    expect(barWidth(42)).toBe(42);
  });
  it("falls back to ok for unknown states", () => {
    expect(budgetState("exceeded")).toBe("exceeded");
    expect(budgetState("weird")).toBe("ok");
  });
  it("computes the rollover amount only when enabled", () => {
    expect(rolloverCents({ limit_cents: 15000, amount_cents: 10000, rollover: true })).toBe(5000);
    expect(rolloverCents({ limit_cents: 15000, amount_cents: 10000, rollover: false })).toBe(0);
  });
});
