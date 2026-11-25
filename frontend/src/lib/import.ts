import type { components } from "@/api/schema";

type Schemas = components["schemas"];
export type CsvFormat = Schemas["CsvFormat"];
export type ColumnMap = Schemas["ColumnMap"];

// ------------------------------------------------------------------ upload helpers

/** The server rejects larger uploads with 413. */
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

/** German message when the file is unusable for upload, otherwise null. */
export function checkUploadFile(file: { name: string; size: number }): string | null {
  if (!/\.(csv|txt)$/i.test(file.name)) return "Bitte eine CSV- oder TXT-Datei wählen.";
  if (file.size === 0) return "Die Datei ist leer.";
  if (file.size > MAX_UPLOAD_BYTES) return "Die Datei ist größer als 5 MB und kann nicht importiert werden.";
  return null;
}

/** Base64 of raw bytes, built in chunks so large files do not overflow the call stack. */
export function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

export async function fileToBase64(file: Blob): Promise<string> {
  return bytesToBase64(new Uint8Array(await file.arrayBuffer()));
}

// ------------------------------------------------------------------ column roles

export type Role =
  | "booking_date"
  | "value_date"
  | "amount"
  | "debit"
  | "credit"
  | "currency"
  | "counterparty_name"
  | "counterparty_iban"
  | "purpose"
  | "booking_text"
  | "balance"
  | "ignore";

export const ROLE_LABEL: Record<Role, string> = {
  booking_date: "Buchungsdatum",
  value_date: "Wertstellung",
  amount: "Betrag",
  debit: "Soll",
  credit: "Haben",
  currency: "Währung",
  counterparty_name: "Gegenpartei",
  counterparty_iban: "IBAN",
  purpose: "Verwendungszweck",
  booking_text: "Buchungstext",
  balance: "Saldo",
  ignore: "ignorieren",
};

export const ROLES = Object.keys(ROLE_LABEL) as Role[];

/** Roles that may be fed by several columns; the server joins them. */
const MULTI_ROLES: readonly Role[] = ["counterparty_name", "counterparty_iban", "purpose"];

/** One role per column, indexed like the headers. */
export type Roles = Role[];

/** Header names are matched loosely on the server, so do the same here. */
export function normalizeHeader(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

function asList(value: string | string[] | null | undefined): string[] {
  if (value == null) return [];
  return Array.isArray(value) ? value : [value];
}

/** Which role each header plays under a given format. */
export function rolesFromFormat(headers: string[], columns: ColumnMap): Roles {
  const roles: Roles = headers.map(() => "ignore");
  const assign = (role: Role, names: string[]) => {
    for (const name of names) {
      const wanted = normalizeHeader(name);
      const index = headers.findIndex((h, i) => roles[i] === "ignore" && normalizeHeader(h) === wanted);
      if (index >= 0) roles[index] = role;
    }
  };
  assign("booking_date", asList(columns.booking_date));
  assign("value_date", asList(columns.value_date));
  assign("amount", asList(columns.amount));
  assign("debit", asList(columns.debit));
  assign("credit", asList(columns.credit));
  assign("currency", asList(columns.currency));
  assign("counterparty_name", asList(columns.counterparty_name));
  assign("counterparty_iban", asList(columns.counterparty_iban));
  assign("purpose", asList(columns.purpose));
  assign("booking_text", asList(columns.booking_text));
  assign("balance", asList(columns.balance));
  return roles;
}

// ------------------------------------------------------------------ mapping -> CsvFormat

export type FileSettings = {
  delimiter: CsvFormat["delimiter"];
  /** One strptime format, or the list a preset ships with. */
  dateFormat: string | string[];
  decimalSeparator: CsvFormat["decimal_separator"];
  /** 1-based line number of the header row; null lets the server detect it. */
  headerLine: number | null;
};

export function settingsFromFormat(format: CsvFormat): FileSettings {
  return {
    delimiter: format.delimiter,
    dateFormat: format.date_format,
    decimalSeparator: format.decimal_separator,
    headerLine: format.header_row == null ? null : format.header_row + 1,
  };
}

export type BuildResult = { format: CsvFormat; problems: [] } | { format: null; problems: string[] };

/**
 * Turns the editable mapping table into the CsvFormat the API expects.
 * `base` carries over what the table cannot edit (encoding, quote character, sign column).
 */
export function buildFormat(
  headers: string[],
  roles: Roles,
  settings: FileSettings,
  base?: CsvFormat | null,
): BuildResult {
  const problems: string[] = [];
  const byRole = (role: Role) => headers.filter((_, i) => roles[i] === role);

  for (const role of ROLES) {
    if (role === "ignore" || MULTI_ROLES.includes(role)) continue;
    if (byRole(role).length > 1) problems.push(`„${ROLE_LABEL[role]}“ ist mehrfach zugeordnet.`);
  }
  const bookingDate = byRole("booking_date")[0];
  if (!bookingDate) problems.push("Bitte eine Spalte als Buchungsdatum zuordnen.");

  const amount = byRole("amount")[0];
  const debit = byRole("debit")[0];
  const credit = byRole("credit")[0];
  if (!amount && !debit && !credit)
    problems.push("Bitte eine Spalte als Betrag (oder Soll und Haben) zuordnen.");
  if (amount && (debit || credit)) problems.push("Betrag und Soll/Haben schließen sich aus.");

  if (problems.length > 0 || !bookingDate) return { format: null, problems };

  const names = (role: Role): string | string[] | null => {
    const found = byRole(role);
    if (found.length === 0) return null;
    return found.length === 1 ? found[0] : found;
  };
  const single = (role: Role): string | null => byRole(role)[0] ?? null;

  // A sign column only makes sense together with its markers, and only while that column exists.
  const signColumn = base?.columns.sign_column;
  const keepSign =
    amount && signColumn && (base?.columns.debit_markers?.length ?? 0) > 0
      ? headers.find((h) => normalizeHeader(h) === normalizeHeader(signColumn))
      : undefined;

  const columns: ColumnMap = {
    booking_date: bookingDate,
    value_date: single("value_date"),
    amount: amount ?? null,
    debit: debit ?? null,
    credit: credit ?? null,
    currency: single("currency"),
    counterparty_name: names("counterparty_name"),
    counterparty_iban: names("counterparty_iban"),
    purpose: names("purpose"),
    booking_text: single("booking_text"),
    balance: single("balance"),
    ...(keepSign ? { sign_column: keepSign, debit_markers: base?.columns.debit_markers ?? [] } : {}),
  };

  const thousands =
    base && base.thousands_separator !== settings.decimalSeparator
      ? base.thousands_separator
      : settings.decimalSeparator === ","
        ? "."
        : ",";

  return {
    format: {
      encoding: base?.encoding ?? "auto",
      delimiter: settings.delimiter,
      quotechar: base?.quotechar ?? '"',
      header_row: settings.headerLine == null ? null : Math.max(0, settings.headerLine - 1),
      date_format: settings.dateFormat,
      decimal_separator: settings.decimalSeparator,
      thousands_separator: thousands,
      columns,
    },
    problems: [],
  };
}

/** German text for the server's `unmapped_required` field names. */
export function describeMissing(fields: string[]): string {
  const labels = fields.map((field) => {
    if (field === "date_format") return "Datumsformat";
    if (field === "booking_date") return "Buchungsdatum";
    if (field === "amount" || field === "debit" || field === "credit" || field === "amount/debit/credit")
      return "Betrag";
    return field in ROLE_LABEL ? ROLE_LABEL[field as Role] : field;
  });
  return [...new Set(labels)].join(", ");
}

/** "%d.%m.%Y" -> "TT.MM.JJJJ", for showing a strptime format to people. */
export function describeDateFormat(format: string | string[]): string {
  const one = (value: string) =>
    value.replaceAll("%d", "TT").replaceAll("%m", "MM").replaceAll("%Y", "JJJJ").replaceAll("%y", "JJ");
  return (Array.isArray(format) ? format : [format]).map(one).join(" oder ");
}
