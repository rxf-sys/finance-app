export type Theme = "system" | "light" | "dark";

const STORAGE_KEY = "fa-theme";

export function readTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    // Storage can be blocked (private mode); the system theme still works.
    return "system";
  }
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", theme);
  }
  try {
    if (theme === "system") {
      localStorage.removeItem(STORAGE_KEY);
    } else {
      localStorage.setItem(STORAGE_KEY, theme);
    }
  } catch {
    // Not persisted when storage is blocked; the choice holds for this page view.
  }
}

export function nextTheme(theme: Theme): Theme {
  const order: Theme[] = ["system", "light", "dark"];
  return order[(order.indexOf(theme) + 1) % order.length];
}
