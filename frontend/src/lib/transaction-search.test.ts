import { describe, expect, it } from "vitest";
import { activeFilterCount, periodRange, toApiQuery, validateTransactionSearch } from "./transaction-search";

const NOW = new Date(2026, 2, 15); // 15 March 2026
const ID = "0b0b0b0b-0000-4000-8000-000000000001";

describe("validateTransactionSearch", () => {
  it("drops invalid and default values", () => {
    expect(
      validateTransactionSearch({
        period: "decade",
        direction: "sideways",
        transfers: "include",
        page: 1,
        from: "2026-13-40",
        uncategorized: "nope",
      }),
    ).toEqual({});
  });

  it("keeps valid filters", () => {
    expect(
      validateTransactionSearch({
        period: "year",
        account: ID,
        category: ID,
        direction: "out",
        transfers: "exclude",
        page: "3",
        q: "rewe",
        uncategorized: true,
      }),
    ).toEqual({
      period: "year",
      account: ID,
      category: ID,
      direction: "out",
      transfers: "exclude",
      page: 3,
      q: "rewe",
      uncategorized: true,
    });
  });

  it("treats explicit dates as a custom period and stringifies numeric search text", () => {
    expect(validateTransactionSearch({ from: "2026-01-02", q: 123 })).toEqual({
      period: "custom",
      from: "2026-01-02",
      q: "123",
    });
  });
});

describe("periodRange", () => {
  it("resolves the presets", () => {
    expect(periodRange({}, NOW)).toEqual({ from: "2026-03-01", to: "2026-03-31" });
    expect(periodRange({ period: "last-month" }, NOW)).toEqual({ from: "2026-02-01", to: "2026-02-28" });
    expect(periodRange({ period: "year" }, NOW)).toEqual({ from: "2026-01-01", to: "2026-12-31" });
    expect(periodRange({ period: "all" }, NOW)).toEqual({ from: null, to: null });
    expect(periodRange({ period: "custom", from: "2026-02-10" }, NOW)).toEqual({
      from: "2026-02-10",
      to: null,
    });
  });

  it("wraps January to the previous year", () => {
    expect(periodRange({ period: "last-month" }, new Date(2026, 0, 5))).toEqual({
      from: "2025-12-01",
      to: "2025-12-31",
    });
  });
});

describe("toApiQuery", () => {
  it("maps the defaults to the current month, first page", () => {
    expect(toApiQuery({}, NOW)).toEqual({
      date_from: "2026-03-01",
      date_to: "2026-03-31",
      limit: 50,
      offset: 0,
    });
  });

  it("maps all filters and paginates", () => {
    expect(
      toApiQuery(
        {
          period: "all",
          account: ID,
          category: ID,
          q: "miete",
          direction: "in",
          tag: ID,
          transfers: "only",
          page: 3,
        },
        NOW,
      ),
    ).toEqual({
      account_id: [ID],
      category_id: [ID],
      q: "miete",
      direction: "in",
      tag_id: ID,
      transfers: "only",
      limit: 50,
      offset: 100,
    });
  });

  it("lets uncategorized win over a category filter", () => {
    const query = toApiQuery({ period: "all", uncategorized: true, category: ID }, NOW);
    expect(query.uncategorized).toBe(true);
    expect(query.category_id).toBeUndefined();
  });
});

describe("activeFilterCount", () => {
  it("counts filters but not the page or the default period", () => {
    expect(activeFilterCount({ page: 2 })).toBe(0);
    expect(activeFilterCount({ period: "all", q: "x", uncategorized: true })).toBe(3);
  });
});
