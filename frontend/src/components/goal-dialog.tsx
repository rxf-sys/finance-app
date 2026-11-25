import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { type FormEvent, useState } from "react";
import { api, type Goal, mutationErrorMessage, unwrap } from "@/api/client";
import { invalidateGoals } from "@/api/planning-queries";
import { accountsQuery } from "@/api/queries";
import { FormField } from "@/components/form-field";
import { MoneyInput } from "@/components/money-input";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { CHART_TOKENS, categoryColor, categoryIcon } from "@/lib/categories";
import { DEFAULT_GOAL_COLOR, DEFAULT_GOAL_ICON, GOAL_ICONS, mustBePrivate } from "@/lib/goals";
import { formatMoneyInput, parseMoneyInput } from "@/lib/money";
import { cn } from "@/lib/utils";

const NO_ACCOUNT = "none";

type Visibility = "shared" | "private";

const VISIBILITY_OPTIONS = [
  { value: "shared", label: "Geteilt (Haushalt)" },
  { value: "private", label: "Privat (nur ich)" },
];

function GoalForm({ goal, onDone }: { goal?: Goal; onDone: (saved?: Goal) => void }) {
  const queryClient = useQueryClient();
  const { data: accounts = [] } = useQuery(accountsQuery);
  const [name, setName] = useState(goal?.name ?? "");
  const [target, setTarget] = useState(goal ? formatMoneyInput(goal.target_cents) : "");
  const [targetDate, setTargetDate] = useState(goal?.target_date ?? "");
  const [accountId, setAccountId] = useState(goal?.account_id ?? NO_ACCOUNT);
  const [visibility, setVisibility] = useState<Visibility>(goal?.visibility ?? "shared");
  const [icon, setIcon] = useState(goal?.icon ?? DEFAULT_GOAL_ICON);
  const [color, setColor] = useState(goal?.color ?? DEFAULT_GOAL_COLOR);
  const [note, setNote] = useState(goal?.note ?? "");

  const linked = accounts.find((a) => a.id === accountId);
  const forcedPrivate = mustBePrivate(linked?.visibility);
  const effectiveVisibility: Visibility = forcedPrivate ? "private" : visibility;
  const targetCents = parseMoneyInput(target);
  const valid = name.trim() !== "" && targetCents !== null && targetCents > 0;

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        name: name.trim(),
        target_cents: targetCents ?? 0,
        target_date: targetDate || null,
        account_id: accountId === NO_ACCOUNT ? null : accountId,
        visibility: effectiveVisibility,
        icon,
        color,
        note: note.trim() || null,
      };
      if (goal) {
        return unwrap(
          await api.PATCH("/api/savings-goals/{goal_id}", {
            params: { path: { goal_id: goal.id } },
            body,
          }),
        );
      }
      return unwrap(await api.POST("/api/savings-goals", { body }));
    },
    onSuccess: async (saved) => {
      await invalidateGoals(queryClient);
      onDone(saved);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (valid) save.mutate();
  }

  const error = mutationErrorMessage(save.error, {
    422: forcedPrivate
      ? "Bitte Name, Zielbetrag und ein Zieldatum in der Zukunft prüfen."
      : "Bitte Name, Zielbetrag und ein Zieldatum in der Zukunft prüfen. Ein Ziel auf einem privaten Konto muss privat sein.",
  });

  return (
    <form onSubmit={submit} className="mt-4 space-y-4">
      <FormField
        label="Name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        maxLength={100}
        required
      />
      <MoneyInput label="Zielbetrag" value={target} onChange={setTarget} required />
      <FormField
        label="Zieldatum (optional)"
        type="date"
        value={targetDate}
        onChange={(e) => setTargetDate(e.target.value)}
        hint="Daraus wird berechnet, wie viel du pro Monat zurücklegen solltest."
      />
      <div className="space-y-1.5">
        <Label htmlFor="goal-account">Mit Konto verknüpfen (optional)</Label>
        <Select
          id="goal-account"
          value={accountId}
          onValueChange={setAccountId}
          options={[
            { value: NO_ACCOUNT, label: "Nicht verknüpft" },
            ...accounts
              .filter((a) => !a.is_archived || a.id === goal?.account_id)
              .map((a) => ({ value: a.id, label: a.name })),
          ]}
        />
        <p className="text-xs text-text-muted">
          {accountId === NO_ACCOUNT
            ? "Ohne Konto zählst du Einzahlungen und Entnahmen selbst."
            : "Der Fortschritt ist der Kontostand. Einzahlungen und Entnahmen sind dann abgeschaltet."}
        </p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="goal-visibility">Sichtbarkeit</Label>
        <Select
          id="goal-visibility"
          value={effectiveVisibility}
          onValueChange={(v) => setVisibility(v as Visibility)}
          options={VISIBILITY_OPTIONS}
          disabled={forcedPrivate}
        />
        <p className="text-xs text-text-muted">
          {forcedPrivate
            ? "Das Konto ist privat, deshalb ist auch das Sparziel privat."
            : effectiveVisibility === "private"
              ? "Nur du siehst dieses Sparziel."
              : "Alle im Haushalt sehen dieses Sparziel."}
        </p>
      </div>
      <fieldset className="space-y-1.5">
        <legend className="text-sm font-medium">Symbol</legend>
        <div className="grid grid-cols-6 gap-1.5">
          {GOAL_ICONS.map((choice) => {
            const Icon = categoryIcon(choice);
            return (
              <button
                key={choice}
                type="button"
                aria-label={choice}
                aria-pressed={icon === choice}
                onClick={() => setIcon(choice)}
                className={cn(
                  "flex size-9 items-center justify-center rounded-lg border",
                  icon === choice
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-text-muted hover:bg-surface-muted",
                )}
              >
                <Icon className="size-4" aria-hidden />
              </button>
            );
          })}
        </div>
      </fieldset>
      <fieldset className="space-y-1.5">
        <legend className="text-sm font-medium">Farbe</legend>
        <div className="flex flex-wrap gap-2">
          {CHART_TOKENS.map((token, index) => (
            <button
              key={token}
              type="button"
              aria-label={`Farbe ${index + 1}`}
              aria-pressed={color === token}
              onClick={() => setColor(token)}
              className="flex size-9 items-center justify-center rounded-full border-2 border-transparent text-white aria-pressed:border-text"
              style={{ backgroundColor: categoryColor(token) }}
            >
              {color === token && (
                <Check className="size-4 text-on-primary mix-blend-difference" aria-hidden />
              )}
            </button>
          ))}
        </div>
      </fieldset>
      <div className="space-y-1.5">
        <Label htmlFor="goal-note">Notiz (optional)</Label>
        <Textarea id="goal-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
      </div>
      {error && <Alert tone="error">{error}</Alert>}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={() => onDone()}>
          Abbrechen
        </Button>
        <Button type="submit" disabled={save.isPending || !valid}>
          {goal ? "Speichern" : "Sparziel anlegen"}
        </Button>
      </div>
    </form>
  );
}

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Edit this goal; without it the dialog creates one. */
  goal?: Goal;
  onSaved?: (goal: Goal) => void;
};

export function GoalDialog({ open, onOpenChange, goal, onSaved }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>{goal ? "Sparziel bearbeiten" : "Neues Sparziel"}</DialogTitle>
        <DialogDescription>Ein Betrag, den du bis zu einem Datum zurücklegen möchtest.</DialogDescription>
        {open && (
          <GoalForm
            goal={goal}
            onDone={(saved) => {
              if (saved) onSaved?.(saved);
              onOpenChange(false);
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
