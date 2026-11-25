import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link2, Lock, Plus, Target } from "lucide-react";
import { useState } from "react";
import type { Goal } from "@/api/client";
import { goalsQuery } from "@/api/planning-queries";
import { GoalDetailDialog } from "@/components/goal-detail-dialog";
import { GoalDialog } from "@/components/goal-dialog";
import { GoalProgress } from "@/components/goal-progress";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { categoryColor, categoryIcon } from "@/lib/categories";
import { sortGoals } from "@/lib/goals";
import { cn } from "@/lib/utils";

function GoalCard({ goal, onOpen }: { goal: Goal; onOpen: () => void }) {
  const Icon = categoryIcon(goal.icon);
  const color = categoryColor(goal.color);
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className={cn(
          "block w-full rounded-xl border bg-surface p-4 text-left hover:bg-surface-muted",
          goal.achieved ? "border-positive/40" : "border-border",
          goal.archived && "opacity-70",
        )}
      >
        <div className="mb-3 flex items-center gap-3">
          <span
            className="flex size-9 shrink-0 items-center justify-center rounded-lg"
            style={{ color, backgroundColor: `color-mix(in srgb, ${color} 14%, transparent)` }}
          >
            <Icon className="size-4" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold">{goal.name}</p>
            <p className="flex items-center gap-2 text-xs text-text-muted">
              {goal.archived && <span>Archiviert</span>}
              {goal.account_name && (
                <span className="flex items-center gap-1 truncate">
                  <Link2 className="size-3" aria-hidden />
                  {goal.account_name}
                </span>
              )}
              {goal.visibility === "private" && (
                <span className="flex items-center gap-1">
                  <Lock className="size-3" aria-hidden />
                  Privat
                </span>
              )}
            </p>
          </div>
        </div>
        <GoalProgress goal={goal} />
      </button>
    </li>
  );
}

export function GoalsPage() {
  const [showArchived, setShowArchived] = useState(false);
  const { data = [], isPending } = useQuery({
    ...goalsQuery(showArchived),
    placeholderData: keepPreviousData,
  });
  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const goals = sortGoals(data);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Sparziele</h1>
        <div className="flex flex-wrap items-center gap-4">
          <label htmlFor="goals-archived" className="flex items-center gap-2 text-sm">
            <Checkbox
              id="goals-archived"
              checked={showArchived}
              onCheckedChange={(v) => setShowArchived(v === true)}
            />
            Archivierte anzeigen
          </label>
          <Button onClick={() => setCreating(true)}>
            <Plus aria-hidden />
            Neues Sparziel
          </Button>
        </div>
      </div>

      {isPending ? null : goals.length === 0 ? (
        <Card className="flex flex-col items-center gap-3 py-10 text-center">
          <Target className="size-8 text-text-muted" aria-hidden />
          <CardTitle>{showArchived ? "Keine Sparziele" : "Noch keine Sparziele"}</CardTitle>
          <CardDescription>
            Lege ein Ziel fest, zum Beispiel den Urlaub oder eine Rücklage, und verfolge den Fortschritt.
          </CardDescription>
          <Button onClick={() => setCreating(true)}>Sparziel anlegen</Button>
        </Card>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {goals.map((goal) => (
            <GoalCard key={goal.id} goal={goal} onOpen={() => setOpenId(goal.id)} />
          ))}
        </ul>
      )}

      <GoalDialog open={creating} onOpenChange={setCreating} onSaved={(goal) => setOpenId(goal.id)} />
      <GoalDetailDialog goalId={openId} onClose={() => setOpenId(null)} />
    </div>
  );
}
