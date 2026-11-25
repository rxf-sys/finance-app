import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown, Search } from "lucide-react";
import { type ReactNode, useId, useMemo, useState } from "react";
import { categoriesQuery } from "@/api/queries";
import { CategoryIconTile } from "@/components/category-badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { buildCategoryTree, categoryIcon, categoryIndex, categoryPath } from "@/lib/categories";
import { cn } from "@/lib/utils";

type CategoryPickerProps = {
  value: string | null;
  onChange: (id: string | null) => void;
  /** Label of the "no category" entry; when omitted the entry is not offered. */
  clearLabel?: string;
  placeholder?: string;
  /** Extra entry shown above the tree, e.g. "Ohne Kategorie" for filters. */
  extraOption?: { label: string; selected: boolean; onSelect: () => void };
  /** Custom trigger content; defaults to the selected category name. */
  children?: ReactNode;
  className?: string;
  id?: string;
  "aria-label"?: string;
};

export function CategoryPicker({
  value,
  onChange,
  clearLabel,
  placeholder = "Kategorie wählen",
  extraOption,
  children,
  className,
  id,
  ...props
}: CategoryPickerProps) {
  const { data: categories = [] } = useQuery(categoriesQuery);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const listId = useId();

  const index = useMemo(() => categoryIndex(categories), [categories]);
  const tree = useMemo(() => buildCategoryTree(categories), [categories]);
  const selected = value ? index.get(value) : undefined;

  const needle = search.trim().toLocaleLowerCase("de");
  const filtered = useMemo(() => {
    if (!needle) return tree;
    return tree
      .map((top) => {
        const topMatches = top.name.toLocaleLowerCase("de").includes(needle);
        const children = top.children.filter(
          (c) => topMatches || c.name.toLocaleLowerCase("de").includes(needle),
        );
        return topMatches || children.length > 0 ? { ...top, children } : null;
      })
      .filter((top) => top !== null);
  }, [tree, needle]);

  function pick(next: string | null) {
    onChange(next);
    setOpen(false);
    setSearch("");
  }

  const TriggerIcon = categoryIcon(selected?.icon);

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setSearch("");
      }}
    >
      <PopoverTrigger asChild>
        {children ? (
          <button type="button" className={className} aria-label={props["aria-label"]}>
            {children}
          </button>
        ) : (
          <button
            type="button"
            id={id}
            aria-label={props["aria-label"]}
            className={cn(
              "flex h-10 w-full items-center justify-between gap-2 rounded-lg border border-border bg-surface-muted px-3 text-left text-sm",
              className,
            )}
          >
            <span className="flex min-w-0 items-center gap-2">
              {selected && <TriggerIcon className="size-4 shrink-0" aria-hidden />}
              <span className={cn("truncate", !selected && "text-text-muted")}>
                {extraOption?.selected
                  ? extraOption.label
                  : selected
                    ? categoryPath(selected, index)
                    : placeholder}
              </span>
            </span>
            <ChevronDown className="size-4 shrink-0 text-text-muted" aria-hidden />
          </button>
        )}
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0">
        <div className="flex items-center gap-2 border-b border-border px-3">
          <Search className="size-4 shrink-0 text-text-muted" aria-hidden />
          <input
            // biome-ignore lint/a11y/noAutofocus: the search field is the point of the popover
            autoFocus
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Kategorie suchen"
            aria-label="Kategorie suchen"
            aria-controls={listId}
            className="h-10 w-full bg-transparent text-sm outline-none placeholder:text-text-muted"
          />
        </div>
        <ul id={listId} className="max-h-72 overflow-y-auto p-1">
          {extraOption && !needle && (
            <Option
              label={extraOption.label}
              selected={extraOption.selected}
              onSelect={() => {
                extraOption.onSelect();
                setOpen(false);
              }}
            />
          )}
          {clearLabel && !needle && (
            <Option label={clearLabel} selected={value === null} onSelect={() => pick(null)} />
          )}
          {filtered.map((top) => (
            <Option
              key={top.id}
              label={top.name}
              category={top}
              selected={top.id === value}
              onSelect={() => pick(top.id)}
              strong
            >
              {top.children.length > 0 && (
                <ul className="ml-6 border-l border-border pl-1">
                  {top.children.map((child) => (
                    <Option
                      key={child.id}
                      label={child.name}
                      selected={child.id === value}
                      onSelect={() => pick(child.id)}
                    />
                  ))}
                </ul>
              )}
            </Option>
          ))}
          {filtered.length === 0 && (
            <li className="px-3 py-4 text-center text-sm text-text-muted">Keine Treffer</li>
          )}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

function Option({
  label,
  category,
  selected,
  onSelect,
  strong,
  children,
}: {
  label: string;
  category?: { icon: string | null; color: string | null };
  selected: boolean;
  onSelect: () => void;
  strong?: boolean;
  children?: ReactNode;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-surface-muted"
      >
        {category && <CategoryIconTile category={category} className="size-6 rounded-md [&_svg]:size-3.5" />}
        <span className={cn("flex-1 truncate", strong && "font-medium")}>{label}</span>
        {selected && <Check className="size-4 text-primary" aria-label="Ausgewählt" />}
      </button>
      {children}
    </li>
  );
}
