import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { Copy, UserMinus } from "lucide-react";
import { type FormEvent, useState } from "react";
import { ApiError, api, type InviteCreated, unwrap } from "@/api/client";
import { householdQuery, invitesQuery, meQuery } from "@/api/queries";
import { FormField } from "@/components/form-field";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { formatDate, formatDateTime, roleLabel } from "@/lib/format";

function InviteSection() {
  const queryClient = useQueryClient();
  const invites = useQuery(invitesQuery);
  const [email, setEmail] = useState("");
  const [created, setCreated] = useState<InviteCreated | null>(null);
  const [copied, setCopied] = useState(false);

  const create = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/household/invites", { body: { email, role: "member" } })),
    onSuccess: (invite) => {
      setCreated(invite);
      setCopied(false);
      setEmail("");
      void queryClient.invalidateQueries({ queryKey: invitesQuery.queryKey });
    },
  });

  const revoke = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE("/api/household/invites/{invite_id}", { params: { path: { invite_id: id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: invitesQuery.queryKey }),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Card>
      <CardTitle>Mitglied einladen</CardTitle>
      <CardDescription>
        Der Link gilt 72 Stunden und nur einmal. Schick ihn selbst weiter, die App versendet keine E-Mails.
      </CardDescription>
      <form onSubmit={submit} className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="flex-1">
          <FormField
            label="E-Mail"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>
        <Button type="submit" disabled={create.isPending}>
          Link erstellen
        </Button>
      </form>
      {create.isError && (
        <Alert tone="error" className="mt-3">
          {create.error instanceof ApiError && create.error.status === 409
            ? "Für diese E-Mail gibt es schon ein Konto."
            : create.error.message}
        </Alert>
      )}
      {created && (
        <div className="mt-3 space-y-2 rounded-lg border border-border bg-surface-muted p-3">
          <p className="text-sm">Einladungslink für {created.email}:</p>
          <code className="block break-all text-xs">{created.invite_url}</code>
          <Button size="sm" variant="secondary" onClick={() => copy(created.invite_url)}>
            <Copy aria-hidden />
            {copied ? "Kopiert" : "Link kopieren"}
          </Button>
        </div>
      )}
      {invites.data && invites.data.length > 0 && (
        <ul className="mt-4 divide-y divide-border text-sm">
          {invites.data.map((invite) => (
            <li key={invite.id} className="flex items-center justify-between gap-3 py-2">
              <span>
                {invite.email}
                <span className="block text-xs text-text-muted">
                  gültig bis {formatDateTime(invite.expires_at)}
                </span>
              </span>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => revoke.mutate(invite.id)}
                disabled={revoke.isPending}
              >
                Zurückziehen
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function HouseholdPage() {
  const queryClient = useQueryClient();
  const { data: me } = useSuspenseQuery(meQuery);
  const household = useQuery(householdQuery);
  const [confirming, setConfirming] = useState<string | null>(null);
  const isOwner = me?.role === "owner";

  const remove = useMutation({
    mutationFn: async (userId: string) =>
      unwrap(await api.DELETE("/api/household/members/{user_id}", { params: { path: { user_id: userId } } })),
    onSuccess: () => {
      setConfirming(null);
      void queryClient.invalidateQueries({ queryKey: householdQuery.queryKey });
    },
  });

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Haushalt {household.data?.name}</h1>
      <Card>
        <CardTitle>Mitglieder</CardTitle>
        {household.isError && (
          <Alert tone="error" className="mt-3">
            {household.error.message}
          </Alert>
        )}
        <ul className="mt-3 divide-y divide-border">
          {household.data?.members.map((member) => (
            <li key={member.user_id} className="flex items-center justify-between gap-3 py-3">
              <div className="min-w-0">
                <p className="truncate font-medium">{member.display_name}</p>
                <p className="truncate text-sm text-text-muted">
                  {member.email} · {roleLabel[member.role]} · seit {formatDate(member.joined_at)}
                </p>
              </div>
              {isOwner && member.user_id !== me?.id && (
                <Button
                  size="sm"
                  variant={confirming === member.user_id ? "danger" : "ghost"}
                  disabled={remove.isPending}
                  onClick={() =>
                    confirming === member.user_id
                      ? remove.mutate(member.user_id)
                      : setConfirming(member.user_id)
                  }
                >
                  <UserMinus aria-hidden />
                  {confirming === member.user_id ? "Wirklich entfernen" : "Entfernen"}
                </Button>
              )}
            </li>
          ))}
        </ul>
      </Card>
      {isOwner && <InviteSection />}
    </div>
  );
}
