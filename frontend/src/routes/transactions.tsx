import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight, Filter, Plus, Receipt, Search, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Account, Category, Transaction } from "@/api/client";
import { accountsQuery, categoriesQuery, tagsQuery, transactionsQuery } from "@/api/queries";
import { Amount } from "@/components/amount";
import { CategorizeOffer, type Categorizer, useCategorize } from "@/components/categorize-offer";
import { CategoryBadge } from "@/components/category-badge";
import { CategoryPicker } from "@/components/category-picker";
import { ManualTransactionDialog } from "@/components/manual-transaction-dialog";
import { TransactionDetailDialog } from "@/components/transaction-detail";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { categoryIndex } from "@/lib/categories";
import { formatDate } from "@/lib/format";
import {
  activeFilterCount,
  PAGE_SIZE,
  PERIOD_LABEL,
  PERIODS,
  periodRange,
  type TransactionSearch,
  toApiQuery,
} from "@/lib/transaction-search";
import { cn } from "@/lib/utils";

const ALL = "all";

// ------------------------------------------------------------------ filters

function FilterBar({
  search,
  update,
}: {
  search: TransactionSearch;
  update: (patch: Partial<TransactionSearch>) => void;
}) {
  const { data: accounts = [] } = useQuery(accountsQuery);
  const { data: tags = [] } = useQuery(tagsQuery);
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(search.q ?? "");
  const timer = useRef<number | undefined>(undefined);

  // The URL is the source of truth: follow it into the field (reset, back button).
  useEffect(() => {
    setText(search.q ?? "");
  }, [search.q]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  function onSearchInput(value: string) {
    setText(value);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => update({ q: value.trim() || undefined }), 300);
  }

  const period = search.period ?? "month";
  const range = periodRange(search);
  const count = activeFilterCount(search);

  function setPeriod(next: string) {
    const value = next as (typeof PERIODS)[number];
    if (value === "custom") {
      update({
        period: "custom",
        from: search.from ?? range.from ?? undefined,
        to: search.to ?? range.to ?? undefined,
      });
    } else {
      update({ period: value === "month" ? undefined : value, from: undefined, to: undefined });
    }
  }

  return (
    <div className="space-y-3 rounded-xl border border-border bg-surface p-3">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-3 left-3 size-4 text-text-muted" aria-hidden />
          <Input
            type="search"
            aria-label="Buchungen durchsuchen"
            placeholder="Suchen"
            className="pl-9"
            value={text}
            onChange={(e) => onSearchInput(e.target.value)}
          />
        </div>
        <Button
          variant="secondary"
          className="md:hidden"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          <Filter aria-hidden /> Filter{count > 0 ? ` (${count})` : ""}
        </Button>
      </div>

      <div className={cn("grid-cols-2 gap-3 md:grid md:grid-cols-4", open ? "grid" : "hidden")}>
        <div className="space-y-1.5">
          <Label htmlFor="f-period">Zeitraum</Label>
          <Select
            id="f-period"
            value={period}
            onValueChange={setPeriod}
            options={PERIODS.map((p) => ({ value: p, label: PERIOD_LABEL[p] }))}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="f-account">Konto</Label>
          <Select
            id="f-account"
            value={search.account ?? ALL}
            onValueChange={(v) => update({ account: v === ALL ? undefined : v })}
            options={[
              { value: ALL, label: "Alle Konten" },
              ...accounts.map((a) => ({ value: a.id, label: a.name })),
            ]}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="f-category">Kategorie</Label>
          <CategoryPicker
            id="f-category"
            value={search.uncategorized ? null : (search.category ?? null)}
            onChange={(id) => update({ category: id ?? undefined, uncategorized: undefined })}
            clearLabel="Alle Kategorien"
            placeholder="Alle Kategorien"
            extraOption={{
              label: "Ohne Kategorie",
              selected: Boolean(search.uncategorized),
              onSelect: () => update({ uncategorized: true, category: undefined }),
            }}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="f-direction">Richtung</Label>
          <Select
            id="f-direction"
            value={search.direction ?? ALL}
            onValueChange={(v) => update({ direction: v === ALL ? undefined : (v as "in" | "out") })}
            options={[
              { value: ALL, label: "Alle" },
              { value: "in", label: "Einnahmen" },
              { value: "out", label: "Ausgaben" },
            ]}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="f-tag">Tag</Label>
          <Select
            id="f-tag"
            value={search.tag ?? ALL}
            onValueChange={(v) => update({ tag: v === ALL ? undefined : v })}
            options={[
              { value: ALL, label: "Alle Tags" },
              ...tags.map((t) => ({ value: t.id, label: t.name })),
            ]}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="f-transfers">Umbuchungen</Label>
          <Select
            id="f-transfers"
            value={search.transfers ?? "include"}
            onValueChange={(v) =>
              update({ transfers: v === "include" ? undefined : (v as "exclude" | "only") })
            }
            options={[
              { value: "include", label: "Mit Umbuchungen" },
              { value: "exclude", label: "Ohne Umbuchungen" },
              { value: "only", label: "Nur Umbuchungen" },
            ]}
          />
        </div>
        {period === "custom" && (
          <>
            <div className="space-y-1.5">
              <Label htmlFor="f-from">Von</Label>
              <Input
                id="f-from"
                type="date"
                value={search.from ?? ""}
                onChange={(e) => update({ from: e.target.value || undefined })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="f-to">Bis</Label>
              <Input
                id="f-to"
                type="date"
                value={search.to ?? ""}
                onChange={(e) => update({ to: e.target.value || undefined })}
              />
            </div>
          </>
        )}
      </div>

      {count > 0 && (
        <button
          type="button"
          className="flex items-center gap-1 text-sm text-primary hover:underline"
          onClick={() => {
            window.clearTimeout(timer.current);
            setText("");
            update({
              period: undefined,
              from: undefined,
              to: undefined,
              account: undefined,
              category: undefined,
              uncategorized: undefined,
              q: undefined,
              direction: undefined,
              tag: undefined,
              transfers: undefined,
            });
          }}
        >
          <X className="size-4" aria-hidden /> Filter zurücksetzen
        </button>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ list

type RowContext = {
  accounts: Map<string, Account>;
  categories: Map<string, Category>;
  categorizer: Categorizer;
  open: (id: string) => void;
  showAccount: boolean;
};

function CategoryCell({ tx, ctx }: { tx: Transaction; ctx: RowContext }) {
  const category = tx.category_id ? ctx.categories.get(tx.category_id) : undefined;
  const parent = category?.parent_id ? ctx.categories.get(category.parent_id) : undefined;
  if (tx.splits.length > 0) return <Badge>Aufgeteilt ({tx.splits.length})</Badge>;
  return (
    <CategoryPicker
      value={tx.category_id}
      onChange={(id) => ctx.categorizer.categorize(tx.id, id)}
      clearLabel="Keine Kategorie"
      aria-label="Kategorie ändern"
      className="max-w-full rounded-full focus-visible:outline-2"
    >
      {category ? (
        <CategoryBadge category={category} parentName={parent?.name} />
      ) : (
        <span className="inline-flex items-center rounded-full border border-dashed border-border px-2 py-0.5 text-xs text-text-muted hover:bg-surface-muted">
          Kategorie wählen
        </span>
      )}
    </CategoryPicker>
  );
}

function TransactionTable({ items, ctx }: { items: Transaction[]; ctx: RowContext }) {
  return (
    <table className="hidden w-full text-sm md:table">
      <thead>
        <tr className="border-b border-border text-left text-xs text-text-muted">
          <th className="px-4 py-2 font-normal">Datum</th>
          <th className="px-4 py-2 font-normal">Gegenpartei und Zweck</th>
          {ctx.showAccount && <th className="px-4 py-2 font-normal">Konto</th>}
          <th className="px-4 py-2 font-normal">Kategorie</th>
          <th className="px-4 py-2 text-right font-normal">Betrag</th>
        </tr>
      </thead>
      <tbody>
        {items.map((tx) => (
          <tr key={tx.id} className="border-b border-border last:border-0 hover:bg-surface-muted/50">
            <td className="px-4 py-2.5 whitespace-nowrap">{formatDate(tx.booking_date)}</td>
            <td className="max-w-sm px-4 py-2.5">
              <button type="button" className="block w-full text-left" onClick={() => ctx.open(tx.id)}>
                <span className="block truncate font-medium">
                  {tx.counterparty_name ?? tx.booking_text ?? "Ohne Gegenpartei"}
                </span>
                <span className="block truncate text-xs text-text-muted">{tx.purpose}</span>
              </button>
            </td>
            {ctx.showAccount && (
              <td className="px-4 py-2.5 text-text-muted">{ctx.accounts.get(tx.account_id)?.name}</td>
            )}
            <td className="px-4 py-2.5">
              <CategoryCell tx={tx} ctx={ctx} />
            </td>
            <td className="px-4 py-2.5 text-right">
              <Amount cents={tx.amount_cents} currency={tx.currency} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TransactionCards({ items, ctx }: { items: Transaction[]; ctx: RowContext }) {
  return (
    <ul className="divide-y divide-border md:hidden">
      {items.map((tx) => (
        <li key={tx.id} className="space-y-1.5 px-3 py-3">
          <button type="button" className="block w-full text-left" onClick={() => ctx.open(tx.id)}>
            <span className="flex items-baseline justify-between gap-3">
              <span className="min-w-0 truncate text-sm font-medium">
                {tx.counterparty_name ?? tx.booking_text ?? "Ohne Gegenpartei"}
              </span>
              <Amount
                cents={tx.amount_cents}
                currency={tx.currency}
                className="shrink-0 text-sm font-medium"
              />
            </span>
            {tx.purpose && <span className="block truncate text-xs text-text-muted">{tx.purpose}</span>}
          </button>
          <div className="flex items-center justify-between gap-2 text-xs text-text-muted">
            <span>
              {formatDate(tx.booking_date)}
              {ctx.showAccount ? ` · ${ctx.accounts.get(tx.account_id)?.name ?? ""}` : ""}
            </span>
            <CategoryCell tx={tx} ctx={ctx} />
          </div>
        </li>
      ))}
    </ul>
  );
}

// ------------------------------------------------------------------ page

export function TransactionsPage({ search }: { search: TransactionSearch }) {
  const navigate = useNavigate();
  const { data: accounts = [] } = useQuery(accountsQuery);
  const { data: categories = [] } = useQuery(categoriesQuery);
  const query = useMemo(() => toApiQuery(search), [search]);
  const list = useQuery(transactionsQuery(query));
  const categorizer = useCategorize();
  const [creating, setCreating] = useState(false);

  function update(patch: Partial<TransactionSearch>) {
    void navigate({
      to: "/transactions",
      search: (previous: TransactionSearch) => ({
        ...previous,
        ...patch,
        page: "page" in patch ? patch.page : undefined,
      }),
      replace: true,
    });
  }
  function setPage(page: number) {
    void navigate({
      to: "/transactions",
      search: (previous: TransactionSearch) => ({ ...previous, page: page > 1 ? page : undefined }),
    });
  }
  function openDetail(id: string | undefined) {
    void navigate({
      to: "/transactions",
      search: (previous: TransactionSearch) => ({ ...previous, tx: id }),
      replace: true,
    });
  }

  const ctx: RowContext = {
    accounts: useMemo(() => new Map(accounts.map((a) => [a.id, a])), [accounts]),
    categories: useMemo(() => categoryIndex(categories), [categories]),
    categorizer,
    open: openDetail,
    showAccount: accounts.length > 1 && !search.account,
  };

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const page = search.page ?? 1;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Buchungen</h1>
        <Button onClick={() => setCreating(true)} disabled={accounts.every((a) => a.is_archived)}>
          <Plus aria-hidden /> Buchung erfassen
        </Button>
      </div>

      <FilterBar search={search} update={update} />
      <CategorizeOffer categorizer={categorizer} />

      {list.isError ? (
        <Card>
          <CardTitle>Buchungen konnten nicht geladen werden</CardTitle>
          <CardDescription>Bitte die Seite neu laden.</CardDescription>
        </Card>
      ) : list.isPending ? (
        <p className="py-8 text-center text-sm text-text-muted">Lädt …</p>
      ) : items.length === 0 ? (
        <Card className="flex flex-col items-center gap-2 py-10 text-center">
          <Receipt className="size-8 text-text-muted" aria-hidden />
          <CardTitle>Keine Buchungen gefunden</CardTitle>
          <CardDescription>
            {activeFilterCount(search) > 0 || search.period !== undefined
              ? "Für diese Filter gibt es keine Buchungen."
              : "In diesem Monat gibt es noch keine Buchungen."}
          </CardDescription>
        </Card>
      ) : (
        <div
          className={cn(
            "overflow-hidden rounded-xl border border-border bg-surface",
            list.isPlaceholderData && "opacity-60",
          )}
        >
          <TransactionTable items={items} ctx={ctx} />
          <TransactionCards items={items} ctx={ctx} />
        </div>
      )}

      {total > 0 && (
        <div className="flex items-center justify-between gap-3 text-sm">
          <span className="text-text-muted">
            {total} Buchungen · Seite {page} von {pages}
          </span>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
              <ChevronLeft aria-hidden /> Zurück
            </Button>
            <Button variant="secondary" size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>
              Weiter <ChevronRight aria-hidden />
            </Button>
          </div>
        </div>
      )}

      <TransactionDetailDialog id={search.tx} onClose={() => openDetail(undefined)} />
      <ManualTransactionDialog open={creating} onOpenChange={setCreating} defaultAccountId={search.account} />
    </div>
  );
}
