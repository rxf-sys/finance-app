import { describe, expect, it } from "vitest";
import { buildMailto, buildPrintHtml, escapeHtml } from "./letter";

const letter = { subject: "Kündigung <A> & B", body: "Zeile 1\nZeile 2", recipient_name: 'Firma "X"' };

describe("letter helpers", () => {
  it("escapes HTML", () => {
    expect(escapeHtml(`<b>"a" & 'b'</b>`)).toBe("&lt;b&gt;&quot;a&quot; &amp; &#39;b&#39;&lt;/b&gt;");
  });
  it("puts only escaped text into the print page", () => {
    const html = buildPrintHtml(letter);
    expect(html).toContain("Kündigung &lt;A&gt; &amp; B");
    expect(html).not.toContain("<A>");
  });
  it("encodes subject and body for mailto", () => {
    const link = buildMailto(letter);
    expect(link.startsWith("mailto:?subject=")).toBe(true);
    expect(link).toContain("body=Zeile%201%0AZeile%202");
  });
});
