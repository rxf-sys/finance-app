import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, Plus, Trash2 } from "lucide-react";
import { type FormEvent, useMemo, useState } from "react";
import { api, type Category, type CategoryKind, mutationErrorMessage, unwrap } from "@/api/client";
import { categoriesQuery, invalidateLedger } from "@/api/queries";
import { CategoryIconTile } from "@/components/category-badge";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { FormField } from "@/components/form-field";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import {
  buildCategoryTree,
  CATEGORY_ICONS,
  CHART_TOKENS,
  categoryColor,
  categoryIcon,
  categoryIndex,
  KIND_LABEL,
} from "@/lib/categories";
import { cn } from "@/lib/utils";
import { RulesTab } from "@/routes/rules-tab";

/** Icons offered in the editor; the lookup map in lib/categories also covers older stored names. */
const ICON_CHOICES = Object.keys(CATEGORY_ICONS);

type DialogState =
  | { mode: "create-top" }
  | { mode: "create-child"; parent: Category }
  | { mode: "edit"; category: Category };

function CategoryDialog({ state, onClose }: { state: DialogState | null; onClose: () => void }) {
  return (
    <Dialog open={state !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        {state && (
          <CategoryForm
            key={state.mode + (state.mode === "edit" ? state.category.id : "")}
            state={state}
            onClose={onClose}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function CategoryForm({ state, onClose }: { state: DialogState; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const editing = state.mode === "edit" ? state.category : null;
  const parent = state.mode === "create-child" ? state.parent : null;
  const isTop = state.mode === "create-top" || (editing !== null && editing.parent_id === null);

  const [name, setName] = useState(editing?.name ?? "");
  const [kind, setKind] = useState<CategoryKind>(editing?.kind ?? "expense");
  const [icon, setIcon] = useState<string | null>(editing?.icon ?? null);
  const [color, setColor] = useState<string | null>(editing?.color ?? parent?.color ?? CHART_TOKENS[0]);

  const save = useMutation({
    mutationFn: async () => {
      const body = { name: name.trim(), icon, color };
      if (editing) {
        return unwrap(
          await api.PATCH("/api/categories/{category_id}", {
            params: { path: { category_id: editing.id } },
            body: isTop ? { ...body, kind } : body,
          }),
        );
      }
      return unwrap(
        await api.POST("/api/categories", {
          body: parent ? { ...body, parent_id: parent.id } : { ...body, kind },
        }),
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: categoriesQuery.queryKey });
      await invalidateLedger(queryClient);
      toast.show(editing ? "Kategorie gespeichert." : "Kategorie angelegt.");
      onClose();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (name.trim()) save.mutate();
  }

  const title = editing
    ? "Kategorie bearbeiten"
    : parent
      ? `Unterkategorie von „${parent.name}“`
      : "Neue Hauptkategorie";

  return (
    <>
      <DialogTitle>{title}</DialogTitle>
      <DialogDescription>
        Symbol und Farbe erscheinen überall, wo die Kategorie angezeigt wird.
      </DialogDescription>
      <form onSubmit={submit} className="mt-4 space-y-4">
        <FormField
          label="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={60}
          required
        />
        {isTop && (
          <div className="space-y-1.5">
            <Label htmlFor="cat-kind">Art</Label>
            <Select
              id="cat-kind"
              value={kind}
              onValueChange={(v) => setKind(v as CategoryKind)}
              options={(["expense", "income", "transfer"] as const).map((k) => ({
                value: k,
                label: KIND_LABEL[k],
              }))}
            />
          </div>
        )}
        <fieldset className="space-y-1.5">
          <legend className="text-sm font-medium">Symbol</legend>
          <div className="grid grid-cols-7 gap-1.5">
            {ICON_CHOICES.map((choice) => {
              const Icon = categoryIcon(choice);
              return (
                <button
                  key={choice}
                  type="button"
                  aria-label={choice}
                  aria-pressed={icon === choice}
                  onClick={() => setIcon(choice)}
                  className={cn(
                    "flex size-9 items-center justify-center rounded-lg border",
                    icon === choice
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-text-muted hover:bg-surface-muted",
                  )}
                >
                  <Icon className="size-4" aria-hidden />
                </button>
              );
            })}
          </div>
        </fieldset>
        <fieldset className="space-y-1.5">
          <legend className="text-sm font-medium">Farbe</legend>
          <div className="flex flex-wrap gap-2">
            {CHART_TOKENS.map((token, index) => (
              <button
                key={token}
                type="button"
                aria-label={`Farbe ${index + 1}`}
                aria-pressed={color === token}
                onClick={() => setColor(token)}
                className="flex size-9 items-center justify-center rounded-full border-2 border-transparent text-white aria-pressed:border-text"
                style={{ backgroundColor: categoryColor(token) }}
              >
                {color === token && (
                  <Check className="size-4 text-on-primary mix-blend-difference" aria-hidden />
                )}
              </button>
            ))}
          </div>
        </fieldset>
        {save.error && (
          <Alert tone="error">
            {mutationErrorMessage(save.error, { 409: "Hier gibt es schon eine Kategorie mit diesem Namen." })}
          </Alert>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Abbrechen
          </Button>
          <Button type="submit" disabled={!name.trim() || save.isPending}>
            Speichern
          </Button>
        </div>
      </form>
    </>
  );
}

function CategoryRow({
  category,
  child,
  onEdit,
  onAddChild,
  onDelete,
}: {
  category: Category;
  child?: boolean;
  onEdit: () => void;
  onAddChild?: () => void;
  onDelete: () => void;
}) {
  return (
    <div className={cn("flex items-center gap-2 py-1.5", child && "pl-8")}>
      <CategoryIconTile category={category} className={child ? "size-7" : "size-8"} />
      <span className={cn("min-w-0 flex-1 truncate text-sm", !child && "font-medium")}>{category.name}</span>
      <span className="text-xs text-text-muted tabular-nums">{category.transaction_count}</span>
      {onAddChild && (
        <Button
          variant="ghost"
          size="icon"
          className="size-8"
          onClick={onAddChild}
          aria-label={`Unterkategorie in ${category.name} anlegen`}
          title="Unterkategorie anlegen"
        >
          <Plus aria-hidden />
        </Button>
      )}
      <Button
        variant="ghost"
        size="icon"
        className="size-8"
        onClick={onEdit}
        aria-label={`${category.name} bearbeiten`}
        title="Bearbeiten"
      >
        <Pencil aria-hidden />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        className="size-8"
        onClick={onDelete}
        aria-label={`${category.name} löschen`}
        title="Löschen"
      >
        <Trash2 aria-hidden />
      </Button>
    </div>
  );
}

function CategoriesTab() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: categories = [], isPending } = useQuery(categoriesQuery);
  const tree = useMemo(() => buildCategoryTree(categories), [categories]);
  const index = useMemo(() => categoryIndex(categories), [categories]);
  const [dialog, setDialog] = useState<DialogState | null>(null);
  const [deleting, setDeleting] = useState<Category | null>(null);

  const seed = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/categories/defaults")),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: categoriesQuery.queryKey });
      toast.show("Standardkategorien angelegt.");
    },
  });
  const remove = useMutation({
    mutationFn: async (category: Category) =>
      unwrap(
        await api.DELETE("/api/categories/{category_id}", { params: { path: { category_id: category.id } } }),
      ),
    onSuccess: async () => {
      setDeleting(null);
      await invalidateLedger(queryClient);
      toast.show("Kategorie gelöscht.");
    },
  });

  if (isPending) return <p className="py-6 text-sm text-text-muted">Lädt …</p>;

  const childCount = deleting ? categories.filter((c) => c.parent_id === deleting.id).length : 0;

  return (
    <div className="space-y-4 pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-text-muted">Zwei Ebenen: Hauptkategorien mit Unterkategorien.</p>
        <Button onClick={() => setDialog({ mode: "create-top" })}>
          <Plus aria-hidden /> Hauptkategorie
        </Button>
      </div>

      {tree.length === 0 ? (
        <Card className="flex flex-col items-center gap-3 py-10 text-center">
          <CardTitle>Noch keine Kategorien</CardTitle>
          <CardDescription>Starte mit einer Auswahl gängiger Kategorien oder lege eigene an.</CardDescription>
          <Button onClick={() => seed.mutate()} disabled={seed.isPending}>
            Standardkategorien anlegen
          </Button>
          {seed.error && <Alert tone="error">{mutationErrorMessage(seed.error)}</Alert>}
        </Card>
      ) : (
        (["income", "expense", "transfer"] as const).map((kind) => {
          const group = tree.filter((t) => t.kind === kind);
          if (group.length === 0) return null;
          return (
            <section key={kind} className="space-y-2">
              <h2 className="text-sm font-semibold text-text-muted">{KIND_LABEL[kind]}</h2>
              <div className="divide-y divide-border rounded-xl border border-border bg-surface px-3">
                {group.map((top) => (
                  <div key={top.id} className="py-1">
                    <CategoryRow
                      category={index.get(top.id) ?? top}
                      onEdit={() => setDialog({ mode: "edit", category: top })}
                      onAddChild={() => setDialog({ mode: "create-child", parent: top })}
                      onDelete={() => setDeleting(top)}
                    />
                    {top.children.map((child) => (
                      <CategoryRow
                        key={child.id}
                        child
                        category={index.get(child.id) ?? child}
                        onEdit={() => setDialog({ mode: "edit", category: child })}
                        onDelete={() => setDeleting(child)}
                      />
                    ))}
                  </div>
                ))}
              </div>
            </section>
          );
        })
      )}

      <CategoryDialog state={dialog} onClose={() => setDialog(null)} />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`„${deleting?.name}“ löschen?`}
        confirmLabel="Kategorie löschen"
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
      >
        <p>
          {deleting?.transaction_count ?? 0} Buchungen verlieren ihre Kategorie
          {childCount > 0 ? `, ${childCount} Unterkategorien werden mit gelöscht` : ""}. Regeln, die auf diese
          Kategorie zeigen, werden entfernt.
        </p>
        {remove.error && (
          <Alert tone="error" className="mt-3">
            {mutationErrorMessage(remove.error)}
          </Alert>
        )}
      </ConfirmDialog>
    </div>
  );
}

export function CategoriesPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Kategorien & Regeln</h1>
      <Tabs defaultValue="categories">
        <TabsList>
          <TabsTrigger value="categories">Kategorien</TabsTrigger>
          <TabsTrigger value="rules">Regeln</TabsTrigger>
        </TabsList>
        <TabsContent value="categories">
          <CategoriesTab />
        </TabsContent>
        <TabsContent value="rules">
          <RulesTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
