import { describe, expect, it } from "vitest";
import { buildConditions, describeConditions } from "./rules";

describe("describeConditions", () => {
  it("summarizes every condition in German", () => {
    expect(
      describeConditions(
        {
          counterparty_contains: "rewe",
          purpose_contains: "kartenzahlung",
          amount_min_cents: -5000,
          amount_max_cents: -100,
          direction: "out",
          account_id: "a1",
        },
        (id) => (id === "a1" ? "Giro" : undefined),
      ),
    ).toEqual([
      "Gegenpartei enthält „rewe“",
      "Verwendungszweck enthält „kartenzahlung“",
      "Betrag von -50,00 € bis -1,00 €",
      "nur Ausgaben",
      "Konto Giro",
    ]);
  });

  it("handles one-sided amounts and IBANs", () => {
    expect(describeConditions({ amount_min_cents: 1000, counterparty_iban: "DE02" })).toEqual([
      "IBAN ist DE02",
      "Betrag ab 10,00 €",
    ]);
    expect(describeConditions({ amount_max_cents: 0, direction: "in" })).toEqual([
      "Betrag bis 0,00 €",
      "nur Einnahmen",
    ]);
  });

  it("returns nothing for empty conditions", () => {
    expect(describeConditions({})).toEqual([]);
  });
});

describe("buildConditions", () => {
  const empty = {
    counterparty: "",
    iban: "",
    purpose: "",
    bookingText: "",
    minCents: null,
    maxCents: null,
    direction: null,
    accountId: null,
  };

  it("omits unset fields and trims text", () => {
    expect(buildConditions({ ...empty, counterparty: "  Rewe ", maxCents: -100, direction: "out" })).toEqual({
      counterparty_contains: "Rewe",
      amount_max_cents: -100,
      direction: "out",
    });
  });

  it("keeps a zero amount, which is a valid bound", () => {
    expect(buildConditions({ ...empty, maxCents: 0 })).toEqual({ amount_max_cents: 0 });
  });

  it("is empty when nothing is set", () => {
    expect(buildConditions(empty)).toEqual({});
  });
});
