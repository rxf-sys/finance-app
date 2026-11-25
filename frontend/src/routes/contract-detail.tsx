import { useMutation, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { ArrowLeft, Ban, FileText, RotateCcw, Trash2, X } from "lucide-react";
import { useState } from "react";
import { api, mutationErrorMessage, unwrap } from "@/api/client";
import { contractQuery, invalidateContracts } from "@/api/planning-queries";
import { Amount } from "@/components/amount";
import { CancellationLetterDialog } from "@/components/cancellation-letter-dialog";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { DeadlineBadge, PriceChangeBadge } from "@/components/contract-badges";
import { ContractForm } from "@/components/contract-form";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import {
  CONTRACT_INTERVAL_LABEL,
  CONTRACT_STATUS_LABEL,
  canDelete,
  canDo,
  formatNotice,
  kindIcon,
  kindLabel,
} from "@/lib/contracts";
import { formatDate } from "@/lib/format";
import { formatMoney } from "@/lib/money";
import { useContractAction } from "@/lib/use-contract-action";

export function ContractDetailPage({ contractId }: { contractId: string }) {
  const { data: contract } = useSuspenseQuery(contractQuery(contractId));
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const [letterOpen, setLetterOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const action = useContractAction();

  const remove = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.DELETE("/api/contracts/{contract_id}", { params: { path: { contract_id: contractId } } }),
      ),
    onSuccess: async () => {
      await navigate({ to: "/contracts" });
      queryClient.removeQueries({ queryKey: ["contracts", "detail", contractId] });
      await invalidateContracts(queryClient);
      toast.show("Vertrag gelöscht.");
    },
  });

  const Icon = kindIcon(contract.kind);
  const run = (a: "cancel" | "ignore" | "reactivate" | "confirm") =>
    action.mutate({ id: contract.id, action: a });
  const deleteError = mutationErrorMessage(remove.error, {
    409: "Nur manuelle oder ignorierte Verträge können gelöscht werden.",
  });

  return (
    <div className="space-y-4">
      <Link
        to="/contracts"
        className="inline-flex items-center gap-1 text-sm text-text-muted hover:text-text"
      >
        <ArrowLeft className="size-4" aria-hidden />
        Alle Verträge
      </Link>

      <Card>
        <div className="flex items-start gap-3">
          <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-surface-muted text-text-muted">
            <Icon className="size-5" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-2xl font-semibold">{contract.name}</h1>
            <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-text-muted">
              <Badge>{CONTRACT_STATUS_LABEL[contract.status]}</Badge>
              {kindLabel(contract.kind)} · {CONTRACT_INTERVAL_LABEL[contract.interval]}
              {contract.is_manual && <Badge>Manuell angelegt</Badge>}
            </p>
          </div>
          <Amount cents={contract.expected_amount_cents} className="text-xl font-semibold" />
        </div>
        <dl className="mt-4 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-text-muted">Pro Monat</dt>
            <dd className="tabular-nums">{formatMoney(contract.monthly_amount_cents)}</dd>
          </div>
          <div>
            <dt className="text-text-muted">Nächste Abbuchung</dt>
            <dd>{contract.next_due_date ? formatDate(contract.next_due_date) : "unbekannt"}</dd>
          </div>
          <div>
            <dt className="text-text-muted">Kündigungsfrist</dt>
            <dd>
              {contract.notice_period_days != null
                ? formatNotice(contract.notice_period_days)
                : "nicht erfasst"}
            </dd>
          </div>
        </dl>
        {(contract.cancellation_deadline || contract.unacknowledged_price_change) && (
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <DeadlineBadge contract={contract} />
            <PriceChangeBadge contract={contract} />
          </div>
        )}
        {contract.status === "detected" && (
          <Alert className="mt-4">
            Das ist ein Vorschlag der App. Bestätige ihn, damit er zu den Fixkosten zählt.
          </Alert>
        )}

        <div className="mt-5 flex flex-wrap gap-2 border-t border-border pt-4">
          <Button
            disabled={!canDo("confirm", contract.status) || action.isPending}
            onClick={() => run("confirm")}
          >
            Bestätigen
          </Button>
          <Button
            variant="secondary"
            disabled={!canDo("cancel", contract.status) || action.isPending}
            onClick={() => run("cancel")}
          >
            <Ban aria-hidden />
            Als gekündigt markieren
          </Button>
          <Button
            variant="secondary"
            disabled={!canDo("ignore", contract.status) || action.isPending}
            onClick={() => run("ignore")}
          >
            <X aria-hidden />
            Ignorieren
          </Button>
          <Button
            variant="secondary"
            disabled={!canDo("reactivate", contract.status) || action.isPending}
            onClick={() => run("reactivate")}
          >
            <RotateCcw aria-hidden />
            Wieder aktivieren
          </Button>
          <Button variant="secondary" onClick={() => setLetterOpen(true)}>
            <FileText aria-hidden />
            Kündigungsschreiben
          </Button>
          <Button
            variant="danger"
            className="sm:ml-auto"
            disabled={!canDelete(contract)}
            title={
              canDelete(contract)
                ? undefined
                : "Nur manuelle oder ignorierte Verträge können gelöscht werden."
            }
            onClick={() => setDeleteOpen(true)}
          >
            <Trash2 aria-hidden />
            Löschen
          </Button>
        </div>
      </Card>

      <Card>
        <CardTitle>Angaben bearbeiten</CardTitle>
        <div className="mt-4">
          <ContractForm
            key={`${contract.id}-${contract.expected_amount_cents}`}
            contract={contract}
            onSaved={() => toast.show("Gespeichert.")}
          />
        </div>
      </Card>

      <Card className="p-0">
        <div className="px-5 pt-5">
          <CardTitle>Zahlungen</CardTitle>
          <CardDescription>Die letzten zugeordneten Buchungen.</CardDescription>
        </div>
        {contract.transactions.length === 0 ? (
          <p className="px-5 py-4 text-sm text-text-muted">Noch keine Buchungen zugeordnet.</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-text-muted">
                <tr className="border-y border-border">
                  <th className="px-5 py-2 font-medium">Datum</th>
                  <th className="px-2 py-2 font-medium">Empfänger</th>
                  <th className="hidden px-2 py-2 font-medium sm:table-cell">Verwendungszweck</th>
                  <th className="px-5 py-2 text-right font-medium">Betrag</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {contract.transactions.map((tx) => (
                  <tr key={tx.id}>
                    <td className="px-5 py-2 whitespace-nowrap">{formatDate(tx.booking_date)}</td>
                    <td className="max-w-40 truncate px-2 py-2">{tx.counterparty_name ?? "–"}</td>
                    <td className="hidden max-w-64 truncate px-2 py-2 text-text-muted sm:table-cell">
                      {tx.purpose ?? "–"}
                    </td>
                    <td className="px-5 py-2 text-right">
                      <Amount cents={tx.amount_cents} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card>
        <CardTitle>Preisverlauf</CardTitle>
        {contract.price_changes.length === 0 ? (
          <CardDescription>Bisher keine Preisänderung erkannt.</CardDescription>
        ) : (
          <ul className="mt-3 divide-y divide-border">
            {contract.price_changes.map((change) => (
              <li key={change.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <span>{formatDate(change.effective_date)}</span>
                <span className="tabular-nums">
                  {formatMoney(Math.abs(change.old_amount_cents))} →{" "}
                  {formatMoney(Math.abs(change.new_amount_cents))}
                </span>
                <span className="text-xs text-text-muted">
                  {change.acknowledged_at ? "zur Kenntnis genommen" : "neu"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <CancellationLetterDialog contractId={contract.id} open={letterOpen} onOpenChange={setLetterOpen} />
      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title="Vertrag löschen?"
        confirmLabel="Löschen"
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      >
        <p>„{contract.name}“ wird endgültig gelöscht. Die zugeordneten Buchungen bleiben erhalten.</p>
        {deleteError && <p className="mt-2 text-negative">{deleteError}</p>}
      </ConfirmDialog>
    </div>
  );
}
