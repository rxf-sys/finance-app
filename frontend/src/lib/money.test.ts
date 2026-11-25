import { describe, expect, it } from "vitest";
import { formatMoney, formatMoneyInput, formatSignedMoney, parseMoneyInput } from "./money";

describe("parseMoneyInput", () => {
  it.each([
    ["1.234,56", 123456],
    ["1234,56", 123456],
    ["1234,5", 123450],
    ["0,07", 7],
    [",5", 50],
    ["12", 1200],
    ["12,", 1200],
    ["-12,50", -1250],
    ["+3,00", 300],
    ["12.50", 1250],
    ["1.234", 123400],
    ["1.234.567,89", 123456789],
    ["  7,00 € ", 700],
    ["0", 0],
    ["-0", 0],
  ])("parses %j to %j", (input, cents) => {
    expect(parseMoneyInput(input)).toBe(cents);
  });

  it.each([
    "",
    "   ",
    "-",
    ",",
    "abc",
    "12abc",
    "1,234,56",
    "1,234",
    "12,345",
    "12.345,6.7",
    "1..234,00",
    "--5",
    "1e5",
    "12-",
    "99999999999999999999",
    "1.23.4",
  ])("rejects %j", (input) => {
    expect(parseMoneyInput(input)).toBeNull();
  });
});

describe("formatMoney", () => {
  it("formats cents as German currency", () => {
    expect(formatMoney(123456)).toBe("1.234,56 €");
    expect(formatMoney(-5)).toBe("-0,05 €");
  });

  it("supports other currencies", () => {
    expect(formatMoney(1000, "USD")).toBe("10,00 $");
  });

  it("prefixes income with a plus sign", () => {
    expect(formatSignedMoney(1000)).toBe("+10,00 €");
    expect(formatSignedMoney(-1000)).toBe("-10,00 €");
  });
});

describe("formatMoneyInput", () => {
  it("round-trips through parseMoneyInput", () => {
    for (const cents of [0, 5, 100, 123456, -1250, -7]) {
      expect(parseMoneyInput(formatMoneyInput(cents))).toBe(cents);
    }
  });
});
