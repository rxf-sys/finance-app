import { type QueryClient, queryOptions } from "@tanstack/react-query";
import { api, unwrap } from "./client";

export type ContractFilter = {
  status?: "detected" | "confirmed" | "cancelled" | "ignored";
  accountId?: string;
};

export const contractsQuery = (filter: ContractFilter = {}) =>
  queryOptions({
    queryKey: ["contracts", "list", filter],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/contracts", {
          params: { query: { status: filter.status, account_id: filter.accountId } },
        }),
      ),
  });

export const contractSummaryQuery = queryOptions({
  queryKey: ["contracts", "summary"],
  queryFn: async () => unwrap(await api.GET("/api/contracts/summary")),
});

export const contractQuery = (id: string) =>
  queryOptions({
    queryKey: ["contracts", "detail", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/contracts/{contract_id}", { params: { path: { contract_id: id } } })),
  });

export const cancellationLetterQuery = (id: string) =>
  queryOptions({
    queryKey: ["contracts", "letter", id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/contracts/{contract_id}/cancellation-letter", {
          params: { path: { contract_id: id } },
        }),
      ),
  });

export const budgetStatusQuery = (month: string) =>
  queryOptions({
    queryKey: ["budgets", "status", month],
    queryFn: async () => unwrap(await api.GET("/api/budgets/status", { params: { query: { month } } })),
  });

export const availableQuery = queryOptions({
  queryKey: ["available"],
  queryFn: async () => unwrap(await api.GET("/api/available")),
});

export const notificationsQuery = queryOptions({
  queryKey: ["notifications", "list"],
  queryFn: async () => unwrap(await api.GET("/api/notifications", { params: { query: { limit: 20 } } })),
});

export const unreadCountQuery = queryOptions({
  queryKey: ["notifications", "unread-count"],
  queryFn: async () => unwrap(await api.GET("/api/notifications/unread-count")),
  refetchInterval: 60_000,
  refetchOnWindowFocus: true,
  staleTime: 30_000,
});

/** Contracts feed 'frei verfügbar' and the notifications, so they are refreshed together. */
export function invalidateContracts(queryClient: QueryClient): Promise<unknown> {
  return Promise.all(
    ["contracts", "available", "notifications"].map((key) =>
      queryClient.invalidateQueries({ queryKey: [key] }),
    ),
  );
}

export function invalidateBudgets(queryClient: QueryClient): Promise<unknown> {
  return queryClient.invalidateQueries({ queryKey: ["budgets"] });
}
