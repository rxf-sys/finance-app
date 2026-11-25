import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Contract, unwrap } from "@/api/client";
import { invalidateContracts } from "@/api/planning-queries";
import { useToast } from "@/components/ui/toast";
import type { ContractAction } from "@/lib/contracts";

const DONE: Record<ContractAction, string> = {
  confirm: "Vertrag bestätigt.",
  cancel: "Vertrag als gekündigt markiert.",
  ignore: "Vertrag ignoriert.",
  reactivate: "Vertrag wieder aktiviert.",
};

/** Runs a status action (confirm, cancel, ignore, reactivate) and refreshes everything that depends on it. */
export function useContractAction(onDone?: (contract: Contract) => void) {
  const queryClient = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: async ({ id, action }: { id: string; action: ContractAction }) => {
      const path = `/api/contracts/{contract_id}/${action}` as const;
      return unwrap(await api.POST(path, { params: { path: { contract_id: id } } }));
    },
    onSuccess: async (contract, { action }) => {
      await invalidateContracts(queryClient);
      toast.show(DONE[action]);
      onDone?.(contract);
    },
    onError: () => toast.show("Das hat nicht geklappt. Bitte die Seite neu laden.", "error"),
  });
}
