import { describe, expect, it } from "vitest";
import {
  canDelete,
  canDo,
  daysUntil,
  deadlineDistance,
  deadlineTone,
  formatNotice,
  kindBreakdown,
  kindLabel,
  monthlyTotal,
  noticeFromDays,
  noticeToDays,
} from "./contracts";

describe("deadlineTone", () => {
  it("is danger when overdue or under 7 days", () => {
    expect(deadlineTone(-3)).toBe("danger");
    expect(deadlineTone(0)).toBe("danger");
    expect(deadlineTone(6)).toBe("danger");
  });
  it("is warning from 7 to 29 days", () => {
    expect(deadlineTone(7)).toBe("warning");
    expect(deadlineTone(29)).toBe("warning");
  });
  it("is neutral from 30 days", () => {
    expect(deadlineTone(30)).toBe("neutral");
    expect(deadlineTone(200)).toBe("neutral");
  });
});

describe("daysUntil", () => {
  const today = new Date(2026, 10, 25, 23, 30);
  it("counts calendar days regardless of the time of day", () => {
    expect(daysUntil("2026-11-25", today)).toBe(0);
    expect(daysUntil("2026-11-26", today)).toBe(1);
    expect(daysUntil("2026-11-20", today)).toBe(-5);
    expect(daysUntil("2027-01-01", today)).toBe(37);
  });
});

describe("deadlineDistance", () => {
  it("uses German wording", () => {
    expect(deadlineDistance(-2)).toBe("seit 2 Tagen überfällig");
    expect(deadlineDistance(0)).toBe("heute");
    expect(deadlineDistance(1)).toBe("morgen");
    expect(deadlineDistance(12)).toBe("in 12 Tagen");
  });
});

describe("kind labels and monthly cost", () => {
  it("labels kinds in German and falls back for unknown ones", () => {
    expect(kindLabel("utilities")).toBe("Strom & Gas / Nebenkosten");
    expect(kindLabel("subscription")).toBe("Abo");
    expect(kindLabel("nope")).toBe("Sonstiges");
  });
  it("sums monthly equivalents", () => {
    expect(monthlyTotal([{ monthly_amount_cents: -1299 }, { monthly_amount_cents: -801 }])).toBe(-2100);
    expect(monthlyTotal([])).toBe(0);
  });
  it("orders the breakdown by cost and computes shares", () => {
    const rows = kindBreakdown([
      { kind: "subscription", count: 2, monthly_cost_cents: 1000 },
      { kind: "insurance", count: 1, monthly_cost_cents: 3000 },
    ]);
    expect(rows.map((r) => r.label)).toEqual(["Versicherung", "Abo"]);
    expect(rows[0].share).toBeCloseTo(0.75);
    expect(kindBreakdown([{ kind: "rent", count: 1, monthly_cost_cents: 0 }])[0].share).toBe(0);
  });
});

describe("notice period", () => {
  it("converts months to days with 30 days per month", () => {
    expect(noticeToDays(3, "months")).toBe(90);
    expect(noticeToDays(14, "days")).toBe(14);
  });
  it("shows full months as months", () => {
    expect(noticeFromDays(90)).toEqual({ value: 3, unit: "months" });
    expect(noticeFromDays(45)).toEqual({ value: 45, unit: "days" });
    expect(noticeFromDays(0)).toEqual({ value: 0, unit: "days" });
  });
  it("formats with singular and plural", () => {
    expect(formatNotice(30)).toBe("1 Monat");
    expect(formatNotice(60)).toBe("2 Monate");
    expect(formatNotice(1)).toBe("1 Tag");
    expect(formatNotice(14)).toBe("14 Tage");
  });
});

describe("status transitions", () => {
  it("allows only what the backend allows", () => {
    expect(canDo("confirm", "detected")).toBe(true);
    expect(canDo("confirm", "confirmed")).toBe(false);
    expect(canDo("cancel", "confirmed")).toBe(true);
    expect(canDo("cancel", "detected")).toBe(false);
    expect(canDo("ignore", "confirmed")).toBe(true);
    expect(canDo("ignore", "cancelled")).toBe(false);
    expect(canDo("reactivate", "cancelled")).toBe(true);
    expect(canDo("reactivate", "ignored")).toBe(true);
    expect(canDo("reactivate", "confirmed")).toBe(false);
  });
  it("deletes only manual or ignored contracts", () => {
    expect(canDelete({ is_manual: true, status: "confirmed" })).toBe(true);
    expect(canDelete({ is_manual: false, status: "ignored" })).toBe(true);
    expect(canDelete({ is_manual: false, status: "confirmed" })).toBe(false);
  });
});
