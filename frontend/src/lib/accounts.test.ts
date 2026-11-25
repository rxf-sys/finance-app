import { describe, expect, it } from "vitest";
import { formatIban } from "./accounts";

describe("formatIban", () => {
  it("groups in blocks of four", () => {
    expect(formatIban("DE89370400440532013000")).toBe("DE89 3704 0044 0532 0130 00");
  });

  it("is stable for already formatted input and short strings", () => {
    expect(formatIban("DE89 3704 0044 0532 0130 00")).toBe("DE89 3704 0044 0532 0130 00");
    expect(formatIban("DE89")).toBe("DE89");
  });
});
