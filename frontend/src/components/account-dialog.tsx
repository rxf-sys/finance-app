import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import {
  type Account,
  type AccountKind,
  type AccountVisibility,
  api,
  mutationErrorMessage,
  unwrap,
} from "@/api/client";
import { invalidateLedger } from "@/api/queries";
import { FormField } from "@/components/form-field";
import { MoneyInput } from "@/components/money-input";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { ACCOUNT_KIND_LABEL, VISIBILITY_LABEL } from "@/lib/accounts";
import { formatMoneyInput, parseMoneyInput } from "@/lib/money";

const KIND_OPTIONS = (Object.keys(ACCOUNT_KIND_LABEL) as AccountKind[]).map((value) => ({
  value,
  label: ACCOUNT_KIND_LABEL[value],
}));
const VISIBILITY_OPTIONS = (Object.keys(VISIBILITY_LABEL) as AccountVisibility[]).map((value) => ({
  value,
  label: value === "private" ? "Privat (nur ich)" : "Geteilt (Haushalt)",
}));

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Edit this account; without it the dialog creates one. */
  account?: Account;
  onSaved?: (account: Account) => void;
};

function AccountForm({
  account,
  onDone,
  onSaved,
}: {
  account?: Account;
  onDone: () => void;
  onSaved?: Props["onSaved"];
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(account?.name ?? "");
  const [kind, setKind] = useState<AccountKind>(account?.kind ?? "giro");
  const [iban, setIban] = useState(account?.iban ?? "");
  const [opening, setOpening] = useState(formatMoneyInput(account?.opening_balance_cents ?? 0));
  const [visibility, setVisibility] = useState<AccountVisibility>(account?.visibility ?? "shared");

  const openingCents = parseMoneyInput(opening);

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        name: name.trim(),
        kind,
        visibility,
        iban: iban.trim() || null,
        opening_balance_cents: openingCents ?? 0,
      };
      if (account) {
        return unwrap(
          await api.PATCH("/api/accounts/{account_id}", {
            params: { path: { account_id: account.id } },
            body,
          }),
        );
      }
      return unwrap(await api.POST("/api/accounts", { body }));
    },
    onSuccess: async (saved) => {
      await invalidateLedger(queryClient);
      onSaved?.(saved);
      onDone();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (openingCents === null || !name.trim()) return;
    save.mutate();
  }

  const error = mutationErrorMessage(save.error, {
    409: "Ein Konto mit dieser IBAN gibt es schon.",
    422: "Bitte Name und IBAN prüfen.",
    403: "Nur die Besitzerin oder der Besitzer kann ein Konto privat stellen.",
  });

  return (
    <form onSubmit={submit} className="mt-4 space-y-4">
      <FormField
        label="Name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        maxLength={100}
        required
      />
      <div className="space-y-1.5">
        <Label htmlFor="account-kind">Art</Label>
        <Select
          id="account-kind"
          value={kind}
          onValueChange={(v) => setKind(v as AccountKind)}
          options={KIND_OPTIONS}
        />
      </div>
      <FormField
        label="IBAN (optional)"
        value={iban}
        onChange={(e) => setIban(e.target.value)}
        autoComplete="off"
        placeholder="DE00 0000 0000 0000 0000 00"
      />
      <MoneyInput
        label="Anfangssaldo"
        value={opening}
        onChange={setOpening}
        hint="Kontostand vor der ersten erfassten Buchung."
        required
      />
      <div className="space-y-1.5">
        <Label htmlFor="account-visibility">Sichtbarkeit</Label>
        <Select
          id="account-visibility"
          value={visibility}
          onValueChange={(v) => setVisibility(v as AccountVisibility)}
          options={VISIBILITY_OPTIONS}
        />
      </div>
      {error && <Alert tone="error">{error}</Alert>}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onDone}>
          Abbrechen
        </Button>
        <Button type="submit" disabled={save.isPending || openingCents === null || !name.trim()}>
          {account ? "Speichern" : "Konto anlegen"}
        </Button>
      </div>
    </form>
  );
}

export function AccountDialog({ open, onOpenChange, account, onSaved }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>{account ? "Konto bearbeiten" : "Konto anlegen"}</DialogTitle>
        <DialogDescription>Buchungen kommen später per Import oder von Hand dazu.</DialogDescription>
        {/* Mounted only while open, so the form always starts from the current account. */}
        {open && <AccountForm account={account} onDone={() => onOpenChange(false)} onSaved={onSaved} />}
      </DialogContent>
    </Dialog>
  );
}
