import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { ChevronDown, ChevronLeft, ChevronRight, Download } from "lucide-react";
import { Fragment, type ReactNode, useState } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CategoryReportRow, YearReport } from "@/api/client";
import { categoryReportQuery, yearReportQuery } from "@/api/planning-queries";
import { accountsQuery } from "@/api/queries";
import { CategoryIconTile } from "@/components/category-badge";
import { FormField } from "@/components/form-field";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { currentMonthKey, shortMonthLabel } from "@/lib/dates";
import { formatMoney } from "@/lib/money";
import {
  type ExportFormat,
  exportRangeValid,
  exportUrl,
  formatSavingsRate,
  hasFlows,
  yearRange,
} from "@/lib/reports";
import { cn } from "@/lib/utils";

const euro = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });

function YearSwitcher({ year, onChange }: { year: number; onChange: (year: number) => void }) {
  return (
    <div className="flex items-center gap-1">
      <Button variant="secondary" size="icon" onClick={() => onChange(year - 1)} aria-label="Vorheriges Jahr">
        <ChevronLeft aria-hidden />
      </Button>
      <p className="min-w-20 text-center text-sm font-medium" aria-live="polite">
        {year}
      </p>
      <Button variant="secondary" size="icon" onClick={() => onChange(year + 1)} aria-label="Nächstes Jahr">
        <ChevronRight aria-hidden />
      </Button>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card className="p-4">
      <p className="text-sm text-text-muted">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="text-xs text-text-muted">{hint}</p>}
    </Card>
  );
}

function YearOverview({ report }: { report: YearReport }) {
  // Months still ahead have no bookings yet; leave them empty instead of plotting zeros.
  const current = currentMonthKey();
  const points = report.months.map((m) => {
    const future = m.month > current;
    return {
      key: m.month,
      label: shortMonthLabel(m.month),
      Einnahmen: future ? null : m.income_cents / 100,
      Ausgaben: future ? null : -m.expense_cents / 100,
      Saldo: future ? null : m.saldo_cents / 100,
    };
  });
  return (
    <section className="space-y-3" aria-labelledby="year-overview">
      <h2 id="year-overview" className="text-lg font-semibold">
        Jahresübersicht
      </h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Einnahmen" value={formatMoney(report.income_cents)} />
        <Stat label="Ausgaben" value={formatMoney(-report.expense_cents)} />
        <Stat label="Saldo" value={formatMoney(report.saldo_cents)} />
        <Stat
          label="Sparquote"
          value={formatSavingsRate(report.savings_rate_bp)}
          hint={
            report.savings_rate_bp === null
              ? "Ohne Einnahmen nicht berechenbar"
              : "Saldo im Verhältnis zu den Einnahmen"
          }
        />
      </div>
      <Card>
        <CardTitle>Einnahmen und Ausgaben pro Monat</CardTitle>
        <div
          className="mt-3 h-72"
          role="img"
          aria-label={`Diagramm: Einnahmen, Ausgaben und Saldo je Monat in ${report.year}`}
        >
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={points} margin={{ top: 4, right: 4, left: 0, bottom: 0 }} barGap={2}>
              <CartesianGrid vertical={false} stroke="var(--border)" />
              <XAxis
                dataKey="label"
                tickLine={false}
                axisLine={false}
                tick={{ fill: "var(--text-muted)", fontSize: 12 }}
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                width={52}
                tick={{ fill: "var(--text-muted)", fontSize: 12 }}
                tickFormatter={(value: number) => euro.format(value)}
              />
              <Tooltip
                cursor={{ fill: "var(--surface-muted)" }}
                formatter={(value) => formatMoney(Math.round(Number(value) * 100))}
                contentStyle={{
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  color: "var(--text)",
                }}
                labelStyle={{ color: "var(--text)", fontWeight: 600 }}
                itemStyle={{ color: "var(--text)" }}
              />
              <Legend wrapperStyle={{ fontSize: 12, color: "var(--text-muted)" }} />
              <Bar
                dataKey="Einnahmen"
                fill="var(--positive)"
                radius={[3, 3, 0, 0]}
                isAnimationActive={false}
              />
              <Bar dataKey="Ausgaben" fill="var(--primary)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
              <Line
                dataKey="Saldo"
                stroke="var(--chart-2)"
                strokeWidth={2}
                dot={{ r: 3, fill: "var(--chart-2)" }}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </section>
  );
}

const CELL = "min-w-28 px-3 py-2 text-right tabular-nums whitespace-nowrap";

function cellText(cents: number): string {
  return cents === 0 ? "–" : formatMoney(cents);
}

function MonthCells({ months, total, strong }: { months: number[]; total: number; strong?: boolean }) {
  return (
    <>
      {months.map((cents, index) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: fixed twelve columns, January first
        <td key={index} className={cn(CELL, cents === 0 && "text-text-muted", strong && "font-semibold")}>
          {cellText(cents)}
        </td>
      ))}
      <td className={cn(CELL, "font-semibold")}>{formatMoney(total)}</td>
    </>
  );
}

function FirstCell({
  children,
  className,
  muted,
}: {
  children: ReactNode;
  className?: string;
  muted?: boolean;
}) {
  return (
    <th
      scope="row"
      className={cn(
        "sticky left-0 z-10 max-w-44 min-w-40 border-r border-border px-3 py-2 text-left font-normal",
        muted ? "bg-surface-muted" : "bg-surface",
        className,
      )}
    >
      {children}
    </th>
  );
}

function CategoryTable({ year }: { year: number }) {
  const [kind, setKind] = useState<"expense" | "income">("expense");
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const { data: report, isPending } = useQuery(categoryReportQuery(year, kind));

  const toggle = (id: string) =>
    setOpen((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  const rows = report?.rows.filter((r) => r.total_cents !== 0) ?? [];
  const uncategorized = report && report.uncategorized.total_cents !== 0 ? report.uncategorized : null;

  return (
    <section className="space-y-3" aria-labelledby="category-report">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="category-report" className="text-lg font-semibold">
          Kategorien nach Monat
        </h2>
        <fieldset className="flex gap-1 rounded-lg bg-surface-muted p-1">
          <legend className="sr-only">Art</legend>
          {(
            [
              ["expense", "Ausgaben"],
              ["income", "Einnahmen"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={kind === value}
              onClick={() => setKind(value)}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm",
                kind === value ? "bg-surface font-medium shadow-sm" : "text-text-muted hover:text-text",
              )}
            >
              {label}
            </button>
          ))}
        </fieldset>
      </div>
      <Card className="overflow-x-auto p-0">
        {isPending || !report ? (
          <p className="p-4 text-sm text-text-muted">Lädt …</p>
        ) : rows.length === 0 && !uncategorized ? (
          <p className="p-4 text-sm text-text-muted">
            {kind === "expense" ? "Keine Ausgaben" : "Keine Einnahmen"} in {year}.
          </p>
        ) : (
          <table className="w-full min-w-[78rem] text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-text-muted">
                <th className="sticky left-0 z-10 border-r border-border bg-surface px-3 py-2 text-left font-medium">
                  Kategorie
                </th>
                {report.totals_cents.map((_, index) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: fixed twelve columns, January first
                  <th key={index} className="min-w-28 px-3 py-2 text-right font-medium">
                    {shortMonthLabel(`${year}-${String(index + 1).padStart(2, "0")}`)}
                  </th>
                ))}
                <th className="px-3 py-2 text-right font-medium">Summe</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((row) => (
                <CategoryRows
                  key={row.category_id ?? row.name}
                  row={row}
                  expanded={row.category_id !== null && open.has(row.category_id)}
                  onToggle={() => row.category_id && toggle(row.category_id)}
                />
              ))}
              {uncategorized && (
                <tr>
                  <FirstCell>
                    <span className="flex items-center gap-2">
                      <CategoryIconTile category={null} className="size-6" />
                      Ohne Kategorie
                    </span>
                  </FirstCell>
                  <MonthCells months={uncategorized.months_cents} total={uncategorized.total_cents} />
                </tr>
              )}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-border">
                <FirstCell muted className="font-semibold">
                  Gesamt
                </FirstCell>
                <MonthCells months={report.totals_cents} total={report.total_cents} strong />
              </tr>
            </tfoot>
          </table>
        )}
      </Card>
    </section>
  );
}

function CategoryRows({
  row,
  expanded,
  onToggle,
}: {
  row: CategoryReportRow;
  expanded: boolean;
  onToggle: () => void;
}) {
  const children = row.children.filter((c) => c.total_cents !== 0);
  const expandable = children.length > 0;
  return (
    <Fragment>
      <tr>
        <FirstCell>
          <div className="flex items-center gap-1">
            {expandable ? (
              <button
                type="button"
                onClick={onToggle}
                aria-expanded={expanded}
                aria-label={`${row.name}: Unterkategorien ${expanded ? "ausblenden" : "anzeigen"}`}
                className="rounded p-0.5 text-text-muted hover:bg-surface-muted"
              >
                {expanded ? (
                  <ChevronDown className="size-4" aria-hidden />
                ) : (
                  <ChevronRight className="size-4" aria-hidden />
                )}
              </button>
            ) : (
              <span className="size-5" aria-hidden />
            )}
            <CategoryIconTile category={row} className="size-6" />
            <span className="ml-1 truncate">{row.name}</span>
          </div>
        </FirstCell>
        <MonthCells months={row.months_cents} total={row.total_cents} />
      </tr>
      {expanded &&
        children.map((child) => (
          <tr key={child.category_id ?? child.name} className="bg-surface-muted/40">
            <FirstCell className="pl-12 text-text-muted">
              <span className="block truncate">{child.name}</span>
            </FirstCell>
            <MonthCells months={child.months_cents} total={child.total_cents} />
          </tr>
        ))}
    </Fragment>
  );
}

function ExportSection({ year }: { year: number }) {
  const { data: accounts = [] } = useQuery(accountsQuery);
  const defaults = yearRange(year);
  const [from, setFrom] = useState(defaults.from);
  const [to, setTo] = useState(defaults.to);
  const [accountId, setAccountId] = useState("all");
  const [format, setFormat] = useState<ExportFormat>("csv");
  const valid = exportRangeValid(from, to);
  const href = exportUrl({
    format,
    from,
    to,
    accountId: accountId === "all" ? undefined : accountId,
  });

  return (
    <section className="space-y-3" aria-labelledby="export">
      <h2 id="export" className="text-lg font-semibold">
        Export
      </h2>
      <Card>
        <CardTitle>Buchungen herunterladen</CardTitle>
        <CardDescription>
          Alle Buchungen, die du sehen darfst, nach Buchungsdatum sortiert. Geteilte Buchungen mit mehreren
          Kategorien erscheinen als eine Zeile je Anteil. Pro Export sind höchstens 100.000 Zeilen möglich,
          grenze sonst Zeitraum oder Konto ein.
        </CardDescription>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <FormField label="Von" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          <FormField label="Bis" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          <div className="space-y-1.5">
            <Label htmlFor="export-account">Konto</Label>
            <Select
              id="export-account"
              value={accountId}
              onValueChange={setAccountId}
              options={[
                { value: "all", label: "Alle Konten" },
                ...accounts.map((a) => ({ value: a.id, label: a.name })),
              ]}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="export-format">Format</Label>
            <Select
              id="export-format"
              value={format}
              onValueChange={(v) => setFormat(v as ExportFormat)}
              options={[
                { value: "csv", label: "CSV" },
                { value: "xlsx", label: "Excel (XLSX)" },
              ]}
            />
          </div>
        </div>
        {!valid && (
          <Alert tone="error" className="mt-3">
            „Von“ darf nicht nach „Bis“ liegen.
          </Alert>
        )}
        <div className="mt-4 flex justify-end">
          {valid ? (
            <Button asChild>
              <a href={href} download>
                <Download aria-hidden />
                Herunterladen
              </a>
            </Button>
          ) : (
            <Button disabled>
              <Download aria-hidden />
              Herunterladen
            </Button>
          )}
        </div>
      </Card>
    </section>
  );
}

export function ReportsPage({ year }: { year: number }) {
  const navigate = useNavigate();
  const { data: report } = useSuspenseQuery(yearReportQuery(year));
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Berichte</h1>
        <YearSwitcher
          year={year}
          onChange={(next) => void navigate({ to: "/reports", search: { year: next } })}
        />
      </div>
      {hasFlows(report.months) ? (
        <YearOverview report={report} />
      ) : (
        <Card className="py-8 text-center">
          <CardTitle>Keine Buchungen in {year}</CardTitle>
          <CardDescription>Wähle ein anderes Jahr oder importiere Buchungen.</CardDescription>
        </Card>
      )}
      <CategoryTable key={year} year={year} />
      <ExportSection key={`export-${year}`} year={year} />
    </div>
  );
}
