/** Browser side of Web Push: support detection and the subscribe/unsubscribe steps. Pure of React. */

export type PushSupport = "supported" | "unsupported" | "ios-not-installed";

export interface BrowserEnv {
  userAgent: string;
  platform: string;
  maxTouchPoints: number;
  /** Running as an installed app (home screen), not in a browser tab. */
  standalone: boolean;
  hasServiceWorker: boolean;
  hasPushManager: boolean;
  hasNotification: boolean;
}

export function readBrowserEnv(): BrowserEnv {
  const nav = navigator as Navigator & { standalone?: boolean };
  return {
    userAgent: nav.userAgent,
    platform: nav.platform,
    maxTouchPoints: nav.maxTouchPoints ?? 0,
    standalone:
      nav.standalone === true ||
      (typeof window.matchMedia === "function" && window.matchMedia("(display-mode: standalone)").matches),
    hasServiceWorker: "serviceWorker" in navigator,
    hasPushManager: "PushManager" in window,
    hasNotification: "Notification" in window,
  };
}

/** iPhone, iPad and iPod, including iPadOS which reports itself as a Mac. */
export function isIos(env: Pick<BrowserEnv, "userAgent" | "platform" | "maxTouchPoints">): boolean {
  if (/iPhone|iPad|iPod/.test(env.userAgent)) return true;
  return env.platform === "MacIntel" && env.maxTouchPoints > 1;
}

export function detectSupport(env: BrowserEnv): PushSupport {
  // On iOS push exists only in the installed app; Safari tabs lack PushManager entirely.
  if (isIos(env) && !env.standalone) return "ios-not-installed";
  if (!env.hasServiceWorker || !env.hasPushManager || !env.hasNotification) return "unsupported";
  return "supported";
}

/** Decode base64url (as the server sends the VAPID public key) to bytes. */
export function base64urlToUint8Array(value: string): Uint8Array<ArrayBuffer> {
  const base64 = value.replaceAll("-", "+").replaceAll("_", "/");
  const binary = atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, "="));
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function sameBytes(a: ArrayBuffer, b: Uint8Array): boolean {
  const left = new Uint8Array(a);
  return left.length === b.length && left.every((byte, index) => byte === b[index]);
}

export type PushFailure = "denied" | "incomplete";

export class PushError extends Error {
  readonly code: PushFailure;

  constructor(code: PushFailure) {
    super(code);
    this.code = code;
  }
}

/** Body of POST /api/push/subscriptions, shaped like `PushSubscription.toJSON()`. */
export interface SubscriptionBody {
  endpoint: string;
  expirationTime: number | null;
  keys: { p256dh: string; auth: string };
}

export interface PushRegistration {
  pushManager: {
    getSubscription(): Promise<PushSubscription | null>;
    subscribe(options: PushSubscriptionOptionsInit): Promise<PushSubscription>;
  };
}

export interface EnableDeps {
  requestPermission(): Promise<NotificationPermission>;
  ready(): Promise<PushRegistration>;
  register(body: SubscriptionBody): Promise<void>;
}

export function toSubscriptionBody(subscription: PushSubscription): SubscriptionBody {
  const json = subscription.toJSON();
  const { p256dh, auth } = json.keys ?? {};
  if (!json.endpoint || !p256dh || !auth) throw new PushError("incomplete");
  return { endpoint: json.endpoint, expirationTime: json.expirationTime ?? null, keys: { p256dh, auth } };
}

/** Ask for permission, (re)subscribe with the server's key and hand the result to the server. */
export async function enablePush(deps: EnableDeps, publicKey: string): Promise<void> {
  if ((await deps.requestPermission()) !== "granted") throw new PushError("denied");
  const registration = await deps.ready();
  const key = base64urlToUint8Array(publicKey);
  const existing = await registration.pushManager.getSubscription();
  const existingKey = existing?.options.applicationServerKey;
  // A subscription made with another key (e.g. after the server key changed) can never receive messages.
  if (existing && existingKey && !sameBytes(existingKey, key)) await existing.unsubscribe();
  const subscription =
    existing && (!existingKey || sameBytes(existingKey, key))
      ? existing
      : await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
  await deps.register(toSubscriptionBody(subscription));
}

export interface DisableDeps {
  getSubscription(): Promise<PushSubscription | null>;
  unregister(endpoint: string): Promise<void>;
}

export async function disablePush(deps: DisableDeps): Promise<void> {
  const subscription = await deps.getSubscription();
  if (!subscription) return;
  const { endpoint } = subscription;
  await subscription.unsubscribe();
  await deps.unregister(endpoint);
}

export interface LogoutDeps {
  /** Resolves to undefined when no service worker is registered (unlike `serviceWorker.ready`). */
  getRegistration(): Promise<Pick<PushRegistration, "pushManager"> | undefined>;
  unregister(endpoint: string): Promise<void>;
}

/** Remove this device's subscription on logout, so it stops receiving the member's notices. */
export async function disablePushOnLogout(deps: LogoutDeps): Promise<void> {
  const registration = await deps.getRegistration();
  if (!registration) return;
  await disablePush({
    getSubscription: () => registration.pushManager.getSubscription(),
    unregister: deps.unregister,
  });
}
