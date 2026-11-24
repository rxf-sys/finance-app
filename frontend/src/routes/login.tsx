import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { KeyRound } from "lucide-react";
import { type FormEvent, useState } from "react";
import { ApiError, api, type LoginResponse, meQueryKey, unwrap } from "@/api/client";
import { FormField } from "@/components/form-field";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { credentialToJson, passkeysSupported, toRequestOptions } from "@/lib/webauthn";

function loginError(error: unknown, step: "password" | "totp" | "passkey"): string {
  if (error instanceof DOMException && error.name === "NotAllowedError") {
    return "Anmeldung mit Passkey abgebrochen.";
  }
  if (error instanceof ApiError) {
    if (error.status === 401 && step === "password") return "E-Mail oder Passwort falsch.";
    if (error.status === 401 && step === "totp") return "Der Code ist ungültig oder wurde schon verwendet.";
    if (error.status === 401 && step === "passkey") return "Dieser Passkey ist nicht bekannt.";
    return error.message;
  }
  return "Anmeldung fehlgeschlagen. Bitte erneut versuchen.";
}

export function LoginPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function finish(result: LoginResponse) {
    if (result.status === "mfa_required" && result.mfa_token) {
      setMfaToken(result.mfa_token);
      return;
    }
    queryClient.setQueryData(meQueryKey, result.user ?? null);
    await navigate({ to: "/" });
  }

  async function run(step: "password" | "totp" | "passkey", action: () => Promise<LoginResponse>) {
    setBusy(true);
    setError(null);
    try {
      await finish(await action());
    } catch (err) {
      setError(loginError(err, step));
    } finally {
      setBusy(false);
    }
  }

  function submitPassword(event: FormEvent) {
    event.preventDefault();
    void run("password", async () =>
      unwrap(await api.POST("/api/auth/login", { body: { email, password } })),
    );
  }

  function submitCode(event: FormEvent) {
    event.preventDefault();
    if (!mfaToken) return;
    void run("totp", async () =>
      unwrap(await api.POST("/api/auth/login/totp", { body: { mfa_token: mfaToken, code } })),
    );
  }

  function loginWithPasskey() {
    void run("passkey", async () => {
      const { challenge_id, options } = unwrap(await api.POST("/api/auth/passkeys/login/options"));
      const credential = await navigator.credentials.get({ publicKey: toRequestOptions(options) });
      if (!(credential instanceof PublicKeyCredential)) {
        throw new DOMException("No credential", "NotAllowedError");
      }
      return unwrap(
        await api.POST("/api/auth/passkeys/login/verify", {
          body: { challenge_id, credential: credentialToJson(credential) },
        }),
      );
    });
  }

  return (
    <div className="flex min-h-dvh items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardTitle className="text-xl">Anmelden</CardTitle>
        <CardDescription>
          {mfaToken
            ? "Gib den 6-stelligen Code aus deiner Authenticator-App ein."
            : "Deine Haushaltsfinanzen."}
        </CardDescription>

        {error && (
          <Alert tone="error" className="mt-4">
            {error}
          </Alert>
        )}

        {mfaToken ? (
          <form onSubmit={submitCode} className="mt-5 space-y-4">
            <FormField
              label="Code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9 ]{6,8}"
              required
              autoFocus
            />
            <Button type="submit" className="w-full" disabled={busy}>
              Bestätigen
            </Button>
            <Button type="button" variant="ghost" className="w-full" onClick={() => setMfaToken(null)}>
              Zurück
            </Button>
          </form>
        ) : (
          <>
            <form onSubmit={submitPassword} className="mt-5 space-y-4">
              <FormField
                label="E-Mail"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="username webauthn"
                required
              />
              <FormField
                label="Passwort"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
              <Button type="submit" className="w-full" disabled={busy}>
                Anmelden
              </Button>
            </form>
            {passkeysSupported() && (
              <>
                <div className="my-4 flex items-center gap-3 text-xs text-text-muted">
                  <span className="h-px flex-1 bg-border" />
                  oder
                  <span className="h-px flex-1 bg-border" />
                </div>
                <Button variant="secondary" className="w-full" onClick={loginWithPasskey} disabled={busy}>
                  <KeyRound aria-hidden />
                  Mit Passkey anmelden
                </Button>
              </>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
