import { formatSignedMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

/** Expenses use the normal text color with a minus sign; only income is tinted. */
export function Amount({
  cents,
  currency = "EUR",
  className,
}: {
  cents: number;
  currency?: string;
  className?: string;
}) {
  return (
    <span className={cn("text-right tabular-nums", cents > 0 && "text-positive", className)}>
      {formatSignedMoney(cents, currency)}
    </span>
  );
}
