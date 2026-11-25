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

export const forecastQuery = (months: 1 | 2 | 3) =>
  queryOptions({
    queryKey: ["forecast", months],
    queryFn: async () => unwrap(await api.GET("/api/forecast", { params: { query: { months } } })),
  });

export const goalsQuery = (includeArchived: boolean) =>
  queryOptions({
    queryKey: ["goals", "list", { includeArchived }],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/savings-goals", { params: { query: { include_archived: includeArchived } } }),
      ),
  });

export const goalQuery = (id: string) =>
  queryOptions({
    queryKey: ["goals", "detail", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/savings-goals/{goal_id}", { params: { path: { goal_id: id } } })),
  });

export const yearReportQuery = (year: number) =>
  queryOptions({
    queryKey: ["reports", "year", year],
    queryFn: async () => unwrap(await api.GET("/api/reports/year", { params: { query: { year } } })),
  });

export const categoryReportQuery = (year: number, kind: "expense" | "income") =>
  queryOptions({
    queryKey: ["reports", "categories", year, kind],
    queryFn: async () =>
      unwrap(await api.GET("/api/reports/categories", { params: { query: { year, kind } } })),
  });

/** Goals that follow an account balance change with transactions, so the forecast moves too. */
export function invalidateGoals(queryClient: QueryClient): Promise<unknown> {
  return queryClient.invalidateQueries({ queryKey: ["goals"] });
}
