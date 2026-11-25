import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { api, mutationErrorMessage, unwrap } from "@/api/client";
import { accountsQuery, invalidateLedger } from "@/api/queries";
import { CategoryPicker } from "@/components/category-picker";
import { FormField } from "@/components/form-field";
import { MoneyInput } from "@/components/money-input";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { toIsoDate } from "@/lib/dates";
import { parseMoneyInput } from "@/lib/money";
import { cn } from "@/lib/utils";

type Props = { open: boolean; onOpenChange: (open: boolean) => void; defaultAccountId?: string };

function ManualForm({ defaultAccountId, onDone }: { defaultAccountId?: string; onDone: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: accounts = [] } = useQuery(accountsQuery);
  const active = accounts.filter((a) => !a.is_archived);
  const [accountId, setAccountId] = useState(
    active.find((a) => a.id === defaultAccountId)?.id ??
      active.find((a) => a.kind === "cash")?.id ??
      active[0]?.id ??
      "",
  );
  const [date, setDate] = useState(toIsoDate(new Date()));
  const [direction, setDirection] = useState<"out" | "in">("out");
  const [amount, setAmount] = useState("");
  const [counterparty, setCounterparty] = useState("");
  const [purpose, setPurpose] = useState("");
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [note, setNote] = useState("");

  const cents = parseMoneyInput(amount);
  const valid = Boolean(accountId) && Boolean(date) && cents !== null && cents !== 0;

  const create = useMutation({
    mutationFn: async () => {
      const magnitude = Math.abs(cents ?? 0);
      return unwrap(
        await api.POST("/api/transactions", {
          body: {
            account_id: accountId,
            booking_date: date,
            amount_cents: direction === "out" ? -magnitude : magnitude,
            counterparty_name: counterparty.trim() || null,
            purpose: purpose.trim() || null,
            note: note.trim() || null,
            category_id: categoryId,
          },
        }),
      );
    },
    onSuccess: async () => {
      await invalidateLedger(queryClient);
      toast.show("Buchung gespeichert.");
      onDone();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (valid) create.mutate();
  }

  return (
    <form onSubmit={submit} className="mt-4 space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="manual-account">Konto</Label>
        <Select
          id="manual-account"
          value={accountId || "none"}
          onValueChange={setAccountId}
          options={
            active.length > 0
              ? active.map((a) => ({ value: a.id, label: a.name }))
              : [{ value: "none", label: "Kein Konto" }]
          }
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <FormField
          label="Datum"
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          required
        />
        <fieldset className="space-y-1.5">
          <legend className="text-sm font-medium">Art</legend>
          <div className="grid h-10 grid-cols-2 gap-1 rounded-lg border border-border p-1">
            {(
              [
                ["out", "Ausgabe"],
                ["in", "Einnahme"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={direction === value}
                onClick={() => setDirection(value)}
                className={cn(
                  "rounded-md text-sm",
                  direction === value
                    ? "bg-primary font-medium text-on-primary"
                    : "text-text-muted hover:bg-surface-muted",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </fieldset>
      </div>
      <MoneyInput label="Betrag" value={amount} onChange={setAmount} required />
      <FormField
        label="Gegenpartei"
        value={counterparty}
        onChange={(e) => setCounterparty(e.target.value)}
        maxLength={200}
      />
      <FormField
        label="Verwendungszweck"
        value={purpose}
        onChange={(e) => setPurpose(e.target.value)}
        maxLength={2000}
      />
      <div className="space-y-1.5">
        <Label htmlFor="manual-category">Kategorie</Label>
        <CategoryPicker
          id="manual-category"
          value={categoryId}
          onChange={setCategoryId}
          clearLabel="Keine Kategorie"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="manual-note">Notiz</Label>
        <Textarea id="manual-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
      </div>
      {create.error && <Alert tone="error">{mutationErrorMessage(create.error)}</Alert>}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onDone}>
          Abbrechen
        </Button>
        <Button type="submit" disabled={!valid || create.isPending}>
          Buchung speichern
        </Button>
      </div>
    </form>
  );
}

export function ManualTransactionDialog({ open, onOpenChange, defaultAccountId }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>Buchung erfassen</DialogTitle>
        <DialogDescription>Zum Beispiel für eine Barzahlung.</DialogDescription>
        {open && <ManualForm defaultAccountId={defaultAccountId} onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  );
}
