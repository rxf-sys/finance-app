import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Play, Plus, Trash2 } from "lucide-react";
import { type FormEvent, useMemo, useState } from "react";
import { api, mutationErrorMessage, type Rule, unwrap } from "@/api/client";
import { accountsQuery, categoriesQuery, invalidateLedger, rulesQuery } from "@/api/queries";
import { CategoryBadge } from "@/components/category-badge";
import { CategoryPicker } from "@/components/category-picker";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { FormField } from "@/components/form-field";
import { MoneyInput } from "@/components/money-input";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";
import { categoryIndex } from "@/lib/categories";
import { formatMoneyInput, parseMoneyInput } from "@/lib/money";
import { buildConditions, describeConditions } from "@/lib/rules";

const ANY = "any";

type Conditions = Record<string, unknown>;
const str = (v: unknown) => (typeof v === "string" ? v : "");
const num = (v: unknown) => (typeof v === "number" ? formatMoneyInput(v) : "");

function RuleForm({ rule, onClose }: { rule: Rule | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: accounts = [] } = useQuery(accountsQuery);
  const c: Conditions = rule?.conditions ?? {};

  const [counterparty, setCounterparty] = useState(str(c.counterparty_contains));
  const [iban, setIban] = useState(str(c.counterparty_iban));
  const [purpose, setPurpose] = useState(str(c.purpose_contains));
  const [bookingText, setBookingText] = useState(str(c.booking_text_contains));
  const [min, setMin] = useState(num(c.amount_min_cents));
  const [max, setMax] = useState(num(c.amount_max_cents));
  const [direction, setDirection] = useState<string>(str(c.direction) || ANY);
  const [accountId, setAccountId] = useState<string>(str(c.account_id) || ANY);
  const [categoryId, setCategoryId] = useState<string | null>(rule?.category_id ?? null);
  const [priority, setPriority] = useState(String(rule?.priority ?? 100));
  const [active, setActive] = useState(rule?.is_active ?? true);

  const minCents = min.trim() ? parseMoneyInput(min) : null;
  const maxCents = max.trim() ? parseMoneyInput(max) : null;
  const amountsInvalid = (min.trim() !== "" && minCents === null) || (max.trim() !== "" && maxCents === null);
  const conditions = buildConditions({
    counterparty,
    iban,
    purpose,
    bookingText,
    minCents,
    maxCents,
    direction: direction === ANY ? null : (direction as "in" | "out"),
    accountId: accountId === ANY ? null : accountId,
  });
  const empty = Object.keys(conditions).length === 0;
  const rangeInvalid = minCents !== null && maxCents !== null && minCents > maxCents;
  const priorityValue = Number.parseInt(priority, 10);
  const valid =
    !empty &&
    !amountsInvalid &&
    !rangeInvalid &&
    categoryId !== null &&
    priorityValue >= 0 &&
    priorityValue <= 10000;

  const save = useMutation({
    mutationFn: async () => {
      if (!categoryId) throw new Error("category missing");
      const body = { category_id: categoryId, conditions, priority: priorityValue, is_active: active };
      if (rule) {
        return unwrap(
          await api.PATCH("/api/rules/{rule_id}", { params: { path: { rule_id: rule.id } }, body }),
        );
      }
      return unwrap(await api.POST("/api/rules", { body }));
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: rulesQuery.queryKey });
      toast.show(rule ? "Regel gespeichert." : "Regel angelegt.");
      onClose();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (valid) save.mutate();
  }

  return (
    <>
      <DialogTitle>{rule ? "Regel bearbeiten" : "Neue Regel"}</DialogTitle>
      <DialogDescription>
        Alle ausgefüllten Bedingungen müssen zugleich zutreffen. Groß- und Kleinschreibung spielt keine Rolle.
      </DialogDescription>
      <form onSubmit={submit} className="mt-4 space-y-4">
        <FormField
          label="Gegenpartei enthält"
          value={counterparty}
          onChange={(e) => setCounterparty(e.target.value)}
          maxLength={200}
        />
        <FormField
          label="Verwendungszweck enthält"
          value={purpose}
          onChange={(e) => setPurpose(e.target.value)}
          maxLength={200}
        />
        <FormField
          label="Buchungstext enthält"
          value={bookingText}
          onChange={(e) => setBookingText(e.target.value)}
          maxLength={100}
        />
        <FormField
          label="IBAN der Gegenpartei"
          value={iban}
          onChange={(e) => setIban(e.target.value)}
          autoComplete="off"
        />
        <div className="grid grid-cols-2 gap-3">
          <MoneyInput label="Betrag von (€)" value={min} onChange={setMin} />
          <MoneyInput label="Betrag bis (€)" value={max} onChange={setMax} />
        </div>
        <p className="-mt-2 text-xs text-text-muted">Ausgaben sind negativ, z. B. -50,00 bis -10,00.</p>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="rule-direction">Richtung</Label>
            <Select
              id="rule-direction"
              value={direction}
              onValueChange={setDirection}
              options={[
                { value: ANY, label: "Beliebig" },
                { value: "in", label: "Einnahmen" },
                { value: "out", label: "Ausgaben" },
              ]}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rule-account">Konto</Label>
            <Select
              id="rule-account"
              value={accountId}
              onValueChange={setAccountId}
              options={[
                { value: ANY, label: "Alle Konten" },
                ...accounts.map((a) => ({ value: a.id, label: a.name })),
              ]}
            />
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="rule-category">Kategorie</Label>
          <CategoryPicker id="rule-category" value={categoryId} onChange={setCategoryId} />
        </div>
        <div className="grid grid-cols-2 items-end gap-3">
          <FormField
            label="Priorität"
            type="number"
            min={0}
            max={10000}
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
            hint="Kleinere Zahl gilt zuerst."
          />
          <div className="flex items-center gap-3 pb-6">
            <Switch id="rule-active" checked={active} onCheckedChange={setActive} />
            <Label htmlFor="rule-active">Aktiv</Label>
          </div>
        </div>
        {empty && <p className="text-xs text-text-muted">Mindestens eine Bedingung ist nötig.</p>}
        {rangeInvalid && <p className="text-xs text-negative">„Von“ darf nicht größer sein als „bis“.</p>}
        {save.error && (
          <Alert tone="error">
            {mutationErrorMessage(save.error, { 422: "Bitte die Bedingungen prüfen, z. B. die IBAN." })}
          </Alert>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Abbrechen
          </Button>
          <Button type="submit" disabled={!valid || save.isPending}>
            Speichern
          </Button>
        </div>
      </form>
    </>
  );
}

export function RulesTab() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: rules = [], isPending } = useQuery(rulesQuery);
  const { data: categories = [] } = useQuery(categoriesQuery);
  const { data: accounts = [] } = useQuery(accountsQuery);
  const index = useMemo(() => categoryIndex(categories), [categories]);
  const [editing, setEditing] = useState<Rule | "new" | null>(null);
  const [deleting, setDeleting] = useState<Rule | null>(null);
  const [applied, setApplied] = useState<number | null>(null);

  const toggle = useMutation({
    mutationFn: async (rule: Rule) =>
      unwrap(
        await api.PATCH("/api/rules/{rule_id}", {
          params: { path: { rule_id: rule.id } },
          body: { is_active: !rule.is_active },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: rulesQuery.queryKey }),
    onError: (error) => toast.show(mutationErrorMessage(error) ?? "", "error"),
  });
  const remove = useMutation({
    mutationFn: async (rule: Rule) =>
      unwrap(await api.DELETE("/api/rules/{rule_id}", { params: { path: { rule_id: rule.id } } })),
    onSuccess: async () => {
      setDeleting(null);
      await queryClient.invalidateQueries({ queryKey: rulesQuery.queryKey });
      toast.show("Regel gelöscht.");
    },
  });
  const apply = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/rules/apply")),
    onSuccess: async (data) => {
      setApplied(data.updated);
      await invalidateLedger(queryClient);
    },
  });

  if (isPending) return <p className="py-6 text-sm text-text-muted">Lädt …</p>;

  return (
    <div className="space-y-4 pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-text-muted">
          Regeln ordnen neue und unkategorisierte Buchungen automatisch zu.
        </p>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            onClick={() => apply.mutate()}
            disabled={apply.isPending || rules.length === 0}
          >
            <Play aria-hidden /> Regeln jetzt anwenden
          </Button>
          <Button onClick={() => setEditing("new")} disabled={categories.length === 0}>
            <Plus aria-hidden /> Regel
          </Button>
        </div>
      </div>

      {applied !== null && (
        <Alert tone="success">
          {applied === 0
            ? "Keine Buchung wurde geändert."
            : applied === 1
              ? "1 Buchung wurde aktualisiert."
              : `${applied} Buchungen wurden aktualisiert.`}
        </Alert>
      )}
      {apply.error && <Alert tone="error">{mutationErrorMessage(apply.error)}</Alert>}

      {rules.length === 0 ? (
        <Card className="flex flex-col items-center gap-2 py-10 text-center">
          <CardTitle>Noch keine Regeln</CardTitle>
          <CardDescription>
            {categories.length === 0
              ? "Lege zuerst Kategorien an."
              : "Eine Regel entsteht auch automatisch, wenn du eine Buchung von Hand einer Kategorie zuordnest."}
          </CardDescription>
        </Card>
      ) : (
        <ul className="divide-y divide-border rounded-xl border border-border bg-surface">
          {rules.map((rule) => {
            const category = index.get(rule.category_id);
            const parent = category?.parent_id ? index.get(category.parent_id) : undefined;
            const summary = describeConditions(
              rule.conditions,
              (id) => accounts.find((a) => a.id === id)?.name,
            );
            return (
              <li
                key={rule.id}
                className={`flex items-start gap-3 px-3 py-3 sm:px-4 ${rule.is_active ? "" : "opacity-60"}`}
              >
                <div className="min-w-0 flex-1 space-y-1.5">
                  <p className="text-sm">{summary.length > 0 ? summary.join(" · ") : "Keine Bedingung"}</p>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-text-muted">→</span>
                    {category ? (
                      <CategoryBadge category={category} parentName={parent?.name} />
                    ) : (
                      <Badge>Kategorie fehlt</Badge>
                    )}
                    <Badge>{rule.source === "manual" ? "Selbst angelegt" : "Automatisch gelernt"}</Badge>
                    <span className="text-xs text-text-muted">Priorität {rule.priority}</span>
                  </div>
                </div>
                <Switch
                  checked={rule.is_active}
                  onCheckedChange={() => toggle.mutate(rule)}
                  aria-label={rule.is_active ? "Regel deaktivieren" : "Regel aktivieren"}
                />
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8"
                  onClick={() => setEditing(rule)}
                  aria-label="Regel bearbeiten"
                >
                  <Pencil aria-hidden />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8"
                  onClick={() => setDeleting(rule)}
                  aria-label="Regel löschen"
                >
                  <Trash2 aria-hidden />
                </Button>
              </li>
            );
          })}
        </ul>
      )}

      <Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent>
          {editing !== null && (
            <RuleForm
              key={editing === "new" ? "new" : editing.id}
              rule={editing === "new" ? null : editing}
              onClose={() => setEditing(null)}
            />
          )}
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title="Regel löschen?"
        confirmLabel="Regel löschen"
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
      >
        <p>Bereits zugeordnete Buchungen behalten ihre Kategorie.</p>
      </ConfirmDialog>
    </div>
  );
}
