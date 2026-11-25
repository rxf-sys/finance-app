import { describe, expect, it } from "vitest";
import { formatDate } from "./format";

describe("formatDate", () => {
  it("uses the German TT.MM.JJJJ format", () => {
    expect(formatDate("2026-03-07T12:00:00Z")).toBe("07.03.2026");
  });
});

describe("formatDate with plain dates", () => {
  it("does not shift date-only strings", () => {
    expect(formatDate("2026-01-01")).toBe("01.01.2026");
  });
});
