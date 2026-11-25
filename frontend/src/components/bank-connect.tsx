import { useMutation, useQuery } from "@tanstack/react-query";
import { Landmark, Search } from "lucide-react";
import { useState } from "react";
import { aspspsQuery } from "@/api/bank-queries";
import { api, mutationErrorMessage, unwrap } from "@/api/client";
import { Alert } from "@/components/ui/alert";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { filterAspsps } from "@/lib/bank";

const COUNTRY = "DE";

/** Starts a bank connection and leaves for the bank's login page. */
export function useStartConnection() {
  return useMutation({
    mutationFn: async (aspspName: string) => {
      const started = unwrap(
        await api.POST("/api/bank-connections", { body: { aspsp_name: aspspName, country: COUNTRY } }),
      );
      window.location.assign(started.redirect_url_to_bank);
      return started;
    },
  });
}

export function startErrorMessage(error: unknown): string | null {
  return mutationErrorMessage(error, {
    422: "Diese Bank ist nicht bekannt.",
    429: "Zu viele Anfragen. Bitte warte kurz.",
    502: "Die Bank oder der Bankdienst antwortet gerade nicht.",
    503: "Der Bankabruf ist nicht eingerichtet.",
  });
}

export function ConnectBankDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [search, setSearch] = useState("");
  const banks = useQuery({ ...aspspsQuery(COUNTRY), enabled: open });
  const start = useStartConnection();
  const filtered = filterAspsps(banks.data ?? [], search);
  const error = startErrorMessage(start.error);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) setSearch("");
      }}
    >
      <DialogContent>
        <DialogTitle>Bank verbinden</DialogTitle>
        <DialogDescription>
          Du wirst zur Anmeldung bei deiner Bank weitergeleitet. Die App liest nur Umsätze und Salden und kann
          nichts überweisen.
        </DialogDescription>
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-border bg-surface-muted px-3">
          <Search className="size-4 shrink-0 text-text-muted" aria-hidden />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Bank suchen"
            aria-label="Bank suchen"
            className="h-10 w-full bg-transparent text-sm outline-none placeholder:text-text-muted"
          />
        </div>
        <p className="mt-2 text-xs text-text-muted">Land: Deutschland</p>
        {error && (
          <Alert tone="error" className="mt-3">
            {error}
          </Alert>
        )}
        <ul className="mt-2 max-h-80 overflow-y-auto rounded-lg border border-border">
          {banks.isPending && (
            <li className="px-3 py-6 text-center text-sm text-text-muted">Lade Banken …</li>
          )}
          {banks.isError && (
            <li className="px-3 py-6 text-center text-sm text-text-muted">
              Die Bankliste konnte nicht geladen werden.
            </li>
          )}
          {banks.data && filtered.length === 0 && (
            <li className="px-3 py-6 text-center text-sm text-text-muted">Keine Treffer</li>
          )}
          {filtered.map((bank) => (
            <li key={bank.name} className="border-b border-border last:border-b-0">
              <button
                type="button"
                disabled={start.isPending}
                onClick={() => start.mutate(bank.name)}
                className="flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm hover:bg-surface-muted disabled:opacity-50"
              >
                <BankLogo logo={bank.logo} />
                <span className="flex-1">{bank.name}</span>
              </button>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}

export function BankLogo({ logo }: { logo?: string | null }) {
  const [failed, setFailed] = useState(false);
  if (!logo || failed) {
    return (
      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-surface-muted text-text-muted">
        <Landmark className="size-4" aria-hidden />
      </span>
    );
  }
  return (
    <img
      src={logo}
      alt=""
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      className="size-8 shrink-0 rounded-lg bg-white object-contain p-0.5"
    />
  );
}
