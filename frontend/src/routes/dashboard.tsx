import { useSuspenseQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight, Landmark, Tag } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { AccountKind, Dashboard } from "@/api/client";
import { dashboardQuery, meQuery } from "@/api/queries";
import { CategoryIconTile } from "@/components/category-badge";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { ACCOUNT_KIND_ICON } from "@/lib/accounts";
import { categoryColor } from "@/lib/categories";
import { addMonths, monthLabel, shortMonthLabel } from "@/lib/dates";
import { formatMoney, formatSignedMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

type Props = { month: string };

function Kpi({ label, cents, tone }: { label: string; cents: number; tone?: "positive" }) {
  return (
    <Card className="flex items-baseline justify-between gap-3 p-4 sm:block">
      <p className="text-sm text-text-muted">{label}</p>
      <p
        className={cn(
          "text-lg font-semibold whitespace-nowrap tabular-nums sm:mt-1 sm:text-2xl",
          tone === "positive" && cents > 0 && "text-positive",
        )}
      >
        {formatSignedMoney(cents)}
      </p>
    </Card>
  );
}

function MonthSwitcher({ month }: { month: string }) {
  const navigate = useNavigate();
  const go = (next: string) => void navigate({ to: "/", search: { month: next } });
  return (
    <div className="flex items-center gap-1">
      <Button
        variant="secondary"
        size="icon"
        onClick={() => go(addMonths(month, -1))}
        aria-label="Vorheriger Monat"
      >
        <ChevronLeft aria-hidden />
      </Button>
      <p className="min-w-36 text-center text-sm font-medium" aria-live="polite">
        {monthLabel(month)}
      </p>
      <Button
        variant="secondary"
        size="icon"
        onClick={() => go(addMonths(month, 1))}
        aria-label="Nächster Monat"
      >
        <ChevronRight aria-hidden />
      </Button>
    </div>
  );
}

function AccountsCard({ data }: { data: Dashboard }) {
  return (
    <Card>
      <div className="flex items-baseline justify-between gap-2">
        <CardTitle>Konten</CardTitle>
        <Link to="/accounts" className="text-sm text-primary hover:underline">
          Alle Konten
        </Link>
      </div>
      <ul className="mt-3 divide-y divide-border">
        {data.accounts.map((account) => {
          const Icon = ACCOUNT_KIND_ICON[account.kind as AccountKind];
          return (
            <li key={account.id}>
              <Link
                to="/accounts/$accountId"
                params={{ accountId: account.id }}
                className="flex items-center gap-3 py-2.5 hover:text-primary"
              >
                <Icon className="size-4 shrink-0 text-text-muted" aria-hidden />
                <span className="min-w-0 flex-1 truncate text-sm">{account.name}</span>
                <span className="text-sm tabular-nums">{formatMoney(account.balance_cents)}</span>
              </Link>
            </li>
          );
        })}
      </ul>
      <div className="mt-2 flex items-center justify-between border-t border-border pt-3">
        <span className="text-sm font-medium">Gesamtvermögen</span>
        <span className="text-base font-semibold tabular-nums">{formatMoney(data.net_worth_cents)}</span>
      </div>
    </Card>
  );
}

function TopCategories({ data }: { data: Dashboard }) {
  const max = Math.max(1, ...data.top_categories.map((c) => Math.abs(c.amount_cents)));
  return (
    <Card>
      <CardTitle>Größte Ausgaben</CardTitle>
      {data.top_categories.length === 0 ? (
        <CardDescription>In diesem Monat gibt es keine Ausgaben.</CardDescription>
      ) : (
        <ul className="mt-3 space-y-3">
          {data.top_categories.map((category) => {
            const amount = Math.abs(category.amount_cents);
            const color = categoryColor(category.color);
            return (
              <li key={category.category_id ?? "none"} className="flex items-center gap-3">
                <CategoryIconTile category={category.category_id ? category : null} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2 text-sm">
                    <span className="truncate">{category.name ?? "Ohne Kategorie"}</span>
                    <span className="tabular-nums">{formatMoney(-amount)}</span>
                  </div>
                  <div className="mt-1 h-2 rounded-full bg-surface-muted">
                    <div
                      className="h-2 rounded-full"
                      style={{ width: `${Math.max(2, (amount / max) * 100)}%`, backgroundColor: color }}
                    />
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function TrendChart({ data }: { data: Dashboard }) {
  const points = data.trend.map((point) => ({
    key: point.month,
    label: shortMonthLabel(point.month),
    Einnahmen: point.income_cents / 100,
    Ausgaben: point.expense_cents / 100,
  }));
  const euro = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });
  return (
    <Card>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <CardTitle>Die letzten 12 Monate</CardTitle>
        <div className="flex gap-4 text-xs text-text-muted">
          <span className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-sm bg-positive" aria-hidden />
            Einnahmen
          </span>
          <span className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-sm bg-primary" aria-hidden />
            Ausgaben
          </span>
        </div>
      </div>
      <div
        className="mt-3 h-64"
        role="img"
        aria-label="Balkendiagramm: Einnahmen und Ausgaben der letzten 12 Monate"
      >
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={points} margin={{ top: 4, right: 4, left: 0, bottom: 0 }} barGap={2}>
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
              width={48}
              tick={{ fill: "var(--text-muted)", fontSize: 12 }}
              tickFormatter={(value: number) => euro.format(value)}
            />
            <Tooltip
              cursor={{ fill: "var(--surface-muted)" }}
              labelFormatter={(_, payload) => {
                const key = payload?.[0]?.payload?.key;
                return typeof key === "string" ? monthLabel(key) : "";
              }}
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
            <Bar dataKey="Einnahmen" fill="var(--positive)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
            <Bar dataKey="Ausgaben" fill="var(--primary)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

export function DashboardPage({ month }: Props) {
  const { data: me } = useSuspenseQuery(meQuery);
  const { data } = useSuspenseQuery(dashboardQuery(month));
  if (!me) return null;
  const unprotected = !me.has_totp && me.passkey_count === 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Übersicht</h1>
        <MonthSwitcher month={month} />
      </div>

      {unprotected && (
        <Alert tone="error">
          Dein Konto ist nur mit einem Passwort geschützt.{" "}
          <Link to="/security" className="font-medium underline">
            Passkey oder TOTP einrichten
          </Link>
        </Alert>
      )}

      {data.accounts.length === 0 ? (
        <Card className="flex flex-col items-center gap-3 py-10 text-center">
          <Landmark className="size-8 text-text-muted" aria-hidden />
          <CardTitle>Noch keine Konten</CardTitle>
          <CardDescription>Lege zuerst ein Konto an, dann erscheinen hier deine Zahlen.</CardDescription>
          <Button asChild>
            <Link to="/accounts">Zu den Konten</Link>
          </Button>
        </Card>
      ) : (
        <>
          {data.uncategorized_count > 0 && (
            <Link
              to="/transactions"
              search={{ period: "all", uncategorized: true }}
              className="flex items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3 text-sm hover:bg-surface-muted"
            >
              <Tag className="size-4 text-accent" aria-hidden />
              <span className="flex-1">
                <span className="font-medium">{data.uncategorized_count} Buchungen ohne Kategorie</span>
                <span className="text-text-muted"> · jetzt zuordnen</span>
              </span>
              <ChevronRight className="size-4 text-text-muted" aria-hidden />
            </Link>
          )}

          <div className="grid gap-3 sm:grid-cols-3">
            <Kpi label="Einnahmen" cents={data.income_cents} tone="positive" />
            <Kpi label="Ausgaben" cents={-data.expense_cents} />
            <Kpi label="Saldo" cents={data.net_cents} tone="positive" />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <AccountsCard data={data} />
            <TopCategories data={data} />
          </div>
          <TrendChart data={data} />
        </>
      )}
    </div>
  );
}
