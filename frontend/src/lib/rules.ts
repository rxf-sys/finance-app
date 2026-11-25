import type { RuleConditions } from "@/api/client";
import { formatMoney } from "./money";

type Conditions = Record<string, unknown>;

function text(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

function cents(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

/** Readable German summary of a rule's conditions, one phrase per set field. */
export function describeConditions(
  conditions: Conditions,
  accountName: (id: string) => string | undefined = () => undefined,
): string[] {
  const parts: string[] = [];
  const counterparty = text(conditions.counterparty_contains);
  if (counterparty) parts.push(`Gegenpartei enthält „${counterparty}“`);
  const iban = text(conditions.counterparty_iban);
  if (iban) parts.push(`IBAN ist ${iban}`);
  const purpose = text(conditions.purpose_contains);
  if (purpose) parts.push(`Verwendungszweck enthält „${purpose}“`);
  const bookingText = text(conditions.booking_text_contains);
  if (bookingText) parts.push(`Buchungstext enthält „${bookingText}“`);

  const min = cents(conditions.amount_min_cents);
  const max = cents(conditions.amount_max_cents);
  if (min !== null && max !== null) parts.push(`Betrag von ${formatMoney(min)} bis ${formatMoney(max)}`);
  else if (min !== null) parts.push(`Betrag ab ${formatMoney(min)}`);
  else if (max !== null) parts.push(`Betrag bis ${formatMoney(max)}`);

  if (conditions.direction === "in") parts.push("nur Einnahmen");
  if (conditions.direction === "out") parts.push("nur Ausgaben");
  const account = text(conditions.account_id);
  if (account) parts.push(`Konto ${accountName(account) ?? "unbekannt"}`);
  return parts;
}

export type RuleForm = {
  counterparty: string;
  iban: string;
  purpose: string;
  bookingText: string;
  /** Euro amounts as typed; parsed by the caller. */
  minCents: number | null;
  maxCents: number | null;
  direction: "in" | "out" | null;
  accountId: string | null;
};

/** Conditions for the API: only fields that are set, text trimmed. */
export function buildConditions(form: RuleForm): RuleConditions {
  const conditions: RuleConditions = {};
  if (form.counterparty.trim()) conditions.counterparty_contains = form.counterparty.trim();
  if (form.iban.trim()) conditions.counterparty_iban = form.iban.trim();
  if (form.purpose.trim()) conditions.purpose_contains = form.purpose.trim();
  if (form.bookingText.trim()) conditions.booking_text_contains = form.bookingText.trim();
  if (form.minCents !== null) conditions.amount_min_cents = form.minCents;
  if (form.maxCents !== null) conditions.amount_max_cents = form.maxCents;
  if (form.direction) conditions.direction = form.direction;
  if (form.accountId) conditions.account_id = form.accountId;
  return conditions;
}
