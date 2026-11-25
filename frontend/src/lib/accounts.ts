import { Banknote, CreditCard, Landmark, type LucideIcon, PiggyBank, Wallet } from "lucide-react";
import type { AccountKind, AccountVisibility } from "@/api/client";

export const ACCOUNT_KIND_ICON: Record<AccountKind, LucideIcon> = {
  giro: Landmark,
  credit_card: CreditCard,
  savings: PiggyBank,
  cash: Banknote,
  other: Wallet,
};

export const ACCOUNT_KIND_LABEL: Record<AccountKind, string> = {
  giro: "Girokonto",
  credit_card: "Kreditkarte",
  savings: "Sparkonto",
  cash: "Bargeld",
  other: "Sonstiges",
};

export const VISIBILITY_LABEL: Record<AccountVisibility, string> = {
  private: "Privat",
  shared: "Geteilt",
};

/** "DE89370400440532013000" -> "DE89 3704 0044 0532 0130 00" */
export function formatIban(iban: string): string {
  return iban.replace(/\s+/g, "").replace(/(.{4})(?=.)/g, "$1 ");
}
