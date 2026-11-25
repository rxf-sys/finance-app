import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { ChevronDown, ChevronRight, History, Link2, Plus, RefreshCw, Unplug } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { bankConnectionsQuery, invalidateBank, syncRunsQuery } from "@/api/bank-queries";
import { api } from "@/api/client";
import { invalidateLedger } from "@/api/queries";
import {
  BankLogo,
  ConnectBankDialog,
  startErrorMessage,
  useStartConnection,
} from "@/components/bank-connect";
import { BankLinkDialog } from "@/components/bank-link-dialog";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import {
  type BankConnection,
  bankErrorMessage,
  canReconnect,
  consentTone,
  formatRetryAfter,
  parseRetryAfter,
  STATUS_LABEL,
  storedErrorText,
} from "@/lib/bank";
import { formatDate, formatDateTime } from "@/lib/format";
import { formatRelativeTime } from "@/lib/relative-time";
import { cn } from "@/lib/utils";

type Props = { connection?: string; error?: string };

const STATUS_CLASS = {
  active: "",
  pending: "",
  expired: "border-negative/40 bg-negative/10 text-negative",
  revoked: "border-negative/40 bg-negative/10 text-negative",
  error: "border-negative/40 bg-negative/10 text-negative",
} as const;

function ConsentLine({ connection }: { connection: BankConnection }) {
  if (!connection.consent_valid_until) return null;
  const tone = consentTone(connection.consent_valid_until);
  return (
    <p
      className={cn(
        "text-sm",
        tone === "expired" && "font-medium text-negative",
        tone === "warning" && "font-medium text-warning",
        tone === "ok" && "text-text-muted",
      )}
    >
      {tone === "expired" ? "Zugriff abgelaufen am " : "Zugriff gültig bis "}
      {formatDate(connection.consent_valid_until)}
      {tone === "warning" && " · bald erneuern"}
    </p>
  );
}

function SyncHistory({ connectionId }: { connectionId: string }) {
  const { data = [], isPending, isError } = useQuery(syncRunsQuery(connectionId));
  if (isPending) return <p className="text-sm text-text-muted">Lade Verlauf …</p>;
  if (isError) return <Alert tone="error">Der Verlauf konnte nicht geladen werden.</Alert>;
  if (data.length === 0) return <p className="text-sm text-text-muted">Noch kein Abruf.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-text-muted">
          <tr className="border-b border-border">
            <th className="py-1.5 pr-3 font-medium">Zeitpunkt</th>
            <th className="py-1.5 pr-3 font-medium">Ergebnis</th>
            <th className="py-1.5 pr-3 text-right font-medium">Neu</th>
            <th className="py-1.5 text-right font-medium">Doppelt</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {data.map((run) => (
            <tr key={run.id}>
              <td className="py-1.5 pr-3 whitespace-nowrap">{formatDateTime(run.started_at)}</td>
              <td className="py-1.5 pr-3">
                {run.status === "completed" ? (
                  "Erfolgreich"
                ) : (
                  <span className="text-negative">
                    Fehlgeschlagen{run.error ? `: ${storedErrorText(run.error)}` : ""}
                  </span>
                )}
              </td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{run.rows_new}</td>
              <td className="py-1.5 text-right tabular-nums">{run.rows_duplicate}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ConnectionCard({
  connection,
  highlighted,
  onLink,
  onSync,
  syncing,
  onDisconnect,
  onReconnect,
  reconnecting,
}: {
  connection: BankConnection;
  highlighted: boolean;
  onLink: () => void;
  onSync: () => void;
  syncing: boolean;
  onDisconnect: () => void;
  onReconnect: () => void;
  reconnecting: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const active = connection.status === "active";

  useEffect(() => {
    if (highlighted) ref.current?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [highlighted]);

  return (
    <div ref={ref} id={`connection-${connection.id}`} className="scroll-mt-20">
      <Card className={cn("space-y-3", highlighted && "ring-2 ring-primary")}>
        <div className="flex items-start gap-3">
          <BankLogo />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle className="truncate">{connection.aspsp_name}</CardTitle>
              <Badge className={STATUS_CLASS[connection.status]}>{STATUS_LABEL[connection.status]}</Badge>
            </div>
            <ConsentLine connection={connection} />
            <p className="text-sm text-text-muted">
              {connection.last_sync_at
                ? `Letzter Abruf ${formatRelativeTime(connection.last_sync_at)}`
                : "Noch nicht abgerufen"}
            </p>
          </div>
        </div>

        {connection.last_error && <Alert tone="error">{storedErrorText(connection.last_error)}</Alert>}

        <div>
          <p className="text-xs font-medium text-text-muted">Verbundene Konten</p>
          {connection.accounts.length === 0 ? (
            <p className="text-sm text-text-muted">
              Noch keine. Verbinde ein Bankkonto mit einem Konto der App.
            </p>
          ) : (
            <ul className="mt-1 space-y-0.5 text-sm">
              {connection.accounts.map((account) => (
                <li key={account.account_id}>
                  <Link
                    to="/accounts/$accountId"
                    params={{ accountId: account.account_id }}
                    className="hover:text-primary"
                  >
                    {account.name}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          {active && (
            <>
              <Button variant="secondary" size="sm" onClick={onLink}>
                <Link2 aria-hidden />
                Konten verbinden
              </Button>
              <Button variant="secondary" size="sm" onClick={onSync} disabled={syncing}>
                <RefreshCw aria-hidden />
                Jetzt abrufen
              </Button>
            </>
          )}
          {canReconnect(connection.status) && (
            <Button size="sm" onClick={onReconnect} disabled={reconnecting}>
              <RefreshCw aria-hidden />
              Neu verbinden
            </Button>
          )}
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setHistoryOpen((v) => !v)}
            aria-expanded={historyOpen}
          >
            <History aria-hidden />
            Verlauf
            {historyOpen ? <ChevronDown aria-hidden /> : <ChevronRight aria-hidden />}
          </Button>
          <Button variant="danger" size="sm" className="sm:ml-auto" onClick={onDisconnect}>
            <Unplug aria-hidden />
            Trennen
          </Button>
        </div>

        {historyOpen && (
          <div className="border-t border-border pt-3">
            <SyncHistory connectionId={connection.id} />
          </div>
        )}
      </Card>
    </div>
  );
}

export function BankPage({ connection: connectionParam, error: errorParam }: Props) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const { data, isPending } = useQuery(bankConnectionsQuery);
  const [connectOpen, setConnectOpen] = useState(false);
  const [linking, setLinking] = useState<BankConnection | null>(null);
  const [disconnecting, setDisconnecting] = useState<BankConnection | null>(null);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);
  const handled = useRef<string | null>(null);
  const start = useStartConnection();

  // The bank callback and the notifications land here with a query parameter: show it once, then strip it.
  useEffect(() => {
    const key = `${connectionParam ?? ""}|${errorParam ?? ""}`;
    if (key === "|" || handled.current === key) return;
    if (errorParam) {
      handled.current = key;
      setNotice({ tone: "error", text: bankErrorMessage(errorParam) });
      void navigate({ to: "/bank", search: {}, replace: true });
      return;
    }
    if (connectionParam && data?.configured) {
      handled.current = key;
      const found = data.connections.find((c) => c.id === connectionParam);
      if (found && found.status === "active" && found.accounts.length === 0) {
        setNotice({
          tone: "success",
          text: `${found.aspsp_name} ist verbunden. Wähle jetzt die Konten aus.`,
        });
        setLinking(found);
      } else if (found) {
        setHighlight(found.id);
      }
      void navigate({ to: "/bank", search: {}, replace: true });
    }
  }, [connectionParam, errorParam, data, navigate]);

  const sync = useMutation({
    mutationFn: async (connection: BankConnection) => {
      const result = await api.POST("/api/bank-connections/{connection_id}/sync", {
        params: { path: { connection_id: connection.id } },
      });
      return {
        status: result.response.status,
        retryAfter: parseRetryAfter(result.response.headers.get("Retry-After")),
      };
    },
    onSuccess: async ({ status, retryAfter }) => {
      if (status === 202) {
        toast.show("Abruf gestartet. Neue Buchungen erscheinen in wenigen Minuten.");
        await Promise.all([invalidateBank(queryClient), invalidateLedger(queryClient)]);
      } else if (status === 429) {
        toast.show(formatRetryAfter(retryAfter ?? 0), "error");
      } else if (status === 409) {
        toast.show("Die Verbindung ist nicht aktiv. Bitte neu verbinden.", "error");
        await invalidateBank(queryClient);
      } else {
        toast.show("Der Abruf konnte nicht gestartet werden.", "error");
      }
    },
    onError: () => toast.show("Der Abruf konnte nicht gestartet werden.", "error"),
  });

  const disconnect = useMutation({
    mutationFn: async (id: string) => {
      const result = await api.DELETE("/api/bank-connections/{connection_id}", {
        params: { path: { connection_id: id } },
      });
      if (!result.response.ok) throw new Error("disconnect failed");
    },
    onSuccess: async () => {
      setDisconnecting(null);
      await invalidateBank(queryClient);
      toast.show("Bankverbindung getrennt.");
    },
    onError: () => toast.show("Trennen hat nicht geklappt.", "error"),
  });

  if (isPending) return <p className="text-sm text-text-muted">Lade …</p>;

  if (!data?.configured) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold">Bankverbindungen</h1>
        <Card className="flex flex-col items-center gap-3 py-10 text-center">
          <Unplug className="size-8 text-text-muted" aria-hidden />
          <CardTitle>Bankabruf ist nicht eingerichtet</CardTitle>
          <CardDescription>
            Die Verwaltung richtet ihn auf dem Server ein (docs/deployment.md, Abschnitt „Bankabruf mit Enable
            Banking einrichten“).
          </CardDescription>
        </Card>
      </div>
    );
  }

  const connections = data.connections;
  const startError = startErrorMessage(start.error);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Bankverbindungen</h1>
        <Button onClick={() => setConnectOpen(true)}>
          <Plus aria-hidden />
          Bank verbinden
        </Button>
      </div>

      {notice && (
        <Alert tone={notice.tone} className="flex items-start justify-between gap-3">
          <span>{notice.text}</span>
          <button type="button" className="shrink-0 underline" onClick={() => setNotice(null)}>
            Schließen
          </button>
        </Alert>
      )}
      {startError && <Alert tone="error">{startError}</Alert>}

      {connections.length === 0 ? (
        <Card className="flex flex-col items-center gap-3 py-10 text-center">
          <Unplug className="size-8 text-text-muted" aria-hidden />
          <CardTitle>Noch keine Bank verbunden</CardTitle>
          <CardDescription>
            Verbinde deine Bank, damit neue Umsätze automatisch kommen. Das geht nur lesend. Der CSV-Import
            bleibt weiter möglich.
          </CardDescription>
          <Button onClick={() => setConnectOpen(true)}>Bank verbinden</Button>
        </Card>
      ) : (
        <div className="space-y-3">
          {connections.map((connection) => (
            <ConnectionCard
              key={connection.id}
              connection={connection}
              highlighted={highlight === connection.id}
              onLink={() => setLinking(connection)}
              onSync={() => sync.mutate(connection)}
              syncing={sync.isPending}
              onDisconnect={() => setDisconnecting(connection)}
              onReconnect={() => start.mutate(connection.aspsp_name)}
              reconnecting={start.isPending}
            />
          ))}
        </div>
      )}

      <ConnectBankDialog open={connectOpen} onOpenChange={setConnectOpen} />
      <BankLinkDialog
        connection={linking}
        onOpenChange={(open) => !open && setLinking(null)}
        onSyncNow={(connection) => sync.mutate(connection)}
      />
      <ConfirmDialog
        open={disconnecting !== null}
        onOpenChange={(open) => !open && setDisconnecting(null)}
        title="Bankverbindung trennen?"
        confirmLabel="Trennen"
        pending={disconnect.isPending}
        onConfirm={() => disconnecting && disconnect.mutate(disconnecting.id)}
      >
        Die Verbindung zu {disconnecting?.aspsp_name} wird getrennt. Die verbundenen Konten und alle bereits
        abgerufenen Buchungen bleiben erhalten; es kommen nur keine neuen mehr.
      </ConfirmDialog>
    </div>
  );
}
