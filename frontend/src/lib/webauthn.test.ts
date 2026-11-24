import { describe, expect, it } from "vitest";
import { base64urlToBuffer, bufferToBase64url } from "./webauthn";

describe("base64url", () => {
  it("round-trips arbitrary bytes without padding", () => {
    const bytes = new Uint8Array([0, 1, 2, 250, 251, 252, 253, 254, 255]);
    const encoded = bufferToBase64url(bytes.buffer);

    expect(encoded).not.toMatch(/[+/=]/);
    expect(new Uint8Array(base64urlToBuffer(encoded))).toEqual(bytes);
  });

  it("decodes values produced by the server", () => {
    // "hello" in base64url, as py_webauthn would send it.
    expect(new TextDecoder().decode(base64urlToBuffer("aGVsbG8"))).toBe("hello");
  });
});
