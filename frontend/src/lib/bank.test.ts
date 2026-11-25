import { describe, expect, it } from "vitest";
import {
  type BankConnection,
  bankErrorMessage,
  canReconnect,
  consentTone,
  filterAspsps,
  formatRetryAfter,
  linkedAccountIds,
  parseRetryAfter,
} from "./bank";

const now = new Date("2026-11-25T12:00:00Z");
const inDays = (d: number) => new Date(now.getTime() + d * 86_400_000).toISOString();

describe("bankErrorMessage", () => {
  it("maps every callback code to its own German message", () => {
    const codes = ["login", "invalid_state", "denied", "rate_limited", "bank_error"];
    const messages = codes.map(bankErrorMessage);
    expect(new Set(messages).size).toBe(codes.length);
    expect(bankErrorMessage("denied")).toContain("nicht freigegeben");
  });
  it("falls back for unknown codes, including prototype names", () => {
    expect(bankErrorMessage("whatever")).toContain("nicht geklappt");
    expect(bankErrorMessage("constructor")).toContain("nicht geklappt");
  });
});

describe("consentTone", () => {
  it("is expired when the time has passed", () => {
    expect(consentTone(inDays(-1), now)).toBe("expired");
    expect(consentTone(now.toISOString(), now)).toBe("expired");
  });
  it("warns under 14 days", () => {
    expect(consentTone(inDays(13), now)).toBe("warning");
    expect(consentTone(inDays(0.5), now)).toBe("warning");
  });
  it("is ok from 14 days", () => {
    expect(consentTone(inDays(14), now)).toBe("ok");
    expect(consentTone(inDays(90), now)).toBe("ok");
  });
});

describe("retry-after", () => {
  it("formats minutes rounded up", () => {
    expect(formatRetryAfter(300)).toBe("Bitte warte noch 5 Minuten");
    expect(formatRetryAfter(61)).toBe("Bitte warte noch 2 Minuten");
    expect(formatRetryAfter(30)).toBe("Bitte warte noch eine Minute");
  });
  it("handles invalid values", () => {
    expect(formatRetryAfter(0)).toContain("gleich");
    expect(formatRetryAfter(Number.NaN)).toContain("gleich");
  });
  it("parses the header", () => {
    expect(parseRetryAfter("120")).toBe(120);
    expect(parseRetryAfter(null)).toBeNull();
    expect(parseRetryAfter("Wed, 21 Oct 2026 07:28:00 GMT")).toBeNull();
  });
});

describe("helpers", () => {
  it("offers reconnect for ended connections only", () => {
    expect(canReconnect("expired")).toBe(true);
    expect(canReconnect("revoked")).toBe(true);
    expect(canReconnect("error")).toBe(true);
    expect(canReconnect("active")).toBe(false);
    expect(canReconnect("pending")).toBe(false);
  });
  it("filters banks by name", () => {
    const banks = [
      { name: "Sparkasse Köln", country: "DE" },
      { name: "N26", country: "DE" },
    ];
    expect(filterAspsps(banks, "  spar").map((b) => b.name)).toEqual(["Sparkasse Köln"]);
    expect(filterAspsps(banks, "")).toHaveLength(2);
  });
  it("collects linked account ids", () => {
    const connections = [
      { accounts: [{ account_id: "a", name: "A", provider_account_uid: "x" }] },
      { accounts: [{ account_id: "b", name: "B", provider_account_uid: null }] },
    ] as BankConnection[];
    expect([...linkedAccountIds(connections)].sort()).toEqual(["a", "b"]);
  });
});
