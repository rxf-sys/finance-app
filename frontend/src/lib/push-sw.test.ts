import { describe, expect, it, vi } from "vitest";
import source from "../../public/push-sw.js?raw";

type Handler = (event: unknown) => void;

const ORIGIN = "https://finanzen.example";

/** Runs the plain service worker script against a fake `self` and returns its handlers. */
function loadWorker(windows: unknown[] = []) {
  const handlers = new Map<string, Handler>();
  const openWindow = vi.fn(async (_url: string) => null);
  const showNotification = vi.fn(async (_title: string, _options: NotificationOptions) => undefined);
  const fakeSelf = {
    addEventListener: (type: string, handler: Handler) => handlers.set(type, handler),
    location: { origin: ORIGIN },
    clients: { matchAll: async () => windows, openWindow },
    registration: { showNotification },
  };
  new Function("self", source)(fakeSelf);

  async function dispatch(type: string, event: object) {
    let pending: Promise<unknown> = Promise.resolve();
    handlers.get(type)?.({ ...event, waitUntil: (promise: Promise<unknown>) => (pending = promise) });
    await pending;
  }
  return { dispatch, openWindow, showNotification };
}

function clickEvent(url: unknown) {
  return { notification: { close: vi.fn(), data: { url } } };
}

describe("push service worker", () => {
  it("shows title, body and link from the JSON payload", async () => {
    const worker = loadWorker();
    const payload = JSON.stringify({ title: "Kündigungsfrist", body: "Noch 14 Tage", url: "/contracts/1" });

    await worker.dispatch("push", { data: { text: () => payload } });

    expect(worker.showNotification).toHaveBeenCalledWith(
      "Kündigungsfrist",
      expect.objectContaining({ body: "Noch 14 Tage", data: { url: "/contracts/1" } }),
    );
  });

  it("falls back to a default title for a plain text payload", async () => {
    const worker = loadWorker();

    await worker.dispatch("push", { data: { text: () => "Hallo" } });

    expect(worker.showNotification).toHaveBeenCalledWith(
      "Finanzen",
      expect.objectContaining({ body: "Hallo" }),
    );
  });

  it("opens in-app paths", async () => {
    const worker = loadWorker();

    await worker.dispatch("notificationclick", clickEvent("/contracts/1?tab=payments"));

    expect(worker.openWindow).toHaveBeenCalledWith("/contracts/1?tab=payments");
  });

  it.each(["//evil.example/x", "/\\evil.example/x", "https://evil.example/", "javascript:alert(1)", 42])(
    "never opens a foreign target for %s",
    async (url) => {
      const worker = loadWorker();

      await worker.dispatch("notificationclick", clickEvent(url));

      expect(worker.openWindow).toHaveBeenCalledWith("/");
    },
  );

  it("reuses an open app window", async () => {
    const window = { url: `${ORIGIN}/`, focus: vi.fn(async () => {}), navigate: vi.fn(async () => window) };
    const worker = loadWorker([window]);

    await worker.dispatch("notificationclick", clickEvent("/budgets"));

    expect(window.focus).toHaveBeenCalled();
    expect(window.navigate).toHaveBeenCalledWith("/budgets");
    expect(worker.openWindow).not.toHaveBeenCalled();
  });

  it("opens a new window when the open one cannot be navigated", async () => {
    const window = {
      url: `${ORIGIN}/`,
      focus: vi.fn(async () => {}),
      navigate: vi.fn(async () => Promise.reject(new TypeError("not controlled"))),
    };
    const worker = loadWorker([window]);

    await worker.dispatch("notificationclick", clickEvent("/budgets"));

    expect(worker.openWindow).toHaveBeenCalledWith("/budgets");
  });
});
