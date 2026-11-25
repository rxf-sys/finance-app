import { Link } from "@tanstack/react-router";
import {
  ChevronRight,
  Landmark,
  LineChart,
  Link2,
  PiggyBank,
  ShieldCheck,
  Tags,
  Target,
  TrendingUp,
  Upload,
  Users,
} from "lucide-react";

const ITEMS = [
  { to: "/accounts", label: "Konten", description: "Konten und Kontostände", icon: Landmark },
  { to: "/budgets", label: "Budgets", description: "Monatslimits je Kategorie", icon: PiggyBank },
  { to: "/forecast", label: "Prognose", description: "Kontostand der nächsten Monate", icon: TrendingUp },
  { to: "/goals", label: "Sparziele", description: "Rücklagen und Fortschritt", icon: Target },
  { to: "/reports", label: "Berichte", description: "Jahresübersicht und Export", icon: LineChart },
  { to: "/bank", label: "Bankverbindungen", description: "Konten per Bankabruf aktuell halten", icon: Link2 },
  { to: "/import", label: "Import", description: "Kontoauszug als CSV einlesen", icon: Upload },
  {
    to: "/categories",
    label: "Kategorien & Regeln",
    description: "Kategorien ordnen, Regeln anlegen",
    icon: Tags,
  },
  { to: "/household", label: "Haushalt", description: "Mitglieder und Einladungen", icon: Users },
  {
    to: "/security",
    label: "Sicherheit",
    description: "Passkeys, Zwei-Faktor-Code und Push",
    icon: ShieldCheck,
  },
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
