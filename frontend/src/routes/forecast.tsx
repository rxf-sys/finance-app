import { useSuspenseQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Info } from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Forecast } from "@/api/client";
import { forecastQuery } from "@/api/planning-queries";
import { Amount } from "@/components/amount";
import { Alert } from "@/components/ui/alert";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { monthLabel } from "@/lib/dates";
import { assumptionLines, FORECAST_PERIODS, type ForecastMonths, summarize } from "@/lib/forecast";
import { formatDate } from "@/lib/format";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

const euro = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });

function shortDate(iso: string): string {
  return `${iso.slice(8, 10)}.${iso.slice(5, 7)}.`;
}

function PeriodSwitch({
  months,
  onChange,
}: {
  months: ForecastMonths;
  onChange: (m: ForecastMonths) => void;
}) {
  return (
    <fieldset className="flex gap-1 rounded-lg bg-surface-muted p-1">
      <legend className="sr-only">Zeitraum</legend>
      {FORECAST_PERIODS.map((period) => (
        <button
          key={period.months}
          type="button"
          aria-pressed={period.months === months}
          onClick={() => onChange(period.months)}
          className={cn(
            "rounded-md px-3 py-1.5 text-sm",
            period.months === months ? "bg-surface font-medium shadow-sm" : "text-text-muted hover:text-text",
          )}
        >
          {period.label}
        </button>
      ))}
    </fieldset>
  );
}

function BalanceChart({ forecast }: { forecast: Forecast }) {
  const summary = summarize(forecast);
  const points = forecast.daily.map((day) => ({ date: day.date, balance: day.balance_cents / 100 }));
  const lowest = summary.lowest;
  const lowIndex = forecast.daily.findIndex((day) => day.date === lowest.date);
  const share = forecast.daily.length > 1 ? lowIndex / (forecast.daily.length - 1) : 0.5;
  // Keep the label inside the plot when the lowest point sits near an edge.
  const labelPosition = share < 0.25 ? "right" : share > 0.75 ? "left" : "top";
  const lowLabel = `${formatMoney(lowest.balance_cents)} am ${formatDate(lowest.date)}`;
  return (
    <div
      className="h-72"
      role="img"
      aria-label={`Verlauf des Kontostands bis ${formatDate(forecast.horizon_end)}. Tiefster Stand: ${lowLabel}.`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 28, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis
            dataKey="date"
            tickLine={false}
            axisLine={false}
            minTickGap={48}
            tick={{ fill: "var(--text-muted)", fontSize: 12 }}
            tickFormatter={shortDate}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={56}
            tick={{ fill: "var(--text-muted)", fontSize: 12 }}
            tickFormatter={(value: number) => euro.format(value)}
          />
          <Tooltip
            labelFormatter={(label) => formatDate(String(label))}
            formatter={(value) => [formatMoney(Math.round(Number(value) * 100)), "Kontostand"]}
            contentStyle={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              color: "var(--text)",
            }}
            labelStyle={{ color: "var(--text)", fontWeight: 600 }}
            itemStyle={{ color: "var(--text)" }}
          />
          <ReferenceLine y={0} stroke="var(--text-muted)" strokeDasharray="4 4" />
          <Area
            type="monotone"
            dataKey="balance"
            stroke="var(--primary)"
            strokeWidth={2}
            fill="var(--primary)"
            fillOpacity={0.1}
            dot={false}
            isAnimationActive={false}
          />
          <ReferenceDot
            x={lowest.date}
            y={lowest.balance_cents / 100}
            r={5}
            fill="var(--primary)"
            stroke="var(--surface)"
            strokeWidth={2}
            ifOverflow="visible"
            label={{
              value: `Tiefster Stand: ${formatMoney(lowest.balance_cents)}`,
              position: labelPosition,
              fill: summary.goesNegative ? "var(--negative)" : "var(--text)",
              fontSize: 12,
              fontWeight: 600,
            }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function MonthsTable({ forecast }: { forecast: Forecast }) {
  return (
    <Card className="overflow-x-auto p-0">
      <table className="w-full min-w-[34rem] text-sm">
        <caption className="px-4 pt-4 pb-2 text-left">
          <CardTitle>Monate im Überblick</CardTitle>
        </caption>
        <thead>
          <tr className="border-b border-border text-xs text-text-muted">
            <th className="px-4 py-2 text-left font-medium">Monat</th>
            <th className="px-3 py-2 text-right font-medium">Einnahmen</th>
            <th className="px-3 py-2 text-right font-medium">Verträge</th>
            <th className="px-3 py-2 text-right font-medium">Variable Ausgaben</th>
            <th className="px-4 py-2 text-right font-medium">Kontostand am Monatsende</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {forecast.months.map((month) => (
            <tr key={month.month}>
              <td className="px-4 py-2.5">{monthLabel(month.month)}</td>
              <td className="px-3 py-2.5 text-right tabular-nums">{formatMoney(month.income_cents)}</td>
              <td className="px-3 py-2.5 text-right tabular-nums">{formatMoney(month.contracts_cents)}</td>
              <td className="px-3 py-2.5 text-right tabular-nums">{formatMoney(month.variable_cents)}</td>
              <td className="px-4 py-2.5 text-right font-medium tabular-nums">
                {formatMoney(month.end_balance_cents)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function EventsCard({ forecast }: { forecast: Forecast }) {
  return (
    <Card>
      <CardTitle>Anstehende Ereignisse</CardTitle>
      {forecast.events.length === 0 ? (
        <CardDescription>Im gewählten Zeitraum sind keine Zahlungen eingeplant.</CardDescription>
      ) : (
        <ul className="mt-2 divide-y divide-border">
          {forecast.events.map((event) => (
            <li
              key={`${event.date}-${event.kind}-${event.contract_id ?? event.name}`}
              className="flex items-baseline gap-3 py-2 text-sm"
            >
              <span className="w-24 shrink-0 text-text-muted tabular-nums">{formatDate(event.date)}</span>
              <span className="min-w-0 flex-1 truncate">
                {event.kind === "income" ? "Erwartete Einnahmen" : event.name}
              </span>
              <Amount cents={event.amount_cents} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function AssumptionsBox({ forecast }: { forecast: Forecast }) {
  return (
    <Card className="bg-surface-muted">
      <div className="flex items-center gap-2">
        <Info className="size-4 text-text-muted" aria-hidden />
        <CardTitle>So rechnet die Prognose</CardTitle>
      </div>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-text-muted">
        {assumptionLines(forecast).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-text-muted">
        Das ist eine Schätzung auf Basis der bisherigen Buchungen, keine Zusage. Einmalige Ausgaben sind nicht
        enthalten.
      </p>
    </Card>
  );
}

export function ForecastPage({ months }: { months: ForecastMonths }) {
  const navigate = useNavigate();
  const { data: forecast } = useSuspenseQuery(forecastQuery(months));
  const summary = summarize(forecast);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Prognose</h1>
        <PeriodSwitch
          months={months}
          onChange={(next) => void navigate({ to: "/forecast", search: { months: next } })}
        />
      </div>

      {forecast.insufficient_history && (
        <Alert tone="info">
          Für eine Prognose gibt es noch zu wenig Verlauf. Bisher zählen nur die bestätigten Verträge,
          Einnahmen und variable Ausgaben fehlen.
        </Alert>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        <Card className="p-4">
          <p className="text-sm text-text-muted">Kontostand heute</p>
          <p className="mt-1 text-xl font-semibold tabular-nums">
            {formatMoney(forecast.start_balance_cents)}
          </p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-text-muted">Am {formatDate(summary.endDate)}</p>
          <p className="mt-1 text-xl font-semibold tabular-nums">{formatMoney(summary.endBalanceCents)}</p>
        </Card>
        <Card className="p-4">
          <p className="text-sm text-text-muted">Tiefster Stand</p>
          <p className="mt-1 text-xl font-semibold tabular-nums">
            {formatMoney(summary.lowest.balance_cents)}
          </p>
          <p className="text-xs text-text-muted">am {formatDate(summary.lowest.date)}</p>
        </Card>
      </div>

      <Card>
        <CardTitle>Kontostand pro Tag</CardTitle>
        <CardDescription>Giro- und Bargeldkonten zusammen, jeweils zum Tagesende.</CardDescription>
        <div className="mt-2">
          <BalanceChart forecast={forecast} />
        </div>
      </Card>

      <MonthsTable forecast={forecast} />
      <EventsCard forecast={forecast} />
      <AssumptionsBox forecast={forecast} />
    </div>
  );
}
