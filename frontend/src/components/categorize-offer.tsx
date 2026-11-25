import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles, X } from "lucide-react";
import { useState } from "react";
import { api, mutationErrorMessage, unwrap } from "@/api/client";
import { categoriesQuery, invalidateLedger } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";

type Offer = { transactionId: string; categoryId: string };
type Vars = { transactionId: string; categoryId: string | null; applyToSimilar: boolean };

/**
 * Sets a transaction's category. After a manual pick the caller can offer "ähnliche Buchungen
 * übernehmen", which repeats the call with apply_to_similar and reports similar_updated.
 */
export function useCategorize() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [offer, setOffer] = useState<Offer | null>(null);

  const mutation = useMutation({
    mutationFn: async ({ transactionId, categoryId, applyToSimilar }: Vars) =>
      unwrap(
        await api.PATCH("/api/transactions/{transaction_id}", {
          params: { path: { transaction_id: transactionId } },
          body: { category_id: categoryId, learn: true, apply_to_similar: applyToSimilar },
        }),
      ),
    onSuccess: async (data, vars) => {
      await invalidateLedger(queryClient);
      if (vars.applyToSimilar) {
        const count = data.similar_updated;
        toast.show(
          count === 0
            ? "Es gab keine ähnlichen Buchungen zum Zuordnen."
            : count === 1
              ? "1 ähnliche Buchung wurde ebenfalls zugeordnet."
              : `${count} ähnliche Buchungen wurden ebenfalls zugeordnet.`,
        );
        setOffer(null);
      } else {
        setOffer(vars.categoryId ? { transactionId: vars.transactionId, categoryId: vars.categoryId } : null);
      }
    },
    onError: (error) => toast.show(mutationErrorMessage(error) ?? "", "error"),
  });

  return {
    offer,
    pending: mutation.isPending,
    dismiss: () => setOffer(null),
    categorize: (transactionId: string, categoryId: string | null) =>
      mutation.mutate({ transactionId, categoryId, applyToSimilar: false }),
    applyToSimilar: () =>
      offer &&
      mutation.mutate({
        transactionId: offer.transactionId,
        categoryId: offer.categoryId,
        applyToSimilar: true,
      }),
  };
}

export type Categorizer = ReturnType<typeof useCategorize>;

export function CategorizeOffer({ categorizer }: { categorizer: Categorizer }) {
  const { data: categories = [] } = useQuery(categoriesQuery);
  const { offer } = categorizer;
  if (!offer) return null;
  const name = categories.find((c) => c.id === offer.categoryId)?.name;
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-primary/40 bg-primary/5 px-4 py-3 text-sm"
    >
      <Sparkles className="size-4 shrink-0 text-primary" aria-hidden />
      <span className="min-w-0 flex-1">
        Zugeordnet{name ? `: ${name}` : ""}. Gleiche Gegenpartei auch zuordnen?
      </span>
      <Button size="sm" onClick={categorizer.applyToSimilar} disabled={categorizer.pending}>
        Auch für ähnliche Buchungen übernehmen
      </Button>
      <Button
        size="icon"
        variant="ghost"
        className="size-8"
        onClick={categorizer.dismiss}
        aria-label="Schließen"
      >
        <X aria-hidden />
      </Button>
    </div>
  );
}
