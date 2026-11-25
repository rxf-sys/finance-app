import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { addMonths, monthLabel } from "@/lib/dates";

export function MonthSwitcher({ month, onChange }: { month: string; onChange: (month: string) => void }) {
  return (
    <div className="flex items-center gap-1">
      <Button
        variant="secondary"
        size="icon"
        onClick={() => onChange(addMonths(month, -1))}
        aria-label="Vorheriger Monat"
      >
        <ChevronLeft aria-hidden />
      </Button>
      <p className="min-w-36 text-center text-sm font-medium" aria-live="polite">
        {monthLabel(month)}
      </p>
      <Button
        variant="secondary"
        size="icon"
        onClick={() => onChange(addMonths(month, 1))}
        aria-label="Nächster Monat"
      >
        <ChevronRight aria-hidden />
      </Button>
    </div>
  );
}
