import { describe, expect, it } from "vitest";
import { formatRelativeTime } from "./relative-time";

const now = new Date("2026-11-25T12:00:00Z");
const ago = (seconds: number) => new Date(now.getTime() - seconds * 1000).toISOString();

describe("formatRelativeTime", () => {
  it("handles seconds and future timestamps", () => {
    expect(formatRelativeTime(ago(20), now)).toBe("gerade eben");
    expect(formatRelativeTime(ago(-30), now)).toBe("gerade eben");
  });
  it("uses minutes with singular and plural", () => {
    expect(formatRelativeTime(ago(60), now)).toBe("vor 1 Minute");
    expect(formatRelativeTime(ago(5 * 60), now)).toBe("vor 5 Minuten");
  });
  it("uses hours", () => {
    expect(formatRelativeTime(ago(3600), now)).toBe("vor 1 Stunde");
    expect(formatRelativeTime(ago(2 * 3600 + 100), now)).toBe("vor 2 Stunden");
  });
  it("uses days, then falls back to the date", () => {
    expect(formatRelativeTime(ago(26 * 3600), now)).toBe("gestern");
    expect(formatRelativeTime(ago(3 * 86400), now)).toBe("vor 3 Tagen");
    expect(formatRelativeTime("2026-11-10T12:00:00Z", now)).toBe("10.11.2026");
  });
});
