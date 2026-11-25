import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing } from "lucide-react";
import { useEffect, useState } from "react";
import { api, mutationErrorMessage, unwrap } from "@/api/client";
import { pushConfigQuery } from "@/api/queries";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  detectSupport,
  disablePush,
  enablePush,
  PushError,
  type PushRegistration,
  readBrowserEnv,
} from "@/lib/push";

/** Everything the card can show; each blocked state has its own German explanation. */
export type PushCardState =
  | { kind: "loading" }
  | { kind: "unsupported" }
  | { kind: "ios-not-installed" }
  | { kind: "no-registration" }
  | { kind: "server-disabled" }
  | { kind: "denied" }
  | { kind: "ready"; active: boolean };

const BLOCKED_TEXT: Record<Exclude<PushCardState["kind"], "loading" | "ready">, string> = {
  unsupported: "Dieser Browser unterstützt keine Push-Benachrichtigungen.",
  "ios-not-installed":
    "Auf iPhone und iPad funktionieren Push-Benachrichtigungen nur in der installierten App. Zuerst im Teilen-Menü von Safari „Zum Home-Bildschirm“ wählen und die App von dort öffnen.",
  "no-registration":
    "Auf diesem Gerät ist noch kein Service Worker aktiv. Das ist normal im Entwicklungsmodus; in der gebauten App wird er beim ersten Laden installiert. Bitte die Seite neu laden.",
  "server-disabled":
    "Push-Benachrichtigungen sind auf dem Server nicht eingerichtet. Der Betreiber muss zuerst einen VAPID-Schlüssel hinterlegen.",
  denied:
    "Benachrichtigungen sind für diese Seite blockiert. In den Website-Einstellungen des Browsers (Schloss-Symbol neben der Adresse) „Benachrichtigungen“ erlauben und die Seite neu laden.",
};

interface ViewProps {
  state: PushCardState;
  busy?: boolean;
  error?: string | null;
  testResult?: string | null;
  onToggle?: (checked: boolean) => void;
  onTest?: () => void;
}

/** Presentational part, kept free of browser APIs so it can be rendered in tests. */
export function PushCardView({ state, busy = false, error, testResult, onToggle, onTest }: ViewProps) {
  return (
    <Card>
      <CardTitle>Push-Benachrichtigungen</CardTitle>
      <CardDescription>
        Kündigungsfristen, Budgetwarnungen und Hinweise direkt aufs Gerät, auch wenn die App geschlossen ist.
        Zwischen 22 und 7 Uhr ist Ruhe, Hinweise aus der Nacht kommen morgens.
      </CardDescription>
      {state.kind === "ready" && (
        <div className="mt-4 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <Label htmlFor="push-switch">Auf diesem Gerät</Label>
            <Switch
              id="push-switch"
              checked={state.active}
              disabled={busy}
              onCheckedChange={(checked) => onToggle?.(checked)}
            />
          </div>
          {state.active && (
            <Button type="button" variant="secondary" onClick={onTest} disabled={busy}>
              <BellRing aria-hidden />
              Test senden
            </Button>
          )}
        </div>
      )}
      {state.kind !== "ready" && state.kind !== "loading" && (
        <Alert className="mt-3">{BLOCKED_TEXT[state.kind]}</Alert>
      )}
      {testResult && (
        <Alert tone="success" className="mt-3">
          {testResult}
        </Alert>
      )}
      {error && (
        <Alert tone="error" className="mt-3">
          {error}
        </Alert>
      )}
    </Card>
  );
}

interface DeviceState {
  support: ReturnType<typeof detectSupport>;
  registration: PushRegistration | null;
  active: boolean;
  permission: NotificationPermission;
}

async function readDevice(): Promise<DeviceState> {
  const support = detectSupport(readBrowserEnv());
  if (support !== "supported") return { support, registration: null, active: false, permission: "default" };
  const registration = (await navigator.serviceWorker.getRegistration()) ?? null;
  const subscription = registration ? await registration.pushManager.getSubscription() : null;
  return { support, registration, active: subscription !== null, permission: Notification.permission };
}

function describePushError(error: unknown): string | null {
  if (error instanceof PushError) {
    return error.code === "denied"
      ? "Die Berechtigung wurde nicht erteilt. Bitte in den Website-Einstellungen des Browsers erlauben."
      : "Der Browser hat kein vollständiges Abo geliefert. Bitte erneut versuchen.";
  }
  if (error instanceof DOMException && error.name === "NotAllowedError") {
    return "Benachrichtigungen sind blockiert. Bitte in den Website-Einstellungen des Browsers erlauben.";
  }
  if (error instanceof DOMException && error.name === "AbortError") {
    return "Der Push-Dienst des Browsers ist gerade nicht erreichbar. Bitte später erneut versuchen.";
  }
  return mutationErrorMessage(error, {
    503: "Push-Benachrichtigungen sind auf dem Server nicht eingerichtet.",
    422: "Der Push-Dienst dieses Browsers wird nicht unterstützt.",
  });
}

export function PushCard() {
  const queryClient = useQueryClient();
  const [device, setDevice] = useState<DeviceState | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);
  const supported = device?.support === "supported";
  const config = useQuery({ ...pushConfigQuery, enabled: supported });

  const refresh = async () => setDevice(await readDevice());
  useEffect(() => {
    void readDevice().then(setDevice);
  }, []);

  const toggle = useMutation({
    mutationFn: async (enable: boolean) => {
      setTestResult(null);
      if (enable) {
        const publicKey = config.data?.public_key;
        if (!publicKey) throw new PushError("incomplete");
        await enablePush(
          {
            requestPermission: () => Notification.requestPermission(),
            ready: () => navigator.serviceWorker.ready,
            register: async (body) => {
              unwrap(await api.POST("/api/push/subscriptions", { body }));
            },
          },
          publicKey,
        );
      } else {
        await disablePush({
          getSubscription: async () =>
            (await (await navigator.serviceWorker.ready).pushManager.getSubscription()) ?? null,
          unregister: async (endpoint) => {
            unwrap(await api.POST("/api/push/unsubscribe", { body: { endpoint } }));
          },
        });
      }
    },
    onSettled: () => {
      void refresh();
      void queryClient.invalidateQueries({ queryKey: pushConfigQuery.queryKey });
    },
  });

  const test = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/push/test")),
    onSuccess: ({ sent, failed, removed }) => {
      if (sent > 0) setTestResult("Testbenachrichtigung gesendet.");
      else if (removed > 0)
        setTestResult("Dieses Gerät war beim Push-Dienst nicht mehr bekannt. Bitte neu aktivieren.");
      else if (failed > 0) setTestResult("Der Push-Dienst hat die Nachricht nicht angenommen.");
      else setTestResult("Es ist kein Gerät angemeldet.");
      void refresh();
    },
  });

  let state: PushCardState;
  if (!device || (supported && config.isPending)) state = { kind: "loading" };
  else if (device.support !== "supported") state = { kind: device.support };
  else if (!device.registration) state = { kind: "no-registration" };
  else if (config.data && !config.data.enabled) state = { kind: "server-disabled" };
  else if (device.permission === "denied") state = { kind: "denied" };
  else state = { kind: "ready", active: device.active };

  return (
    <PushCardView
      state={state}
      busy={toggle.isPending || test.isPending}
      error={describePushError(toggle.error ?? test.error)}
      testResult={testResult}
      onToggle={(checked) => toggle.mutate(checked)}
      onTest={() => {
        setTestResult(null);
        test.mutate();
      }}
    />
  );
}
