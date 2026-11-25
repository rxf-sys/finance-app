import type { Forecast } from "@/api/client";
import { formatMoney } from "@/lib/money";

export type ForecastMonths = 1 | 2 | 3;

export const FORECAST_PERIODS: { months: ForecastMonths; label: string }[] = [
  { months: 1, label: "1 Monat" },
  { months: 2, label: "2 Monate" },
  { months: 3, label: "3 Monate" },
];

export const DEFAULT_FORECAST_MONTHS: ForecastMonths = 3;

export function parseForecastMonths(value: unknown): ForecastMonths {
  const months = Number(value);
  return months === 1 || months === 2 || months === 3 ? months : DEFAULT_FORECAST_MONTHS;
}

type Day = { date: string; balance_cents: number };

/** Lowest daily balance; the earliest day wins a tie. Null for an empty series. */
export function lowestPoint(daily: readonly Day[]): Day | null {
  let lowest: Day | null = null;
  for (const day of daily) {
    if (lowest === null || day.balance_cents < lowest.balance_cents) lowest = day;
  }
  return lowest;
}

/** Balance on the last forecast day, or the start balance when there are no days. */
export function endBalance(forecast: Pick<Forecast, "daily" | "start_balance_cents">): number {
  const last = forecast.daily.at(-1);
  return last ? last.balance_cents : forecast.start_balance_cents;
}

export type ForecastSummary = {
  endBalanceCents: number;
  endDate: string;
  lowest: Day;
  /** The lowest point is below zero. */
  goesNegative: boolean;
  /** Change between today's balance and the end of the horizon. */
  changeCents: number;
};

export function summarize(forecast: Forecast): ForecastSummary {
  const lowest = lowestPoint(forecast.daily) ?? forecast.lowest;
  const endCents = endBalance(forecast);
  return {
    endBalanceCents: endCents,
    endDate: forecast.horizon_end,
    lowest,
    goesNegative: lowest.balance_cents < 0,
    changeCents: endCents - forecast.start_balance_cents,
  };
}

/** Plain-language lines for the "So rechnet die Prognose" box. */
export function assumptionLines(forecast: Pick<Forecast, "assumptions" | "insufficient_history">): string[] {
  const { assumptions, insufficient_history } = forecast;
  const lines = ["Grundlage sind nur Girokonten und Bargeld, die du sehen kannst."];
  if (insufficient_history) {
    lines.push("Es gibt noch zu wenig Verlauf: Nur bestätigte Verträge fließen in die Prognose ein.");
    return lines;
  }
  const months =
    assumptions.months_used === 1
      ? "dem letzten vollständigen Monat"
      : `den letzten ${assumptions.months_used} vollständigen Monaten`;
  lines.push(
    assumptions.income_baseline_cents > 0 && assumptions.income_day !== null
      ? `Einnahmen: typisch ${formatMoney(assumptions.income_baseline_cents)} pro Monat, erwartet um den ${assumptions.income_day}. des Monats.`
      : "Einnahmen: Es wird kein regelmäßiger Geldeingang erwartet.",
  );
  lines.push(
    `Variable Ausgaben: ${formatMoney(assumptions.variable_baseline_cents)} pro Monat, gleichmäßig auf die Tage verteilt.`,
  );
  lines.push(
    `Beide Werte sind der Median aus ${months}, ohne Umbuchungen und ohne Zahlungen bestätigter Verträge.`,
  );
  lines.push("Verträge werden nach ihrem Zahlungsplan eingerechnet.");
  return lines;
}
