import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, Ellipsis, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { type Account, api, mutationErrorMessage, unwrap } from "@/api/client";
import { invalidateLedger } from "@/api/queries";
import { AccountDialog } from "@/components/account-dialog";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useToast } from "@/components/ui/toast";

/** Edit, archive and delete for one account, as a "more" menu with its dialogs. */
export function AccountActions({ account, onDeleted }: { account: Account; onDeleted?: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const archive = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/accounts/{account_id}", {
          params: { path: { account_id: account.id } },
          body: { is_archived: !account.is_archived },
        }),
      ),
    onSuccess: async () => {
      await invalidateLedger(queryClient);
      toast.show(account.is_archived ? "Konto wieder aktiviert." : "Konto archiviert.");
    },
    onError: (error) => toast.show(mutationErrorMessage(error) ?? "", "error"),
  });

  const remove = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.DELETE("/api/accounts/{account_id}", { params: { path: { account_id: account.id } } }),
      ),
    onSuccess: async () => {
      setDeleting(false);
      await invalidateLedger(queryClient);
      toast.show("Konto gelöscht.");
      onDeleted?.();
    },
  });

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label={`Aktionen für ${account.name}`}>
            <Ellipsis aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem onSelect={() => setEditing(true)}>
            <Pencil aria-hidden /> Bearbeiten
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => archive.mutate()}>
            {account.is_archived ? <ArchiveRestore aria-hidden /> : <Archive aria-hidden />}
            {account.is_archived ? "Wieder aktivieren" : "Archivieren"}
          </DropdownMenuItem>
          <DropdownMenuItem danger onSelect={() => setDeleting(true)}>
            <Trash2 aria-hidden /> Löschen
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <AccountDialog open={editing} onOpenChange={setEditing} account={account} />
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={`„${account.name}“ löschen?`}
        confirmLabel="Konto und Buchungen löschen"
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      >
        <p>
          Alle {account.transaction_count} Buchungen dieses Kontos werden mit gelöscht. Das lässt sich nicht
          rückgängig machen. Zum Ausblenden reicht auch Archivieren.
        </p>
        {remove.error && (
          <Alert tone="error" className="mt-3">
            {mutationErrorMessage(remove.error, {
              403: "Nur die Besitzerin oder der Besitzer kann das Konto löschen.",
            })}
          </Alert>
        )}
      </ConfirmDialog>
    </>
  );
}
