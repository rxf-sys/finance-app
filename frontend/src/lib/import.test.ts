import { describe, expect, it } from "vitest";
import {
  buildFormat,
  bytesToBase64,
  checkUploadFile,
  describeDateFormat,
  describeMissing,
  fileToBase64,
  MAX_UPLOAD_BYTES,
  type Roles,
  rolesFromFormat,
  settingsFromFormat,
} from "./import";

const HEADERS = ["Buchungstag", "Valuta", "Name", "IBAN", "Verwendungszweck", "Betrag", "Notiz"];
const SETTINGS = {
  delimiter: ";",
  dateFormat: "%d.%m.%Y",
  decimalSeparator: ",",
  headerLine: 1,
} as const;
const ROLES: Roles = [
  "booking_date",
  "value_date",
  "counterparty_name",
  "counterparty_iban",
  "purpose",
  "amount",
  "ignore",
];

describe("bytesToBase64", () => {
  it("matches the standard encoding", () => {
    expect(bytesToBase64(new TextEncoder().encode("Grüße;1,50"))).toBe("R3LDvMOfZTsxLDUw");
    expect(bytesToBase64(new Uint8Array())).toBe("");
  });

  it("handles inputs larger than one chunk", () => {
    const bytes = new Uint8Array(100_000).map((_, i) => i % 251);
    const decoded = Uint8Array.from(atob(bytesToBase64(bytes)), (char) => char.charCodeAt(0));
    expect(decoded).toEqual(bytes);
  });

  it("encodes a Blob", async () => {
    expect(await fileToBase64(new Blob(["a;b"]))).toBe("YTti");
  });
});

describe("checkUploadFile", () => {
  it("accepts csv and txt up to 5 MB", () => {
    expect(checkUploadFile({ name: "umsaetze.CSV", size: 1000 })).toBeNull();
    expect(checkUploadFile({ name: "export.txt", size: MAX_UPLOAD_BYTES })).toBeNull();
  });

  it("explains rejections in German", () => {
    expect(checkUploadFile({ name: "x.csv", size: MAX_UPLOAD_BYTES + 1 })).toContain("5 MB");
    expect(checkUploadFile({ name: "x.pdf", size: 10 })).toContain("CSV");
    expect(checkUploadFile({ name: "x.csv", size: 0 })).toContain("leer");
  });
});

describe("buildFormat", () => {
  it("builds a CsvFormat from the role table", () => {
    const result = buildFormat(HEADERS, ROLES, SETTINGS);
    expect(result.problems).toEqual([]);
    expect(result.format).toEqual({
      encoding: "auto",
      delimiter: ";",
      quotechar: '"',
      header_row: 0,
      date_format: "%d.%m.%Y",
      decimal_separator: ",",
      thousands_separator: ".",
      columns: {
        booking_date: "Buchungstag",
        value_date: "Valuta",
        amount: "Betrag",
        debit: null,
        credit: null,
        currency: null,
        counterparty_name: "Name",
        counterparty_iban: "IBAN",
        purpose: "Verwendungszweck",
        booking_text: null,
        balance: null,
      },
    });
  });

  it("joins several columns of a multi role into a list", () => {
    const roles: Roles = [...ROLES];
    roles[6] = "purpose";
    const result = buildFormat(HEADERS, roles, SETTINGS);
    expect(result.format?.columns.purpose).toEqual(["Verwendungszweck", "Notiz"]);
  });

  it("supports Soll/Haben instead of Betrag", () => {
    const roles: Roles = [...ROLES];
    roles[5] = "debit";
    roles[6] = "credit";
    const result = buildFormat(HEADERS, roles, SETTINGS);
    expect(result.format?.columns).toMatchObject({ amount: null, debit: "Betrag", credit: "Notiz" });
  });

  it("derives separators and the header row from the settings", () => {
    const result = buildFormat(HEADERS, ROLES, { ...SETTINGS, decimalSeparator: ".", headerLine: 4 });
    expect(result.format).toMatchObject({ thousands_separator: ",", header_row: 3 });
    expect(buildFormat(HEADERS, ROLES, { ...SETTINGS, headerLine: null }).format?.header_row).toBeNull();
  });

  it("keeps encoding and sign column from the base format", () => {
    const base = buildFormat(HEADERS, ROLES, SETTINGS).format;
    if (!base) throw new Error("base format expected");
    const withSign = {
      ...base,
      encoding: "cp1252" as const,
      columns: { ...base.columns, sign_column: "Notiz", debit_markers: ["S"] },
    };
    const result = buildFormat(HEADERS, ROLES, SETTINGS, withSign);
    expect(result.format).toMatchObject({
      encoding: "cp1252",
      columns: { sign_column: "Notiz", debit_markers: ["S"] },
    });
  });

  it("reports missing and conflicting roles in German", () => {
    const none = buildFormat(
      HEADERS,
      HEADERS.map(() => "ignore"),
      SETTINGS,
    );
    expect(none.format).toBeNull();
    expect(none.problems).toEqual([
      "Bitte eine Spalte als Buchungsdatum zuordnen.",
      "Bitte eine Spalte als Betrag (oder Soll und Haben) zuordnen.",
    ]);

    const both: Roles = [...ROLES];
    both[6] = "debit";
    expect(buildFormat(HEADERS, both, SETTINGS).problems).toEqual([
      "Betrag und Soll/Haben schließen sich aus.",
    ]);

    const twice: Roles = [...ROLES];
    twice[1] = "booking_date";
    expect(buildFormat(HEADERS, twice, SETTINGS).problems).toEqual([
      "„Buchungsdatum“ ist mehrfach zugeordnet.",
    ]);
  });
});

describe("rolesFromFormat", () => {
  it("is the inverse of buildFormat, matching headers loosely", () => {
    const built = buildFormat(HEADERS, ROLES, SETTINGS).format;
    if (!built) throw new Error("format expected");
    expect(rolesFromFormat(HEADERS, built.columns)).toEqual(ROLES);
    const shouting = HEADERS.map((h) => h.toUpperCase());
    expect(rolesFromFormat(shouting, built.columns)).toEqual(ROLES);
  });

  it("ignores names that are not in the file", () => {
    const roles = rolesFromFormat(["Datum", "Betrag"], {
      booking_date: "Datum",
      amount: "Betrag",
      counterparty_name: ["Zahlungsempfänger*in", "Zahlungspflichtige*r"],
    });
    expect(roles).toEqual(["booking_date", "amount"]);
  });
});

describe("settingsFromFormat", () => {
  it("shows the header row 1-based", () => {
    const format = buildFormat(HEADERS, ROLES, { ...SETTINGS, headerLine: 3 }).format;
    if (!format) throw new Error("format expected");
    expect(settingsFromFormat(format)).toEqual({ ...SETTINGS, headerLine: 3 });
  });
});

describe("describeMissing", () => {
  it("translates server field names", () => {
    expect(describeMissing(["booking_date", "amount"])).toBe("Buchungsdatum, Betrag");
    expect(describeMissing(["date_format"])).toBe("Datumsformat");
  });
});

describe("describeDateFormat", () => {
  it("shows strptime formats in German tokens", () => {
    expect(describeDateFormat("%d.%m.%Y")).toBe("TT.MM.JJJJ");
    expect(describeDateFormat(["%d.%m.%y", "%d.%m.%Y"])).toBe("TT.MM.JJ oder TT.MM.JJJJ");
  });
});
