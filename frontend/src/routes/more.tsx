import { Link } from "@tanstack/react-router";
import { ChevronRight, ShieldCheck, Tags, Upload, Users } from "lucide-react";

const ITEMS = [
  { to: "/import", label: "Import", description: "Kontoauszug als CSV einlesen", icon: Upload },
  {
    to: "/categories",
    label: "Kategorien & Regeln",
    description: "Kategorien ordnen, Regeln anlegen",
    icon: Tags,
  },
  { to: "/household", label: "Haushalt", description: "Mitglieder und Einladungen", icon: Users },
  { to: "/security", label: "Sicherheit", description: "Passkeys und Zwei-Faktor-Code", icon: ShieldCheck },
] as const;

export function MorePage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Mehr</h1>
      <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-surface">
        {ITEMS.map(({ to, label, description, icon: Icon }) => (
          <li key={to}>
            <Link to={to} className="flex items-center gap-3 px-4 py-3 hover:bg-surface-muted">
              <Icon className="size-5 text-text-muted" aria-hidden />
              <span className="flex-1">
                <span className="block text-sm font-medium">{label}</span>
                <span className="block text-xs text-text-muted">{description}</span>
              </span>
              <ChevronRight className="size-4 text-text-muted" aria-hidden />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
