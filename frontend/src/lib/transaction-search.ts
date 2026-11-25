import { addMonths, currentMonthKey, isIsoDate, monthRange, toIsoDate } from "./dates";

export const PAGE_SIZE = 50;

export const PERIODS = ["month", "last-month", "year", "all", "custom"] as const;
export type Period = (typeof PERIODS)[number];

export const PERIOD_LABEL: Record<Period, string> = {
  month: "Dieser Monat",
  "last-month": "Letzter Monat",
  year: "Dieses Jahr",
  all: "Alle",
  custom: "Eigener Zeitraum",
};

export const DIRECTIONS = ["in", "out"] as const;
export const TRANSFER_MODES = ["include", "exclude", "only"] as const;

/** Filters of the Buchungen page. Everything is optional so the URL stays short. */
export type TransactionSearch = {
  period?: Period;
  from?: string;
  to?: string;
  account?: string;
  category?: string;
  uncategorized?: boolean;
  q?: string;
  direction?: (typeof DIRECTIONS)[number];
  tag?: string;
  transfers?: (typeof TRANSFER_MODES)[number];
  page?: number;
  tx?: string;
};

function str(value: unknown): string | undefined {
  if (typeof value === "number") return String(value); // the router parses "123" to a number
  return typeof value === "string" && value.trim() !== "" ? value : undefined;
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[]): T | undefined {
  return allowed.find((candidate) => candidate === value);
}

/** Tolerant parsing of untrusted URL input: invalid values are dropped, never thrown. */
export function validateTransactionSearch(raw: Record<string, unknown>): TransactionSearch {
  const result: TransactionSearch = {};
  const period = oneOf(raw.period, PERIODS);
  if (period && period !== "month") result.period = period; // "month" is the default
  if (isIsoDate(raw.from)) result.from = raw.from;
  if (isIsoDate(raw.to)) result.to = raw.to;
  if (result.from || result.to) result.period = "custom";
  const account = str(raw.account);
  if (account) result.account = account;
  const category = str(raw.category);
  if (category) result.category = category;
  if (raw.uncategorized === true || raw.uncategorized === "true") result.uncategorized = true;
  const q = str(raw.q);
  if (q) result.q = q;
  const direction = oneOf(raw.direction, DIRECTIONS);
  if (direction) result.direction = direction;
  const tag = str(raw.tag);
  if (tag) result.tag = tag;
  const transfers = oneOf(raw.transfers, TRANSFER_MODES);
  if (transfers && transfers !== "include") result.transfers = transfers;
  const page = Number(raw.page);
  if (Number.isInteger(page) && page > 1) result.page = page;
  const tx = str(raw.tx);
  if (tx) result.tx = tx;
  return result;
}

/** Date range for the selected period; null bounds mean unbounded. */
export function periodRange(
  search: Pick<TransactionSearch, "period" | "from" | "to">,
  now = new Date(),
): { from: string | null; to: string | null } {
  const month = currentMonthKey(now);
  switch (search.period ?? "month") {
    case "month":
      return monthRange(month);
    case "last-month":
      return monthRange(addMonths(month, -1));
    case "year":
      return { from: `${now.getFullYear()}-01-01`, to: `${now.getFullYear()}-12-31` };
    case "all":
      return { from: null, to: null };
    case "custom":
      return { from: search.from ?? null, to: search.to ?? null };
  }
}

/** Query parameters for GET /api/transactions. */
export type TransactionQuery = {
  account_id?: string[];
  category_id?: string[];
  uncategorized?: boolean;
  date_from?: string;
  date_to?: string;
  q?: string;
  direction?: "in" | "out";
  tag_id?: string;
  transfers?: "include" | "exclude" | "only";
  limit: number;
  offset: number;
};

export function toApiQuery(search: TransactionSearch, now = new Date()): TransactionQuery {
  const range = periodRange(search, now);
  const query: TransactionQuery = {
    limit: PAGE_SIZE,
    offset: ((search.page ?? 1) - 1) * PAGE_SIZE,
  };
  if (range.from) query.date_from = range.from;
  if (range.to) query.date_to = range.to;
  if (search.account) query.account_id = [search.account];
  if (search.uncategorized) query.uncategorized = true;
  else if (search.category) query.category_id = [search.category];
  if (search.q) query.q = search.q;
  if (search.direction) query.direction = search.direction;
  if (search.tag) query.tag_id = search.tag;
  if (search.transfers) query.transfers = search.transfers;
  return query;
}

/** Number of active filters besides the period, for the "Filter zurücksetzen" affordance. */
export function activeFilterCount(search: TransactionSearch): number {
  return [
    search.account,
    search.category,
    search.uncategorized,
    search.q,
    search.direction,
    search.tag,
    search.transfers,
    search.period && search.period !== "month" ? search.period : undefined,
  ].filter(Boolean).length;
}

/** Today as ISO date, exported for the manual transaction dialog. */
export function today(): string {
  return toIsoDate(new Date());
}
