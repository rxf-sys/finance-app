import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Check, TrendingUp } from "lucide-react";
import { api, type Contract, unwrap } from "@/api/client";
import { invalidateContracts } from "@/api/planning-queries";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { daysUntil, deadlineDistance, deadlineTone } from "@/lib/contracts";
import { formatDate } from "@/lib/format";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

const TONE_CLASS = {
  danger: "border-negative/40 bg-negative/10 text-negative",
  warning: "border-warning/40 bg-warning/10 text-warning",
  neutral: "border-border bg-surface-muted text-text-muted",
} as const;

/** "Kündigen bis TT.MM.JJJJ", colored by distance; the text carries the meaning, not the color. */
export function DeadlineBadge({ contract }: { contract: Pick<Contract, "cancellation_deadline"> }) {
  if (!contract.cancellation_deadline) return null;
  const days = daysUntil(contract.cancellation_deadline);
  const tone = deadlineTone(days);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
        TONE_CLASS[tone],
      )}
      title={deadlineDistance(days)}
    >
      <CalendarClock className="size-3.5" aria-hidden />
      Kündigen bis {formatDate(contract.cancellation_deadline)}
      <span className="font-normal">({deadlineDistance(days)})</span>
    </span>
  );
}

/** Old and new amount of an unacknowledged price change, with an acknowledge action. */
export function PriceChangeBadge({
  contract,
}: {
  contract: Pick<Contract, "id" | "unacknowledged_price_change">;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const change = contract.unacknowledged_price_change;
  const acknowledge = useMutation({
    mutationFn: async (changeId: string) =>
      unwrap(
        await api.POST("/api/contracts/{contract_id}/price-changes/{price_change_id}/acknowledge", {
          params: { path: { contract_id: contract.id, price_change_id: changeId } },
        }),
      ),
    onSuccess: () => invalidateContracts(queryClient),
    onError: () => toast.show("Das hat nicht geklappt. Bitte erneut versuchen.", "error"),
  });
  if (!change) return null;
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 rounded-full border border-warning/40 bg-warning/10 py-0.5 pr-1 pl-2 text-xs font-medium text-warning">
      <TrendingUp className="size-3.5" aria-hidden />
      Preisänderung: {formatMoney(Math.abs(change.old_amount_cents))} →{" "}
      {formatMoney(Math.abs(change.new_amount_cents))}
      <Button
        variant="ghost"
        size="sm"
        className="h-6 gap-1 px-2 text-xs"
        disabled={acknowledge.isPending}
        onClick={() => acknowledge.mutate(change.id)}
      >
        <Check aria-hidden />
        Zur Kenntnis genommen
      </Button>
    </span>
  );
}
