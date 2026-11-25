import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { type PushCardState, PushCardView } from "./push-card";

const render = (state: PushCardState, props: Partial<Parameters<typeof PushCardView>[0]> = {}) =>
  renderToStaticMarkup(<PushCardView state={state} {...props} />);

describe("PushCardView", () => {
  it("shows the switch and no test button while inactive", () => {
    const html = render({ kind: "ready", active: false });
    expect(html).toContain("Push-Benachrichtigungen");
    expect(html).toContain("Auf diesem Gerät");
    expect(html).toContain('aria-checked="false"');
    expect(html).not.toContain("Test senden");
  });

  it("shows the test button when active", () => {
    const html = render({ kind: "ready", active: true });
    expect(html).toContain('aria-checked="true"');
    expect(html).toContain("Test senden");
  });

  it("disables the controls while busy", () => {
    const html = render({ kind: "ready", active: true }, { busy: true });
    expect(html).toMatch(/<button[^>]*role="switch"[^>]*disabled=""/);
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>(?:(?!<\/button>).)*Test senden/);
    expect(render({ kind: "ready", active: true })).not.toContain('disabled=""');
  });

  it.each([
    ["unsupported", "unterstützt keine Push-Benachrichtigungen"],
    ["ios-not-installed", "Zum Home-Bildschirm"],
    ["no-registration", "kein Service Worker"],
    ["server-disabled", "auf dem Server nicht eingerichtet"],
    ["denied", "Website-Einstellungen"],
  ] as const)("explains the %s state without a switch", (kind, text) => {
    const html = render({ kind });
    expect(html).toContain(text);
    expect(html).not.toContain("push-switch");
    expect(html).not.toContain("Test senden");
  });

  it("shows nothing but the heading while loading", () => {
    const html = render({ kind: "loading" });
    expect(html).toContain("Push-Benachrichtigungen");
    expect(html).not.toContain("role=");
  });

  it("shows errors and test results", () => {
    const html = render(
      { kind: "ready", active: true },
      { error: "Etwas ist schiefgelaufen.", testResult: "Testbenachrichtigung gesendet." },
    );
    expect(html).toContain("Etwas ist schiefgelaufen.");
    expect(html).toContain("Testbenachrichtigung gesendet.");
  });
});
