import type { Category } from "@/api/client";
import { categoryColor, categoryIcon } from "@/lib/categories";
import { cn } from "@/lib/utils";

/** Icon on a tinted tile, so a category is never identified by color alone. */
export function CategoryIconTile({
  category,
  className,
}: {
  category: Pick<Category, "icon" | "color"> | null;
  className?: string;
}) {
  const Icon = categoryIcon(category?.icon);
  const color = categoryColor(category?.color);
  return (
    <span
      className={cn("flex size-8 shrink-0 items-center justify-center rounded-lg", className)}
      style={{ color, backgroundColor: `color-mix(in srgb, ${color} 14%, transparent)` }}
    >
      <Icon className="size-4" aria-hidden />
    </span>
  );
}

export function CategoryBadge({
  category,
  parentName,
}: {
  category: Pick<Category, "name" | "icon" | "color">;
  parentName?: string;
}) {
  const Icon = categoryIcon(category.icon);
  const color = categoryColor(category.color);
  return (
    <span
      className="inline-flex max-w-full items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium"
      style={{ color, backgroundColor: `color-mix(in srgb, ${color} 14%, transparent)` }}
    >
      <Icon className="size-3.5 shrink-0" aria-hidden />
      <span className="truncate">{parentName ? `${parentName} › ${category.name}` : category.name}</span>
    </span>
  );
}
