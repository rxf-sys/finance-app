import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, ArrowDownToLine, ArrowUpFromLine, Pencil, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { api, type Goal, mutationErrorMessage, unwrap } from "@/api/client";
import { goalQuery, invalidateGoals } from "@/api/planning-queries";
import { Amount } from "@/components/amount";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { FormField } from "@/components/form-field";
import { GoalDialog } from "@/components/goal-dialog";
import { GoalProgress } from "@/components/goal-progress";
import { MoneyInput } from "@/components/money-input";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { toIsoDate } from "@/lib/dates";
import { formatDate } from "@/lib/format";
import { parseMoneyInput } from "@/lib/money";

type Direction = "deposit" | "withdrawal";

function ContributionForm({
  goal,
  direction,
  onDone,
}: {
  goal: Goal;
  direction: Direction;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const today = toIsoDate(new Date());
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(today);
  const [note, setNote] = useState("");
  const cents = parseMoneyInput(amount);
  const valid = cents !== null && cents > 0 && date !== "" && date <= today;

  const add = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/savings-goals/{goal_id}/contributions", {
          params: { path: { goal_id: goal.id } },
          body: {
            amount_cents: direction === "deposit" ? (cents ?? 0) : -(cents ?? 0),
            booked_on: date,
            note: note.trim() || null,
          },
        }),
      ),
    onSuccess: async () => {
      await invalidateGoals(queryClient);
      onDone();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (valid) add.mutate();
  }

  const error = mutationErrorMessage(add.error, {
    409: "Dieses Sparziel folgt einem Konto, hier gibt es keine Einzahlungen.",
    422: "Bitte Betrag und Datum prüfen. Das Datum darf nicht in der Zukunft liegen.",
  });

  return (
    <form onSubmit={submit} className="space-y-3 rounded-lg border border-border bg-surface-muted p-3">
      <p className="text-sm font-medium">{direction === "deposit" ? "Einzahlung" : "Entnahme"} erfassen</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <MoneyInput label="Betrag" value={amount} onChange={setAmount} required />
        <FormField
          label="Datum"
          type="date"
          value={date}
          max={today}
          onChange={(e) => setDate(e.target.value)}
          required
        />
      </div>
      <FormField
        label="Notiz (optional)"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        maxLength={200}
      />
      {error && <Alert tone="error">{error}</Alert>}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onDone}>
          Abbrechen
        </Button>
        <Button type="submit" disabled={add.isPending || !valid}>
          Speichern
        </Button>
      </div>
    </form>
  );
}

function GoalDetail({ goalId, onClose }: { goalId: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: goal } = useQuery(goalQuery(goalId));
  const [form, setForm] = useState<Direction | null>(null);
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const archive = useMutation({
    mutationFn: async (archived: boolean) =>
      unwrap(
        await api.PATCH("/api/savings-goals/{goal_id}", {
          params: { path: { goal_id: goalId } },
          body: { archived },
        }),
      ),
    onSuccess: async (_, archived) => {
      await invalidateGoals(queryClient);
      toast.show(archived ? "Sparziel archiviert." : "Sparziel wiederhergestellt.");
    },
    onError: () => toast.show("Das hat nicht geklappt.", "error"),
  });

  const removeContribution = useMutation({
    mutationFn: async (contributionId: string) =>
      unwrap(
        await api.DELETE("/api/savings-goals/{goal_id}/contributions/{contribution_id}", {
          params: { path: { goal_id: goalId, contribution_id: contributionId } },
        }),
      ),
    onSuccess: async () => {
      await invalidateGoals(queryClient);
      toast.show("Eintrag gelöscht.");
    },
    onError: () => toast.show("Löschen hat nicht geklappt.", "error"),
  });

  const remove = useMutation({
    mutationFn: async () =>
      unwrap(await api.DELETE("/api/savings-goals/{goal_id}", { params: { path: { goal_id: goalId } } })),
    onSuccess: async () => {
      setDeleting(false);
      onClose();
      queryClient.removeQueries({ queryKey: ["goals", "detail", goalId] });
      await invalidateGoals(queryClient);
      toast.show("Sparziel gelöscht.");
    },
    onError: () => toast.show("Löschen hat nicht geklappt.", "error"),
  });

  if (!goal) return <p className="mt-4 text-sm text-text-muted">Lädt …</p>;
  const linked = goal.account_id !== null;
  const entries = [...goal.contributions].reverse();

  return (
    <>
      <DialogTitle>{goal.name}</DialogTitle>
      <DialogDescription>
        {linked
          ? `Der Fortschritt folgt dem Kontostand von ${goal.account_name ?? "dem Konto"}.`
          : "Der Fortschritt ist die Summe deiner Einzahlungen und Entnahmen."}
        {goal.visibility === "private" && " Privat, nur du siehst dieses Ziel."}
      </DialogDescription>

      <div className="mt-4">
        <GoalProgress goal={goal} />
      </div>
      {goal.note && <p className="mt-3 text-sm whitespace-pre-line">{goal.note}</p>}

      <div className="mt-4 flex flex-wrap gap-2">
        {!linked && !goal.archived && (
          <>
            <Button onClick={() => setForm("deposit")}>
              <ArrowDownToLine aria-hidden /> Einzahlung
            </Button>
            <Button variant="secondary" onClick={() => setForm("withdrawal")}>
              <ArrowUpFromLine aria-hidden /> Entnahme
            </Button>
          </>
        )}
        <Button variant="secondary" onClick={() => setEditing(true)}>
          <Pencil aria-hidden /> Bearbeiten
        </Button>
        <Button
          variant="secondary"
          onClick={() => archive.mutate(!goal.archived)}
          disabled={archive.isPending}
        >
          {goal.archived ? <ArchiveRestore aria-hidden /> : <Archive aria-hidden />}
          {goal.archived ? "Wiederherstellen" : "Archivieren"}
        </Button>
        <Button variant="ghost" onClick={() => setDeleting(true)}>
          <Trash2 aria-hidden /> Löschen
        </Button>
      </div>

      {form && (
        <div className="mt-4">
          <ContributionForm key={form} goal={goal} direction={form} onDone={() => setForm(null)} />
        </div>
      )}

      {!linked && (
        <section className="mt-5">
          <h3 className="text-sm font-semibold">Einzahlungen und Entnahmen</h3>
          {entries.length === 0 ? (
            <p className="mt-1 text-sm text-text-muted">Noch nichts erfasst.</p>
          ) : (
            <ul className="mt-1 divide-y divide-border">
              {entries.map((entry) => (
                <li key={entry.id} className="flex items-center gap-3 py-2 text-sm">
                  <span className="w-24 shrink-0 text-text-muted tabular-nums">
                    {formatDate(entry.booked_on)}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-text-muted">{entry.note}</span>
                  <Amount cents={entry.amount_cents} />
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Eintrag vom ${formatDate(entry.booked_on)} löschen`}
                    onClick={() => removeContribution.mutate(entry.id)}
                    disabled={removeContribution.isPending}
                  >
                    <Trash2 aria-hidden />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <GoalDialog open={editing} onOpenChange={setEditing} goal={goal} />
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title="Sparziel löschen?"
        confirmLabel="Löschen"
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      >
        Das Sparziel „{goal.name}“ wird mit allen Einzahlungen gelöscht. Konten und Buchungen bleiben
        unverändert. Zum Aufräumen ohne Verlust kannst du es auch archivieren.
      </ConfirmDialog>
    </>
  );
}

export function GoalDetailDialog({ goalId, onClose }: { goalId: string | null; onClose: () => void }) {
  return (
    <Dialog open={goalId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>{goalId && <GoalDetail key={goalId} goalId={goalId} onClose={onClose} />}</DialogContent>
    </Dialog>
  );
}
