import { describe, expect, it, vi } from "vitest";
import {
  type BrowserEnv,
  base64urlToUint8Array,
  detectSupport,
  disablePush,
  disablePushOnLogout,
  enablePush,
  PushError,
  type PushRegistration,
} from "./push";

const DESKTOP: BrowserEnv = {
  userAgent: "Mozilla/5.0 (X11; Linux x86_64) Firefox/140.0",
  platform: "Linux x86_64",
  maxTouchPoints: 0,
  standalone: false,
  hasServiceWorker: true,
  hasPushManager: true,
  hasNotification: true,
};
const IPHONE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1";

describe("base64urlToUint8Array", () => {
  it("decodes base64url without padding", () => {
    expect([...base64urlToUint8Array("aGVsbG8")]).toEqual([104, 101, 108, 108, 111]);
  });

  it("handles the url-safe alphabet", () => {
    // 0xfb 0xff 0xfe is "+//+" in base64 and "-__-" in base64url.
    expect([...base64urlToUint8Array("-__-")]).toEqual([0xfb, 0xff, 0xfe]);
  });

  it("decodes a 65 byte VAPID public key", () => {
    const bytes = new Uint8Array(65).map((_, i) => (i * 7) % 256);
    const encoded = btoa(String.fromCharCode(...bytes))
      .replaceAll("+", "-")
      .replaceAll("/", "_")
      .replaceAll("=", "");
    expect(base64urlToUint8Array(encoded)).toEqual(bytes);
  });
});

describe("detectSupport", () => {
  it("accepts a browser with service worker, push manager and notifications", () => {
    expect(detectSupport(DESKTOP)).toBe("supported");
  });

  it.each(["hasServiceWorker", "hasPushManager", "hasNotification"] as const)("needs %s", (key) => {
    expect(detectSupport({ ...DESKTOP, [key]: false })).toBe("unsupported");
  });

  it("asks iPhone users to install the app first, even though PushManager is missing", () => {
    const safariTab = { ...DESKTOP, userAgent: IPHONE_UA, platform: "iPhone", hasPushManager: false };
    expect(detectSupport(safariTab)).toBe("ios-not-installed");
    expect(detectSupport({ ...safariTab, standalone: true, hasPushManager: true })).toBe("supported");
  });

  it("recognises iPadOS, which reports itself as a Mac", () => {
    const ipad = {
      ...DESKTOP,
      userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
      platform: "MacIntel",
      maxTouchPoints: 5,
    };
    expect(detectSupport(ipad)).toBe("ios-not-installed");
    expect(detectSupport({ ...ipad, maxTouchPoints: 0 })).toBe("supported");
  });
});

const KEY_BYTES = new Uint8Array([4, 1, 2, 3]);
const KEY = "BAECAw";
const NEW_ENDPOINT = "https://fcm.googleapis.com/new";

function subscription(applicationServerKey: Uint8Array | null, endpoint = "https://fcm.googleapis.com/x") {
  return {
    endpoint,
    options: { applicationServerKey: applicationServerKey?.buffer ?? null },
    unsubscribe: vi.fn().mockResolvedValue(true),
    toJSON: () => ({ endpoint, expirationTime: null, keys: { p256dh: "pk", auth: "au" } }),
  } as unknown as PushSubscription;
}

function setup(existing: PushSubscription | null, permission: NotificationPermission = "granted") {
  const created = subscription(KEY_BYTES, NEW_ENDPOINT);
  const registration = {
    pushManager: {
      getSubscription: vi.fn().mockResolvedValue(existing),
      subscribe: vi.fn().mockResolvedValue(created),
    },
  } satisfies PushRegistration;
  const register = vi.fn().mockResolvedValue(undefined);
  const deps = {
    requestPermission: vi.fn().mockResolvedValue(permission),
    ready: vi.fn().mockResolvedValue(registration),
    register,
  };
  return { deps, registration, register };
}

describe("enablePush", () => {
  it("subscribes with the server key and posts the subscription", async () => {
    const { deps, registration, register } = setup(null);

    await enablePush(deps, KEY);

    expect(registration.pushManager.subscribe).toHaveBeenCalledWith({
      userVisibleOnly: true,
      applicationServerKey: KEY_BYTES,
    });
    expect(register).toHaveBeenCalledWith({
      endpoint: NEW_ENDPOINT,
      expirationTime: null,
      keys: { p256dh: "pk", auth: "au" },
    });
  });

  it("does not subscribe or post when permission is refused", async () => {
    const { deps, registration, register } = setup(null, "denied");

    await expect(enablePush(deps, KEY)).rejects.toMatchObject({ code: "denied" });
    expect(deps.ready).not.toHaveBeenCalled();
    expect(registration.pushManager.subscribe).not.toHaveBeenCalled();
    expect(register).not.toHaveBeenCalled();
  });

  it("replaces a subscription made with another application server key", async () => {
    const stale = subscription(new Uint8Array([4, 9, 9, 9]), "https://fcm.googleapis.com/old");
    const { deps, registration, register } = setup(stale);

    await enablePush(deps, KEY);

    expect(stale.unsubscribe).toHaveBeenCalledOnce();
    expect(registration.pushManager.subscribe).toHaveBeenCalledOnce();
    expect(register).toHaveBeenCalledWith(expect.objectContaining({ endpoint: NEW_ENDPOINT }));
  });

  it("reuses a subscription made with the current key", async () => {
    const current = subscription(KEY_BYTES, "https://fcm.googleapis.com/current");
    const { deps, registration, register } = setup(current);

    await enablePush(deps, KEY);

    expect(current.unsubscribe).not.toHaveBeenCalled();
    expect(registration.pushManager.subscribe).not.toHaveBeenCalled();
    expect(register).toHaveBeenCalledWith(
      expect.objectContaining({ endpoint: "https://fcm.googleapis.com/current" }),
    );
  });

  it("rejects subscriptions without keys", async () => {
    const { deps, registration } = setup(null);
    const broken = {
      toJSON: () => ({ endpoint: "https://fcm.googleapis.com/x" }),
    } as unknown as PushSubscription;
    registration.pushManager.subscribe.mockResolvedValue(broken);

    await expect(enablePush(deps, KEY)).rejects.toBeInstanceOf(PushError);
  });
});

describe("disablePush", () => {
  it("unsubscribes the browser and tells the server", async () => {
    const current = subscription(KEY_BYTES, "https://fcm.googleapis.com/current");
    const unregister = vi.fn().mockResolvedValue(undefined);

    await disablePush({ getSubscription: async () => current, unregister });

    expect(current.unsubscribe).toHaveBeenCalledOnce();
    expect(unregister).toHaveBeenCalledWith("https://fcm.googleapis.com/current");
  });

  it("does nothing without a subscription", async () => {
    const unregister = vi.fn();
    await disablePush({ getSubscription: async () => null, unregister });
    expect(unregister).not.toHaveBeenCalled();
  });
});

describe("disablePushOnLogout", () => {
  it("removes the subscription of this device", async () => {
    const current = subscription(KEY_BYTES, "https://fcm.googleapis.com/current");
    const unregister = vi.fn().mockResolvedValue(undefined);
    const pushManager = { getSubscription: async () => current, subscribe: vi.fn() };

    await disablePushOnLogout({ getRegistration: async () => ({ pushManager }), unregister });

    expect(current.unsubscribe).toHaveBeenCalledOnce();
    expect(unregister).toHaveBeenCalledWith("https://fcm.googleapis.com/current");
  });

  it("does nothing without a service worker registration", async () => {
    const unregister = vi.fn();
    await disablePushOnLogout({ getRegistration: async () => undefined, unregister });
    expect(unregister).not.toHaveBeenCalled();
  });
});
