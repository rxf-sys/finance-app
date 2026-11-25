import { describe, expect, it } from "vitest";
import { goalBarWidth, mustBePrivate, progressText, sortGoals, targetText } from "./goals";

describe("progressText", () => {
  it("formats progress against the target", () => {
    expect(progressText({ progress_cents: 120_000, target_cents: 500_000 })).toMatch(
      /^1\.200,00\s€ von 5\.000,00\s€$/,
    );
  });
});

describe("goalBarWidth", () => {
  it("clamps to 0..100", () => {
    expect(goalBarWidth(-5)).toBe(0);
    expect(goalBarWidth(42)).toBe(42);
    expect(goalBarWidth(130)).toBe(100);
  });
});

describe("targetText", () => {
  const base = { achieved: false, target_date: null, monthly_needed_cents: null, remaining_cents: 100 };
  it("is empty without a date", () => {
    expect(targetText(base)).toBeNull();
  });
  it("shows the date and the monthly amount", () => {
    expect(targetText({ ...base, target_date: "2027-03-31", monthly_needed_cents: 25_000 })).toMatch(
      /^bis 31\.03\.2027 · noch 250,00\s€ pro Monat$/,
    );
  });
  it("shows only the date when no monthly amount is known", () => {
    expect(targetText({ ...base, target_date: "2027-03-31" })).toBe("bis 31.03.2027");
  });
  it("says achieved", () => {
    expect(targetText({ ...base, achieved: true, target_date: "2027-03-31" })).toBe("Ziel erreicht");
  });
});

describe("sortGoals", () => {
  it("puts open goals before achieved and archived ones", () => {
    const goals = [
      { id: "a", achieved: true, archived: false },
      { id: "b", achieved: false, archived: true },
      { id: "c", achieved: false, archived: false },
    ];
    expect(sortGoals(goals).map((g) => g.id)).toEqual(["c", "a", "b"]);
  });
});

describe("mustBePrivate", () => {
  it("is true only for private accounts", () => {
    expect(mustBePrivate("private")).toBe(true);
    expect(mustBePrivate("shared")).toBe(false);
    expect(mustBePrivate(undefined)).toBe(false);
  });
});
