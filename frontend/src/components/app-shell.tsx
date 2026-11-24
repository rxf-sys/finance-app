import { useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { Link, Outlet, useNavigate } from "@tanstack/react-router";
import { LayoutDashboard, LogOut, Monitor, Moon, ShieldCheck, Sun, Users } from "lucide-react";
import { useState } from "react";
import { api } from "@/api/client";
import { meQuery } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { applyTheme, nextTheme, readTheme, type Theme } from "@/lib/theme";

const NAV = [
  { to: "/", label: "Übersicht", icon: LayoutDashboard },
  { to: "/household", label: "Haushalt", icon: Users },
  { to: "/security", label: "Sicherheit", icon: ShieldCheck },
] as const;

const THEME_ICON = { system: Monitor, light: Sun, dark: Moon } satisfies Record<Theme, unknown>;
const THEME_LABEL: Record<Theme, string> = {
  system: "Design: System",
  light: "Design: Hell",
  dark: "Design: Dunkel",
};

export function AppShell() {
  const { data: me } = useSuspenseQuery(meQuery);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [theme, setTheme] = useState<Theme>(readTheme);
  const ThemeIcon = THEME_ICON[theme];

  function toggleTheme() {
    const next = nextTheme(theme);
    applyTheme(next);
    setTheme(next);
  }

  async function logout() {
    await api.POST("/api/auth/logout");
    queryClient.clear();
    await navigate({ to: "/login" });
  }

  return (
    <div className="flex min-h-dvh">
      <aside className="hidden w-56 shrink-0 flex-col border-r border-border bg-surface p-4 md:flex">
        <p className="px-2 text-lg font-semibold">Finanzen</p>
        <nav className="mt-6 flex flex-col gap-1">
          {NAV.map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              className="flex items-center gap-3 rounded-lg px-2 py-2 text-sm text-text-muted hover:bg-surface-muted"
              activeProps={{ className: "bg-surface-muted font-medium !text-primary" }}
              activeOptions={{ exact: true }}
            >
              <Icon className="size-4" aria-hidden />
              {label}
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

        <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-6 pb-24 md:pb-6">
          <Outlet />
        </main>

        <nav className="fixed inset-x-0 bottom-0 grid grid-cols-3 border-t border-border bg-surface md:hidden">
          {NAV.map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              className="flex flex-col items-center gap-1 py-2 text-xs text-text-muted"
              activeProps={{ className: "!text-primary font-medium" }}
              activeOptions={{ exact: true }}
            >
              <Icon className="size-5" aria-hidden />
              {label}
            </Link>
          ))}
        </nav>
      </div>
    </div>
  );
}
