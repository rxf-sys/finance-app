import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronRight, CircleHelp, Lightbulb } from "lucide-react";
import {
  availableQuery,
  budgetStatusQuery,
  contractSummaryQuery,
  contractsQuery,
} from "@/api/planning-queries";
import { Amount } from "@/components/amount";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { mostCritical } from "@/lib/budgets";
import { daysUntil, deadlineDistance, kindIcon } from "@/lib/contracts";
import { formatDate } from "@/lib/format";
import { formatMoney, formatSignedMoney } from "@/lib/money";
import { BudgetRow } from "@/routes/budgets";

/** "Frei verfügbar" tile; the popover explains where the number comes from. */
export function AvailableTile() {
  const { data } = useQuery(availableQuery);
  if (!data) return <Card className="p-4 text-sm text-text-muted">Frei verfügbar …</Card>;
  const payments = data.items.filter((item) => item.amount_cents < 0);
  const incomes = data.items.filter((item) => item.amount_cents > 0);
  return (
    <Card className="flex items-baseline justify-between gap-3 p-4 sm:block">
      <div className="flex items-center gap-1">
        <p className="text-sm text-text-muted">Frei verfügbar</p>
        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              className="rounded-full p-1 text-text-muted hover:bg-surface-muted"
              aria-label="So wird Frei verfügbar berechnet"
            >
              <CircleHelp className="size-3.5" aria-hidden />
            </button>
          </PopoverTrigger>
          <PopoverContent className="w-80 p-4 text-sm">
            <p className="font-semibold">So wird gerechnet</p>
            <dl className="mt-2 space-y-1.5">
              <div className="flex justify-between gap-3">
                <dt>Kontostand (Giro und Bargeld)</dt>
                <dd className="tabular-nums">{formatMoney(data.balance_cents)}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt>Abbuchungen bis Monatsende</dt>
                <dd className="tabular-nums">{formatSignedMoney(-data.upcoming_out_cents)}</dd>
              </div>
              {payments.length > 0 && (
                <ul className="space-y-0.5 border-l border-border pl-3 text-xs text-text-muted">
                  {payments.map((item) => (
                    <li key={`${item.contract_id}-${item.due_date}`} className="flex justify-between gap-3">
                      <span className="truncate">
                        {formatDate(item.due_date)} · {item.name}
                      </span>
                      <span className="tabular-nums">{formatSignedMoney(item.amount_cents)}</span>
                    </li>
                  ))}
                </ul>
              )}
              <div className="flex justify-between gap-3">
                <dt>Erwartete Einnahmen</dt>
                <dd className="tabular-nums">{formatSignedMoney(data.upcoming_in_cents)}</dd>
              </div>
              {incomes.length > 0 && (
                <ul className="space-y-0.5 border-l border-border pl-3 text-xs text-text-muted">
                  {incomes.map((item) => (
                    <li key={`${item.contract_id}-${item.due_date}`} className="flex justify-between gap-3">
                      <span className="truncate">
                        {formatDate(item.due_date)} · {item.name}
                      </span>
                      <span className="tabular-nums">{formatSignedMoney(item.amount_cents)}</span>
                    </li>
                  ))}
                </ul>
              )}
              <div className="flex justify-between gap-3 border-t border-border pt-1.5 font-semibold">
                <dt>Frei verfügbar</dt>
                <dd className="tabular-nums">{formatMoney(data.available_cents)}</dd>
              </div>
            </dl>
            <p className="mt-3 text-xs text-text-muted">
              Berücksichtigt nur bestätigte Verträge. Andere Ausgaben bis Monatsende sind nicht eingerechnet.
            </p>
          </PopoverContent>
        </Popover>
      </div>
      <p className="text-lg font-semibold whitespace-nowrap tabular-nums sm:mt-1 sm:text-2xl">
        {formatMoney(data.available_cents)}
      </p>
    </Card>
  );
}

/** Points to detected contracts that wait for a decision. */
export function SuggestionsBanner() {
  const { data } = useQuery(contractSummaryQuery);
  const count = data?.detected_count ?? 0;
  if (count === 0) return null;
  return (
    <Link
      to="/contracts"
      className="flex items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3 text-sm hover:bg-surface-muted"
    >
      <Lightbulb className="size-4 shrink-0 text-accent" aria-hidden />
      <span className="flex-1">
        <span className="font-medium">
          {count === 1 ? "1 neuer Vertragsvorschlag" : `${count} neue Vertragsvorschläge`} prüfen
        </span>
        <span className="text-text-muted"> · bestätigen oder ignorieren</span>
      </span>
      <ChevronRight className="size-4 text-text-muted" aria-hidden />
    </Link>
  );
}

export function BudgetsCard({ month }: { month: string }) {
  const { data = [] } = useQuery(budgetStatusQuery(month));
  const top = mostCritical(data, 3);
  return (
    <Card>
      <div className="flex items-baseline justify-between gap-2">
        <CardTitle>Budgets</CardTitle>
        <Link to="/budgets" search={{ month }} className="text-sm text-primary hover:underline">
          Alle Budgets
        </Link>
      </div>
      {top.length === 0 ? (
        <CardDescription>
          Noch keine Budgets.{" "}
          <Link to="/budgets" search={{ month }} className="text-primary underline">
            Budget anlegen
          </Link>
        </CardDescription>
      ) : (
        <ul className="mt-1 divide-y divide-border">
          {top.map((budget) => (
            <BudgetRow key={budget.id} budget={budget} compact />
          ))}
        </ul>
      )}
    </Card>
  );
}

const UPCOMING_DAYS = 14;

export function UpcomingCard() {
  const { data = [] } = useQuery(contractsQuery({ status: "confirmed" }));
  const upcoming = data
    .filter((c) => c.next_due_date !== null)
    .map((c) => ({ contract: c, days: daysUntil(c.next_due_date as string) }))
    .filter(({ days }) => days >= 0 && days <= UPCOMING_DAYS)
    .sort((a, b) => a.days - b.days || a.contract.name.localeCompare(b.contract.name, "de"));
  return (
    <Card>
      <div className="flex items-baseline justify-between gap-2">
        <CardTitle>Nächste Abbuchungen</CardTitle>
        <Link to="/contracts" className="text-sm text-primary hover:underline">
          Alle Verträge
        </Link>
      </div>
      {upcoming.length === 0 ? (
        <CardDescription>In den nächsten {UPCOMING_DAYS} Tagen ist nichts fällig.</CardDescription>
      ) : (
        <ul className="mt-3 divide-y divide-border">
          {upcoming.map(({ contract, days }) => {
            const Icon = kindIcon(contract.kind);
            return (
              <li key={contract.id}>
                <Link
                  to="/contracts/$contractId"
                  params={{ contractId: contract.id }}
                  className="flex items-center gap-3 py-2.5 hover:text-primary"
                >
                  <Icon className="size-4 shrink-0 text-text-muted" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm">{contract.name}</span>
                    <span className="block text-xs text-text-muted">
                      {formatDate(contract.next_due_date as string)} · {deadlineDistance(days)}
                    </span>
                  </span>
                  <Amount cents={contract.expected_amount_cents} className="text-sm" />
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
