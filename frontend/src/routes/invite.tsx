import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { ApiError, api, meQueryKey, unwrap } from "@/api/client";
import { FormField } from "@/components/form-field";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";

const MIN_PASSWORD = 12;

export function InvitePage({ token }: { token: string }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const invite = useQuery({
    queryKey: ["invite", token],
    queryFn: async () => unwrap(await api.GET("/api/auth/invites/{token}", { params: { path: { token } } })),
    retry: false,
  });
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password !== repeat) {
      setError("Die Passwörter stimmen nicht überein.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = unwrap(
        await api.POST("/api/auth/invites/accept", { body: { token, display_name: name, password } }),
      );
      queryClient.setQueryData(meQueryKey, result.user ?? null);
      await navigate({ to: "/security" });
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 409
          ? "Für diese E-Mail gibt es schon ein Konto. Bitte melde dich an."
          : err instanceof Error
            ? err.message
            : "Beitritt fehlgeschlagen.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardTitle className="text-xl">Einladung annehmen</CardTitle>
        {invite.isPending && <CardDescription>Einladung wird geprüft …</CardDescription>}
        {invite.isError && (
          <Alert tone="error" className="mt-4">
            Diese Einladung ist ungültig, abgelaufen oder wurde schon verwendet.
          </Alert>
        )}
        {invite.data && (
          <>
            <CardDescription>
              Du trittst dem Haushalt <strong className="text-text">{invite.data.household_name}</strong> bei
              ({invite.data.email}).
            </CardDescription>
            {error && (
              <Alert tone="error" className="mt-4">
                {error}
              </Alert>
            )}
            <form onSubmit={submit} className="mt-5 space-y-4">
              <FormField
                label="Dein Name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="name"
                maxLength={100}
                required
              />
              <FormField
                label="Passwort"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                minLength={MIN_PASSWORD}
                hint={`Mindestens ${MIN_PASSWORD} Zeichen. Danach richtest du einen Passkey oder TOTP ein.`}
                required
              />
              <FormField
                label="Passwort wiederholen"
                type="password"
                value={repeat}
                onChange={(e) => setRepeat(e.target.value)}
                autoComplete="new-password"
                minLength={MIN_PASSWORD}
                required
              />
              <Button type="submit" className="w-full" disabled={busy}>
                Beitreten
              </Button>
            </form>
          </>
        )}
      </Card>
    </div>
  );
}
