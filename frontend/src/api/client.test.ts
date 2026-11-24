import { describe, expect, it } from "vitest";
import { ApiError, errorMessage, unwrap } from "./client";

describe("unwrap", () => {
  it("returns data for successful responses", () => {
    const response = new Response(null, { status: 200 });
    expect(unwrap({ data: { ok: true }, response })).toEqual({ ok: true });
  });

  it("throws an ApiError with a German message otherwise", () => {
    const response = new Response(null, { status: 429 });
    expect(() => unwrap({ error: {}, response })).toThrow(ApiError);
    expect(errorMessage(429)).toContain("15 Minuten");
  });
});
