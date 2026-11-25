/** Money is handled as integer cents everywhere; these helpers convert at the UI boundary. */

const MAX_CENTS = 10 ** 13;

const formatters = new Map<string, Intl.NumberFormat>();

function formatterFor(currency: string): Intl.NumberFormat {
  let formatter = formatters.get(currency);
  if (!formatter) {
    formatter = new Intl.NumberFormat("de-DE", { style: "currency", currency });
    formatters.set(currency, formatter);
  }
  return formatter;
}

/** 123456 -> "1.234,56 €" */
export function formatMoney(cents: number, currency = "EUR"): string {
  return formatterFor(currency).format(cents / 100);
}

/** Amount with an explicit sign for flows: "+1.234,56 €" for income, "-12,00 €" for expenses. */
export function formatSignedMoney(cents: number, currency = "EUR"): string {
  const text = formatMoney(cents, currency);
  return cents > 0 ? `+${text}` : text;
}

/** 123456 -> "1234,56", for pre-filling an input (no grouping, no currency symbol). */
export function formatMoneyInput(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  const euros = Math.floor(abs / 100);
  const rest = String(abs % 100).padStart(2, "0");
  return `${sign}${euros},${rest}`;
}

const GROUPED = /^\d{1,3}(\.\d{3})+$/;

/**
 * Parses German money input to integer cents. Accepts "1.234,56", "1234,5", "-12", "12.50", "+3,00".
 * A comma is always the decimal separator; a lone dot is a decimal separator unless it groups
 * thousands ("1.234"). Returns null for empty or invalid input.
 */
export function parseMoneyInput(input: string): number | null {
  let text = input.replace(/[\s€]/g, "");
  let negative = false;
  if (text.startsWith("-") || text.startsWith("+")) {
    negative = text.startsWith("-");
    text = text.slice(1);
  }
  if (text === "") return null;

  let whole: string;
  let fraction = "";
  const comma = text.indexOf(",");
  if (comma >= 0) {
    const head = text.slice(0, comma);
    fraction = text.slice(comma + 1);
    if (head.includes(".") ? !GROUPED.test(head) : !/^\d*$/.test(head)) return null;
    whole = head.replaceAll(".", "");
  } else if (GROUPED.test(text)) {
    whole = text.replaceAll(".", "");
  } else {
    const dot = text.indexOf(".");
    if (dot >= 0) {
      whole = text.slice(0, dot);
      fraction = text.slice(dot + 1);
    } else {
      whole = text;
    }
  }
  if (!/^\d*$/.test(whole) || !/^\d{0,2}$/.test(fraction)) return null;
  if (whole === "" && fraction === "") return null;

  const cents = Number(whole || "0") * 100 + Number(fraction.padEnd(2, "0") || "0");
  if (!Number.isSafeInteger(cents) || cents > MAX_CENTS) return null;
  const result = negative ? -cents : cents;
  return result === 0 ? 0 : result; // never -0
}
