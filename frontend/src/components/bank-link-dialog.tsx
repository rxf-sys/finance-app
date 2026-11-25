import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { type FormEvent, useState } from "react";
import { invalidateBank, providerAccountsQuery } from "@/api/bank-queries";
import { type AccountKind, type AccountVisibility, api, mutationErrorMessage, unwrap } from "@/api/client";
import { accountsQuery, invalidateLedger } from "@/api/queries";
import { FormField } from "@/components/form-field";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { ACCOUNT_KIND_LABEL } from "@/lib/accounts";
import type { BankConnection, ProviderAccount } from "@/lib/bank";
import { toIsoDate } from "@/lib/dates";
import { formatDate } from "@/lib/format";

const KIND_OPTIONS = (Object.keys(ACCOUNT_KIND_LABEL) as AccountKind[]).map((value) => ({
  value,
  label: ACCOUNT_KIND_LABEL[value],
}));
const VISIBILITY_OPTIONS = [
  { value: "shared", label: "Geteilt (Haushalt)" },
  { value: "private", label: "Privat (nur ich)" },
];
const VISIBILITY_HINT: Record<AccountVisibility, string> = {
  shared: "Alle im Haushalt sehen das Konto und seine Buchungen.",
  private: "Nur du siehst das Konto und seine Buchungen.",
};

type Mode = "new" | "existing";

function ProviderAccountForm({
  connection,
  provider,
  onLinked,
}: {
  connection: BankConnection;
  provider: ProviderAccount;
  onLinked: (syncFrom: string) => void;
}) {
  const queryClient = useQueryClient();
  const { data: accounts = [] } = useQuery(accountsQuery);
  const candidates = accounts.filter((a) => !a.is_archived && !a.bank_linked);

  const [mode, setMode] = useState<Mode>("new");
  const [name, setName] = useState(provider.name || connection.aspsp_name);
  const [kind, setKind] = useState<AccountKind>("giro");
  const [visibility, setVisibility] = useState<AccountVisibility>("shared");
  const [existingId, setExistingId] = useState(candidates[0]?.id ?? "");
  const [syncFrom, setSyncFrom] = useState("");

  const link = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/bank-connections/{connection_id}/link", {
          params: { path: { connection_id: connection.id } },
          body: {
            provider_account_uid: provider.uid,
            sync_from: syncFrom || null,
            ...(mode === "new"
              ? { new_account: { name: name.trim(), kind, visibility } }
              : { account_id: existingId }),
          },
        }),
      ),
    onSuccess: async (result) => {
      await Promise.all([invalidateBank(queryClient), invalidateLedger(queryClient)]);
      onLinked(result.sync_from);
    },
  });

  const valid = mode === "new" ? name.trim() !== "" : existingId !== "";
  const error = mutationErrorMessage(link.error, {
    409: "Dieses Bankkonto oder Konto ist schon verbunden.",
    422: "IBAN, Währung oder Datum passen nicht zum gewählten Konto.",
    404: "Das Konto wurde nicht gefunden.",
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (valid) link.mutate();
  }

  return (
    <form onSubmit={submit} className="space-y-3 rounded-xl border border-border p-4">
      <div>
        <p className="text-sm font-medium">{provider.name || "Bankkonto"}</p>
        <p className="text-xs text-text-muted">
          {provider.iban_masked ?? "IBAN nicht angegeben"}
          {provider.currency ? ` · ${provider.currency}` : ""}
        </p>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor={`mode-${provider.uid}`}>Wohin sollen die Buchungen?</Label>
        <Select
          id={`mode-${provider.uid}`}
          value={mode}
          onValueChange={(v) => setMode(v as Mode)}
          options={[
            { value: "new", label: "Neues Konto anlegen" },
            { value: "existing", label: "Mit bestehendem Konto verbinden" },
          ]}
        />
      </div>

      {mode === "new" ? (
        <>
          <FormField
            label="Kontoname"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={100}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor={`kind-${provider.uid}`}>Art</Label>
              <Select
                id={`kind-${provider.uid}`}
                value={kind}
                onValueChange={(v) => setKind(v as AccountKind)}
                options={KIND_OPTIONS}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`vis-${provider.uid}`}>Sichtbarkeit</Label>
              <Select
                id={`vis-${provider.uid}`}
                value={visibility}
                onValueChange={(v) => setVisibility(v as AccountVisibility)}
                options={VISIBILITY_OPTIONS}
              />
            </div>
          </div>
          <p className="text-xs text-text-muted">{VISIBILITY_HINT[visibility]}</p>
        </>
      ) : candidates.length === 0 ? (
        <Alert>Es gibt kein Konto ohne Bankverbindung. Lege stattdessen ein neues Konto an.</Alert>
      ) : (
        <div className="space-y-1.5">
          <Label htmlFor={`existing-${provider.uid}`}>Konto</Label>
          <Select
            id={`existing-${provider.uid}`}
            value={existingId}
            onValueChange={setExistingId}
            options={candidates.map((a) => ({ value: a.id, label: a.name }))}
          />
          <p className="text-xs text-text-muted">
            Die IBAN muss zum Bankkonto passen, falls beim Konto eine hinterlegt ist.
          </p>
        </div>
      )}

      <FormField
        label="Buchungen abrufen ab (optional)"
        type="date"
        max={toIsoDate(new Date())}
        value={syncFrom}
        onChange={(e) => setSyncFrom(e.target.value)}
        hint="Ohne Angabe holt die App die letzten 90 Tage. Bei einem bestehenden Konto mit CSV-Buchungen beginnt sie am Tag nach der letzten vorhandenen Buchung."
      />

      {error && <Alert tone="error">{error}</Alert>}
      <div className="flex justify-end">
        <Button type="submit" disabled={link.isPending || !valid}>
          Verbinden
        </Button>
      </div>
    </form>
  );
}

type Props = {
  connection: BankConnection | null;
  onOpenChange: (open: boolean) => void;
  onSyncNow: (connection: BankConnection) => void;
};

export function BankLinkDialog({ connection, onOpenChange, onSyncNow }: Props) {
  const open = connection !== null;
  const [linked, setLinked] = useState<Record<string, string>>({});
  const accounts = useQuery({
    ...providerAccountsQuery(connection?.id ?? ""),
    enabled: open,
  });
  const done = Object.keys(linked).length;
  const pending = (accounts.data ?? []).filter((p) => !p.linked_account_id && !(p.uid in linked));
  const hasLinkedOnes = (accounts.data ?? []).some((p) => p.linked_account_id);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) setLinked({});
      }}
    >
      <DialogContent className="sm:max-w-xl">
        <DialogTitle>Konten verbinden</DialogTitle>
        <DialogDescription>
          {connection?.aspsp_name}: Wähle, welche Bankkonten die App abrufen soll.
        </DialogDescription>
        <div className="mt-4 space-y-3">
          {accounts.isPending && open && <p className="text-sm text-text-muted">Lade Konten …</p>}
          {accounts.isError && <Alert tone="error">Die Konten der Bank konnten nicht geladen werden.</Alert>}
          {accounts.data && accounts.data.length === 0 && <Alert>Die Bank meldet keine Konten.</Alert>}
          {connection &&
            pending.map((provider) => (
              <ProviderAccountForm
                key={provider.uid}
                connection={connection}
                provider={provider}
                onLinked={(syncFrom) => setLinked((current) => ({ ...current, [provider.uid]: syncFrom }))}
              />
            ))}
          {accounts.data && pending.length === 0 && accounts.data.length > 0 && !done && hasLinkedOnes && (
            <Alert>Alle Bankkonten sind schon verbunden.</Alert>
          )}
          {done > 0 && (
            <Alert tone="success" className="flex items-start gap-2">
              <Check className="mt-0.5 size-4 shrink-0" aria-hidden />
              <span>
                {done === 1 ? "Konto verbunden." : `${done} Konten verbunden.`} Buchungen ab{" "}
                {formatDate(Object.values(linked).sort()[0])}. Der erste Abruf läuft innerhalb der nächsten
                Stunde, oder du startest ihn jetzt.
              </span>
            </Alert>
          )}
        </div>
        <div className="mt-5 flex justify-end gap-2">
          {done > 0 && connection && (
            <Button
              variant="secondary"
              onClick={() => {
                onSyncNow(connection);
                onOpenChange(false);
                setLinked({});
              }}
            >
              Jetzt abrufen
            </Button>
          )}
          <Button
            variant={done > 0 ? "primary" : "secondary"}
            onClick={() => {
              onOpenChange(false);
              setLinked({});
            }}
          >
            {done > 0 ? "Fertig" : "Schließen"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
