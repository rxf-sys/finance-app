import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useState } from "react";
import {
  api,
  type Contract,
  type ContractInterval,
  type ContractKind,
  mutationErrorMessage,
  unwrap,
} from "@/api/client";
import { invalidateContracts } from "@/api/planning-queries";
import { accountsQuery } from "@/api/queries";
import { CategoryPicker } from "@/components/category-picker";
import { FormField } from "@/components/form-field";
import { MoneyInput } from "@/components/money-input";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  CONTRACT_INTERVAL_LABEL,
  CONTRACT_KIND_LABEL,
  type NoticeUnit,
  noticeFromDays,
  noticeToDays,
} from "@/lib/contracts";
import { formatMoneyInput, parseMoneyInput } from "@/lib/money";

const KIND_OPTIONS = (Object.keys(CONTRACT_KIND_LABEL) as ContractKind[]).map((value) => ({
  value,
  label: CONTRACT_KIND_LABEL[value],
}));
const INTERVAL_OPTIONS = (Object.keys(CONTRACT_INTERVAL_LABEL) as ContractInterval[]).map((value) => ({
  value,
  label: CONTRACT_INTERVAL_LABEL[value],
}));
const DIRECTION_OPTIONS = [
  { value: "expense", label: "Ausgabe (Zahlung)" },
  { value: "income", label: "Einnahme" },
];
const UNIT_OPTIONS = [
  { value: "days", label: "Tage" },
  { value: "months", label: "Monate" },
];
const NO_ACCOUNT = "none";

type Props = {
  /** Edit this contract; without it the form creates a manual one. */
  contract?: Contract;
  onSaved?: (contract: Contract) => void;
  onCancel?: () => void;
};

export function ContractForm({ contract, onSaved, onCancel }: Props) {
  const queryClient = useQueryClient();
  const { data: accounts = [] } = useQuery(accountsQuery);
  const notice = contract?.notice_period_days != null ? noticeFromDays(contract.notice_period_days) : null;

  const [name, setName] = useState(contract?.name ?? "");
  const [kind, setKind] = useState<ContractKind>(contract?.kind ?? "subscription");
  const [interval, setInterval] = useState<ContractInterval>(contract?.interval ?? "monthly");
  const [direction, setDirection] = useState(
    contract && contract.expected_amount_cents > 0 ? "income" : "expense",
  );
  const [amount, setAmount] = useState(
    contract ? formatMoneyInput(Math.abs(contract.expected_amount_cents)) : "",
  );
  const [tolerance, setTolerance] = useState(String(contract?.amount_tolerance_pct ?? 10));
  const [accountId, setAccountId] = useState(contract?.account_id ?? NO_ACCOUNT);
  const [categoryId, setCategoryId] = useState<string | null>(contract?.category_id ?? null);
  const [startDate, setStartDate] = useState(contract?.start_date ?? "");
  const [minTermEnd, setMinTermEnd] = useState(contract?.min_term_end ?? "");
  const [noticeValue, setNoticeValue] = useState(notice ? String(notice.value) : "");
  const [noticeUnit, setNoticeUnit] = useState<NoticeUnit>(notice?.unit ?? "months");
  const [customerNumber, setCustomerNumber] = useState(contract?.customer_number ?? "");
  const [note, setNote] = useState(contract?.note ?? "");
  const [nextDue, setNextDue] = useState(contract?.next_due_date ?? "");
  const [counterparty, setCounterparty] = useState("");
  const ids = { account: useId(), category: useId(), kind: useId(), interval: useId(), direction: useId() };

  const cents = parseMoneyInput(amount);
  const toleranceValue = Number(tolerance);
  const toleranceValid = Number.isInteger(toleranceValue) && toleranceValue >= 0 && toleranceValue <= 100;
  const noticeNumber = noticeValue.trim() === "" ? null : Number(noticeValue);
  const noticeValid = noticeNumber === null || (Number.isInteger(noticeNumber) && noticeNumber >= 0);
  const noticeDays = noticeNumber === null || !noticeValid ? null : noticeToDays(noticeNumber, noticeUnit);
  const noticeTooLong = noticeDays !== null && noticeDays > 3650;
  const valid =
    name.trim() !== "" && cents !== null && cents > 0 && toleranceValid && noticeValid && !noticeTooLong;

  const save = useMutation({
    mutationFn: async () => {
      const signed = (direction === "income" ? 1 : -1) * (cents ?? 0);
      const common = {
        name: name.trim(),
        kind,
        interval,
        expected_amount_cents: signed,
        amount_tolerance_pct: toleranceValue,
        category_id: categoryId,
        start_date: startDate || null,
        min_term_end: minTermEnd || null,
        notice_period_days: noticeDays,
        customer_number: customerNumber.trim() || null,
        note: note.trim() || null,
      };
      const account = accountId === NO_ACCOUNT ? null : accountId;
      if (contract) {
        return unwrap(
          await api.PATCH("/api/contracts/{contract_id}", {
            params: { path: { contract_id: contract.id } },
            body: { ...common, account_id: account },
          }),
        );
      }
      return unwrap(
        await api.POST("/api/contracts", {
          body: {
            ...common,
            account_id: account,
            next_due_date: nextDue || null,
            counterparty_name: counterparty.trim() || null,
          },
        }),
      );
    },
    onSuccess: async (saved) => {
      await invalidateContracts(queryClient);
      onSaved?.(saved);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (valid) save.mutate();
  }

  const error = mutationErrorMessage(save.error, {
    422: "Bitte Betrag, Fristen und Verknüpfungen prüfen.",
    404: "Konto oder Kategorie wurde nicht gefunden.",
  });
  const accountOptions = [
    { value: NO_ACCOUNT, label: "Alle Konten" },
    ...accounts
      .filter((a) => !a.is_archived || a.id === contract?.account_id)
      .map((a) => ({ value: a.id, label: a.name })),
  ];

  return (
    <form onSubmit={submit} className="space-y-4">
      <FormField
        label="Name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        maxLength={100}
        required
      />
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor={ids.kind}>Art</Label>
          <Select
            id={ids.kind}
            value={kind}
            onValueChange={(v) => setKind(v as ContractKind)}
            options={KIND_OPTIONS}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={ids.interval}>Intervall</Label>
          <Select
            id={ids.interval}
            value={interval}
            onValueChange={(v) => setInterval(v as ContractInterval)}
            options={INTERVAL_OPTIONS}
          />
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="space-y-1.5">
          <Label htmlFor={ids.direction}>Richtung</Label>
          <Select
            id={ids.direction}
            value={direction}
            onValueChange={setDirection}
            options={DIRECTION_OPTIONS}
          />
        </div>
        <MoneyInput label="Betrag pro Zahlung" value={amount} onChange={setAmount} required />
        <FormField
          label="Toleranz in %"
          type="number"
          inputMode="numeric"
          min={0}
          max={100}
          value={tolerance}
          onChange={(e) => setTolerance(e.target.value)}
          hint="Abweichung, bis zu der Buchungen zugeordnet werden."
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor={ids.account}>Konto</Label>
          <Select id={ids.account} value={accountId} onValueChange={setAccountId} options={accountOptions} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={ids.category}>Kategorie</Label>
          <CategoryPicker
            id={ids.category}
            value={categoryId}
            onChange={setCategoryId}
            clearLabel="Ohne Kategorie"
            placeholder="Ohne Kategorie"
          />
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <FormField
          label="Vertragsbeginn"
          type="date"
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
        />
        <FormField
          label="Mindestlaufzeit bis"
          type="date"
          value={minTermEnd}
          onChange={(e) => setMinTermEnd(e.target.value)}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="notice-value">Kündigungsfrist</Label>
        <div className="grid grid-cols-2 gap-3">
          <input
            id="notice-value"
            type="number"
            inputMode="numeric"
            min={0}
            placeholder="z. B. 3"
            value={noticeValue}
            onChange={(e) => setNoticeValue(e.target.value)}
            aria-invalid={!noticeValid || noticeTooLong}
            className="h-10 w-full rounded-lg border border-border bg-surface-muted px-3 text-sm text-text placeholder:text-text-muted focus:border-primary focus:outline-none"
          />
          <Select
            aria-label="Einheit der Kündigungsfrist"
            value={noticeUnit}
            onValueChange={(v) => setNoticeUnit(v as NoticeUnit)}
            options={UNIT_OPTIONS}
          />
        </div>
        <p className="text-xs text-text-muted">
          Ein Monat zählt als 30 Tage. Aus Mindestlaufzeit und Frist berechnet die App das späteste
          Kündigungsdatum.
        </p>
        {noticeTooLong && <p className="text-xs text-negative">Maximal 3650 Tage (10 Jahre).</p>}
      </div>
      <FormField
        label="Kundennummer"
        value={customerNumber}
        onChange={(e) => setCustomerNumber(e.target.value)}
        maxLength={100}
        autoComplete="off"
      />
      {!contract && (
        <>
          <FormField
            label="Zahlungsempfänger (optional)"
            value={counterparty}
            onChange={(e) => setCounterparty(e.target.value)}
            maxLength={100}
            hint="Damit ordnet die App spätere Buchungen diesem Vertrag zu."
          />
          <FormField
            label="Nächste Abbuchung (optional)"
            type="date"
            value={nextDue}
            onChange={(e) => setNextDue(e.target.value)}
          />
        </>
      )}
      <div className="space-y-1.5">
        <Label htmlFor="contract-note">Notiz</Label>
        <Textarea
          id="contract-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={2000}
        />
      </div>
      {error && <Alert tone="error">{error}</Alert>}
      <div className="flex justify-end gap-2">
        {onCancel && (
          <Button type="button" variant="secondary" onClick={onCancel}>
            Abbrechen
          </Button>
        )}
        <Button type="submit" disabled={save.isPending || !valid}>
          {contract ? "Speichern" : "Vertrag anlegen"}
        </Button>
      </div>
    </form>
  );
}

export function NewContractDialog({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved?: (contract: Contract) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogTitle>Neuer Vertrag</DialogTitle>
        <DialogDescription>
          Für Verträge, die die App nicht von selbst erkennt. Er zählt sofort zu den Fixkosten.
        </DialogDescription>
        <div className="mt-4">
          {open && (
            <ContractForm
              onCancel={() => onOpenChange(false)}
              onSaved={(saved) => {
                onOpenChange(false);
                onSaved?.(saved);
              }}
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
