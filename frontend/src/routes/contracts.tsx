import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { Check, FileSearch, Lightbulb, Plus, X } from "lucide-react";
import { useState } from "react";
import { api, type Contract, unwrap } from "@/api/client";
import { contractSummaryQuery, contractsQuery, invalidateContracts } from "@/api/planning-queries";
import { accountsQuery } from "@/api/queries";
import { Amount } from "@/components/amount";
import { DeadlineBadge, PriceChangeBadge } from "@/components/contract-badges";
import { NewContractDialog } from "@/components/contract-form";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import {
  CONTRACT_INTERVAL_LABEL,
  CONTRACT_STATUS_LABEL,
  type ContractSearch,
  kindBreakdown,
  kindIcon,
  LIST_STATUSES,
  type ListStatus,
} from "@/lib/contracts";
import { formatDate } from "@/lib/format";
import { formatMoney } from "@/lib/money";
import { useContractAction } from "@/lib/use-contract-action";
import { cn } from "@/lib/utils";

const ALL_ACCOUNTS = "all";

function SummaryCard() {
  const { data } = useSuspenseQuery(contractSummaryQuery);
  const rows = kindBreakdown(data.by_kind);
  return (
    <Card>
      <p className="text-sm text-text-muted">Fixkosten pro Monat</p>
      <p className="mt-1 text-3xl font-semibold tabular-nums">{formatMoney(-data.monthly_cost_cents)}</p>
      <p className="mt-1 text-xs text-text-muted">
        Summe der bestätigten Verträge, umgerechnet auf einen Monat.
        {data.monthly_income_cents > 0 &&
          ` Dazu regelmäßige Einnahmen von ${formatMoney(data.monthly_income_cents)}.`}
      </p>
      {rows.length > 0 && (
        <ul className="mt-4 grid gap-2 sm:grid-cols-2">
          {rows.map((row) => {
            const Icon = kindIcon(row.kind);
            return (
              <li key={row.kind} className="flex items-center gap-3 rounded-lg bg-surface-muted px-3 py-2">
                <Icon className="size-4 shrink-0 text-text-muted" aria-hidden />
                <span className="min-w-0 flex-1 truncate text-sm">
                  {row.label} <span className="text-text-muted">({row.count})</span>
                </span>
                <span className="text-sm tabular-nums">{formatMoney(-row.costCents)}</span>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function SuggestionRow({ contract }: { contract: Contract }) {
  const action = useContractAction();
  const Icon = kindIcon(contract.kind);
  return (
    <li className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center">
      <div className="flex min-w-0 flex-1 items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-surface-muted text-text-muted">
          <Icon className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{contract.name}</p>
          <p className="text-xs text-text-muted">
            {CONTRACT_INTERVAL_LABEL[contract.interval]} · {contract.payments_count} Zahlungen
            {contract.last_payment_date && ` · zuletzt ${formatDate(contract.last_payment_date)}`}
          </p>
        </div>
        <Amount cents={contract.expected_amount_cents} className="text-sm font-medium" />
      </div>
      <div className="flex gap-2 sm:justify-end">
        <Button
          size="sm"
          disabled={action.isPending}
          onClick={() => action.mutate({ id: contract.id, action: "confirm" })}
        >
          <Check aria-hidden />
          Bestätigen
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={action.isPending}
          onClick={() => action.mutate({ id: contract.id, action: "ignore" })}
        >
          <X aria-hidden />
          Ignorieren
        </Button>
      </div>
    </li>
  );
}

function Suggestions({ accountId }: { accountId?: string }) {
  const { data = [] } = useQuery(contractsQuery({ status: "detected", accountId }));
  if (data.length === 0) return null;
  return (
    <section aria-labelledby="suggestions-title">
      <Card className="p-0">
        <div className="flex items-start gap-3 border-b border-border px-4 py-3">
          <Lightbulb className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
          <div>
            <h2 id="suggestions-title" className="text-base font-semibold">
              Vorschläge
            </h2>
            <p className="text-sm text-text-muted">
              Die App hat diese wiederkehrenden Zahlungen in deinen Buchungen gefunden. Das sind Vermutungen:
              Bestätige, was stimmt, und ignoriere den Rest.
            </p>
          </div>
        </div>
        <ul className="divide-y divide-border">
          {data.map((contract) => (
            <SuggestionRow key={contract.id} contract={contract} />
          ))}
        </ul>
      </Card>
    </section>
  );
}

function ContractRow({ contract }: { contract: Contract }) {
  const Icon = kindIcon(contract.kind);
  return (
    <li>
      <Link
        to="/contracts/$contractId"
        params={{ contractId: contract.id }}
        className="flex flex-col gap-2 px-4 py-3 hover:bg-surface-muted"
      >
        <span className="flex items-center gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-surface-muted text-text-muted">
            <Icon className="size-4" aria-hidden />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{contract.name}</span>
            <span className="block text-xs text-text-muted">
              {CONTRACT_INTERVAL_LABEL[contract.interval]}
              {contract.next_due_date && ` · nächste Abbuchung ${formatDate(contract.next_due_date)}`}
            </span>
          </span>
          <span className="text-right">
            <Amount cents={contract.expected_amount_cents} className="block text-sm font-medium" />
            {contract.interval !== "monthly" && (
              <span className="block text-xs text-text-muted tabular-nums">
                {formatMoney(contract.monthly_amount_cents)} / Monat
              </span>
            )}
          </span>
        </span>
        {contract.cancellation_deadline && (
          <span className="flex flex-wrap items-center gap-2 pl-12">
            <DeadlineBadge contract={contract} />
          </span>
        )}
      </Link>
      {contract.unacknowledged_price_change && (
        <div className="px-4 pb-3 pl-16">
          <PriceChangeBadge contract={contract} />
        </div>
      )}
    </li>
  );
}

export function ContractsPage({ search }: { search: ContractSearch }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const status: ListStatus = search.status ?? "confirmed";
  const account = search.account ?? ALL_ACCOUNTS;
  const [creating, setCreating] = useState(false);
  const [detectResult, setDetectResult] = useState<number | null>(null);
  const accountId = account === ALL_ACCOUNTS ? undefined : account;

  const { data: accounts = [] } = useQuery(accountsQuery);
  const { data: contracts = [], isPending } = useQuery(contractsQuery({ status, accountId }));

  const detect = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/contracts/detect")),
    onSuccess: async (found) => {
      setDetectResult(found.length);
      await invalidateContracts(queryClient);
    },
    onError: () => toast.show("Die Suche hat nicht geklappt. Bitte später erneut versuchen.", "error"),
  });

  function setFilter(patch: ContractSearch) {
    void navigate({
      to: "/contracts",
      search: (previous: ContractSearch) => ({ ...previous, ...patch }),
    });
  }

  const accountOptions = [
    { value: ALL_ACCOUNTS, label: "Alle Konten" },
    ...accounts.map((a) => ({ value: a.id, label: a.name })),
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Verträge</h1>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => detect.mutate()} disabled={detect.isPending}>
            <FileSearch aria-hidden />
            {detect.isPending ? "Suche läuft …" : "Nach Verträgen suchen"}
          </Button>
          <Button onClick={() => setCreating(true)}>
            <Plus aria-hidden />
            Neuer Vertrag
          </Button>
        </div>
      </div>

      {detectResult !== null && (
        <Alert tone="info">
          {detectResult === 0
            ? "Keine neuen Vorschläge gefunden."
            : detectResult === 1
              ? "1 neuer Vorschlag gefunden. Bitte unten prüfen."
              : `${detectResult} neue Vorschläge gefunden. Bitte unten prüfen.`}
        </Alert>
      )}

      <SummaryCard />
      <Suggestions accountId={accountId} />

      <section aria-labelledby="contracts-title" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="contracts-title" className="text-base font-semibold">
            Meine Verträge
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            <fieldset className="m-0 flex min-w-0 rounded-lg border border-border bg-surface p-0.5">
              <legend className="sr-only">Status</legend>
              {LIST_STATUSES.map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={status === value}
                  onClick={() => setFilter({ status: value === "confirmed" ? undefined : value })}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-sm text-text-muted",
                    status === value && "bg-surface-muted font-medium text-text",
                  )}
                >
                  {value === "confirmed" ? "Aktiv" : CONTRACT_STATUS_LABEL[value]}
                </button>
              ))}
            </fieldset>
            <Select
              aria-label="Konto filtern"
              className="h-9 w-44"
              value={account}
              onValueChange={(value) => setFilter({ account: value === ALL_ACCOUNTS ? undefined : value })}
              options={accountOptions}
            />
          </div>
        </div>

        {isPending ? (
          <Card className="text-sm text-text-muted">Lade …</Card>
        ) : contracts.length === 0 ? (
          <Card className="py-8 text-center">
            <CardTitle>Keine Verträge</CardTitle>
            <CardDescription>
              {status === "confirmed"
                ? "Lass die App nach wiederkehrenden Zahlungen suchen oder lege einen Vertrag von Hand an."
                : "Hier ist nichts."}
            </CardDescription>
          </Card>
        ) : (
          <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-surface">
            {contracts.map((contract) => (
              <ContractRow key={contract.id} contract={contract} />
            ))}
          </ul>
        )}
        {status === "ignored" && contracts.length > 0 && (
          <p className="text-xs text-text-muted">
            <Badge>Hinweis</Badge> Ignorierte Vorschläge schlägt die App nicht noch einmal vor.
          </p>
        )}
      </section>

      <NewContractDialog
        open={creating}
        onOpenChange={setCreating}
        onSaved={(saved) => void navigate({ to: "/contracts/$contractId", params: { contractId: saved.id } })}
      />
    </div>
  );
}
