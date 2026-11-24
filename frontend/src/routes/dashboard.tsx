import { useSuspenseQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { meQuery } from "@/api/queries";
import { Alert } from "@/components/ui/alert";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { roleLabel } from "@/lib/format";

export function DashboardPage() {
  const { data: me } = useSuspenseQuery(meQuery);
  if (!me) return null;
  const unprotected = !me.has_totp && me.passkey_count === 0;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Hallo {me.display_name}</h1>

      {unprotected && (
        <Alert tone="error">
          Dein Konto ist nur mit einem Passwort geschützt.{" "}
          <Link to="/security" className="font-medium underline">
            Passkey oder TOTP einrichten
          </Link>
        </Alert>
      )}

      <Card>
        <CardTitle>{me.household_name}</CardTitle>
        <CardDescription>Deine Rolle: {me.role ? roleLabel[me.role] : "keine"}</CardDescription>
      </Card>

      <Card>
        <CardTitle>Konten</CardTitle>
        <CardDescription>
          Noch keine Konten. Konten und der CSV-Import kommen mit der nächsten Version.
        </CardDescription>
      </Card>
    </div>
  );
}
