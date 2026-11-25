import { useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import {
  Ellipsis,
  FileText,
  Landmark,
  LayoutDashboard,
  LineChart,
  Link2,
  LogOut,
  type LucideIcon,
  Monitor,
  Moon,
  PiggyBank,
  Receipt,
  ShieldCheck,
  Sun,
  Tags,
  Target,
  TrendingUp,
  Upload,
  Users,
} from "lucide-react";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import { meQuery } from "@/api/queries";
import { NotificationBell } from "@/components/notification-bell";
import { Button } from "@/components/ui/button";
import { ToastProvider } from "@/components/ui/toast";
import { disablePushOnLogout } from "@/lib/push";
import { applyTheme, nextTheme, readTheme, type Theme } from "@/lib/theme";
import { cn } from "@/lib/utils";

type NavItem = { to: string; label: string; icon: LucideIcon; exact?: boolean };

/** Everything the desktop sidebar lists. */
const SIDEBAR_NAV: NavItem[] = [
  { to: "/", label: "Übersicht", icon: LayoutDashboard, exact: true },
  { to: "/transactions", label: "Buchungen", icon: Receipt },
  { to: "/contracts", label: "Verträge", icon: FileText },
  { to: "/budgets", label: "Budgets", icon: PiggyBank },
  { to: "/forecast", label: "Prognose", icon: TrendingUp },
  { to: "/goals", label: "Sparziele", icon: Target },
  { to: "/reports", label: "Berichte", icon: LineChart },
  { to: "/accounts", label: "Konten", icon: Landmark },
  { to: "/bank", label: "Bankverbindungen", icon: Link2 },
  { to: "/import", label: "Import", icon: Upload },
  { to: "/categories", label: "Kategorien & Regeln", icon: Tags },
  { to: "/household", label: "Haushalt", icon: Users },
  { to: "/security", label: "Sicherheit", icon: ShieldCheck },
];

/** The bottom bar keeps four tabs; "Mehr" collects the rest. */
const TAB_NAV: NavItem[] = [
  { to: "/", label: "Übersicht", icon: LayoutDashboard, exact: true },
  { to: "/transactions", label: "Buchungen", icon: Receipt },
  { to: "/contracts", label: "Verträge", icon: FileText },
  { to: "/more", label: "Mehr", icon: Ellipsis },
];
const MORE_PATHS = [
  "/more",
  "/accounts",
  "/budgets",
  "/forecast",
  "/goals",
  "/reports",
  "/bank",
  "/import",
  "/categories",
  "/household",
  "/security",
];

const THEME_ICON = { system: Monitor, light: Sun, dark: Moon } satisfies Record<Theme, unknown>;
const THEME_LABEL: Record<Theme, string> = {
  system: "Design: System",
  light: "Design: Hell",
  dark: "Design: Dunkel",
};

function isActive(pathname: string, item: NavItem): boolean {
  if (item.to === "/more") return MORE_PATHS.some((path) => pathname.startsWith(path));
  if (item.exact) return pathname === item.to;
  return pathname === item.to || pathname.startsWith(`${item.to}/`);
}

export function AppShell() {
  const { data: me } = useSuspenseQuery(meQuery);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const [theme, setTheme] = useState<Theme>(readTheme);
  const ThemeIcon = THEME_ICON[theme];

  function toggleTheme() {
    const next = nextTheme(theme);
    applyTheme(next);
    setTheme(next);
  }

  async function logout() {
    if ("serviceWorker" in navigator) {
      // Unsubscribe while the session can still unregister the endpoint. A failure must not keep the
      // member logged in: once unsubscribe() went through, the push service rejects the endpoint and
      // the dispatcher deletes the row on its next send.
      await disablePushOnLogout({
        getRegistration: () => navigator.serviceWorker.getRegistration(),
        unregister: async (endpoint) => {
          unwrap(await api.POST("/api/push/unsubscribe", { body: { endpoint } }));
        },
      }).catch(() => undefined);
    }
    await api.POST("/api/auth/logout");
    queryClient.clear();
    await navigate({ to: "/login" });
  }

  return (
    <ToastProvider>
      <div className="flex min-h-dvh">
        <aside className="hidden w-56 shrink-0 flex-col border-r border-border bg-surface p-4 md:flex">
          <p className="px-2 text-lg font-semibold">Orynthia Finance</p>
          <nav className="mt-6 flex flex-col gap-1" aria-label="Hauptnavigation">
            {SIDEBAR_NAV.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  "flex items-center gap-3 rounded-lg px-2 py-2 text-sm text-text-muted hover:bg-surface-muted",
                  isActive(pathname, item) && "bg-surface-muted font-medium !text-primary",
                )}
              >
                <item.icon className="size-4" aria-hidden />
                {item.label}
              </Link>
            ))}
          </nav>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 items-center justify-between border-b border-border bg-surface px-4">
            <p className="text-sm text-text-muted">
              {me?.household_name} · <span className="text-text">{me?.display_name}</span>
            </p>
            <div className="flex items-center gap-1">
              <NotificationBell />
              <Button
                variant="ghost"
                size="icon"
                onClick={toggleTheme}
                aria-label={THEME_LABEL[theme]}
                title={THEME_LABEL[theme]}
              >
                <ThemeIcon aria-hidden />
              </Button>
              <Button variant="ghost" size="icon" onClick={logout} aria-label="Abmelden" title="Abmelden">
                <LogOut aria-hidden />
              </Button>
            </div>
          </header>

          <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6 pb-24 md:pb-6">
            <Outlet />
          </main>

          <nav
            className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-border bg-surface md:hidden"
            aria-label="Tabs"
          >
            {TAB_NAV.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  "flex flex-col items-center gap-1 py-2 text-xs text-text-muted",
                  isActive(pathname, item) && "!text-primary font-medium",
                )}
              >
                <item.icon className="size-5" aria-hidden />
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
      </div>
    </ToastProvider>
  );
}
