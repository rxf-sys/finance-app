import type { components } from "@/api/schema";

type Schemas = components["schemas"];
export type BankConnection = Schemas["ConnectionOut"];
export type BankConnectionStatus = BankConnection["status"];
export type Aspsp = Schemas["AspspOut"];
export type ProviderAccount = Schemas["ProviderAccountOut"];
export type SyncRun = Schemas["SyncRunOut"];

/** German notices for the error codes the bank callback puts into `/bank?error=`. */
const ERROR_MESSAGES: Record<string, string> = {
  login: "Deine Anmeldung ist abgelaufen. Bitte melde dich an und verbinde die Bank erneut.",
  invalid_state: "Die Anfrage ist abgelaufen oder ungültig. Bitte starte die Verbindung noch einmal.",
  denied: "Der Zugriff wurde bei der Bank nicht freigegeben. Es wurde nichts verbunden.",
  rate_limited: "Die Bank nimmt gerade keine weiteren Anfragen an. Bitte versuche es später noch einmal.",
  bank_error: "Die Bank hat einen Fehler gemeldet. Bitte versuche es später noch einmal.",
};
const UNKNOWN_ERROR = "Die Verbindung zur Bank hat nicht geklappt. Bitte versuche es noch einmal.";

export function bankErrorMessage(code: string): string {
  return Object.hasOwn(ERROR_MESSAGES, code) ? ERROR_MESSAGES[code] : UNKNOWN_ERROR;
}

/**
 * German text for the English `last_error` / sync-run `error` strings the backend stores
 * (constants in app/banking/sync.py and app/api/banking.py). Unknown strings get a generic text.
 */
const STORED_ERRORS: Record<string, string> = {
  "The bank limits requests, will retry later":
    "Die Bank begrenzt gerade die Abrufe. Der nächste Versuch läuft automatisch.",
  "Bank consent expired, please connect again": "Die Zustimmung ist abgelaufen. Bitte verbinde die Bank neu.",
  "Fetching from the bank failed": "Der Abruf bei der Bank ist fehlgeschlagen.",
  "Authorisation was not completed": "Die Freigabe bei der Bank wurde nicht abgeschlossen.",
  "Creating the bank session failed": "Die Verbindung zur Bank konnte nicht eingerichtet werden.",
};
const UNKNOWN_STORED_ERROR = "Beim letzten Abruf ist ein Fehler aufgetreten.";

export function storedErrorText(message: string): string {
  return Object.hasOwn(STORED_ERRORS, message) ? STORED_ERRORS[message] : UNKNOWN_STORED_ERROR;
}

export const STATUS_LABEL: Record<BankConnectionStatus, string> = {
  pending: "Wartet auf die Bank",
  active: "Aktiv",
  expired: "Abgelaufen",
  revoked: "Widerrufen",
  error: "Fehler",
};

/** Expired, revoked and failed connections can be set up again for the same bank. */
export function canReconnect(status: BankConnectionStatus): boolean {
  return status === "expired" || status === "revoked" || status === "error";
}

export type ConsentTone = "expired" | "warning" | "ok";

export const CONSENT_WARNING_DAYS = 14;

/** Red only when the consent is over; a warning under 14 days. */
export function consentTone(validUntil: string, now: Date = new Date()): ConsentTone {
  const remaining = new Date(validUntil).getTime() - now.getTime();
  if (remaining <= 0) return "expired";
  if (remaining < CONSENT_WARNING_DAYS * 86_400_000) return "warning";
  return "ok";
}

/** "Bitte warte noch 5 Minuten" for a Retry-After value in seconds. */
export function formatRetryAfter(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "Bitte versuche es gleich noch einmal";
  const minutes = Math.ceil(seconds / 60);
  if (minutes <= 1) return "Bitte warte noch eine Minute";
  return `Bitte warte noch ${minutes} Minuten`;
}

/** Retry-After header (delta seconds) to a number; null when missing or not numeric. */
export function parseRetryAfter(header: string | null): number | null {
  if (!header || !/^\d+$/.test(header.trim())) return null;
  return Number(header.trim());
}

/** Case-insensitive name search over the bank list. */
export function filterAspsps(banks: Aspsp[], query: string): Aspsp[] {
  const needle = query.trim().toLocaleLowerCase("de");
  if (!needle) return banks;
  return banks.filter((bank) => bank.name.toLocaleLowerCase("de").includes(needle));
}
