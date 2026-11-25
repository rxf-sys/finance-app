import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { KeyRound, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { ApiError, api, unwrap } from "@/api/client";
import { meQuery, passkeysQuery } from "@/api/queries";
import { FormField } from "@/components/form-field";
import { PushCard } from "@/components/push-card";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { formatDate } from "@/lib/format";
import { credentialToJson, passkeysSupported, toCreationOptions } from "@/lib/webauthn";

function describeError(error: unknown, fallback: string): string {
  if (error instanceof DOMException && error.name === "NotAllowedError") return "Vorgang abgebrochen.";
  if (error instanceof DOMException && error.name === "InvalidStateError")
    return "Dieser Passkey ist schon registriert.";
  if (error instanceof ApiError && error.status === 400) return fallback;
  return error instanceof Error ? error.message : fallback;
}

function PasskeySection() {
  const queryClient = useQueryClient();
  const passkeys = useQuery(passkeysQuery);
  const [name, setName] = useState("Dieses Gerät");

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: passkeysQuery.queryKey }),
      queryClient.invalidateQueries({ queryKey: meQuery.queryKey }),
    ]);

  const add = useMutation({
    mutationFn: async () => {
      const { challenge_id, options } = unwrap(await api.POST("/api/auth/passkeys/register/options"));
      const credential = await navigator.credentials.create({ publicKey: toCreationOptions(options) });
      if (!(credential instanceof PublicKeyCredential)) {
        throw new DOMException("No credential", "NotAllowedError");
      }
      return unwrap(
        await api.POST("/api/auth/passkeys/register/verify", {
          body: { challenge_id, name, credential: credentialToJson(credential) },
        }),
      );
    },
    onSuccess: refresh,
  });

  const remove = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE("/api/auth/passkeys/{passkey_id}", { params: { path: { passkey_id: id } } })),
    onSuccess: refresh,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }

  return (
    <Card>
      <CardTitle>Passkeys</CardTitle>
      <CardDescription>Anmeldung per Fingerabdruck, Gesicht oder Geräte-PIN, ohne Passwort.</CardDescription>
      {passkeys.data && passkeys.data.length > 0 && (
        <ul className="mt-3 divide-y divide-border text-sm">
          {passkeys.data.map((passkey) => (
            <li key={passkey.id} className="flex items-center justify-between gap-3 py-2">
              <span>
                {passkey.name}
                <span className="block text-xs text-text-muted">
                  angelegt {formatDate(passkey.created_at)}
                  {passkey.last_used_at ? ` · zuletzt ${formatDate(passkey.last_used_at)}` : ""}
                </span>
              </span>
              <Button
                size="icon"
                variant="ghost"
                aria-label={`${passkey.name} entfernen`}
                onClick={() => remove.mutate(passkey.id)}
                disabled={remove.isPending}
              >
                <Trash2 aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      )}
      {passkeysSupported() ? (
        <form onSubmit={submit} className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="flex-1">
            <FormField
              label="Name des Geräts"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <Button type="submit" disabled={add.isPending}>
            <KeyRound aria-hidden />
            Passkey hinzufügen
          </Button>
        </form>
      ) : (
        <Alert className="mt-3">Dieser Browser unterstützt keine Passkeys.</Alert>
      )}
      {add.isError && (
        <Alert tone="error" className="mt-3">
          {describeError(add.error, "Der Passkey konnte nicht geprüft werden.")}
        </Alert>
      )}
    </Card>
  );
}

function TotpSection({ enabled }: { enabled: boolean }) {
  const queryClient = useQueryClient();
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");

  const done = () => {
    setSetup(null);
    setCode("");
    setPassword("");
    void queryClient.invalidateQueries({ queryKey: meQuery.queryKey });
  };

  const start = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/auth/totp/setup")),
    onSuccess: setSetup,
  });
  const confirm = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/auth/totp/confirm", { body: { code } })),
    onSuccess: done,
  });
  const disable = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/auth/totp/disable", { body: { password, code } })),
    onSuccess: done,
  });

  return (
    <Card>
      <CardTitle>Authenticator-App (TOTP)</CardTitle>
      <CardDescription>
        {enabled
          ? "Aktiv. Bei der Anmeldung mit Passwort wird zusätzlich ein Code abgefragt."
          : "Zweiter Faktor für die Anmeldung mit Passwort, z. B. mit Aegis, 2FAS oder Google Authenticator."}
      </CardDescription>

      {!enabled && !setup && (
        <Button className="mt-4" onClick={() => start.mutate()} disabled={start.isPending}>
          Einrichten
        </Button>
      )}

      {!enabled && setup && (
        <form
          className="mt-4 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            confirm.mutate();
          }}
        >
          <ol className="list-decimal space-y-2 pl-5 text-sm">
            <li>
              Auf dem Handy:{" "}
              <a href={setup.otpauth_uri} className="font-medium text-primary underline">
                in Authenticator-App öffnen
              </a>
              . Sonst den Schlüssel von Hand eingeben:
              <code className="mt-1 block break-all rounded bg-surface-muted p-2 text-xs tracking-wider">
                {setup.secret.match(/.{1,4}/g)?.join(" ")}
              </code>
            </li>
            <li>Den angezeigten 6-stelligen Code hier eingeben.</li>
          </ol>
          <FormField
            label="Code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            inputMode="numeric"
            autoComplete="one-time-code"
            required
          />
          <Button type="submit" disabled={confirm.isPending}>
            Bestätigen
          </Button>
          {confirm.isError && (
            <Alert tone="error">
              {describeError(confirm.error, "Der Code stimmt nicht. Uhrzeit des Handys prüfen.")}
            </Alert>
          )}
        </form>
      )}

      {enabled && (
        <form
          className="mt-4 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            disable.mutate();
          }}
        >
          <FormField
            label="Passwort"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
          <FormField
            label="Aktueller Code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            inputMode="numeric"
            autoComplete="one-time-code"
            required
          />
          <Button type="submit" variant="danger" disabled={disable.isPending}>
            TOTP deaktivieren
          </Button>
          {disable.isError && (
            <Alert tone="error">{describeError(disable.error, "Passwort oder Code ist falsch.")}</Alert>
          )}
        </form>
      )}
    </Card>
  );
}

function PasswordSection() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [mismatch, setMismatch] = useState(false);

  const change = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/auth/password", { body: { current_password: current, new_password: next } }),
      ),
    onSuccess: () => {
      setCurrent("");
      setNext("");
      setRepeat("");
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    setMismatch(next !== repeat);
    if (next === repeat) change.mutate();
  }

  return (
    <Card>
      <CardTitle>Passwort ändern</CardTitle>
      <CardDescription>Andere Geräte werden dabei abgemeldet.</CardDescription>
      <form onSubmit={submit} className="mt-4 space-y-4">
        <FormField
          label="Aktuelles Passwort"
          type="password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          autoComplete="current-password"
          required
        />
        <FormField
          label="Neues Passwort"
          type="password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          autoComplete="new-password"
          minLength={12}
          hint="Mindestens 12 Zeichen."
          required
        />
        <FormField
          label="Neues Passwort wiederholen"
          type="password"
          value={repeat}
          onChange={(e) => setRepeat(e.target.value)}
          autoComplete="new-password"
          minLength={12}
          required
        />
        <Button type="submit" disabled={change.isPending}>
          Passwort ändern
        </Button>
        {mismatch && <Alert tone="error">Die neuen Passwörter stimmen nicht überein.</Alert>}
        {change.isError && (
          <Alert tone="error">{describeError(change.error, "Das aktuelle Passwort ist falsch.")}</Alert>
        )}
        {change.isSuccess && <Alert tone="success">Passwort geändert.</Alert>}
      </form>
    </Card>
  );
}

export function SecurityPage() {
  const { data: me } = useSuspenseQuery(meQuery);
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Sicherheit</h1>
      <PasskeySection />
      <TotpSection enabled={Boolean(me?.has_totp)} />
      <PasswordSection />
      <PushCard />
    </div>
  );
}
