import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { api, type BudgetStatus, mutationErrorMessage, unwrap } from "@/api/client";
import { invalidateBudgets } from "@/api/planning-queries";
import { categoriesQuery } from "@/api/queries";
import { CategoryBadge } from "@/components/category-badge";
import { CategoryPicker } from "@/components/category-picker";
import { MoneyInput } from "@/components/money-input";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { categoryIndex } from "@/lib/categories";
import { formatMoneyInput, parseMoneyInput } from "@/lib/money";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Edit this budget; without it the dialog creates one. */
  budget?: BudgetStatus;
};

function BudgetForm({ budget, onDone }: { budget?: BudgetStatus; onDone: () => void }) {
  const queryClient = useQueryClient();
  const { data: categories = [] } = useQuery(categoriesQuery);
  const [categoryId, setCategoryId] = useState<string | null>(budget?.category_id ?? null);
  const [amount, setAmount] = useState(budget ? formatMoneyInput(budget.amount_cents) : "");
  const [rollover, setRollover] = useState(budget?.rollover ?? false);

  const cents = parseMoneyInput(amount);
  const valid = cents !== null && cents > 0 && (budget !== undefined || categoryId !== null);

  const save = useMutation({
    mutationFn: async () => {
      if (budget) {
        return unwrap(
          await api.PATCH("/api/budgets/{budget_id}", {
            params: { path: { budget_id: budget.id } },
            body: { amount_cents: cents ?? undefined, rollover },
          }),
        );
      }
      return unwrap(
        await api.POST("/api/budgets", {
          body: { category_id: categoryId ?? "", amount_cents: cents ?? 0, rollover },
        }),
      );
    },
    onSuccess: async () => {
      await invalidateBudgets(queryClient);
      onDone();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (valid) save.mutate();
  }

  const error = mutationErrorMessage(save.error, {
    409: "Für diese Kategorie gibt es schon ein Budget.",
    422: "Budgets gibt es nur für Ausgabenkategorien, mit einem Betrag über 0.",
  });
  const category = budget ? categoryIndex(categories).get(budget.category_id) : undefined;

  return (
    <form onSubmit={submit} className="mt-4 space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="budget-category">Kategorie</Label>
        {budget ? (
          <div>
            {category ? (
              <CategoryBadge category={category} />
            ) : (
              <span className="text-sm">{budget.category_name}</span>
            )}
          </div>
        ) : (
          <CategoryPicker id="budget-category" kind="expense" value={categoryId} onChange={setCategoryId} />
        )}
        <p className="text-xs text-text-muted">
          Ein Budget auf eine Oberkategorie zählt die Ausgaben ihrer Unterkategorien mit.
        </p>
      </div>
      <MoneyInput label="Betrag pro Monat" value={amount} onChange={setAmount} required />
      <div className="flex items-start justify-between gap-4">
        <div>
          <Label htmlFor="budget-rollover">Rest in den nächsten Monat mitnehmen</Label>
          <p className="text-xs text-text-muted">
            Was im Vormonat übrig blieb, erhöht das Limit des Monats einmalig.
          </p>
        </div>
        <Switch id="budget-rollover" checked={rollover} onCheckedChange={setRollover} />
      </div>
      {error && <Alert tone="error">{error}</Alert>}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onDone}>
          Abbrechen
        </Button>
        <Button type="submit" disabled={save.isPending || !valid}>
          {budget ? "Speichern" : "Budget anlegen"}
        </Button>
      </div>
    </form>
  );
}

export function BudgetDialog({ open, onOpenChange, budget }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>{budget ? "Budget bearbeiten" : "Neues Budget"}</DialogTitle>
        <DialogDescription>Ein Monatslimit für eine Ausgabenkategorie.</DialogDescription>
        {open && <BudgetForm budget={budget} onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  );
}
