import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, Plus, Trash2, Unlink, X } from "lucide-react";
import { type FormEvent, useState } from "react";
import { api, mutationErrorMessage, type TransactionDetail, unwrap } from "@/api/client";
import {
  accountsQuery,
  categoriesQuery,
  invalidateLedger,
  tagsQuery,
  transactionQuery,
  transferCandidatesQuery,
} from "@/api/queries";
import { Amount } from "@/components/amount";
import { CategorizeOffer, useCategorize } from "@/components/categorize-offer";
import { CategoryBadge } from "@/components/category-badge";
import { CategoryPicker } from "@/components/category-picker";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { MoneyInput } from "@/components/money-input";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { categoryIndex } from "@/lib/categories";
import { formatDate } from "@/lib/format";
import { formatMoney, formatSignedMoney, parseMoneyInput } from "@/lib/money";

const SOURCE_LABEL = { rule: "durch Regel", manual: "von Hand" } as const;

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-text-muted">{label}</dt>
      <dd className="text-sm break-words">{children}</dd>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2 border-t border-border pt-4">
      <h3 className="text-sm font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function useRefresh() {
  const queryClient = useQueryClient();
  return () => invalidateLedger(queryClient);
}

// ------------------------------------------------------------------ notes

function NoteEditor({ tx }: { tx: TransactionDetail }) {
  const refresh = useRefresh();
  const toast = useToast();
  const [note, setNote] = useState(tx.note ?? "");
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/transactions/{transaction_id}", {
          params: { path: { transaction_id: tx.id } },
          body: { note: note.trim() || null, learn: false, apply_to_similar: false },
        }),
      ),
    onSuccess: async () => {
      await refresh();
      toast.show("Notiz gespeichert.");
    },
  });
  return (
    <div className="space-y-2">
      <Label htmlFor="tx-note">Notiz</Label>
      <Textarea id="tx-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
      <div className="flex items-center justify-end gap-2">
        {save.error && <span className="text-xs text-negative">{mutationErrorMessage(save.error)}</span>}
        <Button
          size="sm"
          variant="secondary"
          disabled={save.isPending || note === (tx.note ?? "")}
          onClick={() => save.mutate()}
        >
          Notiz speichern
        </Button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ tags

function TagEditor({ tx }: { tx: TransactionDetail }) {
  const refresh = useRefresh();
  const queryClient = useQueryClient();
  const { data: allTags = [] } = useQuery(tagsQuery);
  const [text, setText] = useState("");

  const setTags = useMutation({
    mutationFn: async (tagIds: string[]) =>
      unwrap(
        await api.PATCH("/api/transactions/{transaction_id}", {
          params: { path: { transaction_id: tx.id } },
          body: { tag_ids: tagIds, learn: false, apply_to_similar: false },
        }),
      ),
    onSuccess: refresh,
  });

  const createAndAdd = useMutation({
    mutationFn: async (name: string) => {
      const existing = allTags.find((t) => t.name.toLowerCase() === name.toLowerCase());
      if (existing) return existing;
      return unwrap(await api.POST("/api/tags", { body: { name } }));
    },
    onSuccess: async (tag) => {
      await queryClient.invalidateQueries({ queryKey: tagsQuery.queryKey });
      setText("");
      if (!tx.tags.some((t) => t.id === tag.id)) setTags.mutate([...tx.tags.map((t) => t.id), tag.id]);
    },
  });

  const current = new Set(tx.tags.map((t) => t.id));
  const needle = text.trim().toLowerCase();
  const suggestions = allTags.filter(
    (t) => !current.has(t.id) && (!needle || t.name.toLowerCase().includes(needle)),
  );
  const canCreate = needle !== "" && !allTags.some((t) => t.name.toLowerCase() === needle);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (text.trim()) createAndAdd.mutate(text.trim());
  }

  return (
    <div className="space-y-2">
      <ul className="flex flex-wrap gap-2" aria-label="Tags">
        {tx.tags.length === 0 && <li className="text-sm text-text-muted">Keine Tags.</li>}
        {tx.tags.map((tag) => (
          <li key={tag.id}>
            <Badge className="gap-1 pr-1 text-text">
              {tag.name}
              <button
                type="button"
                className="rounded-full p-0.5 hover:bg-border"
                aria-label={`Tag ${tag.name} entfernen`}
                onClick={() => setTags.mutate(tx.tags.filter((t) => t.id !== tag.id).map((t) => t.id))}
              >
                <X className="size-3" aria-hidden />
              </button>
            </Badge>
          </li>
        ))}
      </ul>
      <form onSubmit={submit} className="flex gap-2">
        <Input
          aria-label="Tag hinzufügen"
          placeholder="Tag suchen oder neu anlegen"
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={50}
        />
        <Button type="submit" variant="secondary" disabled={!text.trim() || createAndAdd.isPending}>
          <Plus aria-hidden /> {canCreate ? "Neu anlegen" : "Hinzufügen"}
        </Button>
      </form>
      {suggestions.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {suggestions.slice(0, 8).map((tag) => (
            <li key={tag.id}>
              <button
                type="button"
                className="rounded-full border border-dashed border-border px-2 py-0.5 text-xs text-text-muted hover:bg-surface-muted"
                onClick={() => setTags.mutate([...tx.tags.map((t) => t.id), tag.id])}
              >
                + {tag.name}
              </button>
            </li>
          ))}
        </ul>
      )}
      {(createAndAdd.error || setTags.error) && (
        <p className="text-xs text-negative">{mutationErrorMessage(createAndAdd.error ?? setTags.error)}</p>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ splits

type Part = { amount: string; categoryId: string | null; note: string };

function partsFromTx(tx: TransactionDetail): Part[] {
  if (tx.splits.length >= 2) {
    return tx.splits.map((s) => ({
      amount: String(Math.abs(s.amount_cents) / 100).replace(".", ","),
      categoryId: s.category_id,
      note: s.note ?? "",
    }));
  }
  return [
    { amount: "", categoryId: null, note: "" },
    { amount: "", categoryId: null, note: "" },
  ];
}

function SplitEditor({ tx }: { tx: TransactionDetail }) {
  const refresh = useRefresh();
  const toast = useToast();
  const [parts, setParts] = useState<Part[]>(() => partsFromTx(tx));
  const sign = tx.amount_cents < 0 ? -1 : 1;
  const total = Math.abs(tx.amount_cents);
  const cents = parts.map((p) => parseMoneyInput(p.amount));
  const sum = cents.reduce<number>((acc, c) => acc + Math.abs(c ?? 0), 0);
  const remainder = total - sum;
  const valid = parts.length >= 2 && remainder === 0 && cents.every((c) => c !== null && c !== 0);

  const save = useMutation({
    mutationFn: async (body: { amount_cents: number; category_id: string | null; note: string | null }[]) =>
      unwrap(
        await api.PUT("/api/transactions/{transaction_id}/splits", {
          params: { path: { transaction_id: tx.id } },
          body,
        }),
      ),
    onSuccess: async (_, body) => {
      await refresh();
      toast.show(body.length === 0 ? "Aufteilung entfernt." : "Aufteilung gespeichert.");
      if (body.length === 0) setParts(partsFromTx({ ...tx, splits: [] }));
    },
  });

  function update(index: number, patch: Partial<Part>) {
    setParts((current) => current.map((p, i) => (i === index ? { ...p, ...patch } : p)));
  }

  return (
    <div className="space-y-3">
      {parts.map((part, index) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: parts are an ordered, unkeyed form list
        <div key={index} className="space-y-2 rounded-lg border border-border p-3">
          <div className="grid grid-cols-[1fr_auto] items-end gap-2">
            <MoneyInput
              label={`Teil ${index + 1}`}
              value={part.amount}
              onChange={(v) => update(index, { amount: v })}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Teil ${index + 1} entfernen`}
              disabled={parts.length <= 2}
              onClick={() => setParts((current) => current.filter((_, i) => i !== index))}
            >
              <Trash2 aria-hidden />
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-0 flex-1">
              <CategoryPicker
                aria-label={`Kategorie für Teil ${index + 1}`}
                value={part.categoryId}
                onChange={(id) => update(index, { categoryId: id })}
                clearLabel="Keine Kategorie"
              />
            </div>
            {remainder > 0 && (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                onClick={() =>
                  update(index, {
                    amount: String(
                      ((cents[index] === null ? 0 : Math.abs(cents[index] ?? 0)) + remainder) / 100,
                    ).replace(".", ","),
                  })
                }
              >
                Rest übernehmen
              </Button>
            )}
          </div>
        </div>
      ))}
      <div className="flex items-center justify-between text-sm" aria-live="polite">
        <span className="text-text-muted">Noch zu verteilen</span>
        <span className={remainder === 0 ? "font-medium text-positive" : "font-medium"}>
          {formatMoney(sign * remainder, tx.currency)}
        </span>
      </div>
      {remainder < 0 && <Alert tone="error">Die Teile ergeben mehr als den Buchungsbetrag.</Alert>}
      {save.error && (
        <Alert tone="error">
          {mutationErrorMessage(save.error, {
            422: "Die Teile müssen zusammen genau den Buchungsbetrag ergeben.",
          })}
        </Alert>
      )}
      <div className="flex flex-wrap justify-between gap-2">
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() => setParts((c) => [...c, { amount: "", categoryId: null, note: "" }])}
        >
          <Plus aria-hidden /> Teil hinzufügen
        </Button>
        <div className="flex gap-2">
          {tx.splits.length > 0 && (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={save.isPending}
              onClick={() => save.mutate([])}
            >
              Aufteilung entfernen
            </Button>
          )}
          <Button
            type="button"
            size="sm"
            disabled={!valid || save.isPending}
            onClick={() =>
              save.mutate(
                parts.map((p, i) => ({
                  amount_cents: sign * Math.abs(cents[i] ?? 0),
                  category_id: p.categoryId,
                  note: p.note.trim() || null,
                })),
              )
            }
          >
            Aufteilung speichern
          </Button>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ transfers

function TransferSection({ tx }: { tx: TransactionDetail }) {
  const refresh = useRefresh();
  const toast = useToast();
  const { data: accounts = [] } = useQuery(accountsQuery);
  const accountName = (id: string) => accounts.find((a) => a.id === id)?.name ?? "Unbekanntes Konto";
  const [looking, setLooking] = useState(false);
  const peer = useQuery({
    ...transactionQuery(tx.transfer_peer_id ?? ""),
    enabled: Boolean(tx.transfer_peer_id),
  });
  const candidates = useQuery({
    ...transferCandidatesQuery(tx.id),
    enabled: looking && !tx.transfer_peer_id,
  });

  const pair = useMutation({
    mutationFn: async (peerId: string) =>
      unwrap(
        await api.POST("/api/transactions/{transaction_id}/transfer", {
          params: { path: { transaction_id: tx.id } },
          body: { peer_id: peerId },
        }),
      ),
    onSuccess: async () => {
      await refresh();
      setLooking(false);
      toast.show("Als Umbuchung verknüpft.");
    },
  });
  const unpair = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.DELETE("/api/transactions/{transaction_id}/transfer", {
          params: { path: { transaction_id: tx.id } },
        }),
      ),
    onSuccess: async () => {
      await refresh();
      toast.show("Verknüpfung gelöst.");
    },
  });

  if (tx.transfer_peer_id) {
    return (
      <div className="space-y-2">
        <p className="flex items-center gap-2 text-sm">
          <ArrowLeftRight className="size-4 text-text-muted" aria-hidden />
          Umbuchung
          {peer.data && (
            <span className="text-text-muted">
              mit {accountName(peer.data.account_id)} am {formatDate(peer.data.booking_date)} (
              {formatSignedMoney(peer.data.amount_cents, peer.data.currency)})
            </span>
          )}
        </p>
        <Button size="sm" variant="secondary" disabled={unpair.isPending} onClick={() => unpair.mutate()}>
          <Unlink aria-hidden /> Verknüpfung lösen
        </Button>
        {unpair.error && <p className="text-xs text-negative">{mutationErrorMessage(unpair.error)}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {tx.is_transfer && (
        <p className="text-sm text-text-muted">
          Diese Buchung ist als Umbuchung markiert, hat aber keine Gegenbuchung in einem sichtbaren Konto.
        </p>
      )}
      {!looking ? (
        <Button size="sm" variant="secondary" onClick={() => setLooking(true)}>
          <ArrowLeftRight aria-hidden /> Gegenbuchung suchen
        </Button>
      ) : candidates.isPending ? (
        <p className="text-sm text-text-muted">Suche …</p>
      ) : (candidates.data ?? []).length === 0 ? (
        <p className="text-sm text-text-muted">Keine passende Gegenbuchung gefunden.</p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {(candidates.data ?? []).map((candidate) => (
            <li key={candidate.id} className="flex items-center gap-3 px-3 py-2 text-sm">
              <span className="min-w-0 flex-1">
                <span className="block truncate">{accountName(candidate.account_id)}</span>
                <span className="block text-xs text-text-muted">
                  {formatDate(candidate.booking_date)} ·{" "}
                  {formatSignedMoney(candidate.amount_cents, candidate.currency)}
                </span>
              </span>
              <Button size="sm" disabled={pair.isPending} onClick={() => pair.mutate(candidate.id)}>
                Zuordnen
              </Button>
            </li>
          ))}
        </ul>
      )}
      {pair.error && <p className="text-xs text-negative">{mutationErrorMessage(pair.error)}</p>}
    </div>
  );
}

// ------------------------------------------------------------------ dialog

function DetailBody({ tx, onClose }: { tx: TransactionDetail; onClose: () => void }) {
  const { data: accounts = [] } = useQuery(accountsQuery);
  const { data: categories = [] } = useQuery(categoriesQuery);
  const refresh = useRefresh();
  const toast = useToast();
  const categorizer = useCategorize();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const index = categoryIndex(categories);
  const category = tx.category_id ? index.get(tx.category_id) : undefined;
  const hasSplits = tx.splits.length > 0;

  const remove = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.DELETE("/api/transactions/{transaction_id}", {
          params: { path: { transaction_id: tx.id } },
        }),
      ),
    onSuccess: async () => {
      setConfirmDelete(false);
      onClose();
      await refresh();
      toast.show("Buchung gelöscht.");
    },
  });

  return (
    <div className="mt-4 space-y-4">
      <div className="flex items-baseline justify-between gap-3">
        <Amount cents={tx.amount_cents} currency={tx.currency} className="text-2xl font-semibold" />
        {tx.is_transfer && <Badge>Umbuchung</Badge>}
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
        <Field label="Buchungsdatum">{formatDate(tx.booking_date)}</Field>
        <Field label="Wertstellung">{tx.value_date ? formatDate(tx.value_date) : "–"}</Field>
        <Field label="Konto">{accounts.find((a) => a.id === tx.account_id)?.name ?? "–"}</Field>
        <Field label="Buchungstext">{tx.booking_text ?? "–"}</Field>
        <Field label="Gegenpartei">{tx.counterparty_name ?? "–"}</Field>
        <Field label="IBAN der Gegenpartei">{tx.counterparty_iban ?? "–"}</Field>
        <div className="col-span-2">
          <Field label="Verwendungszweck">{tx.purpose ?? "–"}</Field>
        </div>
      </dl>

      <Section title="Kategorie">
        {hasSplits ? (
          <p className="text-sm text-text-muted">
            Die Buchung ist aufgeteilt, die Kategorien stehen bei den Teilen.
          </p>
        ) : (
          <>
            <CategoryPicker
              aria-label="Kategorie der Buchung"
              value={tx.category_id}
              onChange={(id) => categorizer.categorize(tx.id, id)}
              clearLabel="Keine Kategorie"
            />
            {category && tx.category_source && (
              <p className="text-xs text-text-muted">Zugeordnet {SOURCE_LABEL[tx.category_source]}.</p>
            )}
            <CategorizeOffer categorizer={categorizer} />
          </>
        )}
      </Section>

      <Section title="Notiz">
        <NoteEditor key={`${tx.id}-${tx.note ?? ""}`} tx={tx} />
      </Section>

      <Section title="Tags">
        <TagEditor tx={tx} />
      </Section>

      <Section title="Aufteilen">
        <p className="text-xs text-text-muted">
          Verteile den Betrag auf mehrere Kategorien. Die Teile müssen zusammen genau{" "}
          {formatMoney(Math.abs(tx.amount_cents), tx.currency)} ergeben.
        </p>
        <SplitEditor key={`${tx.id}-${tx.splits.map((s) => s.id).join()}`} tx={tx} />
      </Section>

      <Section title="Umbuchung">
        <TransferSection tx={tx} />
      </Section>

      <Section title="Details">
        <details className="rounded-lg border border-border">
          <summary className="cursor-pointer px-3 py-2 text-sm">Rohdaten anzeigen</summary>
          <pre className="max-h-64 overflow-auto border-t border-border px-3 py-2 text-xs whitespace-pre-wrap break-all">
            {tx.raw
              ? JSON.stringify(tx.raw, null, 2)
              : "Für diese Buchung gibt es keine Rohdaten (von Hand erfasst)."}
          </pre>
        </details>
        <div className="pt-2">
          <Button variant="danger" size="sm" onClick={() => setConfirmDelete(true)}>
            <Trash2 aria-hidden /> Buchung löschen
          </Button>
        </div>
      </Section>

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title="Buchung löschen?"
        confirmLabel="Löschen"
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      >
        <p>Die Buchung wird endgültig entfernt. Ein späterer Import legt sie ggf. erneut an.</p>
      </ConfirmDialog>
    </div>
  );
}

export function TransactionDetailDialog({ id, onClose }: { id: string | undefined; onClose: () => void }) {
  const query = useQuery({ ...transactionQuery(id ?? ""), enabled: Boolean(id) });
  const { data: categories = [] } = useQuery(categoriesQuery);
  const tx = query.data;
  const category = tx?.category_id ? categories.find((c) => c.id === tx.category_id) : undefined;
  return (
    <Dialog open={Boolean(id)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogTitle>{tx?.counterparty_name ?? "Buchung"}</DialogTitle>
        <DialogDescription asChild>
          <div>{category ? <CategoryBadge category={category} /> : "Ohne Kategorie"}</div>
        </DialogDescription>
        {query.isError && (
          <Alert tone="error" className="mt-4">
            Die Buchung konnte nicht geladen werden.
          </Alert>
        )}
        {tx && <DetailBody tx={tx} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}
