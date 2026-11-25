/** "2500" basis points -> "25,0 %"; null (no income) -> "–". */
export function formatSavingsRate(basisPoints: number | null): string {
  if (basisPoints === null) return "–";
  return `${new Intl.NumberFormat("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(basisPoints / 100)} %`;
}

export type ExportFormat = "csv" | "xlsx";

export type ExportParams = {
  format: ExportFormat;
  from?: string;
  to?: string;
  accountId?: string;
};

/** Same-origin download link, so session cookies and Cloudflare Access apply. */
export function exportUrl({ format, from, to, accountId }: ExportParams): string {
  const query = new URLSearchParams({ format });
  if (from) query.set("from", from);
  if (to) query.set("to", to);
  if (accountId) query.set("account_id", accountId);
  return `/api/export/transactions?${query.toString()}`;
}

/** The export range is valid when both ends are set in order, or one of them is open. */
export function exportRangeValid(from: string, to: string): boolean {
  return !from || !to || from <= to;
}

export function yearRange(year: number): { from: string; to: string } {
  return { from: `${year}-01-01`, to: `${year}-12-31` };
}

/** Whether the report has any booking at all, to show an empty state. */
export function hasFlows(months: readonly { income_cents: number; expense_cents: number }[]): boolean {
  return months.some((m) => m.income_cents !== 0 || m.expense_cents !== 0);
}
