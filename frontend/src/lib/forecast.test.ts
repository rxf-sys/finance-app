import { describe, expect, it } from "vitest";
import type { Forecast } from "@/api/client";
import { assumptionLines, endBalance, lowestPoint, parseForecastMonths, summarize } from "./forecast";

const daily = [
  { date: "2026-12-01", balance_cents: 100_00 },
  { date: "2026-12-02", balance_cents: -50_00 },
  { date: "2026-12-03", balance_cents: 20_00 },
  { date: "2026-12-04", balance_cents: -50_00 },
];

function forecast(overrides: Partial<Forecast> = {}): Forecast {
  return {
    start_balance_cents: 200_00,
    as_of: "2026-11-30",
    horizon_end: "2026-12-30",
    daily,
    months: [],
    lowest: daily[1],
    events: [],
    assumptions: {
      income_baseline_cents: 2500_00,
      income_day: 28,
      variable_baseline_cents: 900_00,
      months_used: 3,
    },
    insufficient_history: false,
    ...overrides,
  };
}

describe("lowestPoint", () => {
  it("finds the minimum and prefers the earliest day on a tie", () => {
    expect(lowestPoint(daily)).toEqual(daily[1]);
  });
  it("is null without days", () => {
    expect(lowestPoint([])).toBeNull();
  });
});

describe("summarize", () => {
  it("reports end balance, change and a negative low point", () => {
    const summary = summarize(forecast());
    expect(summary.endBalanceCents).toBe(-50_00);
    expect(summary.changeCents).toBe(-250_00);
    expect(summary.goesNegative).toBe(true);
    expect(summary.lowest.date).toBe("2026-12-02");
  });
  it("is not negative when the low point is positive", () => {
    const days = [{ date: "2026-12-01", balance_cents: 10_00 }];
    expect(summarize(forecast({ daily: days, lowest: days[0] })).goesNegative).toBe(false);
  });
});

describe("endBalance", () => {
  it("falls back to the start balance", () => {
    expect(endBalance({ daily: [], start_balance_cents: 5 })).toBe(5);
  });
});

describe("parseForecastMonths", () => {
  it("accepts 1 to 3 and defaults to 3", () => {
    expect(parseForecastMonths("2")).toBe(2);
    expect(parseForecastMonths(1)).toBe(1);
    expect(parseForecastMonths("9")).toBe(3);
    expect(parseForecastMonths(undefined)).toBe(3);
  });
});

describe("assumptionLines", () => {
  it("explains the baselines", () => {
    const text = assumptionLines(forecast()).join("\n");
    expect(text).toContain("2.500,00");
    expect(text).toContain("28.");
    expect(text).toContain("900,00");
    expect(text).toContain("3 vollständigen Monaten");
  });
  it("only mentions contracts without history", () => {
    const lines = assumptionLines(forecast({ insufficient_history: true }));
    expect(lines.join(" ")).toContain("zu wenig Verlauf");
    expect(lines.join(" ")).not.toContain("Median");
  });
});
