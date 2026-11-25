import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { ArrowLeft, Landmark, Plus, Upload } from "lucide-react";
import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { bankConnectionsQuery } from "@/api/bank-queries";
import type { Account } from "@/api/client";
import { accountsQuery, balanceHistoryQuery } from "@/api/queries";
import { AccountActions } from "@/components/account-actions";
import { AccountDialog } from "@/components/account-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { ACCOUNT_KIND_ICON, ACCOUNT_KIND_LABEL, formatIban, VISIBILITY_LABEL } from "@/lib/accounts";
import { monthLabel, shortMonthLabel } from "@/lib/dates";
import { formatDate } from "@/lib/format";
import { formatMoney } from "@/lib/money";
import { formatRelativeTime } from "@/lib/relative-time";

function VisibilityBadge({ account }: { account: Account }) {
  return <Badge>{VISIBILITY_LABEL[account.visibility]}</Badge>;
}

function AccountRow({ account, lastSyncAt }: { account: Account; lastSyncAt?: string | null }) {
  const Icon = ACCOUNT_KIND_ICON[account.kind];
  return (
    <li className={`flex items-center gap-2 px-3 py-3 sm:px-4 ${account.is_archived ? "opacity-70" : ""}`}>
      <Link
        to="/accounts/$accountId"
        params={{ accountId: account.id }}
        className="flex min-w-0 flex-1 items-center gap-3"
      >
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-surface-muted text-text-muted">
          <Icon className="size-5" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="truncate text-sm font-medium">{account.name}</span>
            <VisibilityBadge account={account} />
            {account.is_archived && <Badge>Archiviert</Badge>}
            {account.bank_linked && <Badge>Bankabruf</Badge>}
          </span>
          <span className="block truncate text-xs text-text-muted">
            {ACCOUNT_KIND_LABEL[account.kind]}
            {account.iban ? ` · ${formatIban(account.iban)}` : ""}
            {account.bank_linked && lastSyncAt ? ` · Abruf ${formatRelativeTime(lastSyncAt)}` : ""}
          </span>
        </span>
        <span className="text-right text-sm font-medium tabular-nums">
          {formatMoney(account.balance_cents, account.currency)}
        </span>
      </Link>
      {!account.is_archived && (
        <Button asChild variant="ghost" size="icon" title="Importieren">
          <Link to="/import" search={{ account: account.id }} aria-label={`Importieren in ${account.name}`}>
            <Upload aria-hidden />
          </Link>
        </Button>
      )}
      <AccountActions account={account} />
    </li>
  );
}

export function AccountsPage() {
  const { data: accounts } = useSuspenseQuery(accountsQuery);
  const [creating, setCreating] = useState(false);
  const { data: bank } = useQuery(bankConnectionsQuery);
  // Connections are private to their creator, so the last sync is only known for own links.
  const lastSyncAt = new Map(
    (bank?.configured ? bank.connections : []).flatMap((c) =>
      c.accounts.map((a) => [a.account_id, c.last_sync_at] as const),
    ),
  );
  const active = accounts.filter((a) => !a.is_archived);
  const archived = accounts.filter((a) => a.is_archived);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Konten</h1>
        <Button onClick={() => setCreating(true)}>
          <Plus aria-hidden /> Konto anlegen
        </Button>
      </div>

      {accounts.length === 0 ? (
        <Card className="flex flex-col items-center gap-3 py-10 text-center">
          <Landmark className="size-8 text-text-muted" aria-hidden />
          <CardTitle>Noch keine Konten</CardTitle>
          <CardDescription>
            Lege dein erstes Konto an, um Buchungen zu erfassen oder zu importieren.
          </CardDescription>
        </Card>
      ) : (
        <ul className="divide-y divide-border rounded-xl border border-border bg-surface">
          {[...active, ...archived].map((account) => (
            <AccountRow key={account.id} account={account} lastSyncAt={lastSyncAt.get(account.id)} />
          ))}
        </ul>
      )}

      <AccountDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}

function BalanceChart({ accountId, currency }: { accountId: string; currency: string }) {
  const { data = [] } = useQuery(balanceHistoryQuery(accountId));
  const points = data.map((p) => ({
    key: p.month,
    label: shortMonthLabel(p.month),
    Saldo: p.balance_cents / 100,
  }));
  const euro = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });
  return (
    <Card>
      <CardTitle>Kontostand der letzten 12 Monate</CardTitle>
      <div className="mt-3 h-64" role="img" aria-label="Liniendiagramm des Kontostands am Monatsende">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
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
              width={56}
              tick={{ fill: "var(--text-muted)", fontSize: 12 }}
              tickFormatter={(v: number) => euro.format(v)}
            />
            <Tooltip
              labelFormatter={(_, payload) => {
                const key = payload?.[0]?.payload?.key;
                return typeof key === "string" ? `Ende ${monthLabel(key)}` : "";
              }}
              formatter={(value) => formatMoney(Math.round(Number(value) * 100), currency)}
              contentStyle={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                color: "var(--text)",
              }}
              labelStyle={{ color: "var(--text)", fontWeight: 600 }}
              itemStyle={{ color: "var(--text)" }}
            />
            <Line
              type="monotone"
              dataKey="Saldo"
              stroke="var(--primary)"
              strokeWidth={2}
              dot={{ r: 3 }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

export function AccountDetailPage({ accountId }: { accountId: string }) {
  const { data: accounts } = useSuspenseQuery(accountsQuery);
  const navigate = useNavigate();
  const account = accounts.find((a) => a.id === accountId);

  if (!account) {
    return (
      <div className="space-y-4">
        <Link to="/accounts" className="inline-flex items-center gap-1 text-sm text-primary">
          <ArrowLeft className="size-4" aria-hidden /> Alle Konten
        </Link>
        <Card>
          <CardTitle>Konto nicht gefunden</CardTitle>
          <CardDescription>Es wurde gelöscht oder ist für dich nicht sichtbar.</CardDescription>
        </Card>
      </div>
    );
  }

  const Icon = ACCOUNT_KIND_ICON[account.kind];
  return (
    <div className="space-y-4">
      <Link to="/accounts" className="inline-flex items-center gap-1 text-sm text-primary">
        <ArrowLeft className="size-4" aria-hidden /> Alle Konten
      </Link>

      <Card className="flex flex-wrap items-start gap-4">
        <span className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-surface-muted text-text-muted">
          <Icon className="size-6" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold">{account.name}</h1>
            <VisibilityBadge account={account} />
            {account.is_archived && <Badge>Archiviert</Badge>}
          </div>
          <p className="text-sm text-text-muted">
            {ACCOUNT_KIND_LABEL[account.kind]}
            {account.iban ? ` · ${formatIban(account.iban)}` : ""}
          </p>
          <p className="mt-2 text-2xl font-semibold tabular-nums">
            {formatMoney(account.balance_cents, account.currency)}
          </p>
        </div>
        <AccountActions account={account} onDeleted={() => void navigate({ to: "/accounts" })} />
      </Card>

      <Card>
        <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-text-muted">Buchungen</dt>
            <dd className="font-medium tabular-nums">{account.transaction_count}</dd>
          </div>
          <div>
            <dt className="text-text-muted">Letzte Buchung</dt>
            <dd className="font-medium">
              {account.last_booking_date ? formatDate(account.last_booking_date) : "keine"}
            </dd>
          </div>
          <div>
            <dt className="text-text-muted">Anfangssaldo</dt>
            <dd className="font-medium tabular-nums">
              {formatMoney(account.opening_balance_cents, account.currency)}
            </dd>
          </div>
        </dl>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button asChild variant="secondary">
            <Link to="/transactions" search={{ account: account.id, period: "all" }}>
              Buchungen anzeigen
            </Link>
          </Button>
          {!account.is_archived && (
            <Button asChild variant="secondary">
              <Link to="/import" search={{ account: account.id }}>
                <Upload aria-hidden /> Importieren
              </Link>
            </Button>
          )}
        </div>
      </Card>

      <BalanceChart accountId={account.id} currency={account.currency} />
    </div>
  );
}
