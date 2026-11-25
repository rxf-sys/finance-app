import { useId } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { parseMoneyInput } from "@/lib/money";

type MoneyInputProps = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  required?: boolean;
};

/** Text input for German money amounts; shows an inline error for unparseable text. */
export function MoneyInput({ label, value, onChange, hint, required }: MoneyInputProps) {
  const id = useId();
  const invalid = value.trim() !== "" && parseMoneyInput(value) === null;
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        inputMode="decimal"
        autoComplete="off"
        placeholder="0,00"
        className="text-right tabular-nums"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={invalid}
        required={required}
      />
      {invalid ? (
        <p className="text-xs text-negative">Bitte einen Betrag wie 1.234,56 eingeben.</p>
      ) : (
        hint && <p className="text-xs text-text-muted">{hint}</p>
      )}
    </div>
  );
}
