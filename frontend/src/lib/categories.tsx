import {
  ArrowLeftRight,
  Baby,
  Banknote,
  Car,
  CircleEllipsis,
  Coffee,
  Dumbbell,
  Fuel,
  Gift,
  GraduationCap,
  HandHeart,
  HeartPulse,
  House,
  Landmark,
  type LucideIcon,
  PawPrint,
  PiggyBank,
  Plane,
  ShieldCheck,
  ShoppingBag,
  ShoppingBasket,
  Smartphone,
  Tag,
  Ticket,
  Tv,
  Wallet,
  Wrench,
  Zap,
} from "lucide-react";
import type { Category } from "@/api/client";

/** Icons a category may use. Anything else falls back to FALLBACK_ICON, so stored names stay safe. */
export const CATEGORY_ICONS: Record<string, LucideIcon> = {
  wallet: Wallet,
  house: House,
  "shopping-basket": ShoppingBasket,
  car: Car,
  "shield-check": ShieldCheck,
  ticket: Ticket,
  "shopping-bag": ShoppingBag,
  "heart-pulse": HeartPulse,
  tv: Tv,
  baby: Baby,
  landmark: Landmark,
  "hand-heart": HandHeart,
  banknote: Banknote,
  "circle-ellipsis": CircleEllipsis,
  "arrow-left-right": ArrowLeftRight,
  coffee: Coffee,
  dumbbell: Dumbbell,
  fuel: Fuel,
  gift: Gift,
  "graduation-cap": GraduationCap,
  "paw-print": PawPrint,
  plane: Plane,
  "piggy-bank": PiggyBank,
  smartphone: Smartphone,
  wrench: Wrench,
  zap: Zap,
  tag: Tag,
};

export const FALLBACK_ICON: LucideIcon = Tag;

export function categoryIcon(name: string | null | undefined): LucideIcon {
  return (name && Object.hasOwn(CATEGORY_ICONS, name) ? CATEGORY_ICONS[name] : undefined) ?? FALLBACK_ICON;
}

export const CHART_TOKENS = [
  "chart-1",
  "chart-2",
  "chart-3",
  "chart-4",
  "chart-5",
  "chart-6",
  "chart-7",
  "chart-8",
] as const;

/** CSS color for a stored color token; unknown values fall back to the neutral chart-8. */
export function categoryColor(token: string | null | undefined): string {
  const known = CHART_TOKENS.find((candidate) => candidate === token);
  return `var(--${known ?? "chart-8"})`;
}

export const KIND_LABEL = { income: "Einnahmen", expense: "Ausgaben", transfer: "Umbuchungen" } as const;

export type CategoryNode = Category & { children: Category[] };

/** Two-level tree: top-level categories (by kind order, then name) with their children. */
export function buildCategoryTree(categories: Category[]): CategoryNode[] {
  const kindOrder = { income: 0, expense: 1, transfer: 2 } as const;
  const byName = (a: Category, b: Category) => a.name.localeCompare(b.name, "de");
  return categories
    .filter((c) => c.parent_id === null)
    .sort((a, b) => kindOrder[a.kind] - kindOrder[b.kind] || byName(a, b))
    .map((top) => ({
      ...top,
      children: categories.filter((c) => c.parent_id === top.id).sort(byName),
    }));
}

/** Lookup by id. A child without its own icon inherits the parent's, so badges never show a blank. */
export function categoryIndex(categories: Category[]): Map<string, Category> {
  const byId = new Map(categories.map((c) => [c.id, c]));
  return new Map(
    categories.map((c) => {
      const parent = c.parent_id ? byId.get(c.parent_id) : undefined;
      return [c.id, c.icon || !parent ? c : { ...c, icon: parent.icon }];
    }),
  );
}

/** "Wohnen › Miete" for a child, the plain name for a top-level category. */
export function categoryPath(category: Category, index: Map<string, Category>): string {
  const parent = category.parent_id ? index.get(category.parent_id) : undefined;
  return parent ? `${parent.name} › ${category.name}` : category.name;
}
