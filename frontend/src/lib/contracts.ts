import { House, Landmark, type LucideIcon, PhoneCall, Repeat, ShieldCheck, Tag, Zap } from "lucide-react";
import type { Contract, ContractInterval, ContractKind, ContractStatus } from "@/api/client";

export const CONTRACT_KIND_LABEL: Record<ContractKind, string> = {
  subscription: "Abo",
  insurance: "Versicherung",
  utilities: "Strom & Gas / Nebenkosten",
  telecom: "Telefon & Internet",
  rent: "Miete",
  loan: "Kredit",
  other: "Sonstiges",
};

export const CONTRACT_KIND_ICON: Record<ContractKind, LucideIcon> = {
  subscription: Repeat,
  insurance: ShieldCheck,
  utilities: Zap,
  telecom: PhoneCall,
  rent: House,
  loan: Landmark,
  other: Tag,
};

export const CONTRACT_INTERVAL_LABEL: Record<ContractInterval, string> = {
  weekly: "wöchentlich",
  monthly: "monatlich",
  quarterly: "vierteljährlich",
  half_yearly: "halbjährlich",
  yearly: "jährlich",
};

export const CONTRACT_STATUS_LABEL: Record<ContractStatus, string> = {
  detected: "Vorschlag",
  confirmed: "Aktiv",
  cancelled: "Gekündigt",
  ignored: "Ignoriert",
};

export function kindLabel(kind: string): string {
  return Object.hasOwn(CONTRACT_KIND_LABEL, kind) ? CONTRACT_KIND_LABEL[kind as ContractKind] : "Sonstiges";
}

export function kindIcon(kind: string): LucideIcon {
  return Object.hasOwn(CONTRACT_KIND_ICON, kind) ? CONTRACT_KIND_ICON[kind as ContractKind] : Tag;
}

/** Sum of the monthly equivalents of the given contracts, in cents. Payments are negative. */
export function monthlyTotal(contracts: Pick<Contract, "monthly_amount_cents">[]): number {
  return contracts.reduce((sum, c) => sum + c.monthly_amount_cents, 0);
}

export type KindShare = {
  kind: ContractKind;
  label: string;
  count: number;
  costCents: number;
  share: number;
};

/** Summary rows with German labels and the share of the total cost (0..1), biggest first. */
export function kindBreakdown(
  byKind: { kind: ContractKind; count: number; monthly_cost_cents: number }[],
): KindShare[] {
  const total = byKind.reduce((sum, row) => sum + row.monthly_cost_cents, 0);
  return byKind
    .map((row) => ({
      kind: row.kind,
      label: kindLabel(row.kind),
      count: row.count,
      costCents: row.monthly_cost_cents,
      share: total > 0 ? row.monthly_cost_cents / total : 0,
    }))
    .sort((a, b) => b.costCents - a.costCents || a.label.localeCompare(b.label, "de"));
}

// ------------------------------------------------------------------ deadlines

export type DeadlineTone = "danger" | "warning" | "neutral";

/** Whole calendar days from `today` to an ISO date (negative when in the past). */
export function daysUntil(iso: string, today: Date = new Date()): number {
  const [year, month, day] = iso.split("-").map(Number);
  const target = Date.UTC(year, month - 1, day);
  const start = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((target - start) / 86_400_000);
}

/** Red only for real problems: overdue or under 7 days. Under 30 days is a warning. */
export function deadlineTone(days: number): DeadlineTone {
  if (days < 7) return "danger";
  if (days < 30) return "warning";
  return "neutral";
}

/** "heute", "morgen", "in 12 Tagen", "seit 3 Tagen überfällig". */
export function deadlineDistance(days: number): string {
  if (days < 0) return days === -1 ? "seit 1 Tag überfällig" : `seit ${-days} Tagen überfällig`;
  if (days === 0) return "heute";
  if (days === 1) return "morgen";
  return `in ${days} Tagen`;
}

// ------------------------------------------------------------------ notice period

export type NoticeUnit = "days" | "months";

export const DAYS_PER_MONTH = 30;

/** The backend stores days only; a month counts as 30 days. */
export function noticeToDays(value: number, unit: NoticeUnit): number {
  return unit === "months" ? value * DAYS_PER_MONTH : value;
}

/** Shows full months as months, everything else as days. */
export function noticeFromDays(days: number): { value: number; unit: NoticeUnit } {
  if (days > 0 && days % DAYS_PER_MONTH === 0) return { value: days / DAYS_PER_MONTH, unit: "months" };
  return { value: days, unit: "days" };
}

export function formatNotice(days: number): string {
  const { value, unit } = noticeFromDays(days);
  if (unit === "months") return value === 1 ? "1 Monat" : `${value} Monate`;
  return value === 1 ? "1 Tag" : `${value} Tage`;
}

// ------------------------------------------------------------------ status transitions

export type ContractAction = "confirm" | "cancel" | "ignore" | "reactivate";

/** Mirrors the backend: which action is allowed from which status. */
const ALLOWED: Record<ContractAction, ContractStatus[]> = {
  confirm: ["detected"],
  cancel: ["confirmed"],
  ignore: ["detected", "confirmed"],
  reactivate: ["cancelled", "ignored"],
};

export function canDo(action: ContractAction, status: ContractStatus): boolean {
  return ALLOWED[action].includes(status);
}

/** Only manual contracts and ignored suggestions can be deleted. */
export function canDelete(contract: Pick<Contract, "is_manual" | "status">): boolean {
  return contract.is_manual || contract.status === "ignored";
}

/** Status tabs of the contract list ("detected" suggestions have their own section). */
export const LIST_STATUSES = ["confirmed", "cancelled", "ignored"] as const;
export type ListStatus = (typeof LIST_STATUSES)[number];

/** Filters of the contract list in the URL; defaults (active, all accounts) are left out. */
export type ContractSearch = { status?: Exclude<ListStatus, "confirmed">; account?: string };

/** Tolerant parsing of untrusted URL input: invalid values are dropped, never thrown. */
export function validateContractSearch(raw: Record<string, unknown>): ContractSearch {
  const result: ContractSearch = {};
  if (raw.status === "cancelled" || raw.status === "ignored") result.status = raw.status;
  if (typeof raw.account === "string" && raw.account.trim() !== "") result.account = raw.account;
  return result;
}
