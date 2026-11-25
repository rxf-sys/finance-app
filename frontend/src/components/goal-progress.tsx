import { Check } from "lucide-react";
import type { Goal } from "@/api/client";
import { categoryColor } from "@/lib/categories";
import { goalBarWidth, progressText, targetText } from "@/lib/goals";
import { cn } from "@/lib/utils";

/** Progress bar with "X von Y", percentage and the target date line. */
export function GoalProgress({ goal }: { goal: Goal }) {
  const color = goal.achieved ? "var(--positive)" : categoryColor(goal.color);
  const target = targetText(goal);
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="tabular-nums">{progressText(goal)}</span>
        <span className="font-medium tabular-nums">{goal.percent} %</span>
      </div>
      <div
        className="mt-1.5 h-2 rounded-full bg-surface-muted"
        role="progressbar"
        aria-valuenow={Math.min(goal.percent, 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${goal.name}: ${goal.percent} % erreicht`}
      >
        <div
          className="h-2 rounded-full"
          style={{ width: `${goalBarWidth(goal.percent)}%`, backgroundColor: color }}
        />
      </div>
      {target && (
        <p
          className={cn(
            "mt-1.5 flex items-center gap-1 text-xs text-text-muted",
            goal.achieved && "font-medium text-positive",
          )}
        >
          {goal.achieved && <Check className="size-3.5" aria-hidden />}
          {target}
        </p>
      )}
    </div>
  );
}
