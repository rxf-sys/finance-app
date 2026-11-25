import { describe, expect, it } from "vitest";
import { exportRangeValid, exportUrl, formatSavingsRate, hasFlows, yearRange } from "./reports";

describe("formatSavingsRate", () => {
  it("formats basis points with one decimal", () => {
    expect(formatSavingsRate(2500)).toBe("25,0 %");
    expect(formatSavingsRate(1234)).toBe("12,3 %");
    expect(formatSavingsRate(-550)).toBe("-5,5 %");
    expect(formatSavingsRate(0)).toBe("0,0 %");
  });
  it("shows a dash without income", () => {
    expect(formatSavingsRate(null)).toBe("–");
  });
});

describe("exportUrl", () => {
  it("builds a same-origin url with all filters", () => {
    expect(exportUrl({ format: "xlsx", from: "2026-01-01", to: "2026-12-31", accountId: "abc" })).toBe(
      "/api/export/transactions?format=xlsx&from=2026-01-01&to=2026-12-31&account_id=abc",
    );
  });
  it("omits empty filters", () => {
    expect(exportUrl({ format: "csv", from: "", accountId: undefined })).toBe(
      "/api/export/transactions?format=csv",
    );
  });
});

describe("exportRangeValid", () => {
  it("rejects a reversed range only", () => {
    expect(exportRangeValid("2026-02-01", "2026-01-01")).toBe(false);
    expect(exportRangeValid("2026-01-01", "2026-01-01")).toBe(true);
    expect(exportRangeValid("", "2026-01-01")).toBe(true);
  });
});

describe("yearRange / hasFlows", () => {
  it("covers the whole year", () => {
    expect(yearRange(2026)).toEqual({ from: "2026-01-01", to: "2026-12-31" });
  });
  it("detects an empty year", () => {
    expect(hasFlows([{ income_cents: 0, expense_cents: 0 }])).toBe(false);
    expect(hasFlows([{ income_cents: 0, expense_cents: -1 }])).toBe(true);
  });
});
