import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Pencil, PiggyBank, Plus, Repeat, Trash2 } from "lucide-react";
import { useState } from "react";
import { api, type BudgetStatus, unwrap } from "@/api/client";
import { budgetStatusQuery, invalidateBudgets } from "@/api/planning-queries";
import { categoriesQuery } from "@/api/queries";
import { BudgetDialog } from "@/components/budget-dialog";
import { CategoryIconTile } from "@/components/category-badge";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { MonthSwitcher } from "@/components/month-switcher";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { BUDGET_BAR_COLOR, BUDGET_STATE_LABEL, barWidth, budgetState, rolloverCents } from "@/lib/budgets";
import { categoryIndex } from "@/lib/categories";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

export function BudgetRow({
  budget,
  onEdit,
  onDelete,
  compact,
}: {
  budget: BudgetStatus;
  onEdit?: () => void;
  onDelete?: () => void;
  compact?: boolean;
}) {
  const { data: categories = [] } = useQuery(categoriesQuery);
  const category = categoryIndex(categories).get(budget.category_id) ?? null;
  const state = budgetState(budget.state);
  const carried = rolloverCents(budget);
  const remaining = budget.remaining_cents;
  return (
    <li className="flex items-start gap-3 py-3">
      <CategoryIconTile category={category} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-sm font-medium">{budget.category_name}</span>
          <span className="text-sm whitespace-nowrap tabular-nums">
            {formatMoney(budget.spent_cents)} von {formatMoney(budget.limit_cents)} ({budget.pct} %)
          </span>
        </div>
        <div
          className="mt-1.5 h-2 rounded-full bg-surface-muted"
          role="progressbar"
          aria-valuenow={Math.min(budget.pct, 100)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${budget.category_name}: ${budget.pct} % verbraucht`}
        >
          <div
            className="h-2 rounded-full"
            style={{ width: `${barWidth(budget.pct)}%`, backgroundColor: BUDGET_BAR_COLOR[state] }}
          />
        </div>
        <div className="mt-1 flex flex-wrap items-baseline justify-between gap-x-3 text-xs">
          <span
            className={cn(
              "text-text-muted",
              state === "exceeded" && "font-medium text-negative",
              state === "warning" && "font-medium text-warning",
            )}
          >
            {state === "exceeded"
              ? remaining < 0
                ? `${BUDGET_STATE_LABEL[state]} um ${formatMoney(-remaining)}`
                : "Limit erreicht"
              : `${BUDGET_STATE_LABEL[state]} · noch ${formatMoney(remaining)}`}
          </span>
          {!compact && budget.rollover && (
            <span className="flex items-center gap-1 text-text-muted">
              <Repeat className="size-3" aria-hidden />
              {carried > 0 ? `inkl. ${formatMoney(carried)} Übertrag` : "Übertrag aktiv, nichts übrig"}
            </span>
          )}
        </div>
      </div>
      {onEdit && onDelete && (
        <div className="flex shrink-0 gap-0.5">
          <Button
            variant="ghost"
            size="icon"
            onClick={onEdit}
            aria-label={`${budget.category_name} bearbeiten`}
          >
            <Pencil aria-hidden />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={onDelete}
            aria-label={`${budget.category_name} löschen`}
          >
            <Trash2 aria-hidden />
          </Button>
        </div>
      )}
    </li>
  );
}

export function BudgetsPage({ month }: { month: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: budgets } = useSuspenseQuery(budgetStatusQuery(month));
  const [editing, setEditing] = useState<BudgetStatus | "new" | null>(null);
  const [deleting, setDeleting] = useState<BudgetStatus | null>(null);

  const remove = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE("/api/budgets/{budget_id}", { params: { path: { budget_id: id } } })),
    onSuccess: async () => {
      setDeleting(null);
      await invalidateBudgets(queryClient);
      toast.show("Budget gelöscht.");
    },
    onError: () => toast.show("Löschen hat nicht geklappt.", "error"),
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Budgets</h1>
        <div className="flex flex-wrap items-center gap-3">
          <MonthSwitcher
            month={month}
            onChange={(next) => void navigate({ to: "/budgets", search: { month: next } })}
          />
          <Button onClick={() => setEditing("new")}>
            <Plus aria-hidden />
            Neues Budget
          </Button>
        </div>
      </div>

      {budgets.length === 0 ? (
        <Card className="flex flex-col items-center gap-3 py-10 text-center">
          <PiggyBank className="size-8 text-text-muted" aria-hidden />
          <CardTitle>Noch keine Budgets</CardTitle>
          <CardDescription>
            Lege ein Monatslimit für eine Ausgabenkategorie fest, zum Beispiel Lebensmittel.
          </CardDescription>
          <Button onClick={() => setEditing("new")}>Budget anlegen</Button>
        </Card>
      ) : (
        <Card className="py-2">
          <ul className="divide-y divide-border">
            {budgets.map((budget) => (
              <BudgetRow
                key={budget.id}
                budget={budget}
                onEdit={() => setEditing(budget)}
                onDelete={() => setDeleting(budget)}
              />
            ))}
          </ul>
        </Card>
      )}

      <BudgetDialog
        key={editing === "new" || editing === null ? "new" : editing.id}
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        budget={editing === "new" || editing === null ? undefined : editing}
      />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title="Budget löschen?"
        confirmLabel="Löschen"
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      >
        Das Budget „{deleting?.category_name}“ wird gelöscht. Buchungen bleiben unverändert.
      </ConfirmDialog>
    </div>
  );
}
